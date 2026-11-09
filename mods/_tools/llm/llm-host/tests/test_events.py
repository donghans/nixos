#!/usr/bin/env python3
"""llm-host events.py 시험: 모든 kind·cmd 의 직렬화 왕복, 알 수 없는 kind 는 raw, 깨진 줄 처리, 모르는 필드 보존, 규격 표와의 일치."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E

COMMON = dict(seq=7, ts=1731100000.5, host_session="h1", backend_session="b-uuid", run=None)
SAMPLES = [
    E.SessionReady(backend="claude", backend_version="2.1.317", model="haiku", cwd="/x", capabilities=["a"], tools=["Bash"], skills=["s"], slash=["/p"], mcp=[{"name": "m"}], permission_mode="default"),
    E.SessionInfo(changed={"model": "opus"}),
    E.TurnStarted(turn=2, source="auto"),
    E.TextDelta(block=0, text="안녕 \"따옴표\" \n줄바꿈 😀"),
    E.Thinking(tokens_est=120),
    E.Message(role="assistant", blocks=[{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]),
    E.ToolCall(call="t1", name="Bash", input={"command": "ls"}, run="r1"),
    E.ToolResult(call="t1", content=[{"type": "text", "text": "ok"}], is_error=False),
    E.PermissionRequest(req="q1", tool="Write", display="Write", input={"file_path": "/x"}, call="t2", description="파일 쓰기", suggestions=[{"type": "setMode", "mode": "acceptEdits"}]),
    E.QuestionRequest(req="q2", questions=[{"question": "Q?", "header": "H", "options": [{"label": "a", "description": "d"}], "multiSelect": False}], call="t3"),
    E.RequestResolved(req="q1", outcome="deny", by="policy", message="거부"),
    E.Subtask(state="progress", summary="일하는 중", run="r1"),
    E.Hook(name="Stop", phase="started"),
    E.TurnResult(ok=False, subtype="error_during_execution", text=None, cost_total=0.0123, cost_delta=0.001, permission_denials=[{"tool": "Write"}], terminal_reason="aborted", stop_reason=None, num_turns=3, model_usage={"haiku": {"inputTokens": 1}}),
    E.RateLimit(status="allowed", resets_at=1731200000, window="5h"),
    E.Notice(level="warn", text="sudo 없음"),
    E.SessionEnded(reason="crashed", exit_code=-9),
    E.Raw(vendor="claude", payload={"type": "weird", "n": 1}),
]
CMDS = [
    E.Start(spec={"cwd": "/x", "model": "haiku", "persist": False, "extra_args": ["--a"], "env_extra": {"K": "V"}}),
    E.Send(text="안녕"), E.Send(blocks=[{"type": "text", "text": "x"}]),
    E.Interrupt(),
    E.AnswerPermission(req="q1", allow=True, updated_input={"a": 1}, updated_permissions=[{"type": "setMode"}]),
    E.AnswerPermission(req="q1", allow=False, message="no"),
    E.AnswerQuestion(req="q2", answers={"Q?": ["a", "b"]}, free_text="기타"),
    E.SetPolicy(policy={"default": "deny"}), E.Close(grace=3.0), E.Kill(),
]

# 1. 규격 표와 일치: 모든 kind 가 등록되어 있고 시료가 빠짐없이 있다
check("kind 18종", len(E.EVENT_TYPES) == 18, str(sorted(E.EVENT_TYPES)))
check("명령 8종", len(E.COMMAND_TYPES) == 8)
check("시료가 모든 kind 를 덮는다", {type(s).kind for s in SAMPLES} == set(E.EVENT_TYPES))
check("시료가 모든 명령을 덮는다", {type(c).cmd for c in CMDS} == set(E.COMMAND_TYPES))
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("README 에 모든 kind 가 적혀 있다", all(f"`{k}`" in readme for k in E.EVENT_TYPES), str([k for k in E.EVENT_TYPES if f"`{k}`" not in readme]))
check("README 에 모든 명령이 적혀 있다", all(f"`{k}`" in readme for k in E.COMMAND_TYPES))

# 2. 이벤트 왕복 (객체 동일, 줄 동일, 한 줄)
for s in SAMPLES:
    for k, v in COMMON.items():
        setattr(s, k, v)
    line = E.to_json(s)
    back = E.event_from_json(line)
    check(f"왕복 {s.kind}", back == s and type(back) is type(s), f"{back!r}")
    check(f"재직렬화 동일 {s.kind}", E.to_json(back) == line)
    check(f"한 줄 {s.kind}", "\n" not in line)
    check(f"kind 필드 {s.kind}", json.loads(line)["kind"] == s.kind)
    for k in ("seq", "ts", "host_session", "backend_session", "run", "kind"):
        check(f"공통 필드 {k} ({s.kind})", k in json.loads(line))

# 3. 명령 왕복
for c in CMDS:
    line = E.to_json(c)
    back = E.command_from_json(line)
    check(f"왕복 명령 {c.cmd}", back == c and type(back) is type(c), f"{back!r}")

# 4. 알 수 없는 kind → raw (원문 보존, 공통 필드 유지)
unk = {"kind": "future_thing", "seq": 3, "ts": 5.0, "host_session": "h9", "foo": [1, 2]}
r = E.event_from_dict(unk)
check("알 수 없는 kind → Raw", isinstance(r, E.Raw) and r.vendor == "unknown-kind")
check("원문 보존", r.payload == unk)
check("공통 필드 유지", (r.seq, r.ts, r.host_session) == (3, 5.0, "h9"))
r2 = E.event_from_json(E.to_json(r))
check("Raw 왕복", r2 == r)
check("kind 없는 dict → Raw", isinstance(E.event_from_dict({"a": 1}), E.Raw))
check("dict 아닌 JSON → Raw", isinstance(E.event_from_json("[1,2]"), E.Raw) and E.event_from_json("[1,2]").payload == [1, 2])
bad = E.event_from_json("not json {")
check("JSON 아닌 줄 → Raw(malformed)", isinstance(bad, E.Raw) and bad.vendor == "malformed" and bad.payload == "not json {")
check("None → Raw", isinstance(E.event_from_dict(None), E.Raw))

# 5. 알려진 kind 의 깨진 필드 → Raw(malformed), 원문 보존
for name, d in {"seq 가 문자열": {"kind": "notice", "seq": "x", "text": "t"},
                "text 가 숫자": {"kind": "notice", "text": 5},
                "bool 을 int 로": {"kind": "turn_started", "turn": True},
                "list 자리에 문자열": {"kind": "session_ready", "tools": "Bash"},
                "None 불가 필드": {"kind": "notice", "level": None}}.items():
    r = E.event_from_dict(d)
    check(f"깨진 필드 → Raw: {name}", isinstance(r, E.Raw) and r.vendor == "malformed" and r.payload == d, repr(r))

mr = E.event_from_dict({"kind": "raw", "seq": "x", "vendor": "claude", "payload": {"a": 1}})
check("깨진 raw 도 payload 는 원문 그대로(이중 포장 없음)", isinstance(mr, E.Raw) and mr.payload == {"a": 1} and mr.vendor == "malformed", repr(mr))

# 6. 모르는 필드는 extra 로 보존되어 재직렬화에 나간다 / 기본값 채움
n = E.event_from_dict({"kind": "notice", "text": "hi", "newfield": {"a": 1}})
check("모르는 필드 → extra", isinstance(n, E.Notice) and n.extra == {"newfield": {"a": 1}})
check("재직렬화에 포함", json.loads(E.to_json(n))["newfield"] == {"a": 1})
check("누락 필드는 기본값", E.event_from_dict({"kind": "turn_result"}).ok is True)
check("정수가 float 필드에 허용", E.event_from_dict({"kind": "turn_result", "cost_total": 1}).cost_total == 1)
check("기본 인스턴스 독립(가변 기본값 공유 없음)", E.Message().blocks is not E.Message().blocks)

# 7. 명령 오류는 ValueError
for name, s in {"알 수 없는 cmd": '{"cmd":"nope"}', "JSON 아님": "x", "객체 아님": "[]", "send 둘 다 없음": '{"cmd":"send"}',
                "send 둘 다 있음": '{"cmd":"send","text":"a","blocks":[]}', "allow 가 문자열": '{"cmd":"answer_permission","req":"r","allow":"yes"}',
                "req 누락 형": '{"cmd":"answer_permission","req":3}'}.items():
    try:
        E.command_from_json(s); ok = False
    except ValueError:
        ok = True
    check(f"명령 오류 ValueError: {name}", ok)
c = E.command_from_dict({"cmd": "interrupt", "x": 1})
check("명령의 모르는 필드는 extra", c.extra == {"x": 1})

# 8. 시험 보조: S0 녹화본(있으면)의 줄은 어떤 것이든 Raw 로 감싸 왕복 가능(어댑터 전 단계의 안전판)
FX = os.environ.get("LLM_HOST_FIXTURES")
if FX and os.path.isdir(FX):
    cnt = 0
    for fn in sorted(os.listdir(FX)):
        if fn.endswith(".jsonl"):
            for ln in open(os.path.join(FX, fn), encoding="utf-8"):
                if ln.strip():
                    try:
                        p = json.loads(ln)
                    except ValueError:
                        continue
                    ev = E.Raw(vendor="claude", payload=p); cnt += 1
                    if E.event_from_json(E.to_json(ev)) != ev:
                        check(f"녹화 줄 왕복 {fn}", False)
    check("녹화 줄 Raw 왕복(시험 보조)", cnt > 0, f"{cnt} 줄")

finish("llm-host events")
