"""구성 계산(순수 함수): 상태 + 모니터 → 모니터별 규칙, Lua 규칙 문자열."""
from __future__ import annotations
from .hypr import Mon


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

    def intent(m: Mon) -> tuple[str, float, int]:
        s = st["monitors"].get(m.name, {})
        return s.get("mode") or m.mode, float(s.get("scale") or m.scale), int(s.get("transform") or 0) % 4

    cfg: dict[str, dict] = {}
    for m in mons:
        if m.name not in en:
            cfg[m.name] = {"disabled": True}

    mirror_src = externals[0] if layout == "mirror" else None
    placed: dict[str, tuple[int, int]] = {}
    sizes: dict[str, tuple[int, int]] = {}
    for m in enabled:
        mode, scale, tr = intent(m)
        sizes[m.name] = m.logical(mode, scale, tr)
        cfg[m.name] = {"mode": mode, "scale": scale, "transform": tr}

    layout_mons = [m for m in enabled if not (layout == "mirror" and m.internal)]
    order = [m.name for m in layout_mons]

    def default_spec(m: Mon) -> dict | None:
        i = order.index(m.name)
        if i == 0:
            return None
        if layout == "extend" and m.name == (externals[0].name if externals else "") and internals:
            return {"rel": "above", "of": internals[0].name, "align": "center"}
        return {"rel": "right", "of": order[i - 1], "align": "center"}

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
            c = {"mode": m.mode, "scale": m.scale, "x": m.x, "y": m.y, "transform": m.transform}
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
        f'transform = {int(c.get("transform") or 0)}, disabled = false, mirror = "{c.get("mirror", "")}" }})'
    )


def _overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
