"""Hyprland 접근: hyprctl 호출, 모니터 읽기(Mon), 모드 문자열."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from .config import HYPRCTL

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

    def logical(self, mode: str | None = None, scale: float | None = None, transform: int | None = None) -> tuple[int, int]:
        """배치에 쓰는 논리 크기 (해상도 / 배율, 회전 90/270 이면 가로세로 교환). transform 을 주면 현재 값 대신 그것으로 계산"""
        w, h = self.width, self.height
        if mode and mode != "preferred":
            pm = parse_mode(mode)
            if pm:
                w, h = pm[0], pm[1]
        sc = scale if scale else self.scale
        lw, lh = round(w / sc), round(h / sc)
        tr = self.transform if transform is None else transform
        return (lh, lw) if tr % 2 == 1 else (lw, lh)


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

def mode_groups(m: Mon) -> dict[str, list[float]]:
    g: dict[str, list[float]] = {}
    for w, h, hz in m.modes:
        g.setdefault(f"{w}x{h}", [])
        if not any(abs(hz - x) < 0.05 for x in g[f"{w}x{h}"]):
            g[f"{w}x{h}"].append(hz)
    return {k: sorted(v, reverse=True) for k, v in g.items()}
