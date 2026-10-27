#!/usr/bin/env python3
"""touch-trace — 터치스크린의 원시 입력(libinput debug-events)을 기록하고 제스처 관점으로 요약한다.

  touch_trace.py record <초> [장치노드]   sudo 로 libinput debug-events 를 기록(장치는 이름 "ELAN Touchscreen" 을 /sys/class/input 에서 찾음). 결과를 파일에 남김
  touch_trace.py analyze <기록 파일>      접촉 묶음(모든 손가락이 떼어질 때까지)별로 동시 손가락 수, 재접촉(끊김), 손가락별 이동, 시작 위치를 표로
  touch_trace.py edges <기록 파일>        접촉별 시작 위치(가장자리까지 거리)와 이동량/시간 — 가장자리 스와이프 진단

왜 만들었나(2026-10-19): hyprgrass 제스처가 안 될 때 로그가 안 나와서(Hyprland 의 DEBUG 로그가 파일/저널에 안 남음) 원시 입력으로 원인을 찾았다.
  - 3손가락을 대고 끌면 접촉이 자주 끊겼다 다시 잡혀(15개 중 14개, 간격 중앙값 0.04초) 손가락 수가 바뀌며 제스처가 끝남 → 손가락 수에 덜 민감한 제스처로
  - 가장자리 스와이프는 맨 끝에서 시작한 접촉이 ~0.1초 뒤 끝나(최대 41px 이동) 연속 추적형(gesture)으로는 안 됐고, 완료형(bind)으로 바꾸니 됨
기록 형식 주의: 좌표 필드 앞에 공백이 있을 수 있다(`  0.00/52.59`) — 처음에 이것 때문에 왼쪽 가장자리 접촉이 통째로 빠졌다.
"""
import math
import re
import subprocess
import sys

LINE = re.compile(r"\s*event\d+\s+(TOUCH_\w+)\s+\+([\d.]+)s\s+(\d+) \((\d+)\)(?:\s+([\d.]+)/\s*([\d.]+) \(\s*([\d.]+)/\s*([\d.]+)mm\))?")


def parse(text: str) -> list:
    """[(이벤트, 시각, 슬롯, (x%, y%, x_mm, y_mm) 또는 None)]"""
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            pos = (float(m[5]), float(m[6]), float(m[7]), float(m[8])) if m[5] else None
            out.append((m[1], float(m[2]), int(m[3]), pos))
    return out


def sessions(rows: list) -> list:
    """모든 손가락이 떼어질 때까지를 한 묶음으로."""
    out, cur, active = [], None, set()
    for ev, t, s, p in rows:
        if ev == "TOUCH_DOWN":
            cur = cur if cur is not None else []
            active.add(s)
        if cur is not None:
            cur.append((ev, t, s, p))
        if ev == "TOUCH_UP":
            active.discard(s)
            if not active and cur is not None:
                out.append(cur)
                cur = None
    return out


def summarize(sess: list) -> dict:
    """한 묶음의 요약: 동시 최대 손가락, DOWN 횟수, 재접촉 간격, 손가락별 이동(mm), 지속 시간."""
    act, mx, downs, lastup, gaps, first, last = set(), 0, 0, {}, [], {}, {}
    for ev, t, s, p in sess:
        if ev == "TOUCH_DOWN":
            downs += 1
            if s in lastup:
                gaps.append(round(t - lastup[s], 2))
            act.add(s)
            mx = max(mx, len(act))
            if p:
                first.setdefault(s, p)      # 끊겼다 다시 닿아도 처음 위치를 유지(그 손가락이 처음부터 얼마나 움직였는지)
                last[s] = p
        elif ev == "TOUCH_MOTION" and p and s in last:
            last[s] = p
        elif ev == "TOUCH_UP":
            act.discard(s)
            lastup[s] = t
    moves = {s: (last[s][2] - first[s][2], last[s][3] - first[s][3]) for s in first}
    return {"max_fingers": mx, "downs": downs, "retouches": max(downs - mx, 0), "gaps": gaps, "moves_mm": moves,
            "duration": sess[-1][1] - sess[0][1]}


def touches(rows: list) -> list:
    """접촉(DOWN~UP) 하나하나의 궤적: {"t0","t1","pts":[(t, x%, y%)]}"""
    out, cur = [], {}
    for ev, t, s, p in rows:
        if ev == "TOUCH_DOWN" and p:
            cur[s] = {"t0": t, "pts": [(t, p[0], p[1])]}
        elif ev == "TOUCH_MOTION" and s in cur and p:
            cur[s]["pts"].append((t, p[0], p[1]))
        elif ev == "TOUCH_UP" and s in cur:
            c = cur.pop(s)
            c["t1"] = t
            out.append(c)
    return out


def find_touchscreen() -> str | None:
    import glob, os
    for d in sorted(glob.glob("/sys/class/input/event*")):
        try:
            if open(f"{d}/device/name").read().strip() == "ELAN Touchscreen":
                return "/dev/input/" + os.path.basename(d)
        except OSError:
            pass
    return None


def cmd_analyze(path: str, width_px: int = 2560) -> int:
    ss = sessions(parse(open(path).read()))
    print(f"접촉 묶음 {len(ss)}개\n #  동시  지속(s)  재접촉  손가락별 이동(mm)")
    for i, se in enumerate(ss, 1):
        r = summarize(se)
        mv = " ".join(f"{s}:({dx:+.0f},{dy:+.0f})" for s, (dx, dy) in sorted(r["moves_mm"].items()))
        print(f"{i:2d}  {r['max_fingers']:4d}  {r['duration']:6.2f}  {r['retouches']:5d}   {mv}")
    multi = [summarize(s) for s in ss if summarize(s)["max_fingers"] >= 3]
    if multi:
        gaps = sorted(g for r in multi for g in r["gaps"])
        print(f"\n3손가락 이상 {len(multi)}개 묶음 중 재접촉이 있었던 것 {sum(1 for r in multi if r['retouches'])}개, 재접촉 {sum(r['retouches'] for r in multi)}회"
              + (f", 간격 중앙값 {gaps[len(gaps)//2]}s, 최대 {gaps[-1]}s" if gaps else ""))
    return 0


def cmd_edges(path: str, width_px: int = 2560, height_px: int = 1600) -> int:
    print(" #  방향     시작x(px) 가장자리까지  이동dx(px)  dy(px)  시간(s)")
    for i, c in enumerate(touches(parse(open(path).read())), 1):
        a, b = c["pts"][0], c["pts"][-1]
        sx = a[1] / 100 * width_px
        dx, dy = (b[1] - a[1]) / 100 * width_px, (b[2] - a[2]) / 100 * height_px
        print(f"{i:2d}  {'오른쪽' if sx > width_px / 2 else '왼쪽  '}  {sx:8.0f}  {min(sx, width_px - sx):9.0f}   {dx:+9.0f}  {dy:+6.0f}  {c['t1'] - c['t0']:6.2f}")
    return 0


def main(argv: list) -> int:
    if len(argv) >= 2 and argv[0] == "analyze":
        return cmd_analyze(argv[1])
    if len(argv) >= 2 and argv[0] == "edges":
        return cmd_edges(argv[1])
    if argv[:1] == ["record"] and len(argv) >= 2:
        dev = argv[2] if len(argv) > 2 else find_touchscreen()
        if not dev:
            print("터치스크린 장치를 찾지 못했습니다", file=sys.stderr)
            return 1
        out = f"/tmp/touch-trace-{int(__import__('time').time())}.rec"
        print(f"{dev} 를 {argv[1]}초 기록 → {out} (지금 시험하세요)")
        with open(out, "w") as f:
            subprocess.run(["sudo", "timeout", argv[1], "libinput", "debug-events", "--device", dev], stdout=f, stderr=subprocess.STDOUT)
        return cmd_analyze(out)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
