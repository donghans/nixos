#!/usr/bin/env python3
"""integration_real.py 의 판정 함수(analyze_*)와 /proc 도우미 시험. 비용 0: 실제 claude 를 띄우지 않고 이벤트 목록을 손으로 만든다.
(실제 claude 를 도는 통합 시험 본체는 run-tests.sh 에 넣지 않는다 — 비용이 든다. 사용법은 integration_real.py 머리말.)
이 시험은 판정이 「틀린 결과를 실제로 거르는지」 보는 것이 목적이다: 통과 사례마다 한 군데씩 깨뜨린 변이 사례가 실패해야 한다."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
import integration_real as I

TR = lambda ok=True, text="ok", total=0.01, delta=0.01, **kw: E.TurnResult(ok=ok, subtype="success" if ok else "error_during_execution", text=text, cost_total=total, cost_delta=delta, **kw)

# 비용: 합 == 마지막 누적
good = [[TR(total=0.004, delta=0.004)], [TR(total=0.007, delta=0.003)]]
check("비용 합 일치 통과", I.analyze_cost(good)[0])
check("변이: delta 하나 틀림 → 실패", not I.analyze_cost([[TR(total=0.004, delta=0.004)], [TR(total=0.007, delta=0.001)]])[0])
check("변이: delta 없음(null) → 실패", not I.analyze_cost([[TR(total=0.004, delta=None)]])[0])
check("turn_result 없음 → 실패", not I.analyze_cost([[]])[0])

# hello
ready = E.SessionReady(backend="claude", model="m", backend_session="S")
check("hello 통과", I.analyze_hello([ready, E.TurnStarted(source="user"), TR()])[0])
check("변이: raw 가 섞임 → 실패", not I.analyze_hello([ready, E.Raw(payload={}), TR()])[0])
check("변이: 빈 응답 → 실패", not I.analyze_hello([ready, TR(text="")])[0])

# 권한: 거부 뒤 우회
def deny_run(extra):
    return [E.ToolCall(call="c1", name="Write", input={}), E.PermissionRequest(req="r", tool="Write", call="c1")] + extra + [TR(text="I could not create the file because it was denied.")]
ea = [E.PermissionRequest(req="a", tool="Write"), TR()]
check("권한 통과", I.analyze_permission(ea, deny_run([]), True, False, "c1")[0])
check("변이: 거부 뒤 Bash 로 우회 → 실패", not I.analyze_permission(ea, deny_run([E.ToolCall(call="c2", name="Bash", input={})]), True, False, "c1")[0])
check("변이: 거부했는데 파일이 생김 → 실패", not I.analyze_permission(ea, deny_run([]), True, True, "c1")[0])
check("변이: 허용 파일이 안 생김 → 실패", not I.analyze_permission(ea, deny_run([]), False, False, "c1")[0])
check("변이: 거부 요청이 안 옴 → 실패", not I.analyze_permission(ea, [TR(text="denied")], True, False, "c1")[0])
check("변이: 설명 없는 응답 → 실패", not I.analyze_permission(ea, [E.PermissionRequest(req="r", tool="Write", call="c1"), TR(text="Sure thing!")], True, False, "c1")[0])
check("거부 이전의 도구 호출은 우회로 세지 않음", I.analyze_permission(ea, [E.ToolCall(call="c0", name="Bash", input={})] + deny_run([]), True, False, "c1")[0])

# 질문
qr = E.QuestionRequest(req="q", questions=[{"question": "?", "options": [{"label": "빨강"}]}])
check("질문 통과", I.analyze_question([qr, TR(text="사용자는 빨강을 골랐다")], "빨강")[0])
check("변이: 답이 응답에 없음 → 실패", not I.analyze_question([qr, TR(text="모르겠다")], "빨강")[0])
check("변이: 질문 요청이 없음 → 실패", not I.analyze_question([TR(text="빨강")], "빨강")[0])

# 중단
cut = [E.TextDelta(text="1"), TR(ok=False, text=None, delta=0.003)]
nxt = [TR(text="done")]
check("중단 통과", I.analyze_interrupt(cut, nxt, 12, 0.004)[0])
check("변이: 중단된 턴이 성공으로 끝남 → 실패", not I.analyze_interrupt([E.TextDelta(text="1"), TR(ok=True)], nxt, 12, 0.004)[0])
check("변이: 중단 뒤에도 글자 조각 → 실패", not I.analyze_interrupt([TR(ok=False), E.TextDelta(text="9")], nxt, 12, 0.004)[0])
check("변이: 다음 메시지 응답이 이상함 → 실패", not I.analyze_interrupt(cut, [TR(text="???")], 12, 0.004)[0])
check("변이: 다음 턴이 없음 → 실패", not I.analyze_interrupt(cut, [], 12, 0.004)[0])

# 서브에이전트
sub_ok = [E.ToolCall(call="A1", name="Agent", input={}), E.Subtask(run="A1", state="started"), E.PermissionRequest(req="p", tool="Bash", run="A1"),
          E.Message(run="A1", role="assistant", blocks=[{"type": "text", "text": "sub says hi"}]), E.Subtask(run="A1", state="done"), TR()]
check("서브에이전트 통과(전달 옵션)", I.analyze_subagent(sub_ok, True)[0])
no_text = [e for e in sub_ok if e.kind != "message"]
check("전달 옵션인데 서브 글이 없으면 실패", not I.analyze_subagent(no_text, True)[0])
check("전달 옵션이 아니면 서브 글이 없어도 통과", I.analyze_subagent(no_text, False)[0])
check("변이: run 이 Agent 호출 id 와 다름 → 실패", not I.analyze_subagent([E.ToolCall(call="A1", name="Agent", input={}), E.Subtask(run="ZZ", state="started"), TR()], False)[0])
check("변이: raw 가 섞임 → 실패", not I.analyze_subagent(sub_ok + [E.Raw(payload={})], True)[0])
check("변이: task 이벤트 없음 → 실패", not I.analyze_subagent([e for e in sub_ok if e.kind != "subtask"], True)[0])

# resume
first = {"id": "S", "cost_total": 0.0003, "cost_delta": 0.0003}
check("resume 통과", I.analyze_resume(first, {"id": "S", "cost_total": 0.0028, "cost_delta": None}, "PELICAN-7", "PELICAN")[0])
check("변이: 첫 턴 delta 가 total 그대로(이전분 이중 계산) → 실패", not I.analyze_resume(first, {"id": "S", "cost_total": 0.0028, "cost_delta": 0.0028}, "PELICAN-7", "PELICAN")[0])
check("변이: 다른 세션 id → 실패", not I.analyze_resume(first, {"id": "T", "cost_total": 0.0028, "cost_delta": None}, "PELICAN-7", "PELICAN")[0])
check("변이: 기억하지 못함 → 실패", not I.analyze_resume(first, {"id": "S", "cost_total": 0.0028, "cost_delta": None}, "I do not know", "PELICAN")[0])

# /proc 도우미: 자기가 띄운 자식 그룹으로 확인
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True, env={**os.environ, "LLM_HOST_ID": "unit-xyz"})
import time; time.sleep(0.3)
m = I.group_mem(p.pid)
check("group_mem: 자식 그룹 1개·RSS 양수", m["procs"] == 1 and m["rss_kb"] > 0, str(m))
check("pgid_members: 자식 pid 포함", p.pid in I.pgid_members(p.pid))
check("env_marked: 표지 있는 자식을 찾음", p.pid in I.env_marked("unit-xyz") and p.pid not in I.env_marked("other"))
p.terminate(); p.wait()
check("종료 뒤 그룹·표지에 남지 않음", I.pgid_members(p.pid) == [] and p.pid not in I.env_marked("unit-xyz"))
finish("llm-host integration_real(판정)")
