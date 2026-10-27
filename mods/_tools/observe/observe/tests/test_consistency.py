#!/usr/bin/env python3
"""교차 일관성 시험 — 같은 표본 하나를 usageui 실시간 탭(usagelive)·hostres CLI(render·summary)·hostmetrics 판정이 **같은 숫자**로 보여 주는지,
메모리 구성 막대의 범례가 총량과 맞는지, 스킬 문서의 임계값 표가 코드(CALIB)와 같은지, 문서에 낡은 표현이 없는지 본다."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
SK = os.path.join(DATA, "..", "..", "_data", "claude-skills", "donghans-host-resources")
for p in (ROOT, os.path.join(SK, "scripts"), os.path.join(os.path.dirname(DATA), "_lib", "_testkit")):
    sys.path.insert(0, p)
import time
import hostmetrics as hm
import hostres
import usagelive as lv
from harness import checker
check, finish = checker()

sm = lv.LiveSampler(slow_every=60)
sm.sample(); time.sleep(1.2)
s = sm.sample()
G = hm.GIB
num = lambda rx, text: [float(y) for x in re.findall(rx, text) for y in ((x,) if isinstance(x, str) else x)]
V, M, P = lv.render_verdict(s).plain, lv.render_mem(s, 70).plain, lv.render_pressure(s).plain
H = hostres.render(s, 8)
SUM = hostres.summary(s, [], [])
near = lambda a, b, tol=0.06: a and b and all(abs(x - y) <= tol for x, y in zip(a, b))

check("판정 단어가 세 곳(실시간 박스·hostres 헤더·hm.verdict)에서 같음", hm.verdict(s)[0] in V and f"판정: {hm.verdict(s)[0]}" in H and f"판정 **{hm.verdict(s)[0]}**" in SUM)
check("OOM 까지 여유: 실시간 판정 박스 = hostres 본문 = 요약 = MemAvailable + 스왑 여유 계산값", near(num(r"OOM 까지 여유 ([\d.]+) ?GiB", V), [hm.headroom(s) / G]) and near(num(r"OOM 까지 여유 ([\d.]+) ?GiB", H)[:1], [hm.headroom(s) / G]) and near(num(r"OOM 까지 여유 ([\d.]+) ?GiB", SUM), [hm.headroom(s) / G]))
fl = s["mem"]["reclaimable_floor"] / G
check("보수적 가용: 판정 박스 「~X 바로」= 메모리 박스 = hostres 본문 = 수용량 첫 줄", near(num(r"~([\d.]+) GiB 바로", V), [fl]) and near(num(r"보수적\) ([\d.]+) GiB", M), [fl]) and near(num(r"\(보수적\)\*\*: ([\d.]+)GiB", H), [fl]) and abs(hm.capacity_guide(s)[0][0] - fl) < 1e-9)
av = s["mem"]["available_raw"] / G
check("커널 MemAvailable: 메모리 박스 = hostres 본문 = 수용량 둘째 줄", near(num(r"MemAvailable ([\d.]+) GiB", M), [av]) and near(num(r"커널 MemAvailable ([\d.]+)GiB", H), [av]) and abs(hm.capacity_guide(s)[1][0] - av) < 1e-9)
sw = s["swap"]
check("스왑 사용: 메모리 박스 = hostres 본문(사용/합계)", near(num(r"스왑 사용 ([\d.]+)/([\d.]+) GiB", M), [sw["used"] / G, sw["total"] / G]) and near(num(r"스왑 사용 ([\d.]+)GiB/([\d.]+)GiB", H), [sw["used"] / G, sw["total"] / G]))
cg = hm.capacity_guide(s)
check("수용량 셋째 줄 = MemAvailable + 스왑 여유의 절반, 판정 박스 표시와 같음", abs(cg[2][0] - (av + (sw["total"] - sw["used"]) / G * 0.5)) < 1e-9 and near(num(r"~([\d.]+) 스왑 의존", V), [cg[2][0]]) and near(num(r"~([\d.]+) 캐시 밀어냄", V), [cg[1][0]]))
check("hostres 요약의 수용 한도 세 숫자 = 수용량 표", near(num(r"약 ([\d.]+) GiB 까지 바로, ([\d.]+) GiB 까지 캐시를 밀어내며, ([\d.]+) GiB 까지 스왑", SUM), [cg[0][0], cg[1][0], cg[2][0]]))
# 메모리 막대 범례
parts = lv.mem_segments(s)
leg_gib = sum(num(r"■ .*?\s([\d.]+) GiB", M))
leg_pct = sum(num(r"GiB\s+(\d+)%", M))
check("메모리 범례: 8항목, GiB 합이 총량(반올림 오차 ±0.5), 퍼센트 합이 100±3", len(re.findall(r"■", M)) == 8 and abs(leg_gib - s["mem"]["total"] / G) <= 0.5 and 97 <= leg_pct <= 103, (leg_gib, leg_pct))
check("메모리 구성: 항목 합 == 총량(기타가 나머지를 채움)·음수 없음", abs(sum(b for _, b, _ in parts) - s["mem"]["total"]) < 4096 * 4 and all(b >= 0 for _, b, _ in parts))
check("막대 칸 수 = 요청 폭(색 칸 합)", len(lv.seg_bar(parts, 55).plain) == 55)
mi = s["meminfo"]
check("보수적 가용 = 범례의 빈 메모리 + 식은 캐시(반올림 ±0.15 GiB)", abs(fl - (num(r"빈 메모리\s+([\d.]+) GiB", M)[0] + num(r"식은 캐시\s+([\d.]+) GiB", M)[0])) <= 0.15)
# PSI
pm = s["psi"]["memory"]
pv = num(r"메모리\s+some\s+([\d.-]+)%\s+full\s+([\d.-]+)%", P)
hv = num(r"메모리 PSI: some ([\d.]+)% / full ([\d.]+)%", H)
exp = [pm["some_pct"] if pm["some_pct"] is not None else pm["some_avg10"], pm["full_pct"] if pm["full_pct"] is not None else pm["full_avg10"]]
check("메모리 PSI some/full(구간): 압박 박스 = hostres 본문 = 원자료(소수 첫째 자리)", near(pv, [round(x, 1) for x in exp], 0.11) and near(hv, [round(x, 1) for x in exp], 0.11), (pv, hv, exp))
a60 = num(r"메모리\s+some.*?avg60 some\s+([\d.]+)% full\s+([\d.]+)%", P)
check("avg60: 압박 박스 = 원자료 = 판정이 쓰는 값", near(a60, [round(pm["some_avg60"], 1), round(pm["full_avg60"], 1)], 0.11))
# 판정이 문서 임계값대로 나오는지(경계)
def mk(**kw):
    d = dict(s); d["psi"] = {k: dict(v) for k, v in s["psi"].items()}; d["psi"]["memory"].update(some_pct=0, full_pct=0, full_avg10=0, some_avg10=0, some_avg60=0, full_avg60=0); d["psi"]["memory"].update(kw); return d
c = hm.CALIB
check("경계: full avg60 가 CALIB 값 바로 아래는 여유(또는 용량 때문에만 다름)·같으면 올라감", all(hm.verdict_axes(mk(full_avg60=v))["speed"][0] == w for v, w in ((c["full60_warn"] - 0.01, 0), (c["full60_warn"], 1), (c["full60_press"], 2), (c["full60_crit"], 3))))
# 문서 ↔ 코드
doc = open(os.path.join(SK, "SKILL.md")).read()
gi = lambda x: f"{x / G:.0f} GiB"
check("SKILL.md 판정 표의 용량 임계값 = CALIB", f"<{gi(c['headroom_warn'])}" in doc and f"<{gi(c['headroom_press'])}" in doc and f"<{gi(c['headroom_crit'])}" in doc)
check("SKILL.md 판정 표의 속도 임계값 = CALIB(1%·3%·10%·순간 5%·some 20%)", all(t in doc for t in (f"full ≥{c['full60_warn']:.0f}%", f"full ≥{c['full60_press']:.0f}%", f"full ≥{c['full60_crit']:.0f}%", f"순간 ≥{c['spike']:.0f}%", f"some ≥{c['some60_press']:.0f}%")))
gd = hostres.GUIDE
check("hostres 읽는 법(GUIDE)이 두 축·ZRAM·수용량 표를 설명", all(k in gd for k in ("속도", "용량", "ZRAM", "새 작업이 쓸 메모리별 영향")))
# 낡은 표현
bad = []
for rel in ("SKILL.md", "scripts/hostres.py", "scripts/hostmetrics.py"):
    t = open(os.path.join(SK, rel)).read()
    for stale in ("보수적 가용 <2GiB 주의", "「ZRAM 거의 가득」", "6 실시간 탭", "경험칙이며 이 호스트의 실측으로 보정"):
        if stale in t:
            bad.append((rel, stale))
check("스킬·스크립트에 폐기된 판정 표현이 남아 있지 않음", not bad, bad)
ui = open(os.path.join(ROOT, "usageui.py")).read()
check("usageui.py 에 폐기된 「6 실시간」「1~6」 안내 문구가 남아 있지 않음", "1~6 탭" not in ui and "6 실시간(" not in ui)
finish("consistency")
