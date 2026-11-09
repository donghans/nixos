#!/usr/bin/env python3
"""llm-host claude_adapter.decode 시험: S0 녹화본(tests/fixtures)을 전부 재생해 알려진 종류의 raw 비율 0, 알 수 없는 줄은 raw,
init→session_ready/session_info, cost_delta, run 매핑, text_delta 와 완결 메시지의 중복 표시(shown_as), 권한·질문·서브에이전트·훅."""
import copy, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
from adapter import Adapter
from claude_adapter import ClaudeAdapter

FX = os.path.join(HERE, "fixtures")


def load(name):
    return [json.loads(l) for l in open(os.path.join(FX, name + ".jsonl"), encoding="utf-8") if l.strip()]


def replay(name):
    """녹화본 하나를 새 어댑터에 흘려 (어댑터, [(원본 줄, [이벤트])]) 를 돌려준다. 호스트가 보낸 user 줄은 note_sent 로 알린다."""
    ad = ClaudeAdapter(host_session="h1"); rows = []
    for e in load(name):
        ln = e["line"]
        if e["dir"] == "in" and isinstance(ln, dict) and ln.get("type") == "user":
            ad.note_sent()
        elif e["dir"] == "out":
            rows.append((ln, ad.decode(ln)))
    return ad, rows


check("Adapter 의 추상 메서드를 모두 구현(인스턴스 생성 가능)", isinstance(ClaudeAdapter(), Adapter))
ad0 = ClaudeAdapter()
check("쓰기 쪽(S3): argv·env·encode 가 동작(상세는 test_session.py)", ad0.argv({})[0] == "claude" and isinstance(ad0.env({}), dict)
      and len(ad0.encode(E.Interrupt())) == 1 and ad0.encode(E.Close()) == [])

# ---- 1. 녹화본 전체 재생: raw 0, 줄 수, 왕복
ALL = {}
for name in ("noinit", "perm", "main", "sub"):
    ad, rows = replay(name); ALL[name] = (ad, rows)
    evs = [ev for _, es in rows for ev in es]
    raws = [ev for ev in evs if isinstance(ev, E.Raw)]
    check(f"{name}: 알려진 종류의 raw 0", not raws, str([r.payload.get("type") for r in raws][:3]))
    check(f"{name}: 모든 이벤트가 규격 왕복", all(E.event_from_json(E.to_json(ev)) == ev for ev in evs))
    check(f"{name}: 이벤트에 host_session", all(ev.host_session == "h1" for ev in evs))
check("noinit: 출력이 없어 이벤트도 0(메시지 전 init 없음)", ALL["noinit"][1] == [])
kinds = {ev.kind for n in ("perm", "main", "sub") for _, es in ALL[n][1] for ev in es}
need = {"session_ready", "turn_started", "text_delta", "thinking", "message", "tool_call", "tool_result", "permission_request",
        "question_request", "subtask", "hook", "turn_result", "rate_limit", "notice"}
check("녹화본이 번역한 kind 가 기대와 같다", need <= kinds, str(need - kinds))

def sr0(name):
    return evs_of(name, "session_ready")[0]


def evs_of(name, kind):
    return [ev for _, es in ALL[name][1] for ev in es if ev.kind == kind]

# 줄 → 이벤트 대응: 소비자에게 줄 게 없는 줄만 []
for name in ("perm", "main", "sub"):
    ad, rows = ALL[name]
    empties = [ln for ln, es in rows if not es]
    check(f"{name}: [] 인 줄은 ignored 로 센 것과 같은 수", len(empties) == sum(ad.ignored.values()), f"{len(empties)} vs {ad.ignored}")
    check(f"{name}: [] 인 줄은 stream 뼈대·도구 입력/사고 조각·init 반복·status 반복뿐", all(
        ln["type"] in ("stream_event", "system") for ln in empties))

# ---- 2. init → session_ready 한 번, 이후 session_info(바뀐 것 없으면 없음)
for name in ("perm", "main", "sub"):
    ad, rows = ALL[name]
    n_init = sum(1 for ln, _ in rows if ln.get("subtype") == "init")
    check(f"{name}: init {n_init}번 중 session_ready 는 1번", len(evs_of(name, "session_ready")) == 1 and n_init > 1)
    si = evs_of(name, "session_info")
    check(f"{name}: 첫 턴 뒤 init 에서 늘어난 도구·mcp(계정 커넥터)만 session_info 로, 그 뒤 같은 값은 이벤트 없음",
          len(si) == 1 and set(si[0].changed) == {"tools", "mcp"} and len(si[0].changed["tools"]) > len(sr0(name).tools), str([sorted(e.changed) for e in si]))
sr = evs_of("main", "session_ready")[0]
check("session_ready 필드", sr.backend == "claude" and sr.backend_version == "2.1.317" and sr.model == "claude-haiku-5-5" and sr.permission_mode == "default"
      and "AskUserQuestion" in sr.tools and len(sr.capabilities) == 14 and len(sr.skills) == 45 and len(sr.slash) == 80 and sr.mcp == [] and sr.cwd.endswith("/proj"))
check("session_ready 가 첫 입력 뒤 첫 이벤트(메시지 전 init 없음)", ALL["main"][1][0][1][0].kind == "session_ready")
check("backend_session 이 init 의 session_id", sr.backend_session == "00000000-0000-4000-8000-000000000000")
check("capabilities: init 뒤 interrupt True", ALL["main"][0].capabilities["interrupt"] is True and ClaudeAdapter().capabilities["interrupt"] == "unknown")
check("capabilities 값은 True/False/unknown 뿐", set(map(str, ClaudeAdapter().capabilities.values())) <= {"True", "False", "unknown"})

# ---- 3. 턴·비용
for name in ("perm", "main", "sub"):
    ad, rows = ALL[name]
    n_res = sum(1 for ln, _ in rows if ln.get("type") == "result")
    ts, tr = evs_of(name, "turn_started"), evs_of(name, "turn_result")
    check(f"{name}: turn_started 수 = result 수(턴 안 반복 requesting 은 한 번만)", len(ts) == len(tr) == n_res, f"{len(ts)} {len(tr)} {n_res}")
    check(f"{name}: turn 번호 1부터 증가, source=user(호스트가 보낸 메시지)", [t.turn for t in ts] == list(range(1, n_res + 1)) and all(t.source == "user" for t in ts))
    last_total = [ln["total_cost_usd"] for ln, _ in rows if ln.get("type") == "result"][-1]
    check(f"{name}: cost_delta 합 = 마지막 누적", abs(sum(r.cost_delta for r in tr) - last_total) < 1e-12 and abs(tr[-1].cost_total - last_total) < 1e-12)
    for r in tr:
        mu = sum(v["costUSD"] for v in (r.model_usage or {}).values())
        check(f"{name}: cost_delta 가 model_usage_since_last_result 의 비용 합과 일치(S1 후보 필드 확인)", abs(mu - r.cost_delta) < 1e-9, f"{mu} vs {r.cost_delta}")
mt = evs_of("main", "turn_result")
check("중단된 턴: ok False·error_during_execution·delta 0·terminal_reason", mt[4].ok is False and mt[4].subtype == "error_during_execution"
      and mt[4].cost_delta == 0 and mt[4].terminal_reason == "aborted_streaming" and mt[4].text is None and mt[4].model_usage == {})
check("성공 턴: ok True·text", mt[0].ok and mt[0].text and mt[0].subtype == "success" and mt[0].stop_reason == "end_turn" and mt[0].num_turns == 1)
check("거부 기록(perm)", any(r.permission_denials for r in evs_of("perm", "turn_result")) and all("tool_name" in d for r in evs_of("perm", "turn_result") for d in r.permission_denials))
# note_sent 없이 재생하면 source=auto
ad2 = ClaudeAdapter(); r = [e for ln, _ in ALL["main"][1][:3] for e in ad2.decode(ln)]
check("호스트 발 메시지 기록이 없으면 turn_started.source=auto", [e.source for e in r if e.kind == "turn_started"] == ["auto"])

# ---- 4. message 중복 정책: text_delta 로 보낸 글은 완결 메시지에서 shown_as
for name in ("perm", "main", "sub"):
    ad, rows = ALL[name]
    deltas_by_run = "".join(e.text for e in evs_of(name, "text_delta"))
    flagged = "".join(b["text"] for m in evs_of(name, "message") for b in m.blocks if b["type"] == "text" and b.get("shown_as") == "text_delta")
    unflagged = [b for m in evs_of(name, "message") for b in m.blocks if b["type"] == "text" and "shown_as" not in b]
    check(f"{name}: assistant 글은 전부 델타로 이미 보냈으므로 완결 메시지 글에 shown_as", deltas_by_run == flagged and flagged != "", f"{deltas_by_run!r} {flagged!r}")
    check(f"{name}: shown_as 없는 글은 사용자 입력(user 메시지)뿐", all(m.role == "user" for m in evs_of(name, "message") for b in m.blocks if b["type"] == "text" and "shown_as" not in b))
    check(f"{name}: tool_use/tool_result 블록은 각각 tool_call/tool_result 이벤트와 대응", sum(1 for m in evs_of(name, "message") for b in m.blocks if b["type"] == "tool_use") == len(evs_of(name, "tool_call"))
          and sum(1 for m in evs_of(name, "message") for b in m.blocks if b["type"] == "tool_result") == len(evs_of(name, "tool_result")))
    check(f"{name}: thinking 블록은 서명 없이 text 만", all(set(b) == {"type", "text"} for m in evs_of(name, "message") for b in m.blocks if b["type"] == "thinking"))
# 중단된 턴의 부분 응답: 델타로 그린 글 == 완결 메시지 글(둘 다 표시하면 중복)
ad, rows = ALL["main"]; interrupted_msg = None
for i, (ln, es) in enumerate(rows):
    if ln.get("type") == "result" and ln.get("subtype") == "error_during_execution":
        break
    if ln.get("type") == "assistant":
        interrupted_msg = es[0]
check("중단 직후 부분 응답 메시지는 델타로 이미 그린 글이라 shown_as", interrupted_msg.blocks[0].get("shown_as") == "text_delta" and interrupted_msg.blocks[0]["text"].startswith("1\n2\n3"))
# 델타가 없었던 경우(부분 메시지 옵션 없음)는 shown_as 없음
ad3 = ClaudeAdapter(); asst = next(ln for ln, _ in rows if ln.get("type") == "assistant")
m = ad3.decode(asst)[0]
check("델타 없이 온 글은 shown_as 없음(Message 로 그린다)", "shown_as" not in m.blocks[0] and m.blocks[0]["text"])
ad4 = ClaudeAdapter(); d = {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}, "api_message_id": "m1"}
ad4.decode(d); a = {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "hi"}, {"type": "text", "text": "hi"}]}}
check("델타 1번 → 완결 같은 글 2블록 중 1개만 shown_as", [b.get("shown_as") for b in ad4.decode(a)[0].blocks] == ["text_delta", None])

# ---- 5. 권한·질문
pr = evs_of("perm", "permission_request")
check("권한 요청 4건(Write·Bash 허용/거부)", len(pr) == 4 and [p.tool for p in pr] == ["Write", "Write", "Bash", "Bash"])
p0 = pr[0]
check("permission_request 필드", p0.req and p0.display == "Write" and isinstance(p0.input, dict) and p0.call.startswith("toolu_") and p0.description and isinstance(p0.suggestions, list) and p0.run is None)
check("suggestions 가 백엔드 형식 그대로", any(isinstance(s, dict) and "type" in s for p in pr for s in p.suggestions))
q = evs_of("main", "question_request")
check("AskUserQuestion → question_request", len(q) == 1 and q[0].questions[0]["options"][0]["label"] and q[0].call.startswith("toolu_") and not any(p.tool == "AskUserQuestion" for p in evs_of("main", "permission_request")))
# AskUserQuestion 인데 questions 가 없으면 permission_request 로 낮춘다
r = ClaudeAdapter().decode({"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": {}, "tool_use_id": "t"}})
check("questions 없는 AskUserQuestion → permission_request", r[0].kind == "permission_request")
# interrupt 의 control_response → notice
cr = [n for n in evs_of("main", "notice")]
check("control_response(interrupt) → notice(info, request_id 보존)", len(cr) == 1 and cr[0].level == "info" and cr[0].extra["request_id"] == "s0-int-1" and cr[0].extra["response"] == {"still_queued": []})
e = ClaudeAdapter().decode({"type": "control_response", "response": {"subtype": "error", "request_id": "x", "error": "bad"}})[0]
check("control_response error → notice(error)", e.kind == "notice" and e.level == "error" and "bad" in e.text)

# ---- 6. 서브에이전트·훅(sub 녹화본: 별도 재녹화)
sub_start = next(s for s in evs_of("sub", "subtask") if s.state == "started")
agent_call = next(c for c in evs_of("sub", "tool_call") if c.name == "Agent")
check("task_started 의 run = Agent 도구 호출 id", sub_start.run == agent_call.call and sub_start.summary)
sub_states = [s.state for s in evs_of("sub", "subtask")]
check("subtask 상태 순서 started→progress→updated→done", sub_states == ["started", "progress", "updated", "done"], str(sub_states))
check("모든 subtask 의 run 이 같다(task_updated 는 task_id 표로 이음)", {s.run for s in evs_of("sub", "subtask")} == {agent_call.call})
check("task_notification → done, status 보존", evs_of("sub", "subtask")[-1].extra.get("status") == "completed" and evs_of("sub", "subtask")[-1].summary == "sub-ok")
in_run = [ev for _, es in ALL["sub"][1] for ev in es if ev.run == agent_call.call and ev.kind != "subtask"]
check("parent_tool_use_id 가 붙은 줄의 이벤트에 run", {ev.kind for ev in in_run} >= {"message", "tool_call"} and all(ev.run == agent_call.call for ev in in_run))
check("서브에이전트 안의 호출(Bash)이 run 표에 기록", any(c.name == "Bash" and c.run == agent_call.call for c in evs_of("sub", "tool_call")))
check("주 대화 이벤트의 run 은 None", all(ev.run is None for ev in evs_of("sub", "turn_result") + evs_of("sub", "turn_started")))
check("서브에이전트 안의 tool_result 에도 run", any(t.run == agent_call.call for t in evs_of("sub", "tool_result")))
hk = evs_of("sub", "hook")
check("hook 이벤트: 시작·끝 쌍", len(hk) == 10 and sorted({h.phase for h in hk}) == ["finished", "started"] and {h.name for h in hk} == {"UserPromptSubmit", "PreToolUse:Bash", "Stop"}, str([(h.name, h.phase) for h in hk]))
fin = [h for h in hk if h.phase == "finished"]
check("hook 끝에 outcome·exit_code(extra)", all(h.extra.get("outcome") == "success" and h.extra.get("exit_code") == 0 for h in fin))
# 서브에이전트가 요청한 권한: 도구 호출 id → run (녹화본엔 없어 합성)
ad5 = ClaudeAdapter()
ad5.decode({"type": "assistant", "message": {"id": "m", "content": [{"type": "tool_use", "id": "toolu_sub", "name": "Write", "input": {}}]}, "parent_tool_use_id": "toolu_agent"})
rq = ad5.decode({"type": "control_request", "request_id": "r9", "request": {"subtype": "can_use_tool", "tool_name": "Write", "input": {"file_path": "/x"}, "tool_use_id": "toolu_sub"}})[0]
check("서브에이전트의 권한 요청에 run(합성 시험)", rq.kind == "permission_request" and rq.run == "toolu_agent")
rq2 = ClaudeAdapter().decode({"type": "control_request", "request_id": "r9", "request": {"subtype": "can_use_tool", "tool_name": "Write", "input": {}, "tool_use_id": "unknown"}})[0]
check("모르는 호출 id 의 권한 요청은 run None", rq2.run is None)

# ---- 7. 합성: session_info·알 수 없는 줄
ad6 = ClaudeAdapter()
base = copy.deepcopy(next(ln for ln, _ in ALL["main"][1] if ln.get("subtype") == "init"))
r1 = ad6.decode(base); r2 = ad6.decode(copy.deepcopy(base))
ch = copy.deepcopy(base); ch["model"] = "claude-opus-x"; ch["permissionMode"] = "acceptEdits"; ch["session_id"] = "new-sid"
r3 = ad6.decode(ch)
check("init: ready → (같은 값) 없음 → 바뀌면 session_info 에 바뀐 값만", [e.kind for e in r1] == ["session_ready"] and r2 == []
      and [e.kind for e in r3] == ["session_info"] and r3[0].changed == {"model": "claude-opus-x", "permission_mode": "acceptEdits", "backend_session": "new-sid"}, str(r3))
check("session_info 뒤 비교 기준이 갱신된다", ad6.decode(copy.deepcopy(ch)) == [])

UNK = {
    "알 수 없는 type": {"type": "brand_new", "x": 1},
    "알 수 없는 system subtype": {"type": "system", "subtype": "compact_boundary", "session_id": "s"},
    "status 가 requesting 아님": {"type": "system", "subtype": "status", "status": "compacting"},
    "알 수 없는 stream 안쪽": {"type": "stream_event", "event": {"type": "weird_event"}},
    "알 수 없는 delta": {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "citations_delta"}}},
    "알 수 없는 control_request": {"type": "control_request", "request_id": "r", "request": {"subtype": "hook_callback"}},
    "control_cancel_request": {"type": "control_cancel_request", "request_id": "r"},
    "모양이 틀린 assistant": {"type": "assistant"},
    "모양이 틀린 result 가 아닌 rate_limit": {"type": "rate_limit_event"},
    "type 없음": {"foo": 1},
}
for nm, ln in UNK.items():
    out = ClaudeAdapter().decode(copy.deepcopy(ln))
    check(f"알 수 없는 줄 → raw: {nm}", len(out) == 1 and isinstance(out[0], E.Raw) and out[0].vendor == "claude" and out[0].payload == ln, str(out))
bad = ClaudeAdapter().decode("not json {")
check("JSON 아닌 줄 → raw 원문", len(bad) == 1 and isinstance(bad[0], E.Raw) and bad[0].payload == "not json {")
check("JSON 문자열(str) 줄도 해석", ClaudeAdapter().decode(json.dumps({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 7}))[0].tokens_est == 7)
check("bytes 줄", ClaudeAdapter().decode(b'{"type":"system","subtype":"thinking_tokens","estimated_tokens":7}')[0].tokens_est == 7)
check("빈 줄은 []", ClaudeAdapter().decode("") == [] and ClaudeAdapter().decode("  \n") == [])
check("JSON 배열 → raw", isinstance(ClaudeAdapter().decode("[1]")[0], E.Raw))
rr = ClaudeAdapter().decode({"type": "brand_new", "parent_tool_use_id": "toolu_p", "session_id": "S"})[0]
check("raw 도 run·backend_session 을 단다", rr.run == "toolu_p" and rr.backend_session == "S")
api = ClaudeAdapter().decode({"type": "system", "subtype": "api_retry", "attempt": 2, "max_retries": 5})[0]
check("api_retry → notice(warn, 원문은 extra; 형식 미녹화라 합성 시험)", api.kind == "notice" and api.level == "warn" and "attempt=2" in api.text and api.extra["payload"]["attempt"] == 2)
# S7 실측: 서브에이전트가 돌 때 오는 background_tasks_changed 는 알려진 줄(raw 가 아님) — 이벤트 없이 ignored 로 센다
bg = ClaudeAdapter()
bgl = {"type": "system", "subtype": "background_tasks_changed", "tasks": [{"task_id": "t1", "run_id": "r1", "task_type": "local_agent", "subagent_type": "general-purpose", "description": "d"}], "uuid": "u", "session_id": "S"}
check("background_tasks_changed → 이벤트 없음(raw 아님, ignored 로 셈)", bg.decode(bgl) == [] and bg.ignored.get("system:background_tasks_changed") == 1 and bg.decode({**bgl, "tasks": []}) == [])
# 비용: 누적이 줄면(새 프로세스) total 자체가 delta
adc = ClaudeAdapter(); mk = lambda c: {"type": "result", "subtype": "success", "total_cost_usd": c}
ds = [adc.decode(mk(c))[0].cost_delta for c in (0.5, 0.75, 0.25)]
check("cost_delta: 첫 턴은 total, 이후 차, 줄면 total", ds == [0.5, 0.25, 0.25], str(ds))
# S7 실측: --resume 으로 띄운 프로세스의 total 은 이전 실행분을 포함한 누적이라 첫 턴 delta 는 null, 이후는 그 값 기준
adr = ClaudeAdapter(); adr.argv({"resume": "sid-1"})
dr = [adr.decode(mk(c))[0].cost_delta for c in (0.003, 0.0034)]
check("resume: 첫 턴 cost_delta null, 이후는 첫 total 기준 차", dr[0] is None and abs(dr[1] - 0.0004) < 1e-12, str(dr))
adn = ClaudeAdapter(); adn.argv({}); check("resume 아니면 첫 턴 delta 는 total", adn.decode(mk(0.003))[0].cost_delta == 0.003)
check("total_cost_usd 없는 result 는 cost None", ClaudeAdapter().decode({"type": "result", "subtype": "success"})[0].cost_delta is None)
rl = evs_of("main", "rate_limit")[0]
check("rate_limit 필드", rl.status == "allowed" and rl.window == "five_hour" and isinstance(rl.resets_at, (int, float)))
th = evs_of("main", "thinking")
check("thinking tokens_est 정수", th and all(isinstance(t.tokens_est, int) for t in th))
td = evs_of("main", "text_delta")
check("text_delta block=content index", td and all(isinstance(t.block, int) for t in td))
tc = evs_of("main", "tool_call")
order = [ev.kind for _, es in ALL["perm"][1] for ev in es if ev.kind in ("tool_call", "permission_request", "tool_result")]
check("순서: tool_call → permission_request → tool_result", order[:3] == ["tool_call", "permission_request", "tool_result"], str(order[:4]))

# ---- 8. 선택: p0 의 initA.json(실제 claude init 한 줄, 개인 경로 포함이라 저장소에 없음 — ctx 파일이 있으면 시험)
IA = os.path.expanduser("~/ctx/nixos/files/llm-trust/p5prime-p0/initA.json")
if os.path.exists(IA):
    ia = json.load(open(IA)); ia = ia if ia.get("type") else {"type": "system", **ia}
    ev = ClaudeAdapter().decode(ia)
    check("initA.json → session_ready(스킬 45·슬래시 80·capabilities 14)", len(ev) == 1 and ev[0].kind == "session_ready" and len(ev[0].skills) == 45 and len(ev[0].slash) == 80 and len(ev[0].capabilities) == 14, str(ev)[:200])

finish("llm-host claude_adapter")
