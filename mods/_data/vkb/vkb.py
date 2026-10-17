#!/usr/bin/env python3
"""vkb — 가상 키보드(wvkbd) 제어: 접기/펴기, 크기 조절, 창 가림 방지, 자세 연동.

  vkb show | hide | toggle          키보드 보이기/숨기기 (wvkbd 에 시그널; 보일 때 가려지는 창은 키보드 위로 맞춤, 숨기면 원래대로)
  vkb size <small|medium|large|N>    높이 프리셋 또는 픽셀. 설정 저장 후 키보드를 다시 띄움(wvkbd 는 높이를 시작할 때만 받음)
  vkb size up | down                 프리셋을 한 단계 크게/작게
  vkb size cycle                     small → medium → large → small (터치 버튼용: 한 번 탭하면 다음 크기)
  vkb waybar [toggle|size]           waybar 사용자 지정 모듈용 JSON (키보드 아이콘 / 크기 표시)
  vkb status                         상태 요약 (JSON 이면 --json)
  vkb auto on | off                  자세 연동: 텐트/태블릿이면 자동으로 보이고 노트북 모드면 숨김 (기본 켜짐)
  vkb apply-posture                  자세 허브 소비자(멱등): auto 가 켜져 있으면 현재 자세에 맞춤
  vkb layers <full,special,...>      쓸 레이어(wvkbd -l). 비우면 기본값(full,...). 한 번에 하나만 쓰려면 예: full

wvkbd 의 한계(소스에서 확인): 위치는 하단 전체 폭 고정, 높이는 시작할 때만 지정(-H/-L), "숨기기" 전용 키는 없음(⌨ 키는 레이어 전환).
그래서 접고 펴기는 시그널(SIGUSR1 숨김 / SIGUSR2 표시 / SIGRTMIN 토글), 크기는 재시작으로 처리한다.

창 가림 방지: wvkbd 는 기본으로 하단 배타 영역(exclusive zone)을 요청해서 타일/최대화 창은 자동으로 줄어든다. 떠 있는(floating) 창은
영역과 상관없이 그대로라 가려질 수 있으므로, 보일 때 키보드 윗면보다 아래로 내려온 창만 키보드 위로 맞추고(높이를 줄이고 부족하면 위로 이동),
원래 지오메트리를 기억해 뒀다가 숨길 때 **그 창이 맞춘 상태 그대로일 때만** 복원한다(그 사이 사용자가 옮겼으면 건드리지 않음).

상태 파일: ~/.config/vkb/config.json (사용자 설정), ~/.local/state/vkb/fit.json (창 맞춤 기록)
시험용 환경변수: VKB_HYPRCTL, VKB_CONFIG_DIR, VKB_STATE_DIR, VKB_POSTURE(posture 명령), VKB_SYSTEMCTL
"""
import json
import os
import subprocess
import sys
import time

PRESETS = {"small": 240, "medium": 360, "large": 480}
ORDER = ["small", "medium", "large"]
MIN_WINDOW_H = 260          # 맞춘 뒤 창 높이가 이보다 작아지면 줄이지 않고 위로 옮김
UNIT = "wvkbd.service"

CONF_DIR = os.environ.get("VKB_CONFIG_DIR", os.path.expanduser("~/.config/vkb"))
STATE_DIR = os.environ.get("VKB_STATE_DIR", os.path.expanduser("~/.local/state/vkb"))
CONF = os.path.join(CONF_DIR, "config.json")
FIT = os.path.join(STATE_DIR, "fit.json")
HYPRCTL = os.environ.get("VKB_HYPRCTL", "hyprctl")
POSTURE = os.environ.get("VKB_POSTURE", "posture")
SYSTEMCTL = os.environ.get("VKB_SYSTEMCTL", "systemctl")


# ───────────────────────── 순수 로직 ─────────────────────────
def fit_plan(windows: list[dict], kb_top: int, min_h: int = MIN_WINDOW_H) -> dict:
    """키보드 윗면(kb_top, 화면 좌표) 아래로 내려온 floating 창들을 어떻게 맞출지 계산. {주소: (x, y, w, h)} 반환(바꿀 것만).
    - 창 아래끝이 kb_top 이하면 건드리지 않음
    - 높이를 줄여서 맞춰도 min_h 이상이면 높이만 줄임
    - 아니면 높이를 min_h(또는 원래보다 작게)로 하고 위로 올려서 아래끝을 kb_top 에 맞춤. 위쪽이 화면 위(top_limit)를 넘으면 y 는 top_limit
    windows 각 항목: {address, at:[x,y], size:[w,h], floating, hidden, ...}"""
    plan = {}
    for w in windows:
        if not w.get("floating") or w.get("hidden") or w.get("fullscreen"):
            continue
        x, y = w["at"]
        ww, hh = w["size"]
        bottom = y + hh
        if bottom <= kb_top:
            continue
        new_h = kb_top - y
        if new_h >= min_h:
            plan[w["address"]] = (x, y, ww, new_h)
        else:
            h2 = min(hh, max(min_h, 0))
            h2 = min(h2, kb_top)               # 화면이 아주 작아도 키보드 위로는 들어가게
            ny = max(0, kb_top - h2)
            plan[w["address"]] = (x, ny, ww, h2)
    return plan


def restore_plan(saved: dict, windows: list[dict]) -> dict:
    """저장해 둔 {주소: {"orig": [x,y,w,h], "fitted": [x,y,w,h]}} 에서, 지금도 **맞춘 상태 그대로인 창만** 원래 지오메트리로.
    (그 사이 사용자가 옮기거나 크기를 바꿨으면 건드리지 않음. 닫힌 창은 무시)"""
    cur = {w["address"]: w for w in windows}
    out = {}
    for addr, rec in saved.items():
        w = cur.get(addr)
        if not w:
            continue
        now = [w["at"][0], w["at"][1], w["size"][0], w["size"][1]]
        if now == rec["fitted"]:
            out[addr] = tuple(rec["orig"])
    return out


def next_size(cur: str, direction: str) -> str:
    i = ORDER.index(cur) if cur in ORDER else 1
    return ORDER[max(0, min(len(ORDER) - 1, i + (1 if direction == "up" else -1)))]


def cycle_size(cur: str) -> str:
    i = ORDER.index(cur) if cur in ORDER else 1
    return ORDER[(i + 1) % len(ORDER)]


def size_name(h: int) -> str:
    for k, v in PRESETS.items():
        if v == h:
            return k
    return "custom"


def desired_visibility(mode: str) -> bool:
    return mode in ("tent", "tablet")


# ───────────────────────── 설정/상태 ─────────────────────────
def load_conf() -> dict:
    d = {"height": 360, "auto": True, "layers": ""}
    try:
        d.update(json.load(open(CONF)))
    except (OSError, ValueError):
        pass
    return d


def save_conf(d: dict) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF + ".tmp"
    json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, CONF)


def run(*cmd, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=check)


def hypr_json(*args):
    r = run(HYPRCTL, *args, "-j")
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


# ───────────────────────── wvkbd 제어 ─────────────────────────
def main_pid() -> int:
    r = run(SYSTEMCTL, "--user", "show", "-p", "MainPID", "--value", UNIT).stdout.strip()
    return int(r) if r.isdigit() and int(r) > 0 else 0


def running() -> bool:
    return run(SYSTEMCTL, "--user", "is-active", "--quiet", UNIT).returncode == 0


def kb_layer() -> dict | None:
    """화면에 떠 있는 wvkbd 레이어 서피스(없으면 숨김 상태). {x,y,w,h}"""
    d = hypr_json("layers")
    if not d:
        return None
    for mon in d.values():
        for items in mon.get("levels", {}).values():
            for it in items:
                if "wvkbd" in it.get("namespace", ""):
                    return it
    return None


def signal_unit(sig: str) -> bool:
    if not running():
        return False
    return run(SYSTEMCTL, "--user", "kill", f"--signal={sig}", "--kill-whom=main", UNIT).returncode == 0


def fit_windows(show: bool) -> None:
    """보일 때 가려지는 창을 맞추고, 숨길 때 복원"""
    os.makedirs(STATE_DIR, exist_ok=True)
    wins = hypr_json("clients") or []
    try:
        saved = json.load(open(FIT))
    except (OSError, ValueError):
        saved = {}
    if show:
        layer = None
        for _ in range(20):                    # 키보드 서피스가 나타나 크기가 정해질 때까지 잠깐 기다림
            layer = kb_layer()
            if layer:
                break
            time.sleep(0.1)
        if not layer:
            return
        mons = {m["name"]: m for m in (hypr_json("monitors") or [])}
        # 가장 위(작은 y)인 키보드 윗면 = 화면 y + 레이어 서피스 y (hyprctl layers 의 y 는 모니터 기준)
        mon = next((m for m in mons.values() if m.get("focused")), next(iter(mons.values()), None))
        kb_top = (mon["y"] if mon else 0) + layer["y"]
        plan = fit_plan([w for w in wins if mon is None or w["monitor"] == mon["id"]], kb_top)
        for addr, (x, y, w, h) in plan.items():
            orig = next(c for c in wins if c["address"] == addr)
            if addr not in saved:              # 이미 맞춘 창이면 처음 원본을 유지
                saved[addr] = {"orig": [orig["at"][0], orig["at"][1], orig["size"][0], orig["size"][1]]}
            saved[addr]["fitted"] = [x, y, w, h]
            run(HYPRCTL, "dispatch", f"hl.dsp.window.resize({{ x = {w}, y = {h}, relative = false, window = \"address:{addr}\" }})")
            run(HYPRCTL, "dispatch", f"hl.dsp.window.move({{ x = {x}, y = {y}, relative = false, window = \"address:{addr}\" }})")
        json.dump(saved, open(FIT, "w"))
    else:
        plan = restore_plan(saved, wins)
        for addr, (x, y, w, h) in plan.items():
            run(HYPRCTL, "dispatch", f"hl.dsp.window.resize({{ x = {w}, y = {h}, relative = false, window = \"address:{addr}\" }})")
            run(HYPRCTL, "dispatch", f"hl.dsp.window.move({{ x = {x}, y = {y}, relative = false, window = \"address:{addr}\" }})")
        json.dump({}, open(FIT, "w"))


def refresh_bar() -> None:
    """waybar 모듈(signal 8)을 다시 그리게 함(없으면 무시). 상태가 바뀔 때만 부르므로 폴링이 없다."""
    run("pkill", "-RTMIN+8", "-x", "(.waybar-wrapped|waybar)")


def set_visible(show: bool) -> int:
    if not running():
        print("wvkbd 서비스가 실행 중이 아닙니다 (systemctl --user status wvkbd)", file=sys.stderr)
        return 1
    if show:
        signal_unit("SIGUSR2")
    else:
        signal_unit("SIGUSR1")
    fit_windows(show)
    refresh_bar()
    return 0


def status() -> dict:
    c = load_conf()
    layer = kb_layer()
    return {"running": running(), "visible": bool(layer), "height": c["height"], "auto": c["auto"], "layers": c["layers"],
            "surface": ({"y": layer["y"], "h": layer["h"], "w": layer["w"]} if layer else None)}


def restart(visible: bool) -> None:
    """높이/레이어를 바꾸면 wvkbd 를 다시 띄움(시작 인자). 보이던 상태면 다시 보이게."""
    run(SYSTEMCTL, "--user", "restart", UNIT)
    if visible:
        for _ in range(30):
            if main_pid():
                break
            time.sleep(0.1)
        time.sleep(0.4)
        set_visible(True)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    arg = argv[1] if len(argv) > 1 else ""
    if cmd in ("show", "hide"):
        return set_visible(cmd == "show")
    if cmd == "toggle":
        return set_visible(not bool(kb_layer()))
    if cmd == "size":
        c = load_conf()
        if arg in ("up", "down"):
            cur = next((k for k, v in PRESETS.items() if v == c["height"]), "medium")
            h = PRESETS[next_size(cur, arg)]
        elif arg == "cycle":
            h = PRESETS[cycle_size(size_name(c["height"]))]
        elif arg in PRESETS:
            h = PRESETS[arg]
        elif arg.isdigit() and 120 <= int(arg) <= 900:
            h = int(arg)
        else:
            print("사용: vkb size <small|medium|large|120~900|up|down|cycle>", file=sys.stderr)
            return 2
        if h == c["height"]:
            return 0
        vis = bool(kb_layer())
        # 보이던 키보드면 먼저 창 원복(크기가 바뀌기 전 상태 기준으로 복원)
        if vis:
            fit_windows(False)
        c["height"] = h
        save_conf(c)
        restart(vis)
        refresh_bar()
        return 0
    if cmd == "layers":
        c = load_conf()
        c["layers"] = arg
        save_conf(c)
        restart(bool(kb_layer()))
        return 0
    if cmd == "auto":
        if arg not in ("on", "off"):
            print("사용: vkb auto on|off", file=sys.stderr)
            return 2
        c = load_conf()
        c["auto"] = arg == "on"
        save_conf(c)
        return main(["apply-posture"]) if c["auto"] else 0
    if cmd == "apply-posture":
        c = load_conf()
        if not c["auto"]:
            return 0
        mode = run(POSTURE, "get", "mode").stdout.strip() or "laptop"
        want = desired_visibility(mode)
        if want != bool(kb_layer()):
            return set_visible(want)
        return 0
    if cmd == "waybar":
        # waybar custom 모듈 JSON. toggle: 아이콘(보임/숨김 클래스), size: 키보드가 보일 때만 현재 크기(S/M/L) — 숨김이면 빈 출력(모듈이 사라짐)
        st = status()
        if arg == "size":
            if not st["visible"]:
                return 0
            label = {"small": "S", "medium": "M", "large": "L"}.get(size_name(st["height"]), str(st["height"]))
            print(json.dumps({"text": label, "tooltip": f"가상 키보드 높이 {st['height']}px — 눌러서 크기 변경", "class": "vkbsize"}, ensure_ascii=False))
            return 0
        text = "⌨"
        cls = "on" if st["visible"] else "off"
        tip = ("가상 키보드 보임 — 눌러서 접기" if st["visible"] else "가상 키보드 숨김 — 눌러서 펴기") + f" (자세 연동 {'켜짐' if st['auto'] else '꺼짐'})"
        if not st["running"]:
            cls, tip = "off", "가상 키보드 서비스가 실행 중이 아닙니다"
        print(json.dumps({"text": text, "tooltip": tip, "class": cls}, ensure_ascii=False))
        return 0
    if cmd == "status":
        s = status()
        if "--json" in argv:
            print(json.dumps(s, ensure_ascii=False))
        else:
            print(f"실행 {'예' if s['running'] else '아니오'} · 보임 {'예' if s['visible'] else '아니오'} · 높이 {s['height']}px · 자세 연동 {'켜짐' if s['auto'] else '꺼짐'} · 레이어 {s['layers'] or '기본'}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
