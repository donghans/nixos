"""노트북 밝기: 전원(AC/배터리)별 마지막 밝기 기억·복원 + 배터리에서 일정 시간 입력이 없으면 밝기를 낮춤.

구성
  - watch  : 사용자 서비스(데몬). 몇 초마다 전원 상태와 밝기를 읽어, 같은 전원 상태에서 밝기가 바뀌면 그 상태의 "마지막 밝기"로 기억하고,
             전원이 바뀌면 새 상태의 마지막 밝기로 되돌린다. (알림 없는 폴링이라 간격은 POLL 초)
  - idle N : hypridle 의 N초 유휴 리스너가 부름. 설정한 시간과 같고, 배터리이고, 이번 배터리 사용에서 끄지 않았을 때만 낮춘다.
  - wake   : hypridle 의 복귀(입력 재개) 리스너가 부름. 우리가 낮춘 경우에만 원래 밝기로 되돌린다.
  - 설정(낮출 밝기 %, 대기 시간)은 상태 파일에 영속. "이번 배터리 사용만 끄기"는 $XDG_RUNTIME_DIR(tmpfs)에 두므로 재부팅하면 사라지고,
    AC 로 바뀌면 데몬이 지운다.
밝기는 기기 독립적이지 않게 raw 값으로 기억한다(이 기기는 intel_backlight 하나).
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import time

from .config import STATE_DIR

PS_DIR = os.environ.get("DISPLAYCTL_POWER_SUPPLY", "/sys/class/power_supply")
BL_DIR = os.environ.get("DISPLAYCTL_BACKLIGHT", "/sys/class/backlight")
BRIGHTNESSCTL = os.environ.get("DISPLAYCTL_BRIGHTNESSCTL", "brightnessctl")
RUN_DIR = os.environ.get("DISPLAYCTL_RUNTIME") or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
CONF_FILE = os.path.join(STATE_DIR, "brightness.json")          # 영속: 설정 + 전원별 마지막 밝기
RUN_FILE = os.path.join(RUN_DIR, "displayctl-brightness.json")  # 휘발: 이번 부팅/배터리 사용의 상태
POLL = float(os.environ.get("DISPLAYCTL_BRIGHTNESS_POLL", "2"))

LEVELS = [5, 10, 15, 20, 25]            # 낮출 밝기(%)
DELAYS = [30, 60, 120, 300]             # 입력이 없다고 보는 시간(초) — hypridle 리스너도 이 값마다 하나씩 만든다
DEFAULT_CONF = {"dim_level": 5, "dim_delay": 60, "mem": {}}


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _load(path: str, default: dict) -> dict:
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else dict(default)
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_conf() -> dict:
    c = _load(CONF_FILE, DEFAULT_CONF)
    for k, v in DEFAULT_CONF.items():
        c.setdefault(k, json.loads(json.dumps(v)))
    return c


def load_run() -> dict:
    return _load(RUN_FILE, {})


# ───────────────────────── 센서 ─────────────────────────
def backlight_dir() -> str | None:
    d = sorted(glob.glob(os.path.join(BL_DIR, "*")))
    return d[0] if d else None


def read_brightness() -> tuple[int, int] | None:
    d = backlight_dir()
    if not d:
        return None
    cur, mx = _read(d + "/brightness"), _read(d + "/max_brightness")
    if cur is None or mx is None:
        return None
    return int(cur), int(mx)


def power_state() -> str | None:
    """'ac' | 'bat' | None(전원 정보 없음 = 데스크톱)"""
    mains = [_read(p + "/online") for p in glob.glob(os.path.join(PS_DIR, "*")) if _read(p + "/type") == "Mains"]
    if not mains:
        return None
    return "ac" if "1" in mains else "bat"


def set_brightness(raw: int) -> None:
    subprocess.run([BRIGHTNESSCTL, "-q", "set", str(max(1, int(raw)))], check=False)


def level_raw(pct: int, mx: int) -> int:
    return max(1, round(mx * pct / 100))


def step_pct(pct: int, up: bool) -> int:
    """슬라이더·밝기 키의 한 단계: 10% 이하는 1%씩, 그 위는 5%의 배수로 맞춰 5%씩. 1~100. hwctl/brt-control.sh 와 같은 규칙"""
    if up:
        t = pct + 1 if pct < 10 else (pct // 5 + 1) * 5
    else:
        t = pct - 1 if pct <= 10 else ((pct + 4) // 5 - 1) * 5
    return max(1, min(100, t))


def set_level(pct: int) -> int | None:
    """사용자가 직접 정한 밝기(%). 1~100 으로 제한(0 은 화면이 꺼져 복구가 어려움).
    낮춤 상태면 먼저 끝내고, 지금 전원 상태의 기억 밝기로 바로 저장한다(Wayland 감시 서비스가 없는 TTY 에서도 기억되게). 적용한 %를 돌려줌."""
    b = read_brightness()
    if not b:
        return None
    pct = max(1, min(100, int(pct)))
    r = load_run()
    r["dimmed"] = None                                # 사용자가 직접 정했으니 낮춤 상태는 끝(wake 가 옛 값으로 덮지 않게)
    raw = level_raw(pct, b[1])
    set_brightness(raw)
    r["seen"] = raw
    _save(RUN_FILE, r)
    p = power_state()
    if p:
        c = load_conf()
        c["mem"][p] = raw
        _save(CONF_FILE, c)
    return pct


# ───────────────────────── 설정 ─────────────────────────
def set_conf(level: int | None = None, delay: int | None = None) -> dict:
    c = load_conf()
    if level is not None:
        if level not in LEVELS:
            raise SystemExit(f"밝기는 {LEVELS} 중에서 고르세요")
        c["dim_level"] = level
    if delay is not None:
        if delay not in DELAYS:
            raise SystemExit(f"시간은 {DELAYS}(초) 중에서 고르세요")
        c["dim_delay"] = delay
    _save(CONF_FILE, c)
    return c


def set_paused(paused: bool) -> None:
    """이번 배터리 사용에서만 자동 낮춤을 끄거나 켠다(AC 로 바뀌거나 재부팅하면 켜짐으로 돌아감)"""
    r = load_run()
    r["dim_off"] = bool(paused)
    if paused and r.get("dimmed") is not None:
        wake()
        r = load_run()
        r["dim_off"] = True
    _save(RUN_FILE, r)


def status() -> dict:
    c, r = load_conf(), load_run()
    b = read_brightness()
    return {
        "power": power_state(), "raw": b[0] if b else None, "max": b[1] if b else None,
        "pct": round(100 * b[0] / b[1]) if b else None,
        "dim_level": c["dim_level"], "dim_delay": c["dim_delay"], "paused": bool(r.get("dim_off")), "dimmed": r.get("dimmed") is not None,
        "mem": {k: (round(100 * v / b[1]) if b else v) for k, v in c["mem"].items()},
    }


# ───────────────────────── 유휴 낮춤 ─────────────────────────
def idle(seconds: int) -> bool:
    c, r = load_conf(), load_run()
    if seconds != c["dim_delay"] or r.get("dim_off") or r.get("dimmed") is not None or power_state() != "bat":
        return False
    b = read_brightness()
    if not b:
        return False
    cur, mx = b
    target = level_raw(c["dim_level"], mx)
    if cur <= 0 or cur <= target:          # 덮개를 닫아 꺼진 상태(0)이거나 이미 더 어두우면 건드리지 않음
        return False
    r["dimmed"] = cur
    _save(RUN_FILE, r)
    set_brightness(target)
    return True


def wake() -> bool:
    r = load_run()
    saved = r.get("dimmed")
    if saved is None:
        return False
    r["dimmed"] = None
    _save(RUN_FILE, r)
    set_brightness(saved)
    return True


# ───────────────────────── 부팅/전원 변경 복원(시스템 서비스용) ─────────────────────────
def _wait_backlight(timeout: float = 10.0) -> bool:
    """백라이트 장치가 생기고 systemd-backlight(직전 밝기 복원)가 끝날 때까지 기다린다(그 뒤에 써야 덮어써지지 않음)"""
    end = time.time() + timeout
    while time.time() < end and backlight_dir() is None:
        time.sleep(0.2)
    if backlight_dir() is None:
        return False
    while time.time() < end:
        out = subprocess.run(["systemctl", "list-units", "--state=activating", "--no-legend", "systemd-backlight@*"],
                             capture_output=True, text=True, check=False).stdout.strip()
        if not out:
            break
        time.sleep(0.2)
    return True


def restore_boot(wait: bool = True) -> bool:
    """현재 전원 상태의 기억 밝기를 적용한다. 로그인 화면(greetd)·TTY(kmscon)처럼 사용자 세션이 없을 때를 위한 것으로,
    root 시스템 서비스가 부팅 때와 전원 변경(udev) 때 부른다. 백라이트는 커널 전역이라 한 번 쓰면 어디서든 유지된다."""
    if wait and not _wait_backlight():
        return False
    p, b = power_state(), read_brightness()
    if p is None or b is None or b[0] <= 0:           # 덮개를 닫아 0 인 동안은 건드리지 않음
        return False
    want = load_conf()["mem"].get(p)
    if not want or want == b[0]:
        return False
    set_brightness(min(want, b[1]))
    return True


# ───────────────────────── 데몬 ─────────────────────────
class Watcher:
    """한 번의 tick 이 하는 일을 분리해 둔 것(시험하기 쉽게). 상태는 RUN_FILE 에 두어 데몬이 재시작해도 이어진다."""

    def tick(self) -> None:
        p, b = power_state(), read_brightness()
        if p is None or b is None:
            return
        cur = b[0]
        c, r = load_conf(), load_run()
        last = r.get("power")
        if last != p:
            r["power"] = p
            r["seen"] = cur
            if last is not None:                     # 첫 관측(데몬 시작)에는 건드리지 않고, 실제로 바뀔 때만 복원
                r["dimmed"] = None                   # 전원이 바뀌면 낮춤 상태는 끝 — 새 상태의 기억 밝기가 우선
                if p == "ac":
                    r["dim_off"] = False             # 「이번 배터리 사용만 끄기」는 AC 에 닿으면 풀림
                r["pending"] = p
            _save(RUN_FILE, r)
        if r.get("pending") and cur > 0:             # 덮개를 닫아 0 인 동안은 미뤘다가 열린 뒤에 적용
            want = c["mem"].get(r["pending"])
            r["pending"] = None
            if want and want != cur:
                set_brightness(want)
                cur = want
            elif not want:                           # 이 전원 상태의 기억이 아직 없으면 지금 밝기가 그 시작점
                c["mem"][p] = cur
                _save(CONF_FILE, c)
            r["seen"] = cur
            _save(RUN_FILE, r)
            return
        if cur > 0 and (cur != r.get("seen") or p not in c["mem"]):
            r["seen"] = cur
            if r.get("dimmed") is None:              # 우리가 낮춘 값은 사용자의 밝기가 아니므로 기억하지 않음
                c["mem"][p] = cur
                _save(CONF_FILE, c)
            _save(RUN_FILE, r)


def watch() -> int:
    if backlight_dir() is None or power_state() is None:
        print("백라이트 또는 전원 정보가 없어 종료합니다(데스크톱)")
        return 0
    w = Watcher()
    while True:
        try:
            w.tick()
        except Exception as e:                       # 한 번의 오류로 감시가 멈추지 않게
            print(f"tick 오류: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL)
