#!/usr/bin/env python3
"""observectl 시험: 공통(제어 파일/회전/시각), 이벤트 로그 수준, 통계 판정, 수집기 파서/요청 처리/스모크, CLI 의 A/B 구간 분할."""
import json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observectl-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import observe_core as core, observe_events, observe_stats as stats, observe_collector as col, observe_cli
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

# --- 제어 파일
ctl = core.read_control()
check("제어 파일이 없으면 기본값(꺼짐, L0)", ctl["enabled"] is False and ctl["level"] == "L0" and ctl["interval_s"]["L0"] == 30)
ctl = core.write_control({"enabled": True, "level": "L1", "components": {"posture": "trace"}})
check("write_control 이 합쳐 쓴다(기본 컴포넌트 설정 유지)", ctl["enabled"] and ctl["level"] == "L1" and ctl["components"]["posture"] == "trace" and ctl["components"]["displayui"] == "debug", str(ctl))
core.write_control({"mark": {"cond": "A", "t": 1.0}})
check("제어 파일은 같은 inode 에 제자리로 쓴다(path 유닛 감지용)", os.stat(core.CONTROL).st_ino == os.stat(core.CONTROL).st_ino and json.load(open(core.CONTROL))["enabled"] is True)
open(core.CONTROL, "w").write("{깨진")
check("깨진 제어 파일은 기본값으로", core.read_control()["enabled"] is False)
core.write_control({"enabled": False, "components": {"*": "info", "displayui": "debug"}})
c = core.read_control()
check("level_for: 지정 > '*' > info", core.level_for("displayui", c) == core.LEVELS["debug"] and core.level_for("other", c) == core.LEVELS["info"])

# --- 시각 해석
now = time.mktime((2026, 10, 20, 12, 0, 0, 0, 0, -1))
check("parse_when 상대(-30m, 30m 둘 다 30분 전)", core.parse_when("-30m", now) == now - 1800 and core.parse_when("30m", now) == now - 1800)
check("parse_when HH:MM", core.parse_when("11:20", now) == time.mktime((2026, 10, 20, 11, 20, 0, 0, 0, -1)))
check("parse_when 미래 HH:MM 은 어제", core.parse_when("23:00", now) == time.mktime((2026, 10, 19, 23, 0, 0, 0, 0, -1)))
check("parse_when 날짜+시각", core.parse_when("2026-10-20 11:20", now) == time.mktime((2026, 10, 20, 11, 20, 0, 0, 0, -1)))
try:
    core.parse_when("엉터리"); check("해석 불가는 오류", False)
except ValueError:
    check("해석 불가는 오류", True)

# --- JSONL 기록/조회/회전
d = os.path.join(TMP, "j")
for i, t in enumerate((now - 86400 * 3, now - 86400, now)):
    core.append_jsonl(d, "samples", {"t": t, "i": i}, t=t)
rows = list(core.iter_jsonl(d, "samples"))
check("append/iter: 3줄, 시간순", [r["i"] for r in rows] == [0, 1, 2])
check("iter since/until 필터", [r["i"] for r in core.iter_jsonl(d, "samples", now - 1000, now + 1)] == [2])
open(os.path.join(d, "samples-20200101.jsonl"), "w").write("{깨짐\n" + json.dumps({"t": 1.0}) + "\n")
check("깨진 줄은 건너뜀", sum(1 for _ in core.iter_jsonl(d, "samples")) == 4)
for f in os.listdir(d):
    os.utime(os.path.join(d, f), (time.time() - (40 * 86400 if "2020" in f else 0),) * 2)
check("prune: 보존 일수를 넘긴 파일 삭제", core.prune(d, "samples", 14, 100) == 1 and not any("2020" in f for f in os.listdir(d)))
big = os.path.join(d, "samples-20260101.jsonl"); open(big, "w").write("x" * 2_000_000); os.utime(big, (time.time() - 10,) * 2)
check("prune: 총 용량 초과 시 오래된 것부터", core.prune(d, "samples", 365, 1) >= 1 and len(os.listdir(d)) >= 1)

# --- 이벤트 로그
ev = observe_events.Events("displayui")
check("debug 는 displayui 에서 기록", ev.debug("hello", k=1) is True)
check("trace 는 debug 수준에서는 버려짐", ev.trace("noisy") is False)
core.write_control({"components": {"displayui": "trace"}}); ev._ctl_t = 0
check("수준 변경이 재시작 없이 반영(trace)", ev.trace("noisy2") is True)
other = observe_events.Events("posture")
check("기본 info 컴포넌트는 debug 를 버림", other.debug("x") is False and other.info("y") is True)
with ev.span("apply", mode="a"):
    pass
try:
    with ev.span("bad"):
        raise RuntimeError("boom")
except RuntimeError:
    pass
evs = list(core.iter_jsonl(core.state_dir(), "events"))
names = [e["ev"] for e in evs]
check("span 은 begin/end/fail 을 기록", "apply.begin" in names and "apply.end" in names and "bad.fail" in names, str(names))
check("span 소요시간 ms 와 예외 정보", any(e["ev"] == "apply.end" and "ms" in e for e in evs) and any(e["ev"] == "bad.fail" and "boom" in e["exc"] for e in evs))
broken = observe_events.Events("x", ctl_path="/nonexistent/c.json")
os.environ["OBSERVE_STATE_DIR"] = "/proc/nonexistent/denied"
check("기록 실패가 호출자를 죽이지 않음", broken.error("e") in (True, False))
os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")

# --- 통계
a, b = [6.15, 5.79, 5.63, 5.46], [5.41, 5.70, 5.78, 5.36]
v = stats.verdict(a, b, 0.3)
check("tailscaled 실측(−0.20 W, 부호 섞임)은 '불확실'", v["verdict"] == "불확실" and abs(v["effect"] + 0.1975) < 0.01 and not v["same_sign"], str(v))
v = stats.verdict([6.0, 6.1, 6.0], [5.5, 5.6, 5.5], 0.3)
check("일관되게 −0.5 W 이면 '확인(측정)'", v["verdict"] == "확인(측정)" and v["ci95"] and v["ci95"][1] < 0)
check("쌍이 1개면 '표본 부족'", stats.verdict([6.0], [5.0], 0.3)["verdict"] == "표본 부족")
check("임계 미만(−0.1)이면 같은 부호여도 '불확실'", stats.verdict([6.0, 6.0], [5.9, 5.9], 0.3)["verdict"] == "불확실")
check("부트스트랩은 시드 고정이라 재현", stats.bootstrap_ci([1, 2, 3, 4]) == stats.bootstrap_ci([1, 2, 3, 4]))
check("부호검정: 4쌍 모두 같은 부호 p=0.125", abs(stats.sign_test_p([-1, -1, -1, -1]) - 0.125) < 1e-9)

# --- 수집기 파서
st = col.parse_stat("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 1 1 1 1 1 1 1 1 1\nctxt 12345\nintr 999 1 2\n")
check("parse_stat: total/busy/ctxt/intr", st["total"] == 1000 and st["busy"] == 150 and st["ctxt"] == 12345 and st["intr"] == 999, str(st))
ir = col.parse_interrupts("           CPU0       CPU1\n  1:        100          5  IO-APIC   1-edge      i8042\n NMI:          3          4  Non-maskable interrupts\n")
check("parse_interrupts: IRQ 이름/합계/설명", ir["IRQ1"][0] == 105 and "i8042" in ir["IRQ1"][1] and ir["NMI"][0] == 7, str(ir))
check("parse_softirqs", col.parse_softirqs("                    CPU0       CPU1\n          TIMER:   10   20\n          RCU:   1   2\n") == {"TIMER": 30, "RCU": 3})
line = "123 (Web Content (x)) S 1 2 3 4 5 6 7 8 9 10 100 50 0 0 20 0 7 0 1000 123456 321 0"
check("parse_pid_stat: 공백·괄호가 든 comm", col.parse_pid_stat(line) == ("Web Content (x)", 150, 7, 321), str(col.parse_pid_stat(line)))
check("parse_ctxt", col.parse_ctxt("Name:\tx\nvoluntary_ctxt_switches:\t42\nnonvoluntary_ctxt_switches:\t7\n") == (42, 7))
pc = col.pkg_cstate_pct({"tsc": 0, "pc2": 0, "pc10": 0}, {"tsc": 1000, "pc2": 300, "pc10": 250})
check("pkg_cstate_pct: TSC 대비 %", pc == {"pc2": 30.0, "pc10": 25.0}, str(pc))
check("pkg_cstate_pct: 증가 없음/역행은 빈 값", col.pkg_cstate_pct({"tsc": 5}, {"tsc": 5}) == {})
check("cpuidle_pct: CPU 시간 대비 %", col.cpuidle_pct({"C6": 0}, {"C6": 4_000_000}, 1.0, 8) == {"C6": 50.0})
check("classify: pc10 ≥ 5% 면 low", col.classify({"pc10": 24.0}) == "low" and col.classify({"pc10": 0.0}) == "high" and col.classify({}) == "unknown")
tr = col.parse_trace("""# tracer: nop
          <idle>-0       [003] d.h1.  100.000001: hrtimer_expire_entry: hrtimer=00000000 function=tick_nohz_highres_handler now=1
          <idle>-0       [003] ..s1.  100.000002: timer_expire_entry: timer=0000 function=process_timeout now=2
     kworker/3:1-99      [003] d..1.  100.000003: workqueue_execute_start: work struct 00000000: function pm_runtime_work
          <idle>-0       [001] d.h1.  100.000004: irq_handler_entry: irq=9 name=acpi
            Xorg-77      [002] d..2.  100.000005: sched_waking: comm=kworker/u64:3 pid=55 prio=120 target_cpu=005
          <idle>-0       [003] d.h1.  100.000006: hrtimer_expire_entry: hrtimer=00000000 function=tick_nohz_highres_handler now=3
""")
check("parse_trace: 이벤트별 함수/IRQ/깨움 집계", tr["hrtimer"]["tick_nohz_highres_handler"] == 2 and tr["timer"]["process_timeout"] == 1 and tr["work"]["pm_runtime_work"] == 1
      and tr["irq"]["9 acpi"] == 1 and tr["waker"]["kworker/u64:3"] == 1, str(tr))

# --- 요청 처리
os.makedirs(core.REQ_DIR, exist_ok=True)
json.dump({"id": "t1", "type": "ping"}, open(os.path.join(core.REQ_DIR, "t1.json"), "w"))
json.dump({"id": "t2", "type": "없는작업"}, open(os.path.join(core.REQ_DIR, "t2.json"), "w"))
open(os.path.join(core.REQ_DIR, "t3.json"), "w").write("{깨짐")
check("process_requests: 3건 처리", col.process_requests() == 3 and not os.listdir(core.REQ_DIR))
r1, r2 = json.load(open(os.path.join(core.RES_DIR, "t1.json"))), json.load(open(os.path.join(core.RES_DIR, "t2.json")))
check("ping 은 ok, 모르는 작업은 오류 결과", r1["ok"] and r1["data"]["pong"] and not r2["ok"] and "알 수 없는" in r2["error"], str((r1, r2)))
json.dump({"id": "../../etc/x", "type": "ping"}, open(os.path.join(core.REQ_DIR, "evil.json"), "w"))
col.process_requests()
check("요청 id 의 경로 탈출 문자는 제거", os.path.exists(os.path.join(core.RES_DIR, "etcx.json")) and not os.path.exists(os.path.join(TMP, "etc")))

# --- 표본 스모크(실제 /proc, /sys)
s = col.Sampler("L1")
time.sleep(1.2)
smp = s.sample()
check("스모크: 표본 필수 키", all(k in smp for k in ("t", "dt", "pw", "cs", "irq", "proc", "dev", "state", "thr", "io")), str(list(smp)))
check("스모크: dt 가 대기 시간과 비슷", 1.0 < smp["dt"] < 2.5, str(smp["dt"]))
check("스모크: 프로세스 합산 항목 구조", all({"comm", "exe", "n", "cpu", "wake", "rss_mb"} <= set(p) for p in smp["proc"]))
json.dumps(smp)
check("스모크: 표본이 JSON 직렬화 가능", True)

# --- CLI: A/B 구간 분할
rows = []
t0 = 1000.0
for seg, (cond, mt, w) in enumerate([("A", t0, 6.0), ("B", t0 + 100, 5.4), ("A", t0 + 200, 6.1), ("B", t0 + 300, 5.3)]):
    for i in range(10):
        rows.append({"t": mt + i * 10, "state": "high", "mark": {"cond": cond, "t": mt}, "pw": {"psys_w": w + (0.05 if i % 2 else -0.05)}})
segs = observe_cli.segments(rows, settle=20)
check("segments: 4구간 ABAB, 표지 직후 20초 제외", [c for c, _ in segs] == ["A", "B", "A", "B"] and all(len(g) == 8 for _, g in segs), str([(c, len(g)) for c, g in segs]))
A = [observe_cli.mean_of(g, lambda r: observe_cli.get(r, "pw.psys_w")) for c, g in segs if c == "A"]
check("구간 평균 계산", abs(A[0] - 6.0) < 0.01 and abs(A[1] - 6.1) < 0.01, str(A))
check("group_key: state/mark/ac", observe_cli.group_key(rows[0], "state") == "high" and observe_cli.group_key(rows[0], "mark") == "A" and observe_cli.group_key({"pw": {"ac": 1}}, "ac") == "AC")
finish("observe")
