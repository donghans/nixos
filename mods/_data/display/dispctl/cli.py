"""명령줄 인터페이스(argparse, cmd_* 와 출력)."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from .config import ARRANGES, BUILTIN_PRESETS, COMMON_HZ, COMMON_RES, LAYOUTS, POSTURE, RELS
from .hypr import fmt_mode, get_monitors, hyprctl, split_roles
from .state import load_state, locked, save_state
from .apply import sync_touch, target_transform
from .transaction import Transaction, _pending_clear, _pending_load, cancel_timer, revert_pending
from .ops import go, load_presets, mutated_state, op_back, op_layout, op_rotate, op_set, resolve_preset, restore, save_presets
from .hypr import mode_groups

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
        raise SystemExit("위치 형식: <above|below|left|right>:<기준 모니터>[:start|center|end] (정렬 기본 center)")
    return {"rel": p[0], "of": p[1], "align": p[2] if len(p) > 2 else "center"}


def cmd_set(a) -> int:
    st = op_set(a.monitor, a.res, a.hz, a.scale, parse_pos(a.pos) if a.pos else None)
    tx = Transaction()
    issues = tx.apply(st)
    if a.confirm:
        # 확인을 기다리는 동안 이 프로세스가 죽어도 되돌려지도록 별도 타이머를 먼저 예약 (확인 시간 + 여유 3초)
        tx.arm(a.confirm + 3)
    for i in issues:
        print("⚠ " + i, file=sys.stderr)
    if a.confirm:
        print(f"{a.confirm}초 안에 Enter 를 누르면 유지, 아니면 되돌립니다.", file=sys.stderr)
        import select
        ready, _, _ = select.select([sys.stdin], [], [], a.confirm)
        # 입력이 없거나(시간 초과), 입력 없이 닫힌 경우(EOF)는 확인으로 보지 않음
        if not ready or sys.stdin.readline() == "":
            tx.revert()
            print("되돌렸습니다.", file=sys.stderr)
            return 2
    tx.commit()
    return 1 if issues else 0


def cmd_confirm(a) -> int:
    with locked():
        p = _pending_load()
        if not p:
            print("확인할 변경이 없습니다.", file=sys.stderr)
            return 1
        if p.get("new_state"):
            save_state(p["new_state"])
        _pending_clear()
    cancel_timer()
    return 0


def cmd_revert_pending(a) -> int:
    revert_pending(from_timer=True)
    return 0


def cmd_rotate(a) -> int:
    """displayctl rotate <0|1|2|3|auto> [monitor]. auto: 사용 모드 허브(posture)의 방향을 내장 화면에 반영(laptop 이면 0)"""
    try:
        mons = get_monitors()
    except ValueError:
        return 0        # 컴포지터가 아직 없음(로그인 직전 사용 모드 허브 소비자가 먼저 도는 경우): hyprctl 이 JSON 이 아닌 오류 문장을 냄. 할 일이 없다
    internal = next((m for m in mons if m.internal), None)
    target = next((m for m in mons if m.name == a.monitor), None) if a.monitor else internal
    if target is None:
        print("회전할 모니터가 없습니다", file=sys.stderr)
        return 1
    if a.value == "auto":
        try:                                      # 한 번에 읽음(호출당 파이썬 시작 ~50ms)
            out = subprocess.run([POSTURE, "get", "mode", "rotation"], capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            out = []
        mode = out[0] if out else "laptop"
        rot = out[1] if len(out) > 1 else ""
        want = target_transform(int(rot) if rot.isdigit() else 0, mode)
    elif a.value in ("0", "1", "2", "3"):
        want = int(a.value)
    else:
        print("사용: displayctl rotate <0|1|2|3|auto> [monitor]  (Hyprland transform: 1=90° 2=180° 3=270°)", file=sys.stderr)
        return 2
    if target.disabled or target.mirror_of:
        return 0                                  # 꺼졌거나 미러인 화면은 돌리지 않음
    if target.transform == want:
        return 0                                  # 이미 그 방향이면 아무것도 안 함(깜빡임/불필요한 재적용 방지). 터치는 restore 가 맞춤
    with locked():
        rc = go(op_rotate(target.name, want), quiet=True)
        sync_touch()
        return rc


def cmd_layout(a) -> int:
    return go(op_layout(a.name, a.arrange))


def cmd_present(a) -> int:
    if a.res == "off":
        return cmd_back(a)
    name = f"presentation-{a.res.split('x')[1]}p" if f"presentation-{a.res.split('x')[1]}p" in BUILTIN_PRESETS and not a.hz else None
    st = mutated_state()
    before = {k: copy.deepcopy(st[k]) for k in ("layout", "monitors", "pos")}
    mons = get_monitors()
    mains, subs = split_roles(mons)
    ext = subs[0] if subs else None
    target = ext or (mains[0] if mains else None)
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
    s = sub.add_parser("rotate", help="화면 회전: 0~3(Hyprland transform) 또는 auto(사용 모드 허브의 방향을 내장 화면에 반영)")
    s.add_argument("value")
    s.add_argument("monitor", nargs="?", help="기본은 내장 화면")
    s.set_defaults(fn=cmd_rotate)
    s = sub.add_parser("layout", help="확장/미러/내장만/외부만")
    s.add_argument("name", choices=list(LAYOUTS))
    s.add_argument("--arrange", choices=list(ARRANGES), help="확장 배치(가운데 정렬): stack=외부 위/내장 아래, left=외부 왼쪽, right=외부 오른쪽")
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
    s = sub.add_parser("confirm", help="확인 대기 중인 변경을 유지하고 되돌리기 타이머를 취소")
    s.set_defaults(fn=cmd_confirm)
    s = sub.add_parser("revert-pending", help="확인되지 않은 변경을 이전 구성으로 되돌림 (되돌리기 타이머가 부름)")
    s.set_defaults(fn=cmd_revert_pending)
    a = p.parse_args(argv)
    return a.fn(a)
