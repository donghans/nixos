#!/usr/bin/env python3
"""단계형 eBPF 정밀 모드 시험: 프로그램 문자열·스트림 파싱·요약 계산, 실행기의 제한 시간·단계 변경·부하 상한·실패 처리, 표본에 붙이기, observectl ebpf 제어, explain 표."""
import contextlib, io, json, os, sys, tempfile, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-tiers-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
import observe_core as core, observe_tiers as tiers, observe_collector as col, observe_cli, observe_explain as ex
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

check("실효 샘플링 주파수는 1초 주기와 정수비가 아님(분수부가 0 에서 충분히 멀다 = 위상이 골고루 이동)", abs((1e6 / 53711) % 1 - 0.618) < 0.01 and 18 < tiers.SAMPLE_HZ < 19)
# --- 프로그램
for t in tiers.TIERS:
    sc = tiers.script(t, 30)
    check(f"script({t}): 30초마다 맵을 출력·비우고 TICK 로 간격을 끝냄", "interval:s:30" in sc and "clear(" in sc and "TICK" in sc, sc)
check("script(sample): 비조화 주기(53,711µs, 정수 Hz 아님)·tgid 키 — 1초 주기 에일리어싱 방지", "profile:us:53711" in tiers.script("sample") and "profile:hz" not in tiers.script("sample") and "->tgid" in tiers.script("sample"))
check("script(counts): sched_switch 에서 맵 한 번만 갱신(가벼운 변형)", tiers.script("counts").count("count()") == 1 and "sched_switch" in tiers.script("counts"))
check("script(full): 자발/비자발(prev_state)·on-CPU 시간·tgid", all(k in tiers.script("full") for k in ("prev_state == 0", "@vol", "@invol", "@cpu_ns", "->tgid")))
try:
    tiers.script("bogus"); check("알 수 없는 단계는 오류", False)
except ValueError:
    check("알 수 없는 단계는 오류", True)

# --- 스트림 파싱(실제 bpftrace -f json 모양)
def L(*objs): return [json.dumps(o) for o in objs]
stream = L({"type": "attached_probes", "data": {"probes": 2}},
           {"type": "map", "data": {"@vol": {"100": 300, "200": 50}}}, {"type": "map", "data": {"@invol": {"100": 20}}}, {"type": "map", "data": {"@cpu_ns": {"100": 3_000_000_000}}},
           {"type": "printf", "data": "TICK 1000000000000\n"},
           {"type": "map", "data": {"@vol": {"100": 10}}}, {"type": "printf", "data": "TICK 1030000000000\n"}) + ["깨진 줄"]
recs = list(tiers.parse_stream(stream))
check("parse_stream: TICK 마다 한 간격(2개), 깨진 줄·attached_probes 무시", len(recs) == 2 and recs[0]["tick_ns"] == 1_000_000_000_000 and recs[0]["maps"]["vol"] == {"100": 300, "200": 50} and recs[1]["maps"] == {"vol": {"100": 10}}, str(recs))
check("parse_stream: 간격이 끝나면 맵을 비움(둘째 간격에 첫 간격 값이 섞이지 않음)", "invol" not in recs[1]["maps"])
names = {100: "netdata", 200: "claude", 300: "x"}
res = lambda p: names.get(p, "?")
f = tiers.summarize("full", recs[0], 30.0, res)
r100 = next(p for p in f["procs"] if p["pid"] == 100)
check("summarize(full): 자발 300/30=10/s·비자발 0.7/s·CPU 3초/30초=10%(코어1=100%)·이름 해석", r100 == {"pid": 100, "comm": "netdata", "cpu_core_pct": 10.0, "vol_s": 10.0, "invol_s": 0.7}, str(r100))
check("summarize(full): 전체 전환 합((300+50+20)/30 = 12.3/s)", abs(f["sw_total_s"] - 370 / 30) < 0.1, str(f))
n100 = round(tiers.SAMPLE_HZ * 10.0)
s_ = tiers.summarize("sample", {"maps": {"cpu": {"100": n100, "0": 5000}}, "tick_ns": 0}, 10.0, res)
check("summarize(sample): 실효 주파수×시간 표본이면 100%(코어 1개), pid 0(idle) 제외", abs(s_["procs"][0]["cpu_core_pct"] - 100.0) < 1.0 and s_["procs"][0]["pid"] == 100 and s_["samples"] == n100, str(s_))
c_ = tiers.summarize("counts", {"maps": {"sw": {"100": 600, "200": 60, "0": 99999}}, "tick_ns": 0}, 30.0, res)
check("summarize(counts): 전환/s(600/30=20), 큰 순, pid 0 제외, 합 22", c_["procs"][0] == {"pid": 100, "comm": "netdata", "sw_s": 20.0} and abs(c_["sw_total_s"] - 22.0) < 0.1, str(c_))
many = {"maps": {"sw": {str(i): i for i in range(1, 50)}}, "tick_ns": 0}
check("summarize: 상위 16행만 남김", len(tiers.summarize("counts", many, 10.0, res)["procs"]) == 16)

# --- 실행기(가짜 bpftrace 프로세스)
class FakeProc:
    def __init__(self, lines, hold=False):
        self.lines, self.terminated, self.hold, self._ev = lines, False, hold, threading.Event()
        self.stdout = self
    def __iter__(self):
        for l in self.lines:
            yield l + "\n"
        if self.hold:
            self._ev.wait(5)
    def poll(self): return 0 if (self.terminated or (not self.hold and self._ev.is_set())) else None
    def terminate(self): self.terminated = True; self._ev.set()
    def wait(self, timeout=None): return 0
    def kill(self): self.terminated = True; self._ev.set()
made = []
def popen_factory(lines, hold=True):
    def mk(cmd, **kw):
        p = FakeProc(lines, hold); p.cmd = cmd; made.append(p); return p
    return mk
now = [1000.0]
tick = L({"type": "map", "data": {"@cpu": {"100": 190}}}, {"type": "printf", "data": "TICK 1\n"})
rn = tiers.Runner("/fake/bpftrace", popen=popen_factory(tick), resolve=res, clock=lambda: now[0], interval=30)
check("실행기: 요구가 없으면 시작하지 않음", rn.ensure(None) is False and not made)
check("실행기: bpftrace 경로가 없으면 시작하지 않음", tiers.Runner(None).ensure({"tier": "sample", "until": 9e9}) is False)
check("실행기: 알 수 없는 단계는 시작하지 않음", rn.ensure({"tier": "bogus", "until": now[0] + 600}) is False and not made)
check("실행기: 유효한 요구는 bpftrace 를 올바른 인자로 시작", rn.ensure({"tier": "sample", "until": now[0] + 600}) is True and made[0].cmd[:3] == ["/fake/bpftrace", "-f", "json"] and "profile:us:53711" in made[0].cmd[4], str(made[0].cmd[:3]))
time.sleep(0.3)
got = rn.take()
check("실행기: 집계 간격이 끝나면 요약이 쌓이고 take 가 가져감(한 번만)", got and got["tier"] == "sample" and got["procs"][0]["comm"] == "netdata" and rn.take() is None, str(got))
check("실행기: 같은 단계로 다시 요구해도 새로 띄우지 않음", rn.ensure({"tier": "sample", "until": now[0] + 600}) is True and len(made) == 1)
rn.ensure({"tier": "counts", "until": now[0] + 600})
check("실행기: 단계가 바뀌면 이전 것을 끝내고 새로 시작", len(made) == 2 and made[0].terminated and "sched_switch" in made[1].cmd[4])
now[0] += 700
check("실행기: 제한 시간이 지나면 자동으로 끔(until 이 지남)", rn.ensure({"tier": "counts", "until": 1600.0}) is False and made[1].terminated and rn.stopped_reason == "제한 시간 끝", str(rn.stopped_reason))
now[0] = 1000.0
rn2 = tiers.Runner("/fake/bpftrace", popen=popen_factory(tick), resolve=res, clock=lambda: now[0])
rn2.ensure({"tier": "sample", "until": now[0] + 99999})
check("실행기: 제한 시간은 최대 60분으로 자름", abs(rn2.until - (now[0] + 3600)) < 1, str(rn2.until))
rn2.stop()
# 부하 상한: counts 에서 전환이 상한을 넘으면 스스로 멈춤
heavy = L({"type": "map", "data": {"@sw": {"100": 30000 * 30}}}, {"type": "printf", "data": "TICK 1\n"})
rn3 = tiers.Runner("/fake/bpftrace", popen=popen_factory(heavy), resolve=res, clock=lambda: now[0], interval=30)
rn3.ensure({"tier": "counts", "until": now[0] + 600}); time.sleep(0.4)
check("실행기: 전환이 상한(15000/s)을 넘으면 스스로 멈추고 이유를 남김", made[-1].terminated and "상한" in (rn3.stopped_reason or ""), str(rn3.stopped_reason))
heavy_s = L({"type": "map", "data": {"@cpu": {"100": 560}}}, {"type": "printf", "data": "TICK 1\n"})
rn4 = tiers.Runner("/fake/bpftrace", popen=popen_factory(heavy_s), resolve=res, clock=lambda: now[0])
rn4.ensure({"tier": "sample", "until": now[0] + 600}); time.sleep(0.3)
check("실행기: sample 단계는 부하와 무관하므로 상한으로 멈추지 않음", not made[-1].terminated and rn4.stopped_reason is None)
rn4.stop()
def boom(cmd, **kw): raise OSError("없음")
rn5 = tiers.Runner("/fake/bpftrace", popen=boom, clock=lambda: now[0])
check("실행기: 실행 실패는 예외 없이 이유를 남기고 False", rn5.ensure({"tier": "sample", "until": now[0] + 600}) is False and "실행 실패" in rn5.stopped_reason)

# --- 표본에 붙이기(수집기)
class R:
    def __init__(self, rec, reason=None, running=False): self.rec, self.stopped_reason, self.running = rec, reason, running
    def take(self): r, self.rec = self.rec, None; return r
s1 = col.attach_ebpf({"t": 1}, R({"tier": "full", "procs": []}, running=True))
check("attach_ebpf: 집계가 있으면 표본에 ebpf 로 붙음", s1["ebpf"]["tier"] == "full" and "ebpf_stopped" not in s1)
rr = R(None, "전환 상한", running=False)
s2 = col.attach_ebpf({"t": 2}, rr); s3 = col.attach_ebpf({"t": 3}, rr)
check("attach_ebpf: 스스로 멈춘 이유는 한 번만 알림", s2.get("ebpf_stopped") == "전환 상한" and "ebpf_stopped" not in s3)

# --- observectl ebpf 제어
def cli(*argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            observe_cli.main(["ebpf", *argv])
    except SystemExit as e:
        return buf.getvalue() + "EXIT:" + str(e)
    return buf.getvalue()
core.write_control({"enabled": False})
out = cli("on", "full")
check("observectl ebpf on: 수집이 꺼져 있으면 안내하고 켜지 않음", "EXIT:" in out and "observectl on" in out and not core.read_control().get("ebpf"), out)
core.write_control({"enabled": True})
out = cli("on", "full", "--for", "10m")
e = core.read_control()["ebpf"]
check("observectl ebpf on: 제어 파일에 단계와 제한 시간(10분)을 씀", e["tier"] == "full" and 590 < e["until"] - time.time() <= 600 and "자동으로 꺼집니다" in out, out)
cli("on", "counts", "--for", "5h")
check("observectl ebpf on: 제한 시간은 최대 60분으로 자름", 3590 < core.read_control()["ebpf"]["until"] - time.time() <= 3600)
check("observectl ebpf on: 잘못된 단계·시간 형식은 안내 후 종료", "EXIT:" in cli("on", "bogus") and "EXIT:" in cli("on", "full", "--for", "엉터리"))
check("observectl ebpf status: 켜짐과 남은 시간", "켜짐: counts" in cli("status"))
cli("off")
check("observectl ebpf off: 제어 파일에서 지움", core.read_control().get("ebpf") is None and "꺼짐" in cli("status"))
check("observectl ebpf tiers: 단계 3개의 비용·정확성 표시", all(k in cli("tiers") for k in ("sample", "counts", "full", "0.12%", "1.8%", "안전장치")))

# --- explain 의 정밀(eBPF) 표
T = 1_700_000_000.0
def row(i, tier, procs):
    return {"v": 3, "t": T + i * 30, "dt": 30, "state": "low", "pw": {"psys_w": 5.0, "pkg_w": 2.0, "batt_vi_w": 5.0, "status": "Discharging", "ac": 0}, "irq": {"cpu_all_pct": 3.0, "ctxt_s": 2000, "intr_s": 1000},
            "dev": {"lid": "closed", "vt": "tty1"}, "proc": [], "ebpf": {"tier": tier, "dt": 30.0, "procs": procs}}
g = [row(i, "full", [{"pid": 100, "comm": "netdata", "cpu_core_pct": 4.0, "vol_s": 360.0, "invol_s": 2.0}, {"pid": 200, "comm": "claude", "cpu_core_pct": 8.0, "vol_s": 100.0, "invol_s": 5.0}]) for i in range(6)]
tb = ex.ebpf_table(g)
check("ebpf_table: 간격 평균·CPU 큰 순", tb["records"] == 6 and tb["procs"][0]["comm"] == "claude" and abs(tb["procs"][1]["vol"] - 360.0) < 1e-9 and tb["tiers"] == ["full"], str(tb))
check("ebpf_table: eBPF 가 없는 구간은 None", ex.ebpf_table([{"t": 1, "proc": []}]) is None)
res_ex = ex.build(g, [], T, T + 180, None, None)
txt = "\n".join(ex.render(res_ex, core.hms))
check("explain: 프로세스·앱 섹션에 정밀(eBPF) 표와 정확성 문구", "정밀(eBPF" in txt and "전체(E3)" in txt and "99%" in txt and "netdata" in txt and "360.0" in txt, txt)
finish("tiers")
