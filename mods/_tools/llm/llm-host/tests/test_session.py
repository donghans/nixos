#!/usr/bin/env python3
"""llm-host session.py·fake_claude.py·claude_adapter 쓰기 쪽(S3) 시험. 비용 0: 실제 claude 를 띄우지 않는다.
재생 자료는 S0 녹화본(tests/fixtures)을 시나리오로 바꿔 쓴다: 녹화본의 in 줄은 fake 가 **바이트 단위로** 기대하고, out 줄은 그대로 내보낸다.
그래서 세션이 보낸 응답 줄(user·허용·거부·질문 답)이 녹화본과 바이트 단위로 같지 않으면 fake 가 종료 코드 3 으로 끝나고 시험이 실패한다."""
import asyncio, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
from claude_adapter import ClaudeAdapter
from session import Session

FAKE = os.path.join(ROOT, "fake_claude.py")
FX = os.path.join(HERE, "fixtures")
TMP = tempfile.mkdtemp(prefix="llmhost-s3-")


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def entries(name):
    return [json.loads(l) for l in open(os.path.join(FX, name + ".jsonl"), encoding="utf-8") if l.strip()]


def turns(name):
    """녹화본을 사용자 메시지(in, type=user) 단위로 자른 목록."""
    out = []
    for e in entries(name):
        ln = e["line"]
        if e["dir"] == "in" and isinstance(ln, dict) and ln.get("type") == "user":
            out.append([])
        if out:
            out[-1].append(e)
    return out


def steps_from(ents):
    """녹화 항목 → 시나리오 단계. in: 줄 원문 바이트 일치(인터럽트는 요청 id 가 호스트 몫이라 부분집합) / out: 연속된 것을 emit 하나로."""
    st = []
    for e in ents:
        ln = e["line"]
        if e["dir"] == "in":
            if ln.get("type") == "control_request":
                st.append({"expect": {"control_request": ln["request"]}})
            else:
                st.append({"expect": {"stdin_type": ln["type"], "line": dump(ln)}})
        else:
            if st and "emit" in st[-1]:
                st[-1]["emit"].append(ln)
            else:
                st.append({"emit": [ln]})
    return st


_n = [0]
def write_scenario(steps):
    _n[0] += 1
    p = os.path.join(TMP, f"sc{_n[0]}.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(dump(s) + "\n")
    return p


def make(steps, keep=True, term_wait=5.0, extra_spec=None):
    sc = write_scenario(steps)
    spec = {"exe": [sys.executable, FAKE, sc, "--timeout", "8"], "cwd": TMP, "persist": False, "model": "haiku"}
    spec.update(extra_spec or {})
    return Session(ClaudeAdapter(host_session="h1"), spec, host_session="h1", keep_history=keep, term_wait=term_wait)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def user_text(ents):
    return ents[0]["line"]["message"]["content"]


def kinds(s):
    return [e.kind for e in s.history]


async def finish_clean(s, grace=5.0):
    await s.close(grace)
    return s.exit_code


# ---------------------------------------------------------------- 0. 어댑터 쓰기 쪽 단위
ad = ClaudeAdapter()
a = ad.argv({"model": "haiku", "persist": False})
check("argv: 실행 파일 기본 claude, 스트리밍 옵션 조합(S0 와 같음)", a[0] == "claude" and a[1:8] == ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
      and "--include-hook-events" in a and a[a.index("--permission-mode") + 1] == "manual" and a[a.index("--permission-prompt-tool") + 1] == "stdio"
      and a[a.index("--model") + 1] == "haiku" and "--no-session-persistence" in a and "--resume" not in a, str(a))
a2 = ad.argv({"exe": ["/x/fake", "s.jsonl"], "permission_mode": "acceptEdits", "resume": "sid-1", "extra_args": ["--max-budget-usd", 1]})
check("argv: exe 갈아끼움·권한 모드·resume·extra_args, persist 기본 true 면 플래그 없음",
      a2[:2] == ["/x/fake", "s.jsonl"] and a2[a2.index("--permission-mode") + 1] == "acceptEdits" and a2[a2.index("--resume") + 1] == "sid-1"
      and a2[-2:] == ["--max-budget-usd", "1"] and "--no-session-persistence" not in a2 and "--model" not in a2)
check("argv: exe 가 문자열이어도 된다", ad.argv({"exe": "/x/claude"})[0] == "/x/claude")
os.environ["LLMHOST_TEST_SECRET"] = "x"
env = ad.env({"env_extra": {"A": "1", "TERM": "xterm"}})
check("env: 상속하지 않는다(HOME·PATH·TERM 만 + env_extra 덮어쓰기)", "LLMHOST_TEST_SECRET" not in env and env.get("A") == "1" and env["TERM"] == "xterm"
      and env.get("PATH") == os.environ.get("PATH") and set(env) <= {"HOME", "PATH", "TERM", "A"})
check("encode(Send text): user 줄, note_sent 로 센다", ad.encode(E.Send(text="안녕")) == ['{"type":"user","message":{"role":"user","content":"안녕"}}'] and ad._sent_pending == 1)
blk = [{"type": "text", "text": "x"}]
check("encode(Send blocks)", ad.encode(E.Send(blocks=blk)) == [dump({"type": "user", "message": {"role": "user", "content": blk}})])
for bad in (E.Send(), E.Send(text="a", blocks=blk)):
    try:
        ad.encode(bad); ok = False
    except ValueError:
        ok = True
    check("encode(Send): text·blocks 정확히 하나", ok)
check("호스트 안 명령은 []", all(ad.encode(c) == [] for c in (E.Start(), E.SetPolicy(policy=1), E.Close(), E.Kill())))
i1, i2 = ad.encode(E.Interrupt())[0], ad.encode(E.Interrupt())[0]
check("encode(Interrupt): control_request interrupt, 요청 id 가 매번 다르다", json.loads(i1)["request"] == {"subtype": "interrupt"} and json.loads(i1)["type"] == "control_request"
      and json.loads(i1)["request_id"] != json.loads(i2)["request_id"])
ad.decode({"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "Write", "input": {"file_path": "/x", "content": "c"}, "tool_use_id": "t1"}})
check("encode(AnswerPermission allow): updated_input 없으면 원래 input", ad.encode(E.AnswerPermission(req="r1", allow=True))
      == [dump({"type": "control_response", "response": {"subtype": "success", "request_id": "r1", "response": {"behavior": "allow", "updatedInput": {"file_path": "/x", "content": "c"}}}})])
ad.decode({"type": "control_request", "request_id": "r2", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}, "tool_use_id": "t2"}})
sug = [{"type": "setMode", "mode": "acceptEdits", "destination": "session"}]
o = json.loads(ad.encode(E.AnswerPermission(req="r2", allow=True, updated_input={"command": "ls -l"}, updated_permissions=sug))[0])["response"]["response"]
check("allow: 바꾼 input 과 채택한 제안(updatedPermissions)", o == {"behavior": "allow", "updatedInput": {"command": "ls -l"}, "updatedPermissions": sug})
ad.decode({"type": "control_request", "request_id": "r3", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}, "tool_use_id": "t3"}})
check("deny: message 가 모델에 가는 문구", json.loads(ad.encode(E.AnswerPermission(req="r3", allow=False, message="no way"))[0])["response"]["response"] == {"behavior": "deny", "message": "no way"})
qin = {"questions": [{"question": "Q1", "options": []}, {"question": "Q2", "options": []}, {"question": "Q3", "options": []}]}
ad.decode({"type": "control_request", "request_id": "r4", "request": {"subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": qin, "tool_use_id": "t4"}})
ui = json.loads(ad.encode(E.AnswerQuestion(req="r4", answers={"Q1": "a", "Q2": ["b", "c"]}, free_text="자유"))[0])["response"]["response"]["updatedInput"]
check("answer_question: questions 보존 + answers(다중 선택은 ', ' 로 이음, 자유 입력은 답 없는 첫 질문)",
      ui["questions"] == qin["questions"] and ui["answers"] == {"Q1": "a", "Q2": "b, c", "Q3": "자유"}, str(ui))

# ---------------------------------------------------------------- 1. fake_claude 단독
import subprocess
def fake(steps, stdin_text="", timeout="1"):
    p = subprocess.run([sys.executable, FAKE, write_scenario(steps), "--timeout", timeout], input=stdin_text, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr
rc, out, err = fake([{"emit": [{"a": "한"}, "깨진 줄"]}, {"expect": {"stdin_type": "user", "text": "hi"}}], '{"type":"user","message":{"role":"user","content":"hi"}}\n')
check("fake: emit 은 JSON(비 ASCII 보존)·문자열 그대로, 기대가 맞으면 입력 EOF 뒤 0", rc == 0 and out == '{"a":"한"}\n깨진 줄\n', f"{rc} {out!r} {err}")
rc, _, err = fake([{"expect": {"stdin_type": "user"}}], '{"type":"control_response"}\n')
check("fake: 기대 불일치는 종료 코드 3", rc == 3 and "stdin_type" in err)
rc, _, err = fake([{"expect": {"control_response": {"behavior": "deny"}}}], dump({"type": "control_response", "response": {"subtype": "success", "request_id": "r", "response": {"behavior": "allow"}}}) + "\n")
check("fake: control_response 부분집합 불일치(deny 기대·allow 받음)도 3", rc == 3 and "control_response" in err)
rc, _, _ = fake([{"expect": {"control_response": {"behavior": "deny"}, "request_id": "r"}}], dump({"type": "control_response", "response": {"subtype": "success", "request_id": "r", "response": {"behavior": "deny", "message": "m"}}}) + "\n")
check("fake: control_response 부분집합·request_id 가 맞으면 0", rc == 0)
rc, _, err = fake([{"expect": {"line": "정확히"}}], "정확히 \n")
check("fake: line 은 바이트 단위(끝 공백 하나도 불일치)", rc == 3)
rc, _, err = fake([{"expect": {"stdin_type": "user"}}], "", timeout="5")
check("fake: 입력이 닫히면 5", rc == 5)
p = subprocess.Popen([sys.executable, FAKE, write_scenario([{"expect": {"stdin_type": "user"}}]), "--timeout", "0.5"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    rc = p.wait(timeout=10)
finally:
    p.stdin.close(); p.stdout.close(); p.stderr.close()
check("fake: 기대한 입력이 시간 안에 안 오면 4", rc == 4)
rc, _, _ = fake([{"emit": ["x"]}, {"exit": 9}, {"emit": ["y"]}])
check("fake: exit 단계는 그 코드로 즉시 종료", rc == 9)
rc, _, err = fake([{"bogus": 1}])
check("fake: 알 수 없는 단계는 2", rc == 2)
rc, _, err = fake([{"expect": {"nope": 1}}], "{}\n")
check("fake: 알 수 없는 조건 키는 불일치(3)", rc == 3 and "알 수 없는 조건" in err)

# ---------------------------------------------------------------- 2. 세션: hello (녹화본 main 첫 턴)
T = turns("main")
hello = T[0]


async def t_hello():
    s = make(steps_from(hello))
    await s.start()
    st0 = s.state
    await asyncio.sleep(0.4)
    quiet = list(s.history)                   # 메시지 전에는 아무 이벤트도 없다(S0 확인)
    await s.send(user_text(hello))
    st1 = s.state
    await s.collect_until(lambda e: e.kind == "turn_result")
    st2 = s.state
    code = await finish_clean(s)
    return s, st0, quiet, st1, st2, code

s, st0, quiet, st1, st2, code = run(t_hello())
ks = kinds(s)
check("hello: 기동 직후 idle, 메시지 전 이벤트 0", st0 == "idle" and quiet == [])
check("hello: send 직후 busy, turn_result 직후 idle", st1 == "busy" and st2 == "idle")
check("hello: session_ready 가 첫 이벤트, turn_started·text_delta·message·turn_result 순", ks[0] == "session_ready" and ks.index("turn_started") < ks.index("text_delta") < ks.index("message") < ks.index("turn_result"), str(ks[:12]))
check("hello: seq 가 1부터 빠짐없이 증가·ts·host_session", [e.seq for e in s.history] == list(range(1, len(s.history) + 1)) and all(e.ts > 0 and e.host_session == "h1" for e in s.history))
check("hello: 이벤트에 backend_session(init 이후)", s.history[0].backend_session and s.history[-1].backend_session == s.adapter.backend_session)
check("hello: 가짜가 기대(user 줄 바이트 일치)를 통과해 0 으로 끝남 → close 사유 closed", code == 0 and s.end_reason == "closed" and s.state == "closed" and ks[-1] == "session_ended")
check("hello: 끝난 세션의 자식이 남지 않음", s.pid is not None and not os.path.exists(f"/proc/{s.pid}"))
tr = [e for e in s.history if e.kind == "turn_result"][0]
check("hello: turn_result 에 비용(녹화본 값)", tr.cost_delta is not None and tr.cost_delta == tr.cost_total)

# ---------------------------------------------------------------- 3. 권한 허용·거부 (녹화본 perm 의 Write 허용 턴·거부 턴)
P = turns("perm")


async def t_perm(turn, allow, message=None):
    s = make(steps_from(turn))
    await s.start()
    await s.send(user_text(turn))
    got = await s.collect_until(lambda e: e.kind == "permission_request")
    req = got[-1]
    st_wait, pend = s.state, dict(s.pending)
    ok = await s.answer_permission(req.req, allow, message=message)
    st_after, pend_after = s.state, dict(s.pending)
    await s.collect_until(lambda e: e.kind == "turn_result")
    code = await finish_clean(s)
    return s, req, st_wait, pend, ok, st_after, pend_after, code

s, req, stw, pend, ok, sta, penda, code = run(t_perm(P[0], True))
check("허용: 요청이 오면 waiting_request·대기 표에 있음", stw == "waiting_request" and list(pend) == [req.req] and req.tool == "Write")
check("허용: 응답 뒤 busy·대기 표 비움, request_resolved(allow, user)", ok and sta == "busy" and penda == {}
      and [(e.outcome, e.by, e.req) for e in s.history if e.kind == "request_resolved"] == [("allow", "user", req.req)])
check("허용: 응답 줄이 녹화본과 바이트 단위로 같다(가짜가 3 으로 끝나지 않음)", code == 0 and s.end_reason == "closed")
dmsg = next(e["line"]["response"]["response"]["message"] for e in P[1] if e["dir"] == "in" and e["line"].get("type") == "control_response")
s, req, stw, pend, ok, sta, penda, code = run(t_perm(P[1], False, dmsg))
check("거부: 응답 줄이 녹화본과 바이트 단위로 같다 + request_resolved(deny)", code == 0 and [(e.outcome, e.message) for e in s.history if e.kind == "request_resolved"] == [("deny", dmsg)])
check("거부 뒤 turn_result 까지 정상(권한 거부가 기록됨)", [e for e in s.history if e.kind == "turn_result"][0].permission_denials)

# 응답을 틀리게 보내면(allow 기대에 deny) 가짜가 비정상 종료 → 세션은 crashed 로 알린다
async def t_mismatch():
    s = make(steps_from(P[0]))
    await s.start()
    await s.send(user_text(P[0]))
    got = await s.collect_until(lambda e: e.kind == "permission_request")
    await s.answer_permission(got[-1].req, False, message="x")
    got = await s.collect_until(lambda e: e.kind == "session_ended")
    return s, got
s, got = run(t_mismatch())
check("기대 불일치: 가짜가 3 으로 끝나 session_ended crashed, 가짜의 표준오류가 notice 로 온다", s.end_reason == "crashed" and s.exit_code == 3 and s.state == "crashed"
      and any("fake_claude" in e.text and e.extra.get("stream") == "stderr" for e in s.history if e.kind == "notice"))

# ---------------------------------------------------------------- 4. 질문 답 (녹화본 main 의 AskUserQuestion 턴)
Q = next(t for t in T if "AskUserQuestion" in user_text(t))
qans = next(e["line"]["response"]["response"]["updatedInput"]["answers"] for e in Q if e["dir"] == "in" and e["line"].get("type") == "control_response")


async def t_question():
    s = make(steps_from(Q))
    await s.start()
    await s.send(user_text(Q))
    got = await s.collect_until(lambda e: e.kind == "question_request")
    q = got[-1]
    stw = s.state
    ok = await s.answer_question(q.req, qans)
    await s.collect_until(lambda e: e.kind == "turn_result")
    code = await finish_clean(s)
    return s, q, stw, ok, code
s, q, stw, ok, code = run(t_question())
check("질문: question_request·waiting_request, 답 줄(questions+answers)이 녹화본과 바이트 단위로 같다", stw == "waiting_request" and ok and code == 0 and s.end_reason == "closed"
      and [(e.outcome, e.by) for e in s.history if e.kind == "request_resolved"] == [("answered", "user")])
check("질문: 이후 turn_result 가 오고 idle", s.history[-2].kind == "turn_result" or any(e.kind == "turn_result" for e in s.history))

# ---------------------------------------------------------------- 5. 중단 후 계속 (녹화본 main 의 300 세기 → interrupt → done)
ic = next(i for i, t in enumerate(T) if any(e["dir"] == "in" and e["line"].get("type") == "control_request" for e in t))
INT, NEXT = T[ic], T[ic + 1]


async def t_interrupt():
    s = make(steps_from(INT + NEXT))
    await s.start()
    await s.send(user_text(INT))
    await s.collect_until(lambda e: e.kind == "text_delta")
    await s.interrupt()
    got1 = await s.collect_until(lambda e: e.kind == "turn_result")
    st_mid = s.state
    await s.send(user_text(NEXT))
    got2 = await s.collect_until(lambda e: e.kind == "turn_result")
    code = await finish_clean(s)
    return s, got1, got2, st_mid, code
s, g1, g2, stm, code = run(t_interrupt())
check("중단: interrupt 줄을 가짜가 받고(요청 subtype), 수락 notice 뒤 turn_result(error) 가 온다", any(e.kind == "notice" and e.extra.get("request_id") for e in g1) and not g1[-1].ok)
check("중단 뒤 idle, 다음 메시지가 정상 처리되어 turn_result ok, 가짜 정상 종료", stm == "idle" and g2[-1].ok and code == 0)
ni = next(i for i, e in enumerate(g1) if e.kind == "notice" and e.extra.get("request_id"))
check("중단: 중단 수락 notice 뒤(다음 turn_result 까지)에 글자 조각 0", not any(e.kind == "text_delta" for e in g1[ni:]))

# ---------------------------------------------------------------- 6. 크래시·종료 사유
async def t_crash():
    s = make([{"expect": {"stdin_type": "user"}}, {"emit": [{"type": "control_request", "request_id": "rq1", "request": {"subtype": "can_use_tool", "tool_name": "Write", "input": {"file_path": "/x"}, "tool_use_id": "t1"}}]}, {"sleep": 0.2}, {"exit": 7}])
    await s.start()
    await s.send("go")
    await s.collect_until(lambda e: e.kind == "session_ended")
    return s
s = run(t_crash())
ks = kinds(s)
check("크래시: session_ended(crashed, exit_code 7)·state crashed", s.end_reason == "crashed" and s.exit_code == 7 and s.state == "crashed" and s.history[-1].reason == "crashed" and s.history[-1].exit_code == 7)
check("크래시: 미해결 요청은 request_resolved(deny, session_end) 로 닫히고 session_ended 가 마지막", [(e.by, e.outcome) for e in s.history if e.kind == "request_resolved"] == [("session_end", "deny")] and ks[-1] == "session_ended" and s.pending == {})

async def t_eof():
    s = make([{"emit": [{"type": "brand_new"}]}, {"exit": 0}])
    await s.start()
    await s.collect_until(lambda e: e.kind == "session_ended")
    return s
s = run(t_eof())
check("예기치 않은 종료 코드 0 은 eof(state closed)", s.end_reason == "eof" and s.state == "closed" and s.exit_code == 0)
check("알 수 없는 줄은 raw 로 통과", [e.payload for e in s.history if e.kind == "raw"] == [{"type": "brand_new"}])

async def t_stderr_raw():
    s = make([{"stderr": "경고 하나"}, {"emit": ["깨진 JSON {"]}, {"sleep": 0.2}])
    await s.start()
    await s.collect_until(lambda e: e.kind == "raw")
    await finish_clean(s)
    return s
s = run(t_stderr_raw())
check("표준오류 줄은 notice(warn), JSON 아닌 줄은 raw(원문 문자열)", any(e.kind == "notice" and e.level == "warn" and "경고 하나" in e.text for e in s.history) and any(e.kind == "raw" and e.payload == "깨진 JSON {" for e in s.history))

async def t_nofile():
    s = Session(ClaudeAdapter(), {"exe": ["/nonexistent/claude-x"]}, host_session="h2", keep_history=True)
    await s.start()
    return s
s = run(t_nofile())
check("실행 파일이 없으면 notice(error)·session_ended crashed", s.state == "crashed" and [e.kind for e in s.history] == ["notice", "session_ended"] and s.history[0].level == "error")

# 종료 4단계: SIGTERM 을 무시하는 가짜 → SIGKILL
async def t_sigkill():
    s = make([{"ignore_sigterm": True}, {"emit": [{"type": "brand_new"}]}, {"sleep": 60}], term_wait=0.5)
    await s.start()
    await s.collect_until(lambda e: e.kind == "raw")
    await s.close(grace=0.4)
    return s
s = run(t_sigkill())
notes = [e.text for e in s.history if e.kind == "notice"]
check("close: 입력 닫기→grace→SIGTERM(무시됨)→SIGKILL, 종료 코드 -9, 사유 closed", s.exit_code == -9 and s.end_reason == "closed" and any("SIGTERM" in t for t in notes) and any("SIGKILL" in t for t in notes), str(notes))
check("close: 자식이 남지 않음", not os.path.exists(f"/proc/{s.pid}"))

async def t_sigterm():
    s = make([{"emit": [{"type": "brand_new"}]}, {"sleep": 60}], term_wait=2)
    await s.start()
    await s.collect_until(lambda e: e.kind == "raw")
    await s.close(grace=0.3)
    return s
s = run(t_sigterm())
check("close: 입력을 닫아도 안 끝나면 SIGTERM 으로 끝(종료 코드 -15), SIGKILL 은 안 보냄", s.exit_code == -15 and not any("SIGKILL" in e.text for e in s.history if e.kind == "notice"))

async def t_kill():
    s = make([{"ignore_sigterm": True}, {"emit": [{"type": "brand_new"}]}, {"sleep": 60}])
    await s.start()
    await s.collect_until(lambda e: e.kind == "raw")
    pgid = os.getpgid(s.pid)
    await s.kill()
    return s, pgid
s, pgid = run(t_kill())
check("kill: 사유 killed·종료 코드 -9", s.end_reason == "killed" and s.exit_code == -9 and s.state == "closed")
check("자식은 새 프로세스 그룹(우리 그룹이 아님)", pgid == s.pid and pgid != os.getpgrp())

# 자식이 낳은 손주도 그룹 신호로 정리된다(자기 그룹만)
async def t_group():
    gc = os.path.join(TMP, "grandchild.pid")
    sh = os.path.join(TMP, "spawn.sh")
    open(sh, "w").write(f"#!/bin/sh\nsleep 300 &\necho $! > {gc}\nexec {sys.executable} {FAKE} {write_scenario([{'sleep': 60}])}\n")
    os.chmod(sh, 0o755)
    s = Session(ClaudeAdapter(), {"exe": [sh], "cwd": TMP}, host_session="h3", keep_history=True)
    await s.start()
    for _ in range(100):
        if os.path.exists(gc) and open(gc).read().strip():
            break
        await asyncio.sleep(0.05)
    gpid = int(open(gc).read())
    alive_before = os.path.exists(f"/proc/{gpid}")
    await s.kill()
    await asyncio.sleep(0.3)
    return gpid, alive_before
gpid, alive_before = run(t_group())
check("kill: 그룹 신호로 자식이 낳은 프로세스까지 정리(자기 그룹만)", alive_before and not os.path.exists(f"/proc/{gpid}") or (alive_before and open(f"/proc/{gpid}/stat").read().split()[2] == "Z"))

# ---------------------------------------------------------------- 7. 명령 가드
async def t_guards():
    s = make([{"expect": {"stdin_type": "user"}}, {"emit": [{"type": "brand_new"}]}])
    await s.start()
    unknown = await s.answer_permission("nope", True)
    try:
        await s.start(); again = False
    except RuntimeError:
        again = True
    try:
        await s.command(E.Start()); st = False
    except ValueError:
        st = True
    await s.command(E.SetPolicy(policy={"x": 1}))
    await s.close(grace=2)
    try:
        await s.send("late"); late = False
    except RuntimeError:
        late = True
    return s, unknown, again, st, late
s, unknown, again, st, late = run(t_guards())
check("모르는 req 에 답하면 False·경고 notice(줄을 보내지 않음)", unknown is False and any(e.kind == "notice" and "nope" in e.text for e in s.history))
check("start 두 번·Start 명령은 거부, set_policy 는 저장, 끝난 세션에 send 는 RuntimeError", again and st and late and s.policy == {"x": 1})
check("기대한 입력을 받지 못한 채 close 해도 사유는 closed(우리가 끝낸 것)", s.end_reason == "closed")

# 이벤트 로그는 JSON 줄로 왕복된다
check("세션이 낸 이벤트도 규격 왕복(직렬화→역직렬화 동일)", all(E.event_from_json(E.to_json(e)) == e for e in s.history))

shutil.rmtree(TMP, ignore_errors=True)
finish("llm-host session")
