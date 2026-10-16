#!/usr/bin/env python3
"""displayctl — Hyprland 화면 관리 (확장/미러/노트북만/외부만, 해상도·주사율·배율·상대 위치, 프리젠테이션)

원리
- 모니터 정보는 `hyprctl monitors all -j`, 변경은 `hyprctl eval 'hl.monitor({...})'` 로 한다.
- 모든 전환을 `hyprctl reload` 없이 "명시 규칙"으로 한다. 두 필드를 항상 같이 줘야 상태가 확실히 바뀐다:
  `disabled = false`(없으면 꺼졌던 모니터가 안 켜짐), `mirror = ""`(없으면 미러가 안 풀림).
- 사용자가 정한 구성은 상태 파일(~/.local/state/displayctl/state.json)에 두고, 시작·설정 reload·모니터 연결/해제 때
  `displayctl restore` 로 다시 적용한다 (Hyprland 는 reload 때 런타임 설정을 지움).
- 모니터가 알려 주는 모드(EDID) 외의 해상도/주사율도 시도할 수 있다. 적용 뒤 실제 모드를 읽어 요청과 다르면 알려 준다
  (예: 내장 패널은 48Hz 는 되지만 45/30Hz 는 60Hz 로 돌아감).

(Nix 가 @hyprctl@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/display-manager.nix)
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

HYPRCTL = os.environ.get("DISPLAYCTL_HYPRCTL", "@hyprctl@")
STATE_DIR = os.environ.get("DISPLAYCTL_STATE") or os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "displayctl"
)
CONF_DIR = os.environ.get("DISPLAYCTL_CONF") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "displayctl"
)
STATE_FILE = os.path.join(STATE_DIR, "state.json")
PRESET_FILE = os.path.join(CONF_DIR, "presets.json")
LOCK_FILE = os.path.join(STATE_DIR, "lock")
SETTLE = float(os.environ.get("DISPLAYCTL_SETTLE", "0.8"))  # 적용 뒤 실제 모드를 읽기 시작하기까지 기다리는 시간(초)
VERIFY_TIMEOUT = float(os.environ.get("DISPLAYCTL_VERIFY_TIMEOUT", "4"))  # 검증이 통과할 때까지 기다리는 최대 시간(초)

# 모니터가 알려 주지 않아도 시도해 볼 후보 (적용 뒤 실제 모드로 검증)
COMMON_RES = [
    "3840x2160", "2560x1600", "2560x1440", "1920x1200", "1920x1080",
    "1680x1050", "1600x900", "1440x900", "1366x768", "1280x800", "1280x720",
]
COMMON_HZ = [165, 144, 120, 100, 75, 60, 59.94, 50, 48, 45, 30, 24]
SCALES = [1, 1.25, 1.5, 1.6, 1.75, 2, 2.5, 3]
RELS = {"above": "위", "below": "아래", "left": "왼쪽", "right": "오른쪽"}
ALIGNS = {"start": "시작(위/왼쪽) 맞춤", "center": "가운데 맞춤", "end": "끝(아래/오른쪽) 맞춤"}

LAYOUTS = {
    "extend": "확장 (노트북 + 외부)",
    "mirror": "미러",
    "internal": "노트북 화면만",
    "external": "외부 화면만",
}

# 임시 프리셋: 적용 전 구성을 기억해 두었다가 `displayctl back` 으로 돌아갈 수 있다.
# "@external"/"@internal" 은 첫 번째 외부/내장 모니터를 뜻한다.
BUILTIN_PRESETS = {
    "presentation-1080p": {"label": "프리젠테이션 1920x1080 (미러)", "layout": "mirror", "modes": {"@external": "1920x1080@60"}},
    "presentation-1200p": {"label": "프리젠테이션 1920x1200 (미러)", "layout": "mirror", "modes": {"@external": "1920x1200@60"}},
    "presentation-900p": {"label": "프리젠테이션 1600x900 (미러)", "layout": "mirror", "modes": {"@external": "1600x900@60"}},
    "presentation-720p": {"label": "프리젠테이션 1280x720 (미러)", "layout": "mirror", "modes": {"@external": "1280x720@60"}},
    "laptop-1200p": {"label": "노트북만 1920x1200", "layout": "internal", "modes": {"@internal": "1920x1200@60"}},
    "laptop-native": {"label": "노트북만 2560x1600 60Hz", "layout": "internal", "modes": {"@internal": "2560x1600@60"}},
}


# ───────────────────────── Hyprland 접근 ─────────────────────────
def _env() -> dict:
    env = dict(os.environ)
    if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
        base = os.path.join(env.get("XDG_RUNTIME_DIR", ""), "hypr")
        try:
            dirs = sorted(
                (d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, ".socket.sock"))),
                key=lambda d: os.path.getmtime(os.path.join(base, d)),
            )
            if dirs:
                env["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[-1]
        except OSError:
            pass
    return env


def hyprctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([HYPRCTL, *args], capture_output=True, text=True, env=_env(), timeout=15)


@dataclass
class Mon:
    id: int
    name: str
    desc: str
    width: int
    height: int
    hz: float
    x: int
    y: int
    scale: float
    transform: int
    disabled: bool
    mirror_of: str | None
    modes: list[tuple[int, int, float]] = field(default_factory=list)

    @property
    def internal(self) -> bool:
        return self.name.startswith("eDP")

    @property
    def mode(self) -> str:
        return fmt_mode(self.width, self.height, self.hz)

    def logical(self, mode: str | None = None, scale: float | None = None) -> tuple[int, int]:
        """배치에 쓰는 논리 크기 (해상도 / 배율, 회전 90/270 이면 가로세로 교환)"""
        w, h = self.width, self.height
        if mode and mode != "preferred":
            pm = parse_mode(mode)
            if pm:
                w, h = pm[0], pm[1]
        sc = scale if scale else self.scale
        lw, lh = round(w / sc), round(h / sc)
        return (lh, lw) if self.transform % 2 == 1 else (lw, lh)


def parse_mode(s: str):
    m = re.match(r"^(\d+)x(\d+)@([\d.]+)(?:Hz)?$", s.strip())
    return (int(m[1]), int(m[2]), float(m[3])) if m else None


def fmt_mode(w: int, h: int, hz: float) -> str:
    return f"{w}x{h}@{('%.2f' % hz).rstrip('0').rstrip('.')}"


def get_monitors() -> list[Mon]:
    r = hyprctl("monitors", "all", "-j")
    data = json.loads(r.stdout or "[]")
    names = {m["id"]: m["name"] for m in data}
    out = []
    for m in data:
        mir = m.get("mirrorOf")
        mirror_of = None if mir in (None, "none", "") else names.get(int(mir), str(mir))
        modes = [pm for pm in (parse_mode(s) for s in m.get("availableModes", [])) if pm]
        out.append(Mon(
            id=m["id"], name=m["name"], desc=m.get("description", ""), width=m["width"], height=m["height"],
            hz=float(m["refreshRate"]), x=m["x"], y=m["y"], scale=float(m["scale"]), transform=m.get("transform", 0),
            disabled=bool(m.get("disabled")), mirror_of=mirror_of, modes=modes,
        ))
    return out


def eval_lua(code: str) -> str:
    return hyprctl("eval", code).stdout.strip()


# ───────────────────────── 상태 파일 ─────────────────────────
def default_state() -> dict:
    return {"layout": "extend", "monitors": {}, "pos": {}, "before": None, "preset": None}


def load_state() -> dict | None:
    """저장된 사용자 구성. 없으면 None (= 설정 파일의 기본 구성을 그대로 둠)"""
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        base = default_state()
        base.update(st)
        return base
    except (OSError, ValueError):
        return None


def save_state(st: dict | None) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    if st is None:
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def seed(st: dict, mons: list[Mon]) -> dict:
    """상태에 아직 없는 모니터의 현재 모드/배율을 기록 (이후 레이아웃을 바꿔도 해상도 등이 유지되도록)"""
    for m in mons:
        if m.name not in st["monitors"] and not m.disabled and m.width and m.height:
            st["monitors"][m.name] = {"mode": m.mode, "scale": m.scale}
    return st


# ───────────────────────── 구성 계산 ─────────────────────────
def _off(ref_len: int, my_len: int, align: str) -> int:
    return 0 if align == "start" else (ref_len - my_len) // 2 if align == "center" else ref_len - my_len


def build(mons: list[Mon], st: dict) -> tuple[dict, str]:
    """상태 + 현재 모니터 목록 → 모니터별 규칙. (규칙, 실제로 적용된 레이아웃) 을 돌려준다.
    연결된 모니터로 불가능한 레이아웃(예: 외장이 없는데 '외부만')은 확장으로 바꿔 화면이 모두 꺼지지 않게 한다."""
    internals = [m for m in mons if m.internal]
    externals = [m for m in mons if not m.internal]
    layout = st.get("layout", "extend")
    if layout in ("mirror", "external") and not externals:
        layout = "extend"
    if layout == "internal" and not internals:
        layout = "extend"

    enabled = {"extend": internals + externals, "mirror": internals + externals, "internal": internals, "external": externals}[layout]
    en = {m.name for m in enabled}

    def intent(m: Mon) -> tuple[str, float]:
        s = st["monitors"].get(m.name, {})
        return s.get("mode") or m.mode, float(s.get("scale") or m.scale)

    cfg: dict[str, dict] = {}
    for m in mons:
        if m.name not in en:
            cfg[m.name] = {"disabled": True}

    mirror_src = externals[0] if layout == "mirror" else None
    placed: dict[str, tuple[int, int]] = {}
    sizes: dict[str, tuple[int, int]] = {}
    for m in enabled:
        mode, scale = intent(m)
        sizes[m.name] = m.logical(mode, scale)
        cfg[m.name] = {"mode": mode, "scale": scale}

    layout_mons = [m for m in enabled if not (layout == "mirror" and m.internal)]
    order = [m.name for m in layout_mons]

    def default_spec(m: Mon) -> dict | None:
        i = order.index(m.name)
        if i == 0:
            return None
        if layout == "extend" and m.name == (externals[0].name if externals else "") and internals:
            return {"rel": "above", "of": internals[0].name, "align": "start"}
        return {"rel": "right", "of": order[i - 1], "align": "start"}

    def resolve(name: str, stack: tuple = ()) -> tuple[int, int]:
        if name in placed:
            return placed[name]
        m = next(x for x in layout_mons if x.name == name)
        spec = st["pos"].get(name)
        if not spec or spec.get("of") not in order or spec["of"] == name or spec["of"] in stack or name in stack:
            spec = default_spec(m)
        if spec is None:
            placed[name] = (0, 0)
            return placed[name]
        rx, ry = resolve(spec["of"], stack + (name,))
        rw, rh = sizes[spec["of"]]
        mw, mh = sizes[name]
        rel, al = spec.get("rel", "right"), spec.get("align", "start")
        if rel == "above":
            pos = (rx + _off(rw, mw, al), ry - mh)
        elif rel == "below":
            pos = (rx + _off(rw, mw, al), ry + rh)
        elif rel == "left":
            pos = (rx - mw, ry + _off(rh, mh, al))
        else:
            pos = (rx + rw, ry + _off(rh, mh, al))
        placed[name] = pos
        return pos

    for m in layout_mons:
        cfg[m.name]["x"], cfg[m.name]["y"] = resolve(m.name)
    for m in enabled:
        if layout == "mirror" and m.internal:
            cfg[m.name]["mirror"] = mirror_src.name
    return cfg, layout


def current_cfg(mons: list[Mon]) -> dict:
    """현재 실제 모니터 상태를 규칙으로 (되돌리기용)"""
    cfg = {}
    for m in mons:
        if m.disabled:
            cfg[m.name] = {"disabled": True}
        else:
            c = {"mode": m.mode, "scale": m.scale, "x": m.x, "y": m.y}
            if m.mirror_of:
                c["mirror"] = m.mirror_of
            cfg[m.name] = c
    return cfg


def lua_rule(name: str, c: dict) -> str:
    if c.get("disabled"):
        return f'hl.monitor({{ output = "{name}", disabled = true }})'
    pos = "auto" if "x" not in c or c.get("mirror") else f'{c["x"]}x{c["y"]}'
    return (
        f'hl.monitor({{ output = "{name}", mode = "{c["mode"]}", position = "{pos}", scale = {c["scale"]}, '
        f'disabled = false, mirror = "{c.get("mirror", "")}" }})'
    )


def apply_cfg(cfg: dict) -> list[str]:
    """규칙 적용. 켜는 것 → 미러 → 끄는 것 순서 (모든 화면이 한꺼번에 꺼지는 순간을 피함). 오류 메시지를 돌려준다."""
    def rank(item):
        c = item[1]
        return 2 if c.get("disabled") else 1 if c.get("mirror") else 0
    errs = []
    for name, c in sorted(cfg.items(), key=rank):
        out = eval_lua(lua_rule(name, c))
        if out and out != "ok":
            errs.append(f"{name}: {out}")
    return errs


def _check(cfg: dict) -> list[str]:
    mons = {m.name: m for m in get_monitors()}
    issues = []
    for name, c in cfg.items():
        m = mons.get(name)
        if m is None:
            continue
        if c.get("disabled"):
            if not m.disabled:
                issues.append(f"{name}: 꺼지지 않음")
            continue
        if m.disabled:
            issues.append(f"{name}: 켜지지 않음")
            continue
        if c.get("mirror"):
            if m.mirror_of != c["mirror"]:
                issues.append(f"{name}: 미러가 적용되지 않음")
            continue
        want = parse_mode(c["mode"]) if c["mode"] != "preferred" else None
        if want and (m.width, m.height) != (want[0], want[1]):
            issues.append(f"{name}: 해상도 {c['mode']} 요청 → 실제 {m.mode}")
        elif want and abs(m.hz - want[2]) > 0.6:
            issues.append(f"{name}: 주사율 {want[2]:g}Hz 요청 → 실제 {m.hz:.2f}Hz (이 모니터가 받아들이지 않음)")
        if "x" in c and (m.x, m.y) != (c["x"], c["y"]):
            issues.append(f"{name}: 위치 {c['x']},{c['y']} 요청 → 실제 {m.x},{m.y}")
    return issues


def verify(cfg: dict) -> list[str]:
    """적용 결과를 읽어 요청과 다르면 설명을 돌려준다.
    모니터 전환은 시간이 걸리므로(끄기/켜기/미러는 1~3초) 문제가 없어질 때까지 잠시 기다리며 다시 확인한다."""
    time.sleep(SETTLE)
    deadline = time.time() + VERIFY_TIMEOUT
    while True:
        issues = _check(cfg)
        if not issues or time.time() >= deadline:
            return issues
        time.sleep(0.4)


def migrate_windows(cfg: dict) -> int:
    """꺼지거나 미러가 될 모니터에 있는 창을 남는 모니터로 먼저 옮긴다.
    (모니터가 사라질 때 그 화면에 있던 kitty 가 libwayland-client 에서 segfault 로 죽는 일이 있었음 — 창을 먼저 비워 둠)"""
    mons = get_monitors()
    leaving = {m.name for m in mons if cfg.get(m.name, {}).get("disabled") or cfg.get(m.name, {}).get("mirror")}
    keep = [m for m in mons if m.name not in leaving and not cfg.get(m.name, {}).get("disabled")]
    already_off = {m.name for m in mons if m.disabled}
    leaving -= already_off
    if not leaving or not keep:
        return 0
    target = keep[0].name
    by_id = {m.id: m.name for m in mons}
    moved = 0
    try:
        clients = json.loads(hyprctl("clients", "-j").stdout or "[]")
    except ValueError:
        return 0
    for c in clients:
        if by_id.get(c.get("monitor")) in leaving and c.get("address"):
            hyprctl("dispatch", f'hl.dsp.window.move({{ monitor = "{target}", window = "address:{c["address"]}" }})')
            moved += 1
    if moved:
        time.sleep(0.3)
    return moved


# ───────────────────────── 트랜잭션 (되돌리기 지원) ─────────────────────────
class Transaction:
    """적용 전 실제 구성과 상태 파일을 기억해 두고, 확인 시 저장하거나 되돌린다."""

    def __init__(self) -> None:
        self.prev_state = load_state()
        self.prev_cfg = current_cfg(get_monitors())
        self.cfg: dict = {}
        self.layout = "extend"

    def apply(self, st: dict, do_verify: bool = True) -> list[str]:
        mons = get_monitors()
        self.cfg, self.layout = build(mons, st)
        self.new_state = st
        migrate_windows(self.cfg)
        errs = apply_cfg(self.cfg)
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

    def commit(self) -> None:
        save_state(self.new_state)

    def revert(self) -> list[str]:
        migrate_windows(self.prev_cfg)
        errs = apply_cfg(self.prev_cfg)
        save_state(self.prev_state)
        return errs


def mutated_state() -> dict:
    """현재 저장 상태(없으면 기본)를 복사하고 현재 모니터 값으로 채움"""
    st = load_state() or default_state()
    return seed(copy.deepcopy(st), get_monitors())


# ───────────────────────── 동작 ─────────────────────────
def op_layout(layout: str) -> dict:
    st = mutated_state()
    st["layout"] = layout
    return st


def op_set(mon: str, res: str | None = None, hz: float | None = None, scale: float | None = None, pos: dict | None = None) -> dict:
    st = mutated_state()
    m = next((x for x in get_monitors() if x.name == mon), None)
    if m is None:
        raise SystemExit(f"모니터 없음: {mon}")
    cur = st["monitors"].setdefault(mon, {"mode": m.mode, "scale": m.scale})
    pm = parse_mode(cur["mode"]) or (m.width, m.height, m.hz)
    w, h = (int(x) for x in res.split("x")) if res else (pm[0], pm[1])
    cur["mode"] = fmt_mode(w, h, hz if hz else pm[2])
    if scale:
        cur["scale"] = float(scale)
    if pos is not None:
        st["pos"][mon] = pos
    return st


def resolve_preset(name: str, mons: list[Mon]) -> dict | None:
    """프리셋 → 상태. 임시 프리셋이면 적용 전 구성을 before 에 기억"""
    user = load_presets().get(name)
    st = mutated_state()
    if user:
        before = {k: copy.deepcopy(st[k]) for k in ("layout", "monitors", "pos")}
        st.update({k: copy.deepcopy(user[k]) for k in ("layout", "monitors", "pos") if k in user})
        st["preset"] = name
        st["before"] = st.get("before") or before
        return st
    b = BUILTIN_PRESETS.get(name)
    if not b:
        return None
    before = {k: copy.deepcopy(st[k]) for k in ("layout", "monitors", "pos")}
    ext = next((m for m in mons if not m.internal), None)
    internal = next((m for m in mons if m.internal), None)
    for target, mode in b["modes"].items():
        m = ext if target == "@external" else internal
        if m is None:
            continue
        st["monitors"].setdefault(m.name, {"mode": m.mode, "scale": m.scale})["mode"] = mode
    st["layout"] = b["layout"]
    st["preset"] = name
    st["before"] = st.get("before") or before
    return st


def op_back() -> dict | None:
    st = load_state()
    if not st or not st.get("before"):
        return None
    st = copy.deepcopy(st)
    st.update(st.pop("before"))
    st["before"] = None
    st["preset"] = None
    return st


def load_presets() -> dict:
    try:
        with open(PRESET_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_presets(p: dict) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(PRESET_FILE, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)


def go(st: dict, quiet: bool = False) -> int:
    tx = Transaction()
    issues = tx.apply(st)
    tx.commit()
    if not quiet:
        for i in issues:
            print("⚠ " + i, file=sys.stderr)
    return 1 if issues else 0


def restore() -> int:
    """시작·reload·모니터 연결/해제 때 호출: 저장된 구성을 다시 적용 (저장된 게 없으면 아무것도 안 함)"""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOCK_FILE, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = load_state()
        if not st:
            return 0
        mons = get_monitors()
        if not mons:
            return 0
        cfg, _ = build(mons, st)
        migrate_windows(cfg)
        apply_cfg(cfg)
        return 0


# ───────────────────────── 출력 ─────────────────────────
def table(rows: list[list[str]]) -> str:
    from unicodedata import east_asian_width

    def w(s: str) -> int:
        return sum(2 if east_asian_width(c) in "WF" else 1 for c in s)
    widths = [max(w(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c + " " * (widths[i] - w(c)) for i, c in enumerate(r)).rstrip() for r in rows)


def cmd_status(a) -> int:
    mons = get_monitors()
    st = load_state()
    if a.json:
        print(json.dumps({"monitors": [m.__dict__ for m in mons], "state": st}, ensure_ascii=False, indent=1))
        return 0
    rows = [["모니터", "설명", "모드", "배율", "위치", "상태"]]
    for m in mons:
        stat = "꺼짐" if m.disabled else f"미러({m.mirror_of})" if m.mirror_of else "켜짐"
        rows.append([m.name, m.desc[:28], m.mode, f"x{m.scale:g}", f"{m.x},{m.y}", stat])
    print(table(rows))
    if st:
        extra = f" (프리셋: {st['preset']})" if st.get("preset") else ""
        print(f"\n저장된 구성: 레이아웃 {st['layout']}{extra}" + ("  ← `displayctl back` 으로 이전 구성 복귀 가능" if st.get("before") else ""))
    else:
        print("\n저장된 구성 없음 (설정 파일의 기본 구성)")
    return 0


def mode_groups(m: Mon) -> dict[str, list[float]]:
    g: dict[str, list[float]] = {}
    for w, h, hz in m.modes:
        g.setdefault(f"{w}x{h}", [])
        if not any(abs(hz - x) < 0.05 for x in g[f"{w}x{h}"]):
            g[f"{w}x{h}"].append(hz)
    return {k: sorted(v, reverse=True) for k, v in g.items()}


def cmd_modes(a) -> int:
    mons = {m.name: m for m in get_monitors()}
    m = mons.get(a.monitor)
    if not m:
        print(f"모니터 없음: {a.monitor} (있는 것: {', '.join(mons)})", file=sys.stderr)
        return 1
    g = mode_groups(m)
    print(f"{m.name} — 모니터가 알려 준 모드 (EDID)")
    for res, hzs in sorted(g.items(), key=lambda kv: -int(kv[0].split("x")[0]) * int(kv[0].split("x")[1])):
        print(f"  {res:>10}: " + "  ".join(f"{x:g}" for x in hzs) + " Hz")
    custom = [r for r in COMMON_RES if r not in g]
    print("\n사용자 지정으로 시도해 볼 수 있는 해상도(되는지는 적용 후 확인): " + ", ".join(custom))
    print("사용자 지정 주사율 후보: " + ", ".join(f"{x:g}" for x in COMMON_HZ) + " Hz")
    return 0


def parse_pos(s: str) -> dict:
    p = s.split(":")
    if p[0] not in RELS or len(p) < 2:
        raise SystemExit("위치 형식: <above|below|left|right>:<기준 모니터>[:start|center|end]")
    return {"rel": p[0], "of": p[1], "align": p[2] if len(p) > 2 else "start"}


def cmd_set(a) -> int:
    st = op_set(a.monitor, a.res, a.hz, a.scale, parse_pos(a.pos) if a.pos else None)
    tx = Transaction()
    issues = tx.apply(st)
    for i in issues:
        print("⚠ " + i, file=sys.stderr)
    if a.confirm:
        print(f"{a.confirm}초 안에 Enter 를 누르면 유지, 아니면 되돌립니다.", file=sys.stderr)
        import select
        ready, _, _ = select.select([sys.stdin], [], [], a.confirm)
        if not ready:
            tx.revert()
            print("되돌렸습니다.", file=sys.stderr)
            return 2
    tx.commit()
    return 1 if issues else 0


def cmd_layout(a) -> int:
    return go(op_layout(a.name))


def cmd_present(a) -> int:
    if a.res == "off":
        return cmd_back(a)
    name = f"presentation-{a.res.split('x')[1]}p" if f"presentation-{a.res.split('x')[1]}p" in BUILTIN_PRESETS and not a.hz else None
    st = mutated_state()
    before = {k: copy.deepcopy(st[k]) for k in ("layout", "monitors", "pos")}
    mons = get_monitors()
    ext = next((m for m in mons if not m.internal), None)
    target = ext or next((m for m in mons if m.internal), None)
    if target is None:
        print("모니터 없음", file=sys.stderr)
        return 1
    st["monitors"].setdefault(target.name, {"mode": target.mode, "scale": target.scale})["mode"] = fmt_mode(*(int(x) for x in a.res.split("x")), a.hz or 60)
    st["layout"] = "extend" if a.extend or not ext else "mirror"
    st["preset"] = name or "presentation"
    st["before"] = st.get("before") or before
    return go(st)


def cmd_back(a) -> int:
    st = op_back()
    if st is None:
        print("돌아갈 이전 구성이 없습니다.", file=sys.stderr)
        return 1
    return go(st)


def cmd_preset(a) -> int:
    ps = load_presets()
    if a.action == "list":
        print("내장:")
        for k, v in BUILTIN_PRESETS.items():
            print(f"  {k:20} {v['label']}")
        print("사용자:" + ("" if ps else " (없음)"))
        for k in ps:
            print(f"  {k}")
        return 0
    if not a.name:
        print("이름이 필요합니다", file=sys.stderr)
        return 1
    if a.action == "save":
        st = mutated_state()
        ps[a.name] = {k: st[k] for k in ("layout", "monitors", "pos")}
        save_presets(ps)
        print(f"저장: {a.name}")
        return 0
    if a.action == "delete":
        ps.pop(a.name, None)
        save_presets(ps)
        return 0
    st = resolve_preset(a.name, get_monitors())
    if st is None:
        print(f"프리셋 없음: {a.name}", file=sys.stderr)
        return 1
    return go(st)


def cmd_reset(a) -> int:
    save_state(None)
    hyprctl("reload")
    return 0


def cmd_restore(a) -> int:
    return restore()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="displayctl", description="Hyprland 화면 관리")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="모니터 현황")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("modes", help="모니터가 지원하는 해상도/주사율")
    s.add_argument("monitor")
    s.set_defaults(fn=cmd_modes)
    s = sub.add_parser("layout", help="확장/미러/노트북만/외부만")
    s.add_argument("name", choices=list(LAYOUTS))
    s.set_defaults(fn=cmd_layout)
    s = sub.add_parser("set", help="해상도/주사율/배율/위치 변경")
    s.add_argument("monitor")
    s.add_argument("--res", help="예: 1920x1080")
    s.add_argument("--hz", type=float, help="예: 60, 48")
    s.add_argument("--scale", type=float)
    s.add_argument("--pos", help="above|below|left|right:<기준 모니터>[:start|center|end]")
    s.add_argument("--confirm", type=int, metavar="초", help="이 시간 안에 Enter 가 없으면 되돌림")
    s.set_defaults(fn=cmd_set)
    s = sub.add_parser("present", help="프리젠테이션 모드 (해상도 고정). off 로 복귀")
    s.add_argument("res", help="예: 1920x1080, 1600x900, off")
    s.add_argument("--hz", type=float)
    s.add_argument("--extend", action="store_true", help="미러 대신 확장 상태로 외부 해상도만 고정")
    s.set_defaults(fn=cmd_present)
    s = sub.add_parser("back", help="임시 프리셋/프리젠테이션 적용 전 구성으로 복귀")
    s.set_defaults(fn=cmd_back)
    s = sub.add_parser("preset", help="프리셋 목록/적용/저장/삭제")
    s.add_argument("action", choices=["list", "load", "save", "delete"])
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_preset)
    s = sub.add_parser("reset", help="저장된 구성을 지우고 설정 파일의 기본 구성으로")
    s.set_defaults(fn=cmd_reset)
    s = sub.add_parser("restore", help="저장된 구성을 다시 적용 (시작/reload/모니터 변경 시 자동 호출)")
    s.set_defaults(fn=cmd_restore)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
