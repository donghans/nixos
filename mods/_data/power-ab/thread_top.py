#!/usr/bin/env python3
"""thread_top — 지정한 이름(부분 일치)의 프로세스들의 **스레드별** CPU 사용률과 자발적 깨어남(voluntary ctx switch)을 N초 동안 샘플링해 상위를 보여 준다.
누가(어느 스레드가) 깨어남을 만드는지 가를 때 쓴다. 일반 사용자 권한으로 된다(자기 프로세스).
  thread_top.py <프로세스 이름 부분 문자열> [초=10] [상위 개수=10]
  예) thread_top.py electron 10 12     /  thread_top.py tailscaled 15"""
import os, sys, time

PAT = sys.argv[1]
SEC = float(sys.argv[2]) if len(sys.argv) > 2 else 10
TOP = int(sys.argv[3]) if len(sys.argv) > 3 else 10
HZ = os.sysconf("SC_CLK_TCK")


def procs():
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            comm = open(f"/proc/{d}/comm").read().strip()
            cmd = open(f"/proc/{d}/cmdline").read().replace("\0", " ")
        except OSError:
            continue
        if PAT in comm or PAT in cmd:
            yield int(d), comm, cmd


def kind(cmd):
    for w in cmd.split():
        if w.startswith("--type="):
            return w[7:]
    return "main" if "electron" in cmd else ""


def snap():
    out = {}
    for pid, comm, cmd in procs():
        try:
            for t in os.listdir(f"/proc/{pid}/task"):
                base = f"/proc/{pid}/task/{t}"
                st = open(f"{base}/stat").read()
                name = st[st.index("(") + 1:st.rindex(")")]
                f = st[st.rindex(")") + 2:].split()
                cpu = int(f[11]) + int(f[12])
                vol = 0
                for l in open(f"{base}/status"):
                    if l.startswith("voluntary_ctxt_switches"):
                        vol = int(l.split()[1])
                out[(pid, int(t))] = (kind(cmd), name, cpu, vol)
        except OSError:
            pass
    return out


a = snap()
time.sleep(SEC)
b = snap()
rows = []
for k, (kd, nm, c1, v1) in b.items():
    if k in a:
        c0, v0 = a[k][2], a[k][3]
        rows.append(((c1 - c0) / HZ / SEC * 100, (v1 - v0) / SEC, k[0], k[1], kd, nm))
rows.sort(key=lambda r: -(r[1] + r[0] * 10))
print(f"{'pid':>7} {'tid':>7} {'종류':<10} {'스레드 이름':<24} {'CPU%':>6} {'깨어남/s':>9}   (샘플 {SEC:g}초, 일치 스레드 {len(rows)}개)")
for cpu, vol, pid, tid, kd, nm in rows[:TOP]:
    print(f"{pid:>7} {tid:>7} {kd:<10} {nm:<24} {cpu:>6.2f} {vol:>9.1f}")
print(f"합계: CPU {sum(r[0] for r in rows):.2f}% · 깨어남 {sum(r[1] for r in rows):.1f}/s")
