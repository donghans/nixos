#!/usr/bin/env python3
"""hostmetrics(호스트 측정·판정 모듈) 시험: print 없음, begin/end 증분, snapshot 래퍼, 판정 기준, python3 -I 에서 hostres 가 import 되는지."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SK = os.path.join(os.path.dirname(ROOT), "..", "..", "_data", "claude-skills", "donghans-host-resources", "scripts")
sys.path.insert(0, SK); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
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

G = hm.GIB
def psi_k(full10=0.0, some10=0.0, full60=0.0, some60=0.0, full_pct=0.0, some_pct=0.0):
    return dict(some_avg10=some10, full_avg10=full10, some_avg60=some60, full_avg60=full60, some_pct=some_pct, full_pct=full_pct)
def fake(avail=8.0, floor=3.0, swap_total=39.0, swap_used=30.0, devices=(), pswpin=0.0, mem=None, io=None, **psi_mem):
    return dict(psi={"memory": psi_k(**psi_mem), "cpu": psi_k(), "io": io or psi_k()},
                rates=dict(pswpin=pswpin, pswpout=0, pgmajfault=0, refault_file=0, allocstall=0),
                mem=dict(reclaimable_floor=floor * G, available_raw=avail * G, **(mem or {})), swap=dict(total=swap_total * G, used=swap_used * G, devices=list(devices)))
lvl = lambda s: hm.verdict(s)[0]
check("verdict: 정상은 여유(속도·용량 모두 0)", lvl(fake()) == "여유" and hm.verdict_axes(fake())["speed"][0] == 0 and hm.verdict_axes(fake())["capacity"][0] == 0)
check("verdict(속도): full avg60 ≥1% 주의 · ≥3% 압박 · ≥10% 심각", [lvl(fake(full60=x)) for x in (0.5, 1.5, 3.5, 11)] == ["여유", "주의", "압박", "심각"])
check("verdict(속도): some avg60 ≥20% 도 압박", lvl(fake(some60=25)) == "압박")
check("verdict(속도): avg60 은 낮고 full 순간(구간·avg10)만 ≥5% 면 주의(순간 튐 문구), 4% 는 여유", lvl(fake(full_pct=6)) == "주의" and "순간" in hm.verdict(fake(full10=6))[1][0] and lvl(fake(full10=4, full_pct=4)) == "여유")
check("verdict: ZRAM 슬롯이 99% 차도 판정에 영향 없음(여유)", lvl(fake(devices=[dict(name="/dev/zram0", kind="zram", size=15 * G, used=14.8 * G, orig=13 * G, compressed=5 * G)])) == "여유")
check("verdict: 스왑 되읽기가 커도 PSI 가 낮으면 판정 영향 없음(예전엔 주의였음)", lvl(fake(pswpin=5000.0)) == "여유")
check("verdict: 보수적 가용이 작아도(0.5 GiB) OOM 여유가 충분하면 여유(예전엔 주의)", lvl(fake(floor=0.5)) == "여유")
check("verdict(용량): OOM 까지 여유 <8 주의 · <3 압박 · <1 심각(MemAvailable + 스왑 여유)", [lvl(fake(avail=a, swap_total=10, swap_used=10 - f)) for a, f in ((4, 3), (1.5, 1), (0.5, 0.2))] == ["주의", "압박", "심각"])
check("verdict(용량): 이유에 [용량], 속도는 [속도] 표시, 두 축 중 높은 쪽", hm.verdict(fake(avail=1.5, swap_total=10, swap_used=9))[1][0].startswith("[용량]") and hm.verdict(fake(full60=3.5, avail=1.5, swap_total=10, swap_used=9))[0] == "압박")
check("headroom = MemAvailable + 스왑 여유(음수 방지)", abs(hm.headroom(fake(avail=4, swap_total=10, swap_used=3)) - 11 * G) < 1 and hm.headroom(fake(avail=4, swap_total=10, swap_used=12)) == 4 * G)
cg = hm.capacity_guide(fake(avail=8, floor=3, swap_total=39, swap_used=30))
check("capacity_guide: 보수적 ≤ 낙관 ≤ 스왑 포함, 마지막은 무한대(OOM 위험)", cg[0][0] < cg[1][0] < cg[2][0] and cg[3][0] == float("inf") and abs(cg[2][0] - (8 + 4.5)) < 1e-6)
z = fake(devices=[dict(name="/dev/zram0", kind="zram", size=15 * G, used=14.8 * G, orig=13.8 * G, compressed=5.3 * G), dict(name="/var/lib/swapfile", kind="disk", size=24 * G, used=15 * G)])
il = "\n".join(hm.info_lines(z))
check("info_lines: ZRAM 슬롯·압축률·「위험 신호가 아니다」, 디스크 스왑, 보수적 가용", "ZRAM 슬롯 99%" in il and "압축률 2.6" in il and "위험 신호가 아니다" in il and "디스크 스왑 15.0/24.0" in il and "보수적 가용" in il)
check("info_lines: 보정된 호스트는 스왑 기준점(실측) 줄과 p50·p99, 메모 포함", ("beelink-ser7-co" != hm.HOST) or ("스왑 기준점(실측" in il and "p99" in il and "기준점 메모" in il))
orig_host = hm.HOST; hm.HOST = "some-other-host"
il2 = "\n".join(hm.info_lines(z)); hm.HOST = orig_host
check("info_lines: 벤치마크 안 한 호스트는 「스왑 기준점 없음」과 swapbench.py 안내", "스왑 기준점 없음" in il2 and "swapbench.py" in il2 and "스왑 기준점(실측" not in il2)
check("mount_source: 루트 마운트의 장치 문자열을 돌려줌, swap_rotational 은 디스크 장치만 키로", isinstance(hm.mount_source("/"), str) and set(hm.swap_rotational(z["swap"]["devices"])) == {"/var/lib/swapfile"})
rot = [dict(name="/dev/sdz", kind="disk", size=G, used=0)]
check("swap_rotational: 존재하지 않는 장치는 None(모름)으로 안전하게", hm.swap_rotational(rot) == {"/dev/sdz": None})
# 압박 귀속
c1 = {"/": (0, 0, 0, 0), "a": (10_000_000, 0, 10.0, 0), "a/b": (9_000_000, 0, 9.0, 0), "c": (3_000_000, 0, 3.0, 0), "d": (100_000, 0, 0.1, 0)}
cu = hm.pressure_culprits({}, c1, 1.0, False)
check("pressure_culprits: 하위가 80% 이상이면 상위 대신 하위, 독립 cgroup 은 유지, 0.5% 미만은 제외", [r["path"] for r in cu] == ["a/b", "c"], cu)
c0 = {"a": (0, 0, 0, 0), "c": (0, 0, 0, 0)}
cu = hm.pressure_culprits(c0, {"a": (500_000, 100_000, 1, 0), "c": (2_000_000, 0, 1, 0)}, 10.0, True)
check("pressure_culprits: 구간이 있으면 누적 µs 차이를 구간 길이로 나눈 % (a 5%, c 20%)", [(r["path"], r["some_pct"]) for r in cu] == [("c", 20.0), ("a", 5.0)] and cu[1]["full_pct"] == 1.0)
env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
r = subprocess.run([sys.executable, "-I", os.path.join(SK, "hostres.py"), "--secs", "0", "--hist", "0", "--no-sessions", "--no-guide"], capture_output=True, text=True, env=env, cwd="/")
check("python3 -I hostres.py 가 import 오류 없이 실행되고 판정 절을 낸다", r.returncode == 0 and "## 호스트 자원" in r.stdout, r.stderr[-300:])
finish("hostmetrics")
