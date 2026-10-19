"""되돌리기: 확인 대기 기록(pending.json), systemd 타이머, Transaction."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from .config import NOTIFY, PENDING_FILE, SYSTEMCTL, SYSTEMD_RUN, TIMER_UNIT
from .hypr import get_monitors, parse_mode
from .state import load_state, locked, save_state
from .layout import build, current_cfg
from .apply import apply_cfg, migrate_windows, verify

# 되돌리기 타이머가 별도 프로세스로 실행할 진입 스크립트: 패키지 한 단계 위의 displayctl.py
# (예전 단일 파일에서는 __file__ 이 곧 진입 스크립트였다 — 분리 후 __file__ 은 이 모듈이라 revert-pending 이 아무 일도 안 했음: 시험이 잡아냄)
ENTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "displayctl.py")

# ───────────────────────── 트랜잭션 (되돌리기 지원) ─────────────────────────
# ───────────────────────── 되돌리기 타이머 ─────────────────────────
def _pending_load() -> dict | None:
    try:
        with open(PENDING_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _pending_clear() -> None:
    try:
        os.remove(PENDING_FILE)
    except OSError:
        pass


def _notify(text: str) -> None:
    if NOTIFY:
        try:
            subprocess.run([NOTIFY, "-u", "normal", "화면 설정", text], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def cancel_timer() -> None:
    subprocess.run([SYSTEMCTL, "--user", "stop", f"{TIMER_UNIT}.timer", f"{TIMER_UNIT}.service"], capture_output=True)


def schedule_timer(seconds: float) -> None:
    """seconds 뒤에 revert-pending 을 실행하는 systemd 사용자 타이머. 부모 프로세스와 무관하게 돈다."""
    cancel_timer()
    subprocess.run(
        [SYSTEMD_RUN, "--user", "--quiet", "--collect", f"--unit={TIMER_UNIT}", f"--on-active={max(1, round(seconds))}s",
         sys.executable, ENTRY, "revert-pending"],
        capture_output=True,
    )


def revert_pending(from_timer: bool = False, fallback: tuple | None = None) -> bool:
    """확인되지 않은 변경을 되돌린다. 대기 기록이 없으면 아무것도 안 함(이미 확인했거나 되돌린 경우). 되돌렸으면 True.
    from_timer: 타이머 서비스가 직접 부른 경우 — 자기 자신(서비스)을 stop 하지 않음"""
    with locked():
        p = _pending_load()
        if p:
            cfg, state = p["prev_cfg"], p["prev_state"]
        elif fallback:
            cfg, state = fallback
        else:
            return False
        migrate_windows(cfg)
        apply_cfg(cfg)
        save_state(state)
        _pending_clear()
    if not from_timer:
        cancel_timer()
    if p:
        _notify("확인이 없어서 이전 화면 설정으로 되돌렸습니다.")
    return True


class Transaction:
    """적용 전 실제 구성과 상태 파일을 기억해 두고, 확인 시 저장하거나 되돌린다.
    arm() 으로 별도 프로세스(systemd 타이머)에 되돌리기를 예약해 두면 이 프로세스가 죽어도 되돌려진다."""

    def __init__(self) -> None:
        self.prev_state = load_state()
        self.prev_cfg = current_cfg(get_monitors())
        self.cfg: dict = {}
        self.layout = "extend"
        self.new_state: dict | None = None

    def apply(self, st: dict, do_verify: bool = True) -> list[str]:
        mons = get_monitors()
        self.cfg, self.layout = build(mons, st)
        self.new_state = st
        migrate_windows(self.cfg)
        errs = apply_cfg(self.cfg, mons)
        if not do_verify:
            return errs
        issues = verify(self.cfg)
        # 모니터가 거부해 다른 모드로 돌아간 항목은 상태를 실제 값으로 정정 (거부된 요청이 이후 작업에 계속 남지 않도록)
        actual = {m.name: m for m in get_monitors()}
        for name, c in self.cfg.items():
            m = actual.get(name)
            if m and not c.get("disabled") and not c.get("mirror") and not m.disabled and name in st["monitors"]:
                want = parse_mode(c["mode"])
                if want and ((m.width, m.height) != (want[0], want[1]) or abs(m.hz - want[2]) > 0.6):
                    st["monitors"][name]["mode"] = m.mode
        return errs + issues

    def arm(self, seconds: float) -> None:
        """이미 적용한 변경을 seconds 뒤에 자동으로 되돌리도록 예약. 그 전에 commit() 하면 취소됨.
        확인 전에 또 변경하면 가장 처음의(마지막으로 확인된) 구성을 기준으로 되돌린다."""
        with locked():
            old = _pending_load()
            rec = {
                "prev_cfg": old["prev_cfg"] if old else self.prev_cfg,
                "prev_state": old["prev_state"] if old else self.prev_state,
                "new_state": self.new_state,  # (다른 프로세스가 `displayctl confirm` 으로 확인할 때 저장할 구성)
                "deadline": time.time() + seconds,
            }
            with open(PENDING_FILE + ".tmp", "w") as f:
                json.dump(rec, f, ensure_ascii=False)
            os.replace(PENDING_FILE + ".tmp", PENDING_FILE)
            schedule_timer(seconds)

    def commit(self) -> None:
        with locked():
            save_state(self.new_state)
            _pending_clear()
        cancel_timer()

    def revert(self) -> list[str]:
        revert_pending(fallback=(self.prev_cfg, self.prev_state))
        return []
