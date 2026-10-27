#!/usr/bin/env python3
"""stop_candidates.py — 후보 프로세스를 SIGSTOP 으로 멈춰 두고 패키지 C-state 잔류율·전력을 비교한다(되돌림은 SIGCONT, 종료·중단 때 반드시 실행). root 로 실행.
사용: sudo stop_candidates.py <perf 경로> <구간초> <안정화초> <라운드> <comm1,comm2,...>   (comm 은 /proc/<pid>/comm 의 정확한 이름, 기준선은 자동 포함)"""
import os, random, signal, statistics, subprocess, sys, time
PERF, SEG, SETTLE, ROUNDS, CANDS = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5].split(",")
EV = "msr/tsc/,cstate_pkg/c8-residency/,cstate_pkg/c10-residency/,power/energy-psys/,power/energy-pkg/"
stopped = set()
def pids(comm):
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if open("/proc/%s/comm" % d).read().strip() == comm and os.getpgid(int(d)) is not None: out.append(int(d))
            except Exception: pass
    return out
def cont_all():
    for p in list(stopped):
        try: os.kill(p, signal.SIGCONT)
        except ProcessLookupError: pass
        stopped.discard(p)
for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(s, lambda *a: (cont_all(), sys.exit(130)))
def measure():
    time.sleep(SETTLE)
    o = subprocess.run([PERF, "stat", "-a", "-x,", "-e", EV, "--", "sleep", str(SEG - SETTLE)], capture_output=True, text=True).stderr
    v = {}
    for l in o.splitlines():
        f = l.split(",")
        if len(f) > 3:
            try: v[f[2]] = float(f[0])
            except ValueError: pass
    base = v["msr/tsc/"] / os.cpu_count(); dur = SEG - SETTLE
    return {"deep": 100 * (v["cstate_pkg/c8-residency/"] + v["cstate_pkg/c10-residency/"]) / base,
            "psys": v["power/energy-psys/"] / dur, "pkg": v["power/energy-pkg/"] / dur}
rows = []
try:
    for r in range(ROUNDS):
        order = [""] + CANDS; random.shuffle(order)
        for c in order:
            ps = pids(c) if c else []
            for p in ps:
                try: os.kill(p, signal.SIGSTOP); stopped.add(p)
                except ProcessLookupError: pass
            m = measure(); cont_all()
            rows.append((r, c or "(기준선)", m)); print("round %d %-18s 멈춘 pid %2d  deep %.1f%% psys %.3f W pkg %.3f W" % (r, c or "(기준선)", len(ps), m["deep"], m["psys"], m["pkg"]), flush=True)
            time.sleep(5)    # 풀린 직후 밀린 일 처리 시간
finally:
    cont_all()
print("\n후보별 (같은 라운드 기준선 대비 평균, 라운드 간 표준편차):")
for c in CANDS:
    dd = []; dp = []; dk = []
    for r in range(ROUNDS):
        b = [x[2] for x in rows if x[0] == r and x[1] == "(기준선)"]; k = [x[2] for x in rows if x[0] == r and x[1] == c]
        if b and k: dd.append(k[0]["deep"] - b[0]["deep"]); dp.append(k[0]["psys"] - b[0]["psys"]); dk.append(k[0]["pkg"] - b[0]["pkg"])
    if dd:
        sd = lambda x: ("±%.2f" % statistics.stdev(x)) if len(x) > 1 else ""
        print("  %-18s 깊은 상태 %+.1f%%p%s  psys %+.3f W%s  pkg %+.3f W%s  (n=%d)" % (c, statistics.mean(dd), sd(dd), statistics.mean(dp), sd(dp), statistics.mean(dk), sd(dk), len(dd)))
