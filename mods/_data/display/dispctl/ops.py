"""동작(상태를 어떻게 바꿀지): layout/set/rotate/preset/back, 적용(go)과 복원(restore)."""
from __future__ import annotations

import copy
import json
import os
import sys
from .config import BUILTIN_PRESETS, CONF_DIR, PRESET_FILE
from .hypr import Mon, fmt_mode, get_monitors, mode_groups, parse_mode
from .state import default_state, load_state, locked, seed
from .layout import build
from .apply import apply_cfg, migrate_windows, sync_touch
from .transaction import Transaction, _pending_load, revert_pending

def mutated_state() -> dict:
    """현재 저장 상태(없으면 기본)를 복사하고 현재 모니터 값으로 채움"""
    st = load_state() or default_state()
    return seed(copy.deepcopy(st), get_monitors())


# ───────────────────────── 동작 ─────────────────────────
def current_arrange(st: dict | None, mons: list["Mon"]) -> str:
    """저장된 위치 설정에서 지금 확장 배치가 stack/left/right 중 무엇인지 (사용자 지정이면 'custom')"""
    ext = next((m for m in mons if not m.internal), None)
    internal = next((m for m in mons if m.internal), None)
    if ext is None or internal is None:
        return "stack"
    pos = (st or {}).get("pos") or {}
    spec = pos.get(ext.name)
    other = {k: v for k, v in pos.items() if k != ext.name}
    if other:
        return "custom"
    if not spec:
        return "stack"
    if spec.get("of") != internal.name or spec.get("align", "center") != "center":
        return "custom"
    return {"above": "stack", "left": "left", "right": "right"}.get(spec.get("rel"), "custom")


def op_layout(layout: str, arrange: str | None = None) -> dict:
    st = mutated_state()
    st["layout"] = layout
    if arrange:
        mons = get_monitors()
        ext = next((m for m in mons if not m.internal), None)
        internal = next((m for m in mons if m.internal), None)
        if ext is not None and internal is not None:
            st["pos"].pop(ext.name, None)
            st["pos"].pop(internal.name, None)
            if arrange in ("left", "right"):
                st["pos"][ext.name] = {"rel": arrange, "of": internal.name, "align": "center"}
    return st



def op_rotate(mon: str, transform: int) -> dict:
    """모니터의 회전(Hyprland transform 0~3)을 상태에 기록. 다른 값은 그대로(restore/레이아웃 변경에도 유지됨)"""
    st = mutated_state()
    m = next((x for x in get_monitors() if x.name == mon), None)
    ent = st["monitors"].setdefault(mon, {"mode": m.mode if m else "preferred", "scale": m.scale if m else 1.0})
    ent["transform"] = int(transform) % 4
    return st



def op_set(mon: str, res: str | None = None, hz: float | None = None, scale: float | None = None, pos: dict | None = None) -> dict:
    st = mutated_state()
    m = next((x for x in get_monitors() if x.name == mon), None)
    if m is None:
        raise SystemExit(f"모니터 없음: {mon}")
    cur = st["monitors"].setdefault(mon, {"mode": m.mode, "scale": m.scale})
    pm = parse_mode(cur["mode"]) or (m.width, m.height, m.hz)
    w, h = (int(x) for x in res.split("x")) if res else (pm[0], pm[1])
    if not hz:
        hz = pm[2]
        if res:
            # 해상도만 바꿀 때의 주사율: 그 해상도를 모니터가 지원하면 그중 가장 가까운 값, 아니면 정수로 반올림
            # (목록 밖 해상도에 현재 값 60.04 를 그대로 붙이면 "1920x1200@60.04" 가 거부됨 — 실측)
            native = mode_groups(m).get(f"{w}x{h}")
            hz = min(native, key=lambda x: abs(x - hz)) if native else float(round(hz))
    cur["mode"] = fmt_mode(w, h, hz)
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
    """시작·reload·모니터 연결/해제 때 호출: 저장된 구성을 다시 적용 (저장된 게 없으면 아무것도 안 함).
    확인되지 않은 변경(pending)이 남아 있으면(예: 확인 전에 재부팅/재로그인) 그 변경을 적용하지 않고 이전 구성으로 되돌린다."""
    with locked():
        if _pending_load():
            revert_pending()
            return 0
        st = load_state()
        if not st:
            return 0
        mons = get_monitors()
        if not mons:
            return 0
        cfg, _ = build(mons, st)
        migrate_windows(cfg)
        apply_cfg(cfg, mons)
        sync_touch()
        return 0
