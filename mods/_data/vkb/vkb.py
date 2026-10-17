#!/usr/bin/env python3
"""vkb — 가상 키보드(wvkbd) 제어: 접기/펴기, 크기 조절, 창 가림 방지, 자세 연동.

  vkb show | hide | toggle          키보드 보이기/숨기기 (wvkbd 에 시그널; 보일 때 가려지는 창은 키보드 위로 맞춤, 숨기면 원래대로)
  vkb size <small|medium|large|MM>   키 한 줄 높이 프리셋(8/10/12.5mm) 또는 mm(4~30). 화면 dpi 로 픽셀을 계산. 설정 저장 후 다시 띄움(wvkbd 는 높이를 시작할 때만 받음)
  vkb size up | down                 프리셋을 한 단계 크게/작게
  vkb size cycle                     small → medium → large → small (터치 버튼용: 한 번 탭하면 다음 크기)
  vkb mode <dock|float|toggle>       하단 고정(창이 줄어듦) / 플로팅(화면 아래에서 띄워 창 위에 겹침). 둘 다 같은 폭(가운데). 키보드 안의 ⧉ 키도 같은 동작
  vkb keywidth <mm>                  키 한 개 폭(8~30mm). 키보드 폭 = 15키 × 이 값
  vkb waybar [toggle|size|mode]      waybar 사용자 지정 모듈용 JSON. 노트북 모드에서는 키보드가 떠 있을 때만 보임(텐트/태블릿에서 항상 보임)
  vkb args                           wvkbd 실행 인자(한 줄에 하나): 화면 물리 크기로 계산한 높이/폭/글자 크기, 모드, 레이어
  vkb status                         상태 요약 (JSON 이면 --json)
  vkb auto on | off                  자세 연동: 텐트/태블릿이면 자동으로 보이고 노트북 모드면 숨김 (기본 켜짐)
  vkb apply-posture                  자세 허브 소비자(멱등): auto 가 켜져 있으면 현재 자세에 맞춤
  vkb layers <full,special,...>      쓸 레이어(wvkbd -l). 비우면 기본값(full,...). 한 번에 하나만 쓰려면 예: full

wvkbd 는 패치(mods/_data/wvkbd/float-hangul-numrow.patch)를 적용해 쓴다: 플로팅 모드(--float, 시그널 RTMIN+1 토글/+2 도킹/+3 플로팅), ⧉ 키, 한/영 키,
가로 배열의 숫자 줄, 모드가 바뀐 뒤 호출하는 훅(--on-mode → `vkb mode-changed`). 높이는 여전히 시작할 때만 받으므로 크기는 재시작으로 처리하고,
접고 펴기는 시그널(SIGUSR1 숨김 / SIGUSR2 표시 / SIGRTMIN 토글)로 한다.

크기: 키 한 줄 높이를 mm 로 정하고 화면 물리 크기(hyprctl monitors 의 physicalWidth)로 픽셀을 계산한다(가로 배열 5줄, 세로 배열 6줄).
키보드 폭은 도킹/플로팅 모두 15키 × 키 폭(기본 16mm)으로 가운데에 두고(화면 전체 폭으로 늘리지 않음), 글자 크기는 줄 높이에 비례.

창 가림 방지(하단 고정일 때만): wvkbd 는 기본으로 하단 배타 영역(exclusive zone)을 요청해서 타일/최대화 창은 자동으로 줄어든다. 떠 있는(floating) 창은
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

PRESETS = {"small": 8.0, "medium": 10.0, "large": 12.5}      # 키 한 줄 높이(mm)
ORDER = ["small", "medium", "large"]
KEY_MM = 16.0               # 키 한 개 폭(mm). 키보드 폭 = 15키 × 이 값(도킹/플로팅 공통, 화면 전체 폭으로 늘리지 않음)
LAND_ROWS, PORT_ROWS, LAND_UNITS = 5, 6, 15
FLOAT_MARGIN = 12           # 플로팅 키보드와 화면 아래 사이(px)
DEFAULT_GEOM = {"w": 2560, "h": 1600, "mm_w": 340.0, "mm_h": 220.0}
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


def size_name(v) -> str:
    """설정값(프리셋 이름 또는 mm)의 표시 이름"""
    if v in PRESETS:
        return v
    for k, mm in PRESETS.items():
        try:
            if abs(mm - float(v)) < 0.01:
                return k
        except (TypeError, ValueError):
            break
    return "custom"


def row_mm_of(size) -> float:
    if size in PRESETS:
        return PRESETS[size]
    try:
        return min(30.0, max(4.0, float(size)))
    except (TypeError, ValueError):
        return PRESETS["medium"]


def compute_layout(row_mm: float, key_mm: float, geom: dict) -> dict:
    """화면 물리 크기로 키보드 치수를 계산. geom: 논리 픽셀 w,h 와 물리 mm_w,mm_h. 높이는 화면의 45% 를 넘기지 않음."""
    ppm = geom["w"] / geom["mm_w"]                 # 논리 픽셀/mm
    row = row_mm * ppm
    cap = geom["h"] * 0.45
    land = int(min(round(row * LAND_ROWS), cap))
    port = int(min(round(row * PORT_ROWS), cap))
    row_px = land / LAND_ROWS
    return {"land": land, "port": port, "width": int(min(round(LAND_UNITS * key_mm * ppm), geom["w"])),
            "font_pt": int(max(12, min(32, round(row_px * 0.24)))), "ppm": round(ppm, 3)}


def desired_visibility(mode: str) -> bool:
    return mode in ("tent", "tablet")


# ───────────────────────── 설정/상태 ─────────────────────────
def load_conf() -> dict:
    d = {"size": "medium", "key_mm": KEY_MM, "mode": "dock", "auto": True, "layers": ""}
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


def geom() -> dict:
    """포커스된(없으면 첫) 모니터의 논리 픽셀 크기와 물리 크기(mm). 못 읽으면 이 기기 기본값."""
    mons = hypr_json("monitors") or []
    m = next((x for x in mons if x.get("focused")), mons[0] if mons else None)
    try:
        sc = float(m.get("scale") or 1.0)
        w, h = m["width"] / sc, m["height"] / sc
        mw, mh = float(m["physicalWidth"]), float(m["physicalHeight"])
        if m.get("transform", 0) % 2 == 1:         # 90/270도 회전: 가로세로가 바뀜
            w, h, mw, mh = h, w, mh, mw
        if w > 0 and mw > 0:
            return {"w": w, "h": h, "mm_w": mw, "mm_h": mh}
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return dict(DEFAULT_GEOM)


def wvkbd_args(c: dict, g: dict) -> list[str]:
    L = compute_layout(row_mm_of(c["size"]), float(c["key_mm"]), g)
    a = ["-H", str(L["port"]), "-L", str(L["land"]), "--fn", f"NanumGothic {L['font_pt']}", "--hidden"]
    a += ["--width", str(L["width"]), "--float-margin", str(FLOAT_MARGIN)]
    if c["mode"] == "float":
        a.append("--float")
    if c["layers"]:
        a += ["-l", c["layers"], "--landscape-layers", c["layers"]]
    return a


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
    fit_windows(show and load_conf()["mode"] == "dock")
    refresh_bar()
    return 0


def status() -> dict:
    c = load_conf()
    layer = kb_layer()
    return {"running": running(), "visible": bool(layer), "size": size_name(c["size"]), "row_mm": row_mm_of(c["size"]), "mode": c["mode"],
            "auto": c["auto"], "layers": c["layers"], "surface": ({"y": layer["y"], "h": layer["h"], "w": layer["w"]} if layer else None)}


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
        cur = size_name(c["size"])
        if arg in ("up", "down"):
            new = next_size(cur, arg)
        elif arg == "cycle":
            new = cycle_size(cur)
        elif arg in PRESETS:
            new = arg
        else:
            try:
                mm = float(arg)
            except ValueError:
                mm = 0
            if not 4 <= mm <= 30:
                print("사용: vkb size <small|medium|large|4~30(mm)|up|down|cycle>", file=sys.stderr)
                return 2
            new = size_name(mm) if size_name(mm) != "custom" else mm
        if new == c["size"]:
            return 0
        vis = bool(kb_layer())
        # 보이던 키보드면 먼저 창 원복(크기가 바뀌기 전 상태 기준으로 복원)
        if vis:
            fit_windows(False)
        c["size"] = new
        save_conf(c)
        restart(vis)
        refresh_bar()
        return 0
    if cmd == "keywidth":
        try:
            mm = float(arg)
        except ValueError:
            mm = 0
        if not 8 <= mm <= 30:
            print("사용: vkb keywidth <8~30(mm)>", file=sys.stderr)
            return 2
        c = load_conf()
        if mm == float(c["key_mm"]):
            return 0
        vis = bool(kb_layer())
        if vis:
            fit_windows(False)
        c["key_mm"] = mm
        save_conf(c)
        restart(vis)
        return 0
    if cmd == "mode":
        c = load_conf()
        want = {"dock": "dock", "float": "float", "toggle": "float" if c["mode"] == "dock" else "dock"}.get(arg)
        if not want:
            print("사용: vkb mode <dock|float|toggle>", file=sys.stderr)
            return 2
        if want == c["mode"]:
            return 0
        if running():
            # wvkbd 가 모드를 바꾸고 훅(vkb mode-changed)으로 알려줌: 설정 저장/창 맞춤은 거기서
            signal_unit("SIGRTMIN+3" if want == "float" else "SIGRTMIN+2")
        else:
            c["mode"] = want
            save_conf(c)
        return 0
    if cmd == "mode-changed":
        # wvkbd 의 --on-mode 훅. 환경변수 WVKBD_MODE=dock|float
        m = os.environ.get("WVKBD_MODE", arg)
        if m not in ("dock", "float"):
            return 2
        c = load_conf()
        c["mode"] = m
        save_conf(c)
        fit_windows(False)                      # 이전 모드에서 맞춰 둔 창을 원복
        if m == "dock":
            for _ in range(10):                 # 키보드가 다시 나타났는지(보이는 상태였는지) 잠깐 확인
                if kb_layer():
                    fit_windows(True)
                    break
                time.sleep(0.1)
        refresh_bar()
        return 0
    if cmd == "args":
        print("\n".join(wvkbd_args(load_conf(), geom())))
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
        if c["auto"]:
            mode = run(POSTURE, "get", "mode").stdout.strip() or "laptop"
            if desired_visibility(mode) != bool(kb_layer()):
                return set_visible(desired_visibility(mode))   # 안에서 waybar 도 갱신
        refresh_bar()                          # 자세가 바뀌면 waybar 버튼이 나타나거나 사라져야 함
        return 0
    if cmd == "waybar":
        # waybar custom 모듈 JSON. 빈 출력이면 모듈이 사라짐. 노트북 모드에서는 키보드가 떠 있을 때만 보임(텐트/태블릿에서는 항상)
        st = status()
        posture = run(POSTURE, "get", "mode").stdout.strip() or "laptop"
        if posture == "laptop" and not st["visible"]:
            return 0
        if arg == "size":
            if not st["visible"]:
                return 0
            label = {"small": "S", "medium": "M", "large": "L"}.get(st["size"], f"{st['row_mm']:g}")
            print(json.dumps({"text": label, "tooltip": f"가상 키보드 키 높이 {st['row_mm']:g}mm — 눌러서 크기 변경", "class": "vkbsize"}, ensure_ascii=False))
            return 0
        if arg == "mode":
            if not st["visible"]:
                return 0
            fl = st["mode"] == "float"
            print(json.dumps({"text": "⧉", "tooltip": ("플로팅 — 눌러서 하단 고정" if fl else "하단 고정 — 눌러서 플로팅(창을 줄이지 않고 위에 겹침)"),
                              "class": "on" if fl else "off"}, ensure_ascii=False))
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
            print(f"실행 {'예' if s['running'] else '아니오'} · 보임 {'예' if s['visible'] else '아니오'} · 크기 {s['size']}({s['row_mm']:g}mm) · 모드 {'플로팅' if s['mode'] == 'float' else '하단 고정'} · 자세 연동 {'켜짐' if s['auto'] else '꺼짐'} · 레이어 {s['layers'] or '기본'}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
