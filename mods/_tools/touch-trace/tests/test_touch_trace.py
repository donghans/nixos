#!/usr/bin/env python3
"""touch-trace 파서/요약 시험(실측 기록에서 뽑은 줄 형식 포함)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_lib", "_testkit"))
import touch_trace as tt
from harness import checker
check, finish = checker()

REC = """-event4   DEVICE_ADDED                 ELAN Touchscreen                  seat0 default group1  cap:t  size 332x226mm ntouches 10 calib
 event4   TOUCH_DOWN                   +0.000s\t0 (0) 99.97/51.62 (332.00/116.50mm)
 event4   TOUCH_MOTION                 +0.050s\t0 (0) 99.50/51.60 (330.40/116.50mm)
 event4   TOUCH_UP                     +0.123s\t0 (0)
 event4   TOUCH_DOWN                   +2.580s\t0 (0)  0.00/52.59 ( 0.00/118.70mm)
 event4   TOUCH_DOWN                   +2.600s\t1 (1) 10.00/52.00 (33.20/117.40mm)
 event4   TOUCH_UP                     +2.700s\t1 (1)
 event4   TOUCH_DOWN                   +2.740s\t1 (1) 10.10/52.00 (33.50/117.40mm)
 event4   TOUCH_MOTION                 +2.800s\t1 (1) 20.00/52.00 (66.40/117.40mm)
 event4   TOUCH_UP                     +2.900s\t1 (1)
 event4   TOUCH_UP                     +2.950s\t0 (0)
"""
rows = tt.parse(REC)
check("좌표 앞에 공백이 있는 줄(왼쪽 가장자리 0.00%)도 파싱", any(r[3] and r[3][0] == 0.0 for r in rows), str(len(rows)))
check("DEVICE_ADDED 줄은 무시", all(r[0].startswith("TOUCH_") for r in rows) and len(rows) == 10)
ss = tt.sessions(rows)
check("모든 손가락이 떼어질 때까지가 한 묶음(2개)", len(ss) == 2, str(len(ss)))
r = tt.summarize(ss[1])
check("묶음 2: 동시 최대 2, DOWN 3회 → 재접촉 1회, 간격 0.04초", r["max_fingers"] == 2 and r["downs"] == 3 and r["retouches"] == 1 and r["gaps"] == [0.04], str(r))
check("손가락별 이동(mm): 슬롯 1 은 (끊겼다 다시 닿아도) 처음 위치 기준", abs(r["moves_mm"][1][0] - (66.40 - 33.20)) < 1e-6, str(r["moves_mm"]))
t = tt.touches(rows)
check("접촉 4개(재접촉은 별개 접촉)", len(t) == 4, str(len(t)))
check("첫 접촉: 오른쪽 끝에서 시작해 이동 0.5%", abs(t[0]["pts"][0][1] - 99.97) < 1e-9 and abs(t[0]["pts"][-1][1] - 99.50) < 1e-9)
finish("touch-trace")
