#!/usr/bin/env python3
"""pc_idle_noise.py — 한가한 상태의 패키지 C-state 잔류율과 psys 를 같은 구간에서 반복 측정해 소음 폭과 둘의 관계를 본다. root 로 실행.
사용: sudo pc_idle_noise.py <perf 경로> [구간초=60] [구간수=12]   결과: 구간별 줄 + 요약(평균·표준편차·PC10 과 psys 의 상관)"""
import os, re, statistics, subprocess, sys
PERF = sys.argv[1]; SEG = int(sys.argv[2]) if len(sys.argv) > 2 else 60; N = int(sys.argv[3]) if len(sys.argv) > 3 else 12
EV = "msr/tsc/,cstate_pkg/c2-residency/,cstate_pkg/c3-residency/,cstate_pkg/c6-residency/,cstate_pkg/c8-residency/,cstate_pkg/c10-residency/,power/energy-psys/,power/energy-pkg/"
rows = []
for i in range(N):
    o = subprocess.run([PERF, "stat", "-a", "-x,", "-e", EV, "--", "sleep", str(SEG)], capture_output=True, text=True).stderr
    v = {}
    for l in o.splitlines():
        f = l.split(",")
        if len(f) > 3:
            try: v[f[2]] = float(f[0])
            except ValueError: pass
    base = v["msr/tsc/"] / os.cpu_count()
    pc = {k.split("/")[1].replace("-residency", ""): 100 * x / base for k, x in v.items() if "cstate" in k}
    psys = v.get("power/energy-psys/", 0) / SEG   # perf 가 이미 J 로 줌
    pkg = v.get("power/energy-pkg/", 0) / SEG
    pc["deep"] = pc["c8"] + pc["c10"]
    rows.append((pc, psys, pkg))
    print("seg %2d psys %.3f W pkg %.3f W  " % (i, psys, pkg) + " ".join("%s=%.1f%%" % kv for kv in pc.items()), flush=True)
def stat(xs): return "평균 %.3f 표준편차 %.3f" % (statistics.mean(xs), statistics.stdev(xs))
print("\n요약:")
print("  psys W", stat([r[1] for r in rows])); print("  pkg  W", stat([r[2] for r in rows]))
for k in rows[0][0]: print("  %s %%" % k, stat([r[0][k] for r in rows]))
x = [r[0]["deep"] for r in rows]; y = [r[1] for r in rows]
if statistics.stdev(x) > 0 and statistics.stdev(y) > 0:
    mx, my = statistics.mean(x), statistics.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)
    print("  PC8+PC10 잔류율과 psys: 상관 %.2f, 기울기 %.3f W/%%p" % (cov / (statistics.stdev(x) * statistics.stdev(y)), cov / statistics.variance(x)))
