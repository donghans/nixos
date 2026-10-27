#!/usr/bin/env python3
"""스팬/트레이스 시험: ID·부모-자식·프로세스 간 전파, observe-emit span-*, 트리/에너지/요약 계산, observectl trace 출력."""
import io, json, os, subprocess, sys, tempfile, time, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-trace-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
os.environ.pop("OBSERVE_TRACE", None)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "_testkit"))
import observe_core as core, observe_events as oe, observe_trace as tr, observe_cli
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)
core.write_control({"components": {"*": "info", "tt": "debug"}})

def events():
    return list(core.iter_jsonl(core.state_dir(), "events"))

# --- 같은 프로세스 안: 부모-자식, 같은 trace
ev = oe.Events("tt")
with ev.span("outer", level="info", a=1) as o:
    with ev.span("inner", level="info") as i:
        check("스팬 안에서 current() 가 안쪽 스팬", oe.current() == (o.trace, i.id))
    check("안쪽이 끝나면 current() 가 바깥으로 복귀", oe.current() == (o.trace, o.id))
check("스팬 밖에서는 current() 없음", oe.current() is None)
sp = tr.build_spans(events())
byname = {s["name"]: s for s in sp}
check("inner.parent == outer.id, 같은 trace", byname["inner"]["parent"] == byname["outer"]["id"] and byname["inner"]["trace"] == byname["outer"]["trace"])
check("outer 는 루트(parent 없음), 속성 a=1, status ok, ms 있음", byname["outer"]["parent"] is None and byname["outer"]["attrs"].get("a") == 1 and byname["outer"]["status"] == "ok" and byname["outer"]["ms"] is not None)
try:
    with ev.span("boom", level="info"):
        raise ValueError("x")
except ValueError:
    pass
b = {s["name"]: s for s in tr.build_spans(events())}["boom"]
check("예외는 fail 로 기록(예외 정보 포함)", b["status"] == "fail" and "ValueError" in b["attrs"]["exc"])
with ev.span("late", level="info") as lt:
    lt.set(rows=7)
check("sp.set 으로 끝 이벤트에 속성 추가", {s["name"]: s for s in tr.build_spans(events())}["late"]["attrs"].get("rows") == 7)
with oe.Events("other").span("quiet"):
    pass
check("debug 수준 스팬은 info 컴포넌트에서 버려짐", "quiet.begin" not in [x["ev"] for x in events()] and oe.current() is None)

# --- 프로세스 간: span-run
emit = [sys.executable, os.path.join(ROOT, "observe_emit.py")]
env = {**os.environ, "PYTHONPATH": ROOT}
child = "import os,sys; sys.path.insert(0, %r); from observe_events import Events; import observe_events as o; print(os.environ.get('OBSERVE_TRACE','')); " \
        "ev=Events('child')\nwith ev.span('work', level='info'): pass" % ROOT
r = subprocess.run(emit + ["span-run", "nixup", "build", "target=os", "--", sys.executable, "-c", child], capture_output=True, text=True, env=env)
check("span-run: 종료 코드 0 전달·자식이 OBSERVE_TRACE 를 받음", r.returncode == 0 and ":" in r.stdout.strip(), r.stdout + r.stderr)
sp = tr.build_spans(events())
run = next(s for s in sp if s["name"] == "build")
work = next(s for s in sp if s["name"] == "work")
check("span-run: 실행 파일 이름만 기록(인자 없음)·속성 target=os", run["attrs"].get("cmd") == os.path.basename(sys.executable) and run["attrs"].get("target") == "os" and "-c" not in json.dumps(run["attrs"]), str(run["attrs"]))
check("자식 프로세스의 스팬이 span-run 스팬 아래로 붙음(같은 trace)", work["parent"] == run["id"] and work["trace"] == run["trace"], str((work, run)))
r = subprocess.run(emit + ["span-run", "nixup", "badcmd", "--", sys.executable, "-c", "import sys; sys.exit(3)"], env=env)
bad = next(s for s in tr.build_spans(events()) if s["name"] == "badcmd")
check("span-run: 실패 종료 코드 3 을 그대로 돌려주고 fail·exit=3 기록", r.returncode == 3 and bad["status"] == "fail" and bad["attrs"].get("exit") == 3, str(bad))
r = subprocess.run(emit + ["span-run", "nixup", "nocmd", "--", "/nonexistent/cmd"], env=env)
check("span-run: 없는 명령은 127", r.returncode == 127)

# --- 신호: Ctrl-C 를 받아도 자식을 강제로 죽이지 않고 자식의 정리(cleanup)가 끝나길 기다린다(nixup 의 잠금 해제 등)
import signal
marker = os.path.join(TMP, "cleanup.txt")
slow = ("import signal, sys, time\n"
        "def h(n, f):\n"
        "    time.sleep(0.3); open(%r, 'w').write('cleaned'); sys.exit(0)\n"
        "signal.signal(signal.SIGINT, h); signal.signal(signal.SIGTERM, h)\n"
        "print('ready', flush=True); time.sleep(30)\n") % marker
for sig, label in ((signal.SIGINT, "SIGINT(프로세스 그룹 전체)"), (signal.SIGTERM, "SIGTERM(span-run 에게만)")):
    if os.path.exists(marker):
        os.unlink(marker)
    pr = subprocess.Popen(emit + ["span-run", "nixup", "sigtest", "--", sys.executable, "-c", slow], env=env, stdout=subprocess.PIPE, text=True, start_new_session=True)
    pr.stdout.readline()                                   # 자식이 핸들러를 건 뒤(ready)에 보낸다
    if sig == signal.SIGINT:
        os.killpg(pr.pid, sig)                             # 터미널의 Ctrl-C 와 같다: 그룹 전체에 전달
    else:
        os.kill(pr.pid, sig)                               # span-run 에게만 → 자식에게 전달돼야 함
    rc = pr.wait(timeout=10)
    check(f"{label}: 자식이 스스로 정리를 마친 뒤 끝남(강제 종료 아님)", os.path.exists(marker) and open(marker).read() == "cleaned" and rc == 0, f"rc={rc} marker={os.path.exists(marker)}")
    st = [s for s in tr.build_spans(events()) if s["name"] == "sigtest"][-1]
    check(f"{label}: 스팬은 정상 종료로 기록", st["t1"] is not None and st["status"] == "ok", str(st))
killed = subprocess.Popen(emit + ["span-run", "nixup", "sigkilled", "--", sys.executable, "-c", "import os,signal; os.kill(os.getpid(), signal.SIGKILL)"], env=env)
check("신호로 죽은 자식은 128+번호(137) 로 전달", killed.wait(timeout=10) == 137)

r = subprocess.run(emit + ["span-probe"], capture_output=True, text=True, env=env)
check("span-probe: 0 으로 끝나고 아무것도 출력/기록하지 않음", r.returncode == 0 and r.stdout == "" and r.stderr == "", r.stdout + r.stderr)

# --- span-begin / span-end (셸 흐름)
tok = subprocess.run(emit + ["span-begin", "lid", "close", "state=closed"], capture_output=True, text=True, env=env).stdout.strip()
check("span-begin 이 토큰 출력(6 필드)", tok.count("|") == 5, tok)
time.sleep(0.05)
subprocess.run(emit + ["span-end", tok, "action=screen-off"], env=env)
lc = next(s for s in tr.build_spans(events()) if s["name"] == "close")
check("span-end: 시작·끝 짝, 소요 ≥ 50ms, 속성", lc["status"] == "ok" and lc["ms"] >= 50 and lc["attrs"].get("action") == "screen-off" and lc["attrs"].get("state") == "closed", str(lc))
tok = subprocess.run(emit + ["span-begin", "lid", "open"], capture_output=True, text=True, env=env).stdout.strip()
check("끝나지 않은 스팬은 running(t1=None)", next(s for s in tr.build_spans(events()) if s["name"] == "open")["status"] == "running")
r = subprocess.run(emit + ["lid", "info", "plain", "k=1"], env=env)
check("기존 사용법(컴포넌트 수준 이벤트)은 그대로", r.returncode == 0 and any(e["ev"] == "plain" and e["k"] == 1 for e in events()))

# --- 트리/에너지/요약(합성 데이터)
T = 1_000_000.0
def mk(sid, parent, name, a, b, status="ok", comp="c"):
    return {"id": sid, "trace": "T", "parent": parent, "comp": comp, "name": name, "t0": T + a, "t1": None if b is None else T + b, "ms": None if b is None else (b - a) * 1000, "status": status, "attrs": {}, "pid": 1}
spans = [mk("a", None, "root", 0, 100), mk("b", "a", "child1", 10, 40), mk("c", "a", "child2", 50, 90, "fail"), mk("d", "b", "grand", 15, 20), mk("z", "gone", "orphan", 5, 6)]
order = [(d, s["name"]) for d, s in tr.order_tree(spans)]
check("order_tree: 깊이우선·형제는 시작 순·부모 없는 건 루트", order == [(0, "root"), (1, "child1"), (2, "grand"), (1, "child2"), (0, "orphan")], str(order))
samples = [{"t": T + 30 * i, "dt": 30, "pw": {"psys_w": 4.0, "batt_vi_w": 5.0, "status": "Discharging", "q_uah": 3000000 - i * 1000, "v_uv": 15000000}} for i in range(-1, 8)]
e = tr.energy(samples, T, T + 100)
check("energy: 4 W × 100 s = 0.111 Wh, 평균 4 W", e and abs(e["psys_wh"] - 400 / 3600) < 1e-6 and abs(e["avg_psys_w"] - 4.0) < 1e-9 and abs(e["batt_wh"] - 500 / 3600) < 1e-6, str(e))
e2 = tr.energy(samples, T + 15, T + 20)
check("energy: 표본보다 짧은 구간도 겹친 시간만큼(5 s × 4 W)", abs(e2["psys_wh"] - 20 / 3600) < 1e-6 and e2["cover_s"] == 5, str(e2))
check("energy: 겹치는 표본이 없으면 None", tr.energy(samples, T + 9999, T + 10000) is None and tr.energy(samples, T + 5, T + 5) is None)
long_s = [{"t": T + 60 * i, "dt": 60, "pw": {"psys_w": 4.0, "status": "Discharging", "q_uah": 3000000 - i * 100, "v_uv": 15000000}} for i in range(0, 30)]
el = tr.energy(long_s, T + 60, T + 1260)
check("energy: 10분 이상이면 누적 계량 Wh 도(20 구간 × 100 µAh × 15 V = 0.03 Wh)", el["coulomb_wh"] is not None and abs(el["coulomb_wh"] - 0.03) < 1e-6, str(el))
check("energy: 방전이 아니면 계량값 없음", tr.energy([dict(s, pw={**s["pw"], "status": "Charging"}) for s in long_s], T + 60, T + 1260)["coulomb_wh"] is None)
rows = {r["name"]: r for r in tr.summarize(spans, samples)}
check("summarize: 횟수·실패·진행 중·소요 중앙값", rows["child2"]["fail"] == 1 and rows["root"]["n"] == 1 and abs(rows["root"]["p50"] - 100) < 1e-9)
sm = tr.summarize([mk("x", None, "job", 0, 10), mk("y", None, "job", 20, 50), mk("w", None, "job", 60, None)], samples)[0]
check("summarize: 이름별 합산(3회, 진행 중 1)·에너지는 끝난 것만", sm["n"] == 3 and sm["running"] == 1 and sm["wh_n"] == 2 and abs(sm["wh_sum"] - 4.0 * 40 / 3600) < 1e-6, str(sm))
lines = tr.render_trace(spans, samples, 110, T + 200)
check("render_trace: 줄 수 = 스팬 수, 들여쓰기·실패 표시·에너지", len(lines) == 5 and lines[2].lstrip().startswith("c:grand") and "✗" in lines[3] and "Wh" in lines[0], "\n".join(lines))
check("render_trace: 폭 안에 들어옴", all(len(l) <= 110 + 4 for l in lines), str(max(len(l) for l in lines)))
check("fmt_dur", tr.fmt_dur(0.5) == "500ms" and tr.fmt_dur(12) == "12.0s" and tr.fmt_dur(300) == "5.0분" and tr.fmt_dur(None) == "…")
check("fmt_energy: 표본 적으면 ~ 표시", tr.fmt_energy({"n": 1, "cover_s": 5, "psys_wh": 0.01, "avg_psys_w": 4, "coulomb_wh": None}).startswith("~") and tr.fmt_energy(None) == "-")

# --- observectl trace (CLI)
for s in samples:
    pass
now = time.time()
for i in range(12):
    core.append_jsonl(core.SAMPLE_DIR, "samples", {"t": now - 360 + i * 30, "dt": 30, "pw": {"psys_w": 4.0, "batt_vi_w": 5.0, "status": "Discharging"}})
def run_cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        observe_cli.main(["trace", *args])
    return buf.getvalue()
out = run_cli("--since", "1h", "-n", "50")
check("observectl trace: 폭포에 build/work 스팬과 트레이스 헤더", "== trace" in out and "nixup:build" in out and "child:work" in out, out)
out = run_cli("--since", "1h", "--by")
check("observectl trace --by: 이름별 요약표", "nixup:build" in out and "평균 Wh" in out, out)
out = run_cli("--since", "1h", "--comp", "lid")
check("observectl trace --comp: 필터", "lid:close" in out and "nixup:build" not in out, out)
try:
    run_cli("--since", "1h", "--name", "없는이름")
    check("스팬 없으면 안내 후 종료", False)
except SystemExit as e:
    check("스팬 없으면 안내 후 종료", "스팬이 없습니다" in str(e))
finish("trace")
