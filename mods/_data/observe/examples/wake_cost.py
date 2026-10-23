#!/usr/bin/env python3
"""wake_cost.py — 깨움 사건 1회당 에너지(μJ) 측정 (R3). root 로 실행(RAPL 카운터 읽기).
한 코어에 고정한 프로세스가 초당 R 번 타이머로 깨어나는 부하를 만들고, R 을 바꿔 가며(라운드마다 순서 섞음) 구간 평균 전력을 RAPL 로 잰다.
같은 라운드 안에서 R=0 대비 증가분 ÷ 실제 깨움 횟수 = 깨움 1회당 에너지. 사용: sudo wake_cost.py [SEG초=45] [SETTLE=10] [ROUNDS=4] [CPU=2] [rates=0,500,2000,8000]"""
import os, random, statistics, sys, time
SEG = float(sys.argv[1]) if len(sys.argv) > 1 else 45; SETTLE = float(sys.argv[2]) if len(sys.argv) > 2 else 10
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 4; CPU = int(sys.argv[4]) if len(sys.argv) > 4 else 2
RATES = [int(x) for x in (sys.argv[5] if len(sys.argv) > 5 else "0,500,2000,8000").split(",")]
WRAP = 262143328850
def rd(i):
    with open("/sys/class/powercap/intel-rapl:%d/energy_uj" % i) as f: return int(f.read())
def seg(rate):
    """한 구간: 안정화 동안 부하만, 이후 측정. 반환 (psys W, pkg W, 실제 깨움/s)"""
    end = time.monotonic() + SEG; t_meas = time.monotonic() + SETTLE
    n = 0; started = False; e = None; t0 = None; n0 = 0
    period = 1.0 / rate if rate else None
    nxt = time.monotonic()
    while True:
        now = time.monotonic()
        if not started and now >= t_meas:
            started = True; e = (rd(1), rd(0)); t0 = time.monotonic(); n0 = n
        if now >= end: break
        if period is None:
            time.sleep(min(0.5, end - now)); continue
        nxt += period
        d = nxt - time.monotonic()
        if d > 0: time.sleep(d)
        else: nxt = time.monotonic()
        n += 1
    e1 = (rd(1), rd(0)); t1 = time.monotonic(); dt = t1 - t0
    return ((e1[0] - e[0]) % WRAP / 1e6 / dt, (e1[1] - e[1]) % WRAP / 1e6 / dt, (n - n0) / dt)
os.sched_setaffinity(0, {CPU})
rows = []
for r in range(ROUNDS):
    order = RATES[:]; random.shuffle(order)
    for rate in order:
        ps, pk, act = seg(rate); rows.append((r, rate, ps, pk, act))
        print("round %d rate %5d → 실제 %7.1f/s psys %.3f W pkg %.3f W" % (r, rate, act, ps, pk), flush=True)
print("\n깨움 1회당 에너지 (같은 라운드 R=0 대비, μJ):")
for rate in RATES:
    if rate == 0: continue
    out = {"psys": [], "pkg": []}
    for r in range(ROUNDS):
        base = [x for x in rows if x[0] == r and x[1] == 0]; cur = [x for x in rows if x[0] == r and x[1] == rate]
        if base and cur and cur[0][4] > 0:
            out["psys"].append((cur[0][2] - base[0][2]) / cur[0][4] * 1e6); out["pkg"].append((cur[0][3] - base[0][3]) / cur[0][4] * 1e6)
    for k, v in out.items():
        if v: print("  rate %5d %-4s: %s  평균 %.1f μJ%s" % (rate, k, " ".join("%.0f" % x for x in v), statistics.mean(v), "  표준편차 %.1f" % statistics.stdev(v) if len(v) > 1 else ""))
