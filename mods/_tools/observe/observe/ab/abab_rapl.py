#!/usr/bin/env python3
"""abab_lib.sh 가 구간 경계에서 읽은 RAPL 누적 카운터(.rapl)로 구간별 평균 전력과 쌍별 A−B 를 계산한다.
수집기 30초 격자와 무관한 정확한 구간 평균이다. 평균은 안정화(SETTLE) 이후 구간 기준. 사용: abab_rapl.py <파일.rapl>"""
import os, statistics, sys

WRAP = 262143328850  # max_energy_range_uj (psys·package-0 동일)

def watts(e0, e1, t0, t1):
    d = (e1 - e0) % WRAP
    return d / 1e6 / ((t1 - t0) / 1e9)

def parse(text):
    segs = []
    for ln in text.splitlines():
        f = ln.split("\t")
        if len(f) != 5:
            continue
        try:
            r = [tuple(int(x) for x in s.split()) for s in f[2:5]]
        except ValueError:
            continue
        if any(len(x) != 3 for x in r):
            continue
        (t0, ps0, pk0), (t1, ps1, pk1), (t2, ps2, pk2) = r
        segs.append({"cond": f[0], "label": f[1], "dur": (t2 - t0) / 1e9,
                     "psys": watts(ps1, ps2, t1, t2), "pkg": watts(pk1, pk2, t1, t2),
                     "psys_all": watts(ps0, ps2, t0, t2)})
    return segs

def report(segs, bcoef=None):
    if not segs:
        return "RAPL 구간 기록 없음(sudo -n 으로 energy_uj 를 읽지 못했거나 구간이 없음)"
    out = ["RAPL 직접 읽기(안정화 이후 평균, 구간 경계 정확):", "  구간      길이(s)  psys(W)  pkg(W)  psys전체(W)"]
    for s in segs:
        out.append("  %-8s %7.1f %8.3f %7.3f %9.3f" % (s["label"], s["dur"], s["psys"], s["pkg"], s["psys_all"]))
    a = [s for s in segs if s["cond"] == "A"]; b = [s for s in segs if s["cond"] == "B"]
    n = min(len(a), len(b))
    if n:
        for key in ("psys", "pkg"):
            d = [a[i][key] - b[i][key] for i in range(n)]
            line = "  %s A−B 쌍별: %s  평균 %+.3f W" % (key, " ".join("%+.3f" % x for x in d), statistics.mean(d))
            if n > 1:
                line += "  표준편차 %.3f  부호 %d/%d" % (statistics.stdev(d), sum(1 for x in d if x > 0) if statistics.mean(d) > 0 else sum(1 for x in d if x < 0), n)
            out.append(line)
        if n > 1 and len(b) > 1:   # 시간 표류 보정: A 를 이웃한 두 B 의 평균과 비교
            for key in ("psys",):
                d = [a[i][key] - (b[i - 1][key] + b[i][key]) / 2 for i in range(1, n)]
                out.append("  %s A−(이웃 B 평균, 표류 보정): %s  평균 %+.3f W" % (key, " ".join("%+.3f" % x for x in d), statistics.mean(d)))
        if bcoef:   # psys ≈ b·pkg + 상수 (b 는 조건마다 다름 — 이 시험이 아닌 다른 시험·상시 기록에서 구한 값을 받는다)
            dps = statistics.mean(a[i]["psys"] - b[i]["psys"] for i in range(n))
            dpk = bcoef * statistics.mean(a[i]["pkg"] - b[i]["pkg"] for i in range(n))
            out.append("  psys A−B 분해(b=%.2f): CPU 패키지 몫 %+.3f W + 패키지 밖(화면·Wi-Fi·SSD) 몫 %+.3f W = %+.3f W" % (bcoef, dpk, dps - dpk, dps))
    return "\n".join(out)

if __name__ == "__main__":
    args = sys.argv[1:]; bval = float(os.environ.get("ABAB_RAPL_B") or 0) or None
    if "--b" in args:
        i = args.index("--b"); bval = float(args[i + 1]); del args[i:i + 2]
    print(report(parse(open(args[0]).read()), bval))
