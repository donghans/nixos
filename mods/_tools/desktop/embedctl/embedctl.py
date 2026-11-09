#!/usr/bin/env python3
"""embedctl — MSI Summit E16Flip(MS-1592) 한 기종의 EC 상태(충전 상한·성능 모드·Cooler Boost)를 허용 목록으로만 다룬다.

  embedctl status   [--json]                 기종·펌웨어 게이트, 충전 상한, 성능 모드, Cooler Boost, 팬 RPM·온도, 전원 상태(읽기 전용)
  embedctl snapshot [--out 파일] [--json]    위 상태를 스냅샷(JSON)으로. 파일은 --out 으로 지정할 때만 쓴다(자동 저장 없음)

종료 코드: 0 성공 · 2 입력/사용법 오류 · 3 게이트·허용 목록 거부 · 4 권한(polkit)·helper 실패 · 5 되읽기 값 불일치.
EC 바이트를 못 읽는 환경(SSH 세션 등)에서도 `status` 는 사용자 권한으로 읽히는 부분만 내고 종료 코드 0 이다.
설계·근거: ctx `plan/embedctl-구현`. 설치본에서는 ctlkit.py·embedlib.py 가 이 파일과 같은 디렉터리에 있다.
"""
import argparse
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
    "unknown": "펌웨어를 읽지 못함 — 쓰기 거부",
}
ACCESS_TEXT = {"direct": "직접(root)", "helper": "helper(polkit)", "unavailable": "사용 불가 — EC 값 없음"}


def _cells(s):
    """터미널 칸 수(한글·전각은 2칸). `ljust` 는 글자 수라 한글 라벨 표가 어긋난다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def render_status(st):
    g, c, p = st["gate"], st["charge"], st["power"]
    rows = []
    rows.append(("기종", f"{g['board'] or '?'} · EC 펌웨어 {g['fw'] or '?'} ({GATE_TEXT[g['state']]})"))
    rows.append(("EC 접근", ACCESS_TEXT[st["access"]]))
    ec = st["ec"]
    if c["end"] is None:
        rows.append(("충전 상한", "읽지 못함(sysfs 에 임계값 파일이 없음)"))
    else:
        eff = f"{c['limit']}%" + ("" if c["set"] else " (미설정 = 100% 로 동작)")
        rows.append(("충전 상한", f"{eff}  [sysfs end={c['end']}, start={c['start']}" + (f", EC 0xD7=0x{ec['d7']:02X}" if ec else "") + "]"))
    if st["mode"]:
        m = st["mode"]
        flags = ("" if m["supported"] else " · 모드 미지원") + ("" if m["active"] else " · 비활성")
        rows.append(("성능 모드", f"{m['name']}{flags}  [EC 0xD2=0x{m['raw']:02X}]"))
        rows.append(("Cooler Boost", ("켜짐" if st["boost"] else "꺼짐") + f"  [EC 0x98=0x{ec['b98']:02X}]"))
    else:
        rows.append(("성능 모드", "알 수 없음(EC 를 읽지 못함)"))
        rows.append(("Cooler Boost", "알 수 없음(EC 를 읽지 못함)"))
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


def run(a, name, fn):
    if a.json:
        ctlkit.run_json(a, f"{CMD} {name}", fn)
    else:
        a.out = ctlkit.Out(a, False)
        try:
            fn(a)
        except SystemExit as e:
            if e.code not in (None, 0):
                print(e.code if isinstance(e.code, str) else f"종료 코드 {e.code}", file=sys.stderr)
                sys.exit(e.code if isinstance(e.code, int) else 1)


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
    a = ap.parse_args(argv)
    run(a, a.name, a.fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
