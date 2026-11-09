#!/usr/bin/env python3
"""llm-host recorder.py(S6) 시험: 로그 파일 권한 0600, text_delta 제외, 보존 기간 삭제, 비용 합계, 원본 줄 녹화, max_budget_usd 인자.
비용 0: 가짜 백엔드만 띄운다. 시험은 임시 폴더 안에서만 쓰고 지운다(~/.local/state 를 건드리지 않는다)."""
import asyncio, json, os, shutil, stat, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
import host as H
import recorder as R
from claude_adapter import ClaudeAdapter

FAKE = os.path.join(ROOT, "fake_claude.py")
TMP = tempfile.mkdtemp(prefix="llmhost-s6-")
_n = [0]


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def scenario(steps):
    _n[0] += 1
    p = os.path.join(TMP, f"sc{_n[0]}.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(dump(s) + "\n")
    return p


def spec_for(steps, **kw):
    d = {"exe": [sys.executable, FAKE, scenario(steps), "--timeout", "8"], "cwd": TMP, "persist": False}
    d.update(kw)
    return d


def turn(tag, cost):
    return [{"expect": {"stdin_type": "user"}},
            {"emit": [{"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": f"hi-{tag}"}}, "session_id": f"bk-{tag}"},
                      {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"reply-{tag}"}]}, "session_id": f"bk-{tag}"},
                      {"type": "result", "subtype": "success", "is_error": False, "result": f"reply-{tag}", "total_cost_usd": cost, "num_turns": 1, "session_id": f"bk-{tag}"}]}]


def new_host(**kw):
    _n[0] += 1
    return H.SessionHost(lambda hs: ClaudeAdapter(host_session=hs), registry_dir=os.path.join(TMP, f"reg{_n[0]}"), **kw)


def run(coro, t=60):
    return asyncio.run(asyncio.wait_for(coro, t))


# ---------------------------------------------------------------- 1. EventLog: 권한·제외·왕복
old_umask = os.umask(0)                     # umask 0 이어도 0600 이어야 한다
root1 = os.path.join(TMP, "logs1")
lg = R.EventLog("s1", root1)
lg.record(E.TextDelta(host_session="s1", text="secret-ish", seq=1))
lg.record(E.ToolCall(host_session="s1", call="c1", name="Bash", input={"command": "echo 한글"}, seq=2))
lg.record(E.TurnResult(host_session="s1", text="ok", cost_total=0.5, cost_delta=0.5, seq=3))
lg.close()
os.umask(old_umask)
rows = R.read_log(lg.path)
check("로그 파일 권한 0600", mode(lg.path) == 0o600, oct(mode(lg.path)))
check("로그 폴더 권한 0700(상위 root 포함)", mode(lg.dir) == 0o700 and mode(root1) == 0o700, f"{oct(mode(lg.dir))} {oct(mode(root1))}")
check("위치는 <root>/<host_session>/events.jsonl", lg.path == os.path.join(root1, "s1", "events.jsonl"))
check("text_delta 는 기본 제외, 나머지는 기록(log_open 줄 + 2건)", [r["kind"] for r in rows] == ["log_open", "tool_call", "turn_result"] and lg.skipped == 1 and lg.written == 2)
check("기록한 줄이 event_from_json 으로 되살아난다(한글 그대로)", E.event_from_json(json.dumps(rows[1])).input == {"command": "echo 한글"})
lg2 = R.EventLog("s2", root1, include=True)
lg2.record(E.TextDelta(host_session="s2", text="x", seq=1)); lg2.close()
check("include=True 면 text_delta 도 기록", [r["kind"] for r in R.read_log(lg2.path)] == ["log_open", "text_delta"])
os.chmod(lg.path, 0o644)
lg3 = R.EventLog("s1", root1); lg3.record(E.Notice(host_session="s1", text="again")); lg3.close()
check("이미 있는 파일은 이어 쓰고 권한을 0600 으로 되돌린다", mode(lg.path) == 0o600 and [r["kind"] for r in R.read_log(lg.path)].count("log_open") == 2)
bad = None
try:
    R.EventLog("../x", root1)
except ValueError as e:
    bad = e
check("host_session 에 경로 문자가 있으면 거부", bad is not None)
blocked = os.path.join(TMP, "afile"); open(blocked, "w").close()
lg4 = R.EventLog("s1", blocked)
r4 = lg4.record(E.Notice(host_session="s1", text="x"))
check("로그를 못 써도 예외 없이 errors 로 센다", r4 is False and lg4.errors == 1)

# ---------------------------------------------------------------- 2. 보존 기간 삭제
root2 = os.path.join(TMP, "logs2"); os.makedirs(root2)
NOW = 1_800_000_000.0
def mk(name, age_days, extra=False):
    d = os.path.join(root2, name); os.makedirs(d)
    f = os.path.join(d, "events.jsonl"); open(f, "w").write("{}\n")
    t = NOW - age_days * 86400; os.utime(f, (t, t))
    if extra:
        open(os.path.join(d, "keep.txt"), "w").write("x")
    return d
mk("old", 15); mk("edge_new", 13.9); mk("old_extra", 30, extra=True); mk("fresh", 0)
os.makedirs(os.path.join(root2, "nolog")); open(os.path.join(root2, "nolog", "other.txt"), "w").write("x")
outside = os.path.join(TMP, "outside"); os.makedirs(outside)
of = os.path.join(outside, "events.jsonl"); open(of, "w").write("{}\n"); os.utime(of, (NOW - 99 * 86400,) * 2)
os.symlink(outside, os.path.join(root2, "linkdir"))
removed = R.purge_logs(root2, 14, now=NOW)
left = sorted(os.listdir(root2))
check("14일 넘은 로그만 지운다(old·old_extra 삭제, 13.9일·방금 것 유지)", removed == ["old", "old_extra"] and "old" not in left and "edge_new" in left and "fresh" in left, f"{removed} {left}")
check("폴더에 다른 파일이 있으면 폴더는 남긴다", os.path.isdir(os.path.join(root2, "old_extra")) and os.listdir(os.path.join(root2, "old_extra")) == ["keep.txt"])
check("events.jsonl 이 없는 폴더·심볼릭 링크 대상은 건드리지 않는다", os.path.exists(os.path.join(root2, "nolog", "other.txt")) and os.path.exists(of))
check("없는 root 는 빈 목록", R.purge_logs(os.path.join(TMP, "nope"), 14) == [])
err = None
try:
    R.purge_logs(root2, -1)
except ValueError as e:
    err = e
check("음수 보존 기간은 거부", err is not None)
check("기본 보존 기간은 14일", R.DEFAULT_RETENTION_DAYS == 14)

# ---------------------------------------------------------------- 3. 비용 누적
ct = R.CostTracker()
for d, t in ((0.25, 0.25), (0.5, 0.75), (0.0, 0.75)):
    ct.add(E.TurnResult(cost_delta=d, cost_total=t))
ct.add(E.TurnResult(cost_delta=None, cost_total=None)); ct.add(E.Notice(text="x"))
check("비용: 델타 합 0.75 = 마지막 누적, 턴 4·가격 있는 턴 3", abs(ct.total - 0.75) < 1e-12 and ct.last_total == 0.75 and ct.turns == 4 and ct.priced_turns == 3, str(ct.summary()))

async def t_host():
    logroot = os.path.join(TMP, "hostlogs"); rawdir = os.path.join(TMP, "raw")
    # 방금 시작하는 호스트가 오래된 로그를 지운다
    od = os.path.join(logroot, "ancient"); os.makedirs(od)
    of2 = os.path.join(od, "events.jsonl"); open(of2, "w").write("{}\n"); os.utime(of2, (time.time() - 20 * 86400,) * 2)
    h = new_host(log_root=logroot, raw_dir=rawdir, keep_history=True)
    A = await h.start_session(spec_for(turn("A", 0.0102) + turn("A2", 0.0302)), host_session="a")
    B = await h.start_session(spec_for(turn("B", 0.005)), host_session="b")
    for s, n in ((A, 2), (B, 1)):
        for i in range(n):
            await s.send(f"m{i}")
            await s.collect_until(lambda e: e.kind == "turn_result", 10)
    mid = h.cost_summary()
    await h.close_all(grace=5)
    h.release("b")
    return h, A, B, mid, logroot, rawdir
h, A, B, mid, logroot, rawdir = run(t_host())
check("호스트가 시작할 때 보존 기간을 넘은 로그를 지운다", h.purged_logs == ["ancient"] and not os.path.exists(os.path.join(logroot, "ancient")))
la, lb = os.path.join(logroot, "a", "events.jsonl"), os.path.join(logroot, "b", "events.jsonl")
ra = R.read_log(la)
check("세션마다 따로 로그가 생기고 0600", os.path.exists(la) and os.path.exists(lb) and mode(la) == 0o600 and mode(lb) == 0o600 and mode(os.path.dirname(la)) == 0o700)
check("로그에 turn_result 2건·session_ended 가 있고 text_delta 는 없다(세션 내 history 에는 있었다)",
      [r["kind"] for r in ra].count("turn_result") == 2 and ra[-1]["kind"] == "session_ended"
      and "text_delta" not in {r["kind"] for r in ra} and any(e.kind == "text_delta" for e in A.history))
check("로그 줄의 seq 가 history 와 같고 host_session 이 자기 세션", [r["seq"] for r in ra[1:]] == [e.seq for e in A.history if e.kind != "text_delta"] and {r["host_session"] for r in ra[1:]} == {"a"})
cs = h.cost_summary()
check("비용 합계: 세션 a 는 0.0302(=마지막 누적), b 는 0.005, 전체 0.0352 — release 한 세션도 포함",
      abs(cs["sessions"]["a"]["total"] - 0.0302) < 1e-9 and cs["sessions"]["a"]["last_cost_total"] == 0.0302
      and abs(cs["sessions"]["b"]["total"] - 0.005) < 1e-9 and abs(cs["total"] - 0.0352) < 1e-9 and cs["turns"] == 3 and "b" not in h.sessions, str(cs))
check("진행 중에도 합계를 볼 수 있다(중간값은 최종값 이하)", mid["total"] <= cs["total"] + 1e-12 and mid["turns"] == 3)
logged_cost = sum(r.get("cost_delta") or 0 for r in ra if r["kind"] == "turn_result")
check("로그의 cost_delta 합이 cost_summary 와 같다", abs(logged_cost - cs["sessions"]["a"]["total"]) < 1e-9)
rawa = R.read_log(os.path.join(rawdir, "a.raw.jsonl"))
check("원본 줄 녹화: in 2건·out 에 글자 조각·result 가 있고 형식은 fixtures 와 같다({t,dir,line}), 0600",
      [r["dir"] for r in rawa].count("in") == 2 and any(r["dir"] == "out" and r["line"].get("type") == "stream_event" for r in rawa)
      and all(set(r) == {"t", "dir", "line"} for r in rawa) and mode(os.path.join(rawdir, "a.raw.jsonl")) == 0o600
      and rawa[0]["line"] == {"type": "user", "message": {"role": "user", "content": "m0"}})

# ---------------------------------------------------------------- 4. log_deltas, 싱크 예외, 기동 실패
async def t_misc():
    logroot = os.path.join(TMP, "hostlogs2")
    h = new_host(log_root=logroot, log_deltas=True, retention_days=None)
    s = await h.start_session(spec_for(turn("D", 0.001)), host_session="d")
    def boom(ev):
        raise RuntimeError("sink bug")
    s.sinks.append(boom)
    await s.send("x"); await s.collect_until(lambda e: e.kind == "turn_result", 10)
    alive = s.running
    await h.close_all(grace=5)
    # 실행 파일 없음 → 기동 실패 세션도 로그가 닫히고 합계가 0
    h2 = new_host(log_root=logroot, retention_days=None)
    f = await h2.start_session({"exe": ["/nonexistent/claude-xyz"], "cwd": TMP, "persist": False}, host_session="f")
    await h2.close_all(grace=2)
    return logroot, alive, f, h2
logroot2, alive, f, h2 = run(t_misc())
check("log_deltas=True 면 글자 조각도 기록", "text_delta" in {r["kind"] for r in R.read_log(os.path.join(logroot2, "d", "events.jsonl"))})
check("싱크가 예외를 내도 세션은 살아 있고 이벤트는 계속 온다", alive)
rf = R.read_log(os.path.join(logroot2, "f", "events.jsonl"))
check("기동 실패 세션도 notice·session_ended(crashed)가 로그에 남고 열린 로그가 없다", [r["kind"] for r in rf][-1] == "session_ended" and rf[-1]["reason"] == "crashed" and h2._logs == {})
check("log_root 를 주지 않으면 로그를 만들지 않는다", not os.path.exists(os.path.join(TMP, "never")) and new_host().log_root is None)

# ---------------------------------------------------------------- 5. max_budget_usd
ad = ClaudeAdapter(host_session="x")
a0 = ad.argv({})
check("max_budget_usd 기본값 없음 — 인자가 안 붙는다", "--max-budget-usd" not in a0)
a1 = ad.argv({"max_budget_usd": 2.5})
check("max_budget_usd=2.5 → --max-budget-usd 2.5", a1[a1.index("--max-budget-usd") + 1] == "2.5" and a1.count("--max-budget-usd") == 1)
a2 = ad.argv({"max_budget_usd": 5})
check("정수도 받는다(5)", a2[a2.index("--max-budget-usd") + 1] == "5")
def raises(v):
    try:
        ad.argv({"max_budget_usd": v}); return False
    except ValueError:
        return True
check("0·음수·불리언·문자열·NaN·무한대는 ValueError", all(raises(v) for v in (0, -1, True, "3", float("nan"), float("inf"))))
async def t_bad_budget():
    h = new_host()
    try:
        await h.start_session(spec_for(IDLE_, max_budget_usd=-1)); ok = False
    except ValueError:
        ok = True
    return ok, h.active
IDLE_ = []
ok, active = run(t_bad_budget())
check("잘못된 예산으로 start_session 이 실패해도 자리(상한)를 잡고 있지 않다", ok and active == 0)

shutil.rmtree(TMP, ignore_errors=True)
finish("llm-host recorder")
