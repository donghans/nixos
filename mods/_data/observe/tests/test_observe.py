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

core.append_jsonl(d, "future", {"t": time.time() + 9 * 3600, "i": 99})
core.append_jsonl(d, "future", {"t": time.time() - 5, "i": 1})
check("부팅 직후 9시간 앞선 가짜 미래 시각 줄은 건너뜀", [r["i"] for r in core.iter_jsonl(d, "future")] == [1])

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
sd = col.statsd_lines({"pw": {"psys_w": 4.1234, "pkg_w": 1.5, "batt_vi_w": 5.0, "status": "Discharging", "batt_pct": "50"}, "cs": {"pc8": 12.0, "pc10": 0.0},
                       "state": "high", "proc": [{"ctxsw_vol_s": 3}, {"ctxsw_vol_s": 4}], "irq": {"cpu_all_pct": 2.0, "ctxt_s": 2500},
                       "dev": {"psr": {"mode": "PSR1 enabled", "sink": "inactive"}, "wifi": {"ps": "off"}}})
sdm = dict(l.split("|")[0].split(":") for l in sd)
check("statsd_lines: 게이지 형식·접두사", all(l.startswith("observe.") and l.endswith("|g") for l in sd), str(sd))
check("statsd_lines: 방전 중이면 방전 전력만 값, 충전 전력 0", sdm["observe.batt_discharge_w"] == "5.0" and sdm["observe.batt_charge_w"] == "0", str(sdm))
check("statsd_lines: 상태/PSR/전환(상위·전체)/CPU 전체/패키지 C-state", sdm["observe.state_low"] == "0" and sdm["observe.psr_on"] == "1" and sdm["observe.psr_sink_active"] == "0" and sdm["observe.ctxsw_top_all_threads_per_s"] == "7" and sdm["observe.ctxsw_all_per_s"] == "2500" and sdm["observe.cpu_all_pct"] == "2.0" and "observe.wake_per_s" not in sdm and "observe.ctxsw_vol_top_per_s" not in sdm and sdm["observe.pkg_pc8"] == "12.0" and sdm["observe.pkg_pc10"] == "0.0", str(sdm))
check("statsd_lines: 값이 없으면 줄을 만들지 않는다(문자열은 보내지 않음)", "observe.pkg_pc2" not in sdm and "observe.psys_w" in sdm and not any(not v.replace(".", "", 1).replace("-", "", 1).isdigit() for v in sdm.values()))
check("statsd_lines: 빈 표본은 빈 목록", col.statsd_lines({}) == [])
import socket as _s
rx = _s.socket(_s.AF_INET, _s.SOCK_DGRAM); rx.bind(("127.0.0.1", 0)); rx.settimeout(2)
col.STATSD_ADDR = rx.getsockname()
check("statsd_send: UDP 로 실제 전송", col.statsd_send({"pw": {"psys_w": 3.0}}) == 1 and rx.recv(1000).decode() == "observe.psys_w:3.0|g")
col.STATSD_ADDR = ("127.0.0.1", 1)                                   # 아무도 안 듣는 포트: 오류 없이 지나가야 한다
check("statsd_send: 수신자가 없어도 예외 없음", isinstance(col.statsd_send({"pw": {"psys_w": 3.0}}), int))
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
check("스모크: 표본 형식이 최신(v3)이고 옛 필드 이름이 없음", smp["v"] == core.SCHEMA and "batt_vi_w" in smp["pw"] and "batt_w" not in smp["pw"] and "cpu_all_pct" in smp["irq"] and "cpu_busy_pct" not in smp["irq"], str(smp["pw"]))
check("스모크: 프로세스 합산 항목 구조", all({"comm", "exe", "n", "cpu_core_pct", "ctxsw_vol_s", "rss_mb"} <= set(p) and not ({"cpu", "wake"} & set(p)) for p in smp["proc"]))
json.dumps(smp)
# --- 옛 형식(v1) 표본 읽기 호환: 값은 그대로, 이름만 v2 로, legacy 표시
old = {"t": 1700000000.0, "pw": {"psys_w": 4.0, "batt_w": 5.5, "status": "Discharging"}, "irq": {"cpu_busy_pct": 3.2, "ctxt_s": 2000},
       "proc": [{"comm": "claude", "exe": "claude", "n": 1, "cpu": 8.5, "wake": 30.0, "rss_mb": 400}], "thr": [{"comm": "x", "thr": "t", "cpu": 1.5, "wake": 9.0}]}
n1 = core.normalize_sample(json.loads(json.dumps(old)))
check("normalize_sample: 필드 이름 v1 → 최신(값 그대로, proc 전환은 ctxsw_vol_leader_s)", n1["pw"]["batt_vi_w"] == 5.5 and "batt_w" not in n1["pw"] and n1["irq"]["cpu_all_pct"] == 3.2 and "cpu_busy_pct" not in n1["irq"]
      and n1["proc"][0]["cpu_core_pct"] == 8.5 and n1["proc"][0]["ctxsw_vol_leader_s"] == 30.0 and not ({"cpu", "wake", "ctxsw_vol_s"} & set(n1["proc"][0])) and n1["thr"][0]["cpu_core_pct"] == 1.5 and n1["thr"][0]["ctxsw_vol_s"] == 9.0, str(n1))
check("normalize_sample: 옛 표본은 v=3, legacy=True", n1["v"] == 3 and n1["legacy"] is True)
v2 = {"v": 3, "t": 1.0, "pw": {"batt_vi_w": 1.0}}
check("normalize_sample: 최신(v3)은 그대로(legacy 없음)", core.normalize_sample(dict(v2)) == v2 and "legacy" not in core.normalize_sample(dict(v2)))
check("normalize_sample: 두 번 적용해도 같음(멱등)", core.normalize_sample(core.normalize_sample(json.loads(json.dumps(old)))) == n1)
core.append_jsonl(core.SAMPLE_DIR, "samples", {**old, "t": time.time() - 100})
rd = list(core.iter_jsonl(core.SAMPLE_DIR, "samples", time.time() - 200))
check("iter_jsonl(samples): 파일에는 옛 이름 그대로 있지만 읽으면 새 이름·legacy", any(r.get("legacy") and "batt_vi_w" in r["pw"] and r["proc"][0]["ctxsw_vol_leader_s"] == 30.0 for r in rd), str(rd[-1:]))
raw_line = open(core.day_file(core.SAMPLE_DIR, "samples", time.time() - 100)).read()
check("원본 파일은 고쳐 쓰지 않는다(옛 이름 보존)", '"batt_w"' in raw_line and '"cpu_busy_pct"' in raw_line)
core.append_jsonl(core.state_dir(), "events", {"t": time.time() - 50, "comp": "x", "ev": "keep", "pw": {"batt_w": 1}})
ev_back = [e for e in core.iter_jsonl(core.state_dir(), "events", time.time() - 100) if e.get("ev") == "keep"]
check("이벤트 로그(events)는 정규화하지 않는다(사용자 필드 보존)", ev_back and ev_back[0]["pw"] == {"batt_w": 1} and "legacy" not in ev_back[0], str(ev_back))
# observectl: 옛 이름 옵션 호환
import io as _io, contextlib as _cx
buf = _io.StringIO()
with _cx.redirect_stdout(buf):
    observe_cli.main(["window", "--since", "10m", "--by", "none"])
wout = buf.getvalue()
check("observectl window: 옛 형식 표본 안내·새 열 이름(V×I/상위전환/전체CPU%)", "옛 형식 표본" in wout and "V×I" in wout and "상위전환/s" in wout and "전체CPU%" in wout, wout)
# 옛 표본만 있을 때 --by ctxsw(옛 이름 wake 포함)는 순위를 만들지 않고 이유를 안내한다 — 옛 값은 메인 스레드만 센 값이라 순위가 왜곡됨
for by in ("wake", "ctxsw"):
    buf = _io.StringIO()
    try:
        with _cx.redirect_stdout(buf):
            observe_cli.main(["top", "--since", "10m", "--by", by])
        check(f"observectl top --by {by}: 옛 표본뿐이면 안내 후 종료", False, buf.getvalue())
    except SystemExit as e:
        check(f"observectl top --by {by}: 옛 표본뿐이면 안내 후 종료", "새 형식" in str(e) and ("옛 이름" in buf.getvalue() if by == "wake" else True), str(e) + buf.getvalue())

# --- observectl ab (다지표·자동 검증·판정 문구)
import io as _io2, contextlib as _cx2
def _ab_rows(deltas, seg_len=16, lids=None, acs=None, vi_noise=None, base_t=None):
    """deltas: [(조건, psys, pkg, vi, 계량 W)] 구간 목록 — 구간마다 30초 표본 seg_len 개. q_uah 는 계량 W 에서 역산(15 V)."""
    out, t, q = [], (base_t or time.time() - 7200), 3_000_000
    for i, (cond, psys, pkg, vi, cw) in enumerate(deltas):
        mt = t
        for k in range(seg_len):
            out.append({"t": t, "dt": 30, "state": "low", "mark": {"cond": cond, "t": mt, "note": ""},
                        "pw": {"psys_w": psys, "pkg_w": pkg, "batt_vi_w": vi + (0.5 if (vi_noise and k % 2) else 0), "q_uah": int(q), "v_uv": 15_000_000, "status": "Discharging", "ac": (acs or {}).get(i, 0)},
                        "dev": {"lid": (lids or {}).get(i, "closed"), "wifi": {"ssid": "x"}}})
            t += 30
            q -= cw / 15.0 * 1e6 * 30 / 3600          # 계량 W → 30초 동안 줄어든 µAh
    return out
def _run_ab(rows, *argv):
    d = os.path.join(TMP, "ab"); os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.unlink(os.path.join(d, f))
    for r in rows:
        core.append_jsonl(d, "samples", r, t=r["t"])
    old = core.SAMPLE_DIR
    core.SAMPLE_DIR = d; observe_cli.core.SAMPLE_DIR = d
    buf = _io2.StringIO()
    try:
        with _cx2.redirect_stdout(buf):
            observe_cli.main(["ab", "--since", "3h", "--settle", "20", "--min-samples", "3", *argv])
    finally:
        core.SAMPLE_DIR = old; observe_cli.core.SAMPLE_DIR = old
    return buf.getvalue()
A = ("A", 5.0, 2.0, 6.0, 6.0); B = ("B", 4.0, 1.6, 5.0, 5.0)
out = _run_ab(_ab_rows([A, B, A, B, A, B]))
check("ab: 3쌍·모든 지표 같은 방향 → 종합 '확인(측정)'", "종합: 확인(측정)" in out, out)
out = _run_ab(_ab_rows([A, B, A, B]))
check("ab: 2쌍이면 종합이 '일치(약함)'(확인이라 하지 않음)", "종합: 일치(약함)" in out and "종합: 확인" not in out, out)
check("ab: 지표 4개를 한꺼번에 출력(psys·패키지·순간 V×I·누적 계량)", all(k in out for k in ("psys(RAPL", "패키지(RAPL)", "순간 V×I", "누적 계량")), out)
# 순간 V×I 만 반대 부호(표본 적음 → 신뢰 낮음으로 제외) — 실제 #58 상황
vi_bad = [("A", 5.0, 2.0, 5.0, 6.0), ("B", 4.0, 1.6, 5.8, 5.0), ("A", 5.0, 2.0, 5.0, 6.0), ("B", 4.0, 1.6, 5.8, 5.0), ("A", 5.0, 2.0, 5.0, 6.0), ("B", 4.0, 1.6, 5.8, 5.0)]
out = _run_ab(_ab_rows(vi_bad, seg_len=6))
check("ab: V×I 가 반대여도 표본이 적으면 '신뢰 낮음'으로 표시하고 종합에서 제외", "신뢰 낮음" in out and "신뢰 낮아 제외한 지표" in out and "부호가 다름" not in out, out)
# 신뢰 가능한 지표끼리 반대 → 불확실
conf = [("A", 5.0, 2.0, 6.0, 6.0), ("B", 4.0, 2.4, 5.0, 5.0)] * 3          # psys 는 줄고 pkg 는 늘어남
out = _run_ab(_ab_rows(conf))
check("ab: 신뢰 가능한 지표끼리 부호가 다르면 종합 '불확실'", "종합: 불확실 — 신뢰 가능한 지표끼리 부호가 다름" in out, out)
# 덮개가 구간 중간에 바뀜 → 무효
out = _run_ab(_ab_rows([A, B, A, B, A, B], lids={4: "open", 5: "open"}))
check("ab: 구간 사이에 덮개 상태가 다르면 '무효'", "종합: 무효" in out and "lid" in out, out)
out = _run_ab(_ab_rows([A, B, A, B, A, B], lids={4: "open", 5: "open"}), "--allow-mixed", "lid")
check("ab: --allow-mixed lid 면 허용", "종합: 무효" not in out, out)
out = _run_ab(_ab_rows([A, B, A, B], acs={2: 1, 3: 1}))
check("ab: AC 상태가 구간마다 다르면 무효", "종합: 무효" in out and "ac" in out, out)
short = _ab_rows([A, B, A, B]) + _ab_rows([A], seg_len=2, lids={0: "open"}, base_t=time.time() - 7200 + 16 * 30 * 4 + 60)
out = _run_ab(short)
check("ab: 짧아서 버려진 구간에서 덮개가 달랐으면 경고(통계는 유지)", "버려진 짧은 구간" in out and "종합: 무효" not in out, out)
out = _run_ab(_ab_rows([A, B, A, B, A, B]), "--require", "dev.lid=open")
check("ab: --require 가 어긋나면 무효", "종합: 무효" in out and "--require" in out, out)
out = _run_ab(_ab_rows([A, B, A, B, A, B]), "--metric", "psys_w")
check("ab: --metric 으로 한 지표만도 가능", "psys(RAPL" in out and "패키지(RAPL)" not in out, out)
w, err = observe_cli.segment_coulomb(_ab_rows([A], seg_len=16)[0:16])
check("segment_coulomb: 계량 W 복원(6 W)·양자화 오차(≈54/구간초)", w is not None and abs(w - 6.0) < 0.15 and 0.05 < err < 0.2, str((w, err)))
check("segment_coulomb: 충전 중이면 None", observe_cli.segment_coulomb([dict(r, pw={**r["pw"], "status": "Charging"}) for r in _ab_rows([A], seg_len=16)]) == (None, None))


# --- (v3) 프로세스별 자발적 전환은 모든 스레드 합 — /proc/<pid>/status 는 메인 스레드뿐
import tempfile as _tf2
fp = _tf2.mkdtemp(prefix="fakeproc-")
def _mk(pid, comm, nthr, tasks, cpu=100):
    os.makedirs(f"{fp}/{pid}/task", exist_ok=True)
    stat = f"{pid} ({comm}) S 1 1 1 0 -1 0 0 0 0 0 {cpu} 0 0 0 20 0 {nthr} 0 0 0 {1000}\n"
    open(f"{fp}/{pid}/stat", "w").write(stat)
    open(f"{fp}/{pid}/status", "w").write(f"Name:\t{comm}\nvoluntary_ctxt_switches:\t{tasks[0][0]}\nnonvoluntary_ctxt_switches:\t1\n")   # 메인 스레드만 보임
    for tid, (v, n) in enumerate(tasks, start=pid):
        os.makedirs(f"{fp}/{pid}/task/{tid}", exist_ok=True)
        open(f"{fp}/{pid}/task/{tid}/stat", "w").write(stat.replace(f"{pid} (", f"{tid} (", 1))
        open(f"{fp}/{pid}/task/{tid}/status", "w").write(f"voluntary_ctxt_switches:\t{v}\nnonvoluntary_ctxt_switches:\t{n}\n")
_mk(100, "multi", 3, [(10, 0), (200, 1), (300, 2)])          # 메인 10 + 나머지 스레드 500
_mk(101, "single", 1, [(7, 0)])
old_proc = col.PROC
col.PROC = fp
try:
    smp_obj = col.Sampler("L0")
    procs, thr = smp_obj._procs()
finally:
    col.PROC = old_proc
check("수집기: 멀티스레드 프로세스는 모든 스레드의 자발적 전환을 합산(10+200+300=510, 메인 스레드만이면 10)", procs[100][3] == 510, str(procs.get(100)))
check("수집기: 스레드 1개 프로세스는 그대로(7)", procs[101][3] == 7, str(procs.get(101)))
check("수집기: L0 에서는 스레드 상세(thr)를 만들지 않음", thr == {})
col.PROC = fp
try:
    procs1, thr1 = col.Sampler("L1")._procs()
finally:
    col.PROC = old_proc
check("수집기 L1: 같은 합계 + 스레드별 행(3개)을 한 번에", procs1[100][3] == 510 and len([k for k in thr1 if k[0] == 100]) == 3, str((procs1.get(100), list(thr1))))

# v1/v2 → v3 변환: proc 행의 ctxsw_vol_s 는 ctxsw_vol_leader_s 로(합산·비교 금지), thr 행은 그대로
v2s = {"v": 2, "t": 1.0, "pw": {"batt_vi_w": 1.0}, "irq": {"cpu_all_pct": 1.0}, "proc": [{"comm": "x", "cpu_core_pct": 3.0, "ctxsw_vol_s": 9.0}], "thr": [{"comm": "x", "thr": "t", "cpu_core_pct": 1.0, "ctxsw_vol_s": 4.0}]}
n3 = core.normalize_sample(json.loads(json.dumps(v2s)))
check("v2→v3: proc 행 ctxsw_vol_s 는 ctxsw_vol_leader_s 로 바뀜(메인 스레드만이라는 뜻)", n3["proc"][0].get("ctxsw_vol_leader_s") == 9.0 and "ctxsw_vol_s" not in n3["proc"][0] and n3["v"] == 3 and n3["legacy"], str(n3))
check("v2→v3: thr 행(스레드 단위)은 그대로 ctxsw_vol_s", n3["thr"][0].get("ctxsw_vol_s") == 4.0 and "ctxsw_vol_leader_s" not in n3["thr"][0])
n13 = core.normalize_sample(json.loads(json.dumps(old)))
check("v1→v3: wake 는 두 단계를 거쳐 ctxsw_vol_leader_s", n13["proc"][0].get("ctxsw_vol_leader_s") == 30.0 and "wake" not in n13["proc"][0] and "ctxsw_vol_s" not in n13["proc"][0], str(n13["proc"]))
v3s = {"v": 3, "t": 1.0, "proc": [{"comm": "x", "ctxsw_vol_s": 9.0}]}
check("v3 는 그대로(이름·legacy 변화 없음)", core.normalize_sample(json.loads(json.dumps(v3s))) == v3s)
check("정규화는 멱등(v1→v3 를 두 번 적용해도 같음)", core.normalize_sample(core.normalize_sample(json.loads(json.dumps(old)))) == n13)

# observectl: 옛 표본은 전환 순위·합계에서 제외하고 안내
core.append_jsonl(core.SAMPLE_DIR, "samples", {"v": 3, "t": time.time() - 40, "dt": 30, "pw": {"psys_w": 3.0}, "irq": {"cpu_all_pct": 1.0, "ctxt_s": 100}, "state": "low",
                  "proc": [{"comm": "multi", "exe": "multi", "n": 1, "cpu_core_pct": 5.0, "ctxsw_vol_s": 510.0, "rss_mb": 1}], "dev": {}})
buf = _io.StringIO()
with _cx.redirect_stdout(buf):
    observe_cli.main(["top", "--since", "10m", "--by", "ctxsw"])
tout = buf.getvalue()
check("top --by ctxsw: 옛 표본 제외 안내 + 새 표본의 멀티스레드 프로세스가 보임(510/s) + 열 이름", "제외" in tout and "multi" in tout and "510" in tout and "claude" not in tout and "자발전환/s" in tout and "코어1개=100%" in tout, tout)
buf = _io.StringIO()
with _cx.redirect_stdout(buf):
    observe_cli.main(["top", "--since", "10m", "--by", "cpu"])
check("top --by cpu: 옛 표본도 포함(CPU 는 프로세스 전체 값이라 유효)", "claude" in buf.getvalue() and "multi" in buf.getvalue(), buf.getvalue())
finish("observe")
