#!/usr/bin/env python3
"""hostmetrics(호스트 측정·판정 모듈) 시험: print 없음, begin/end 증분, snapshot 래퍼, 판정 기준, python3 -I 에서 hostres 가 import 되는지."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SK = os.path.join(os.path.dirname(ROOT), "claude-skills", "donghans-host-resources", "scripts")
sys.path.insert(0, SK); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import hostmetrics as hm
from harness import checker
check, finish = checker()

src = open(os.path.join(SK, "hostmetrics.py")).read()
check("hostmetrics 에 print 호출이 없다(출력은 호출부 몫)", "print(" not in src)

b = hm.begin()
s0 = hm.end(b, measured=False)
check("end(measured=False): 구간 값(PSI 구간·변화율·CPU 사용률)은 None", s0["psi"]["memory"]["full_pct"] is None and s0["rates"]["pswpin"] is None and s0["rates"]["allocstall"] is None)
b = hm.begin()
import time; time.sleep(0.3)
s1 = hm.end(b)
check("end(measured=True): 변화율 값이 숫자(0 이상)", s1["rates"]["pswpin"] >= 0 and s1["rates"]["allocstall"] >= 0 and 0.2 < s1["window_s"] < 5)
check("보수적 가용 ≤ 총 메모리, 키 구조(mem·swap·psi·rates·cpu·tmpfs)", 0 < s1["mem"]["reclaimable_floor"] <= s1["mem"]["total"] and {"mem", "swap", "psi", "rates", "cpu", "tmpfs", "window_s"} <= set(s1))
s2 = hm.snapshot(0)
check("snapshot(0) 은 end(begin(), False) 와 같은 구조", set(s2) == set(s0) and s2["rates"]["pswpin"] is None)

def fake(**kw):
    d = dict(psi={k: dict(some_avg10=0.0, full_avg10=0.0, some_pct=0.0, full_pct=0.0) for k in ("memory", "cpu", "io")},
             rates=dict(pswpin=0.0, pswpout=0, pgmajfault=0, refault_file=0, allocstall=0),
             mem=dict(reclaimable_floor=8 * hm.GIB), swap=dict(total=8 * hm.GIB, used=0, devices=[]))
    for k, v in kw.items():
        d[k].update(v) if isinstance(v, dict) else d.__setitem__(k, v)
    return d
check("verdict: 정상은 여유", hm.verdict(fake())[0] == "여유")
check("verdict: 메모리 PSI full ≥1% 는 압박, ≥5% 는 심각", hm.verdict(fake(psi={"memory": dict(some_avg10=0, full_avg10=0, some_pct=0, full_pct=1.5)}))[0] == "압박" and hm.verdict(fake(psi={"memory": dict(some_avg10=0, full_avg10=0, some_pct=0, full_pct=6)}))[0] == "심각")
check("verdict: pswpin 높아도 PSI 낮으면 주의(압박 아님)", hm.verdict(fake(rates={"pswpin": 5000.0}))[0] == "주의")
check("verdict: 보수적 가용 2GiB 미만은 주의", hm.verdict(fake(mem={"reclaimable_floor": 1 * hm.GIB}))[0] == "주의")

env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
r = subprocess.run([sys.executable, "-I", os.path.join(SK, "hostres.py"), "--secs", "0", "--hist", "0", "--no-sessions", "--no-guide"], capture_output=True, text=True, env=env, cwd="/")
check("python3 -I hostres.py 가 import 오류 없이 실행되고 판정 절을 낸다", r.returncode == 0 and "## 호스트 자원" in r.stdout, r.stderr[-300:])
finish("hostmetrics")
