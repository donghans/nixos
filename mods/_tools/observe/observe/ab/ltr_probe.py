#!/usr/bin/env python3
"""ltr_probe — **root**. 90초 동안 1초마다 PMC 의 CNV(Wi-Fi/BT) LTR 을 읽어 2 ms 대/20 ms 대 비율을 세고, 같은 구간의 패키지 C-state(MSR PC2/3/6/8/10 %)를 함께 낸다.
패키지가 왜 깊게 못 자는지 볼 때(장치 LTR 이 원인인지) 쓴다. 2026-10-20: CNV LTR 은 2 ms ↔ 20.5 ms 로 오르내리지만 20 ms 가 77% 인 때도 패키지는 PC3 에 막혀 있었음(ctx 장부 #44)."""
import os, re, struct, time, collections
PC={"pc2":0x60D,"pc3":0x3F8,"pc6":0x3F9,"pc8":0x630,"pc10":0x632}
fd=os.open("/dev/cpu/0/msr",os.O_RDONLY)
rd=lambda r: struct.unpack("Q",os.pread(fd,8,r))[0]
def snap(): return {k:rd(v) for k,v in PC.items()}, rd(0x10)
def cnv():
    for l in open("/sys/kernel/debug/pmc_core/ltr_show"):
        m=re.search(r"PMC0:CNV\s+LTR: RAW: (\S+)\s+Non-Snoop\(ns\): (\d+)\s+Snoop\(ns\): (\d+)",l)
        if m: return int(m[3])
    return None
vals=[]; s0=snap(); t0=time.time()
while time.time()-t0<90:
    vals.append(cnv()); time.sleep(1)
s1=snap(); dt=s1[1]-s0[1]
c=collections.Counter(("2ms대" if v<5_000_000 else "20ms대" if v>15_000_000 else "그 외") for v in vals if v)
print("CNV LTR 분포(1초 샘플 %d개):"%len(vals), dict(c), " 최소 %.1f ms 최대 %.1f ms"%(min(v for v in vals if v)/1e6, max(vals)/1e6))
print("같은 구간 패키지 C-state(%):", {k: round((s1[0][k]-s0[0][k])/dt*100,1) for k in PC})
