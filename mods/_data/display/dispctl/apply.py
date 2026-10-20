"""규칙 적용(겹침 방지 순서), 적용 검증, 창 이동, 화면 회전의 터치 동기화."""
from __future__ import annotations

import json
import time
from .config import SETTLE, VERIFY_TIMEOUT
from .hypr import Mon, eval_lua, get_monitors, hyprctl, parse_mode
from .observelog import events

_ev = events("dispctl")
from .layout import _overlap, lua_rule

def apply_cfg(cfg: dict, mons: list[Mon] | None = None) -> list[str]:
    """규칙 적용. 오류 메시지를 돌려준다.
    전환 중간에 켜진 두 모니터가 같은 위치에서 겹치면 Hyprland 가 화면에 "monitor layout is set up incorrectly ...
    overlaps" 말풍선(로그에는 안 남음)을 띄우므로, 어느 순간에도 켜진 모니터끼리 겹치지 않게 순서를 짠다.
    (끈 모니터와 미러는 겹침 검사에 들어가지 않음 — 실측)
      1) 끌 모니터 (적어도 하나가 계속 켜져 있을 때만 먼저 끔)
      2) 소스가 이미 켜져 있는 미러 (미러가 되면 겹침 검사에서 빠짐)
      3) 이미 켜져 있던 모니터의 재배치/모드 변경
      4) 꺼져 있다가(또는 미러였다가) 켜질 모니터. 지금 켜져 있는 모니터와 겹치면 먼저 오른쪽 끝의 임시 위치에 켬
      5) 나머지 미러
      6) 끌 모니터 (계속 켜져 있는 게 없을 때는 모든 화면이 꺼지는 순간을 피해 마지막에)
      7) 임시 위치에 켠 모니터를 최종 위치로"""
    cur = {m.name: m for m in (mons if mons is not None else get_monitors())}
    lit = {n for n, m in cur.items() if not m.disabled}                       # 화면이 켜진 모니터(미러 포함)
    on = {n for n in lit if not cur[n].mirror_of}                              # 그중 따로 영상을 내는 모니터 (겹침 검사 대상)
    dis = [n for n, c in cfg.items() if c.get("disabled")]
    mir = [n for n, c in cfg.items() if c.get("mirror")]
    plain = [n for n, c in cfg.items() if not c.get("disabled") and not c.get("mirror")]
    stays = any(n in lit for n in plain + mir)
    late = [n for n in dis if n in lit] if not stays else []
    # 미러의 소스가 이미 켜져 있으면 먼저 미러로 바꿔 겹침 검사에서 뺌
    early_mir = [n for n in mir if cfg[n]["mirror"] in on and cfg[n]["mirror"] in plain]
    late_mir = [n for n in mir if n not in early_mir]
    errs: list[str] = []
    _ev.info("apply.plan", lit=sorted(lit), disable=dis, mirror=mir, plain=plain, late=late, early_mirror=early_mir)

    def run(name: str, c: dict) -> None:
        out = eval_lua(lua_rule(name, c))
        _ev.info("apply.rule", mon=name, disabled=bool(c.get("disabled")), mirror=c.get("mirror"), mode=c.get("mode"), scale=c.get("scale"),
                 x=c.get("x"), y=c.get("y"), out=(out or "")[:200])
        if out and out != "ok":
            errs.append(f"{name}: {out}")

    def final_rect(n: str) -> tuple:
        c = cfg[n]
        w, h = cur[n].logical(c["mode"], c["scale"], c.get("transform"))
        return (c["x"], c["y"], w, h)

    def cur_rect(n: str) -> tuple:
        m = cur[n]
        return (m.x, m.y, *m.logical())

    for n in dis:
        if n not in late:
            run(n, cfg[n])
    for n in early_mir:
        run(n, cfg[n])
    present: list[tuple] = []
    for n in plain:
        if n in on:
            run(n, cfg[n])
            present.append(final_rect(n))
    # 아직 바뀌지 않은 채 남아 있는 모니터(나중에 미러가 되거나 꺼질 것들)는 지금 위치 그대로 존재
    present += [cur_rect(n) for n in on if n in late_mir or n in late]
    temp = []
    for n in plain:
        if n in on:
            continue
        fr = final_rect(n)
        if any(_overlap(fr, r) for r in present):
            right = max(r[0] + r[2] for r in present)
            run(n, dict(cfg[n], x=right, y=0))
            temp.append(n)
            present.append((right, 0, fr[2], fr[3]))
        else:
            run(n, cfg[n])
            present.append(fr)
    for n in late_mir:
        run(n, cfg[n])
    for n in late:
        run(n, cfg[n])
    for n in temp:
        run(n, cfg[n])
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
        if "transform" in c and m.transform != int(c["transform"] or 0):
            issues.append(f"{name}: 회전 {c['transform']} 요청 → 실제 {m.transform}")
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
    _ev.info("migrate.windows", leaving=sorted(leaving), target=target, moved=moved)
    return moved



# 사용 모드 허브의 rotation(기기를 시계방향으로 돌린 각도) → Hyprland monitor transform. 화면 내용은 기기와 반대로 돌려야 똑바로 보이므로
# 시계방향으로 90° 돌렸으면 내용을 반시계 90° 돌린다 = wl_output "90"(= transform 1). **실제 화면에서 확인 필요**(문서 참고).
ROTATION_TO_TRANSFORM = {0: 0, 90: 1, 180: 2, 270: 3}


def sync_touch(mons: list[Mon] | None = None) -> list[str]:
    """내장 화면의 회전을 터치스크린/스타일러스에 같이 적용한다. Hyprland 는 터치 좌표를 `모니터 위치 + 정규화 좌표 × 모니터 크기` 로만 계산해서
    모니터가 회전해도 터치는 따라 돌지 않으므로(소스 확인: Touch.cpp), 장치별 transform(libinput 보정 행렬)을 모니터 transform 과 같은 값으로 맞춘다.
    hl.device 설정은 reload 때 초기화되므로 restore 때도 다시 호출한다. 꺼진/미러인 내장 화면이면 0. 적용한 장치 이름 목록을 돌려준다."""
    mons = mons if mons is not None else get_monitors()
    internal = next((m for m in mons if m.internal), None)
    tr = internal.transform if internal and not internal.disabled and not internal.mirror_of else 0
    try:
        d = json.loads(hyprctl("devices", "-j").stdout or "{}")
    except ValueError:
        return []
    names = [x["name"] for k in ("touch", "tablets") for x in d.get(k, []) if x.get("name")]
    for n in names:
        eval_lua(f'hl.device({{ name = "{n}", transform = {tr} }})')
    return names


def target_transform(rotation: int, posture_mode: str) -> int:
    """사용 모드/기기 회전 → 내장 화면 transform. laptop 모드에서는 항상 0(세로로 들어도 돌리지 않음)"""
    return 0 if posture_mode == "laptop" else ROTATION_TO_TRANSFORM.get(int(rotation) % 360, 0)
