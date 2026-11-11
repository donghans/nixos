#!/usr/bin/env python3
"""embedctl — MSI Summit E16Flip(MS-1592) 한 기종의 EC 상태(충전 상한·성능 모드·Cooler Boost)를 허용 목록으로만 다룬다.
lockdown 아래에서도 동작하도록 debugfs/WMI 없이 **sysfs(msi-ec 커널 모듈)만** 쓴다.

  embedctl status   [--json]                 기종·펌웨어 게이트, 충전 상한, 성능 모드, Cooler Boost, 팬 RPM·온도, 전원 상태(읽기 전용, 일반 사용자 권한)
  embedctl snapshot [--out 파일] [--json]    위 상태를 스냅샷(JSON, schema 2)으로. 파일은 --out 으로 지정할 때만 쓴다(자동 저장 없음)
  embedctl charge <50..100> [--json]         충전 상한(%)을 정한다. 100 이 「상한 없음」과 같다
  embedctl mode turbo|comfort|eco [--json]   성능 모드. turbo 는 과전압·오버클럭 모드다. sport 는 이 펌웨어에서 쓸 수 없다(비활성)
  embedctl boost on|off [--json]             Cooler Boost(팬 최대)
  embedctl restore <스냅샷> [--dry-run] [--json]   스냅샷의 충전 상한·성능 모드·Cooler Boost 로 되돌린다(먼저 전부 검증하고, 같은 값은 건너뜀)

쓰기 동작은 root helper(`embedctl-root@<동작>.service`, polkit 허용)가 게이트 → 쓰기 → 되읽기 확인 순서로 한다.
종료 코드: 0 성공 · 2 입력/사용법 오류 · 3 게이트·허용 목록 거부 · 4 권한(polkit)·helper 실패 · 5 되읽기 값 불일치.
msi-ec 가 없으면 `status` 는 게이트 `no_msi_ec` 와 이유를 내고 종료 코드 0 이며, 쓰기는 모두 거부(3)한다.
설계·근거: ctx `plan/embedctl-lockdown`, `plan/embedctl-구현`. 설치본에서는 ctlkit.py·embedlib.py 가 이 파일과 같은 디렉터리에 있다.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "..", "_lib", "ctlkit")):     # 설치본: 같은 디렉터리 / 소스: _lib/ctlkit
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)
import ctlkit      # noqa: E402
import embedlib as lib   # noqa: E402

CMD = "embedctl"
GATE_TEXT = {
    "verified": "검증됨",
    "unverified_fw": "미검증 펌웨어 — 쓰기 거부(읽기만)",
    "unsupported_board": "지원하지 않는 기종 — 쓰기 거부(읽기만)",
    "no_msi_ec": "msi-ec 없음 — EC 를 읽을 수 없고 쓰기 거부",
}
LABEL = lib.LABEL


class Fail(Exception):
    """종료 코드와 메시지를 함께 내는 실패. data 가 있으면 --json 봉투에 같이 실린다."""

    def __init__(self, code, msg, data=None):
        super().__init__(msg)
        self.code, self.msg, self.data = code, msg, data


def _cells(s):
    """터미널 칸 수(한글·전각은 2칸). `ljust` 는 글자 수라 한글 라벨 표가 어긋난다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def render_status(st):
    g, c, p = st["gate"], st["charge"], st["power"]
    rows = []
    rows.append(("기종", f"{g['board'] or '?'} · EC 펌웨어 {g['fw'] or '?'} ({GATE_TEXT[g['state']]})"))
    if c["end"] is None:
        rows.append(("충전 상한", "읽지 못함(sysfs 에 임계값 파일이 없음)"))
    else:
        eff = f"{c['limit']}%" + ("" if c["set"] else " (미설정 = 100% 로 동작)")
        rows.append(("충전 상한", f"{eff}  [sysfs end={c['end']}, start={c['start']}]"))
    if st["mode"]:
        m = st["mode"]
        rows.append(("성능 모드", f"{lib.mode_label(m['text'])}  [msi-ec shift_mode={m['text']}]"))
        w = st["modes"]["writable"]
        rows.append(("모드 선택지", (" · ".join(w) if w else "없음") + "  (turbo 는 오버클럭)" + "".join(f" · {d}(사용 불가)" for d in st["modes"]["disabled"])))
    else:
        rows.append(("성능 모드", "알 수 없음(msi-ec 없음)"))
    if st["boost"] is None:
        rows.append(("Cooler Boost", "알 수 없음(msi-ec 없음)"))
    else:
        rows.append(("Cooler Boost", "켜짐" if st["boost"] else "꺼짐"))
    fans = st["fans"]
    rows.append(("팬", " · ".join(f"fan{i + 1} {v}" for i, v in enumerate(fans)) + " RPM" if fans else "읽지 못함"))
    rows.append(("온도", f"패키지 {st['temp_pkg']:.1f}°C" if st["temp_pkg"] is not None else "읽지 못함"))
    ac = {True: "AC 연결", False: "배터리", None: "?"}[p["ac"]]
    rows.append(("전원", f"{ac} · {p['status'] or '?'} {p['capacity'] if p['capacity'] is not None else '?'}%"))
    w = max(_cells(k) for k, _ in rows)
    out = [f"{k}{' ' * (w - _cells(k))}  {v}" for k, v in rows]
    for x in st["warnings"]:
        out.append(f"(주의) {x}")
    return "\n".join(out)


def cmd_status(a):
    st = lib.collect_status()
    a.out.done(st)
    if a.json:
        for w in st["warnings"]:
            a.out.note(w)
    else:
        print(render_status(st))


def cmd_snapshot(a):
    snap = lib.make_snapshot(lib.collect_status())
    if a.out_file:
        path = os.path.abspath(a.out_file)
        try:
            with open(path, "w") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
                f.write("\n")
        except OSError as e:
            sys.exit(f"스냅샷을 쓰지 못했다({path}): {e}")
        snap["written"] = path
        if not a.json:
            print(f"스냅샷을 저장했다: {path}")
    elif not a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
    a.out.done(snap)


# --- 쓰기 동작 --------------------------------------------------------------------------------
def helper_act(inst):
    try:
        return lib.helper_call(inst, timeout=30)
    except lib.HelperError as e:
        raise Fail(e.code, str(e))


def cmd_action(a):
    kind = a.cmd
    inst = {"charge": f"charge-{getattr(a, 'percent', 0)}", "mode": f"mode-{getattr(a, 'value', '')}", "boost": f"boost-{getattr(a, 'value', '')}"}[kind]
    warnings = []
    if kind == "charge":
        for f, name, val in lib.tlp_charge_settings():
            warnings.append(f"TLP 설정에 {name}={val} 가 있다({f}) — TLP 가 다음에 적용할 때 이 값을 덮어쓸 수 있다")
    data, line = lib.action_summary(kind, helper_act(inst))
    data["warnings"] = warnings
    a.out.done(data)
    if a.json:
        for w in warnings:
            a.out.note(w)
    else:
        print(line)
        for w in warnings:
            print(f"(주의) {w}")


def cmd_restore(a):
    try:
        with open(a.file) as f:
            snap = json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(2, f"스냅샷을 읽지 못했다({a.file}): {e}")
    # 먼저 전부 검증한다(restore_plan 은 아무것도 쓰지 않는다): 하나라도 안 맞으면 아무것도 쓰지 않는다
    try:
        plan, notes = lib.restore_plan(snap, lib.collect_status())
    except lib.RestoreError as e:
        raise Fail(e.code, e.msg if e.code != 2 else f"{e.msg}: {a.file}")
    if not plan:
        print("이미 스냅샷과 같은 상태다 — 할 일이 없다.")
        a.out.done({"dry_run": a.dry_run, "plan": [], "applied": [], "notes": notes})
        return
    if a.dry_run:
        print("복원 계획(적용하지 않음):")
        for p in plan:
            print(f"  {p['text']}  [{p['instance']}]")
        a.out.done({"dry_run": True, "plan": [{"instance": p["instance"], "text": p["text"]} for p in plan], "applied": [], "notes": notes})
        return
    applied = []
    for p in plan:
        try:
            res = lib.helper_call(p["instance"], timeout=30)
        except lib.HelperError as e:
            done = [x["instance"] for x in applied]
            raise Fail(e.code, f"{p['instance']} 적용 실패: {e} (이미 적용된 것: {done or '없음'})", data={"applied": applied})
        data, line = lib.action_summary(p["kind"], res)
        data["instance"] = p["instance"]
        applied.append(data)
        print(line)
    for n in notes:
        print(f"(참고) {n}")
    a.out.done({"dry_run": False, "plan": [{"instance": p["instance"], "text": p["text"]} for p in plan], "applied": applied, "notes": notes})


# --- 실행 틀 ----------------------------------------------------------------------------------
def run(a, name, fn):
    """--json 이면 ctlkit 봉투로, 아니면 텍스트로. Fail(코드, 메시지)은 봉투의 error·exit_code 와 프로세스 종료 코드로 그대로 나간다."""
    cmd = f"{CMD} {name}"
    a.out = ctlkit.Out(a, bool(a.json))
    buf = io.StringIO()
    code, err, data = 0, None, None
    try:
        if a.json:
            with contextlib.redirect_stdout(buf):
                fn(a)
        else:
            fn(a)
    except Fail as f:
        code, err, data = f.code, f.msg, f.data
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, int):
                code = e.code
            else:
                code, err = 1, str(e.code)
    if a.json:
        if code:
            ctlkit.emit_json(cmd, False, data=data, text=buf.getvalue() or None, notes=a.out.notes, error=err or f"종료 코드 {code}", code=code)
        elif a.out.data is not None:
            ctlkit.emit_json(cmd, True, data=a.out.data, notes=a.out.notes)
        else:
            ctlkit.emit_json(cmd, True, text=buf.getvalue(), notes=a.out.notes)
    elif err:
        print(err, file=sys.stderr)
    if code:
        sys.exit(code)


def _percent(s):
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"정수여야 한다: {s!r}")
    if not (lib.CHARGE_MIN <= v <= lib.CHARGE_MAX):
        raise argparse.ArgumentTypeError(f"{lib.CHARGE_MIN}~{lib.CHARGE_MAX} 만 허용한다(받은 값 {v}). 100 이 「상한 없음」과 같다")
    return v


def _mode(s):
    if s in lib.DISABLED_MODES:
        raise argparse.ArgumentTypeError(f"{s} 는 쓸 수 없다 — {lib.DISABLED_MODES[s]}. 선택지: {', '.join(lib.MODE_ORDER)}")
    if s not in lib.MODE_ORDER:
        raise argparse.ArgumentTypeError(f"알 수 없는 모드 {s!r} (선택지: {', '.join(lib.MODE_ORDER)}; sport 는 사용 불가)")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(prog="embedctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="현재 상태(읽기 전용)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status, name="status")
    n = sub.add_parser("snapshot", help="상태 스냅샷(JSON)")
    n.add_argument("--out", dest="out_file", metavar="파일", help="이 경로에 저장(지정하지 않으면 표준출력)")
    n.add_argument("--json", action="store_true")
    n.set_defaults(fn=cmd_snapshot, name="snapshot")
    c = sub.add_parser("charge", help="충전 상한(%%)")
    c.add_argument("percent", type=_percent, metavar=f"{lib.CHARGE_MIN}..{lib.CHARGE_MAX}")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_action, name="charge")
    m = sub.add_parser("mode", help="성능 모드 (turbo=오버클럭 · comfort=균형 · eco=저전력; sport 는 사용 불가)",
                       description="성능 모드(msi-ec shift_mode). turbo = 과전압·오버클럭, comfort = 균형, eco = 저전력. sport 는 사용 불가 — 이 펌웨어에서 msi-ec 가 지원하지 않아 sysfs 로 쓸 수 없다. "
                                   "turbo/comfort/eco 로 바꾸면 sport 로는 되돌릴 수 없다.")
    m.add_argument("value", type=_mode)
    m.add_argument("--json", action="store_true")
    m.set_defaults(fn=cmd_action, name="mode")
    b = sub.add_parser("boost", help="Cooler Boost")
    b.add_argument("value", choices=["on", "off"])
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_action, name="boost")
    r = sub.add_parser("restore", help="스냅샷으로 복원")
    r.add_argument("file", metavar="스냅샷")
    r.add_argument("--dry-run", action="store_true", help="계획만 보이고 적용하지 않는다")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_restore, name="restore")
    a = ap.parse_args(argv)
    run(a, a.name, a.fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
