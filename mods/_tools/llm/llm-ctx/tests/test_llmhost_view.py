#!/usr/bin/env python3
"""llmhost_view 시험(비용 0, 표준 라이브러리만): 이벤트 → 줄 렌더링의 기대 텍스트, 녹화본(llm-host/tests/fixtures) 재생 결과, 읽기 오류 안내.
화면(llmui 9 탭)은 test_llmui.py 가 본다. 화면 확인은 사용자와 같이 볼 때만(계획 13 H-3)이라 이 텍스트 시험이 그 대체다."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import llmhost_view as v

FX = os.path.join(ROOT, "..", "llm-host", "tests", "fixtures")


def T(evs):
    return v.to_text(v.render_events(evs))


# ---- 1. 합성 이벤트의 기대 텍스트(전 종류)
evs = [
    {"kind": "session_ready", "backend": "claude", "backend_version": "2.1.317", "model": "haiku", "cwd": "/w", "permission_mode": "manual", "tools": ["a", "b"]},
    {"kind": "turn_started", "turn": 1, "source": "user"},
    {"kind": "thinking", "tokens_est": 12}, {"kind": "thinking", "tokens_est": 13},
    {"kind": "text_delta", "block": 0, "text": "안"}, {"kind": "text_delta", "block": 0, "text": "녕\n둘째 줄"},
    {"kind": "message", "role": "assistant", "blocks": [{"type": "text", "text": "안녕\n둘째 줄", "shown_as": "text_delta"}]},
    {"kind": "tool_call", "call": "c1", "name": "Bash", "input": {"command": "ls -la"}},
    {"kind": "permission_request", "req": "r1", "tool": "Bash", "display": "Bash", "input": {"command": "ls -la"}, "description": "목록 보기"},
    {"kind": "request_resolved", "req": "r1", "outcome": "allow", "by": "user"},
    {"kind": "tool_result", "call": "c1", "content": "a.txt", "is_error": False},
    {"kind": "tool_call", "call": "c2", "name": "Read", "input": {"file_path": "/x"}},
    {"kind": "tool_result", "call": "c2", "content": [{"type": "text", "text": "없음"}], "is_error": True},
    {"kind": "question_request", "req": "q1", "questions": [{"question": "색은?", "header": "색", "options": [{"label": "빨강", "description": "붉다"}, {"label": "파랑"}]}]},
    {"kind": "subtask", "state": "started", "summary": "조사"},
    {"kind": "hook", "name": "Stop", "phase": "started"},
    {"kind": "notice", "level": "warn", "text": "재시도"},
    {"kind": "turn_result", "ok": True, "text": "안녕\n둘째 줄", "cost_total": 0.0123, "cost_delta": 0.01, "permission_denials": []},
    {"kind": "turn_result", "ok": False, "subtype": "error_during_execution", "cost_total": 0.0123, "cost_delta": 0.0, "permission_denials": [{}]},
    {"kind": "raw", "vendor": "claude", "payload": {}},
    {"kind": "session_ended", "reason": "closed", "exit_code": 0},
]
GOLD = """● 세션 시작 — claude 2.1.317  모델 haiku  권한모드 manual  도구 2개
  cwd /w
─ 턴 1 (사용자)
  … 생각 중(≈12 토큰)
  안녕
  둘째 줄
▸ Bash [위험]  command=ls -la
? 권한 요청 [r1] Bash [위험]: Bash
    목록 보기
  = [r1] allow (결정: user)
  ↳ a.txt
▸ Read  file_path=/x
  ↳ 오류: 없음
? 질문 [q1]
  색 색은?
    - 빨강 — 붉다
    - 파랑
  ⇢ 하위 작업 started: 조사
  (훅 Stop started)
  ! warn: 재시도
✔ 결과 성공 · 이번 $0.0100 · 누적 $0.0123
✔ 결과 실패(error_during_execution) · 이번 $0.0000 · 누적 $0.0123 · 거부 1건
  ? 알 수 없는 줄(claude)
■ 세션 끝 — closed (종료 코드 0)"""
got = T(evs)
check("합성 이벤트 전 종류의 렌더링이 기대 텍스트와 같다", got == GOLD, "\n--- got\n" + got)
check("모든 줄의 스타일이 STYLES 안", all(s in v.STYLES for s, _ in v.render_events(evs)))
check("shown_as 블록은 다시 그리지 않는다(글이 한 번만)", got.count("둘째 줄") == 1)
check("shown_as 없는 완결 메시지 글은 그린다(부분 메시지 옵션 없는 경우)",
      "  혼자 온 글" in T([{"kind": "message", "role": "assistant", "blocks": [{"type": "text", "text": "혼자 온 글"}]}]))
check("글 조각 없이 turn_result 만 있으면 결과 문구를 보인다", "  최종 문구" in T([{"kind": "turn_result", "ok": True, "text": "최종 문구"}]))
check("연속 thinking 은 한 줄", T([{"kind": "thinking", "tokens_est": 1}, {"kind": "thinking", "tokens_est": 2}]).count("생각 중") == 1)
check("알 수 없는 kind 는 숨기지 않고 표시", "알 수 없는 이벤트 'zzz'" in T([{"kind": "zzz"}]))
check("긴 도구 결과는 한 줄로 줄임(…)", T([{"kind": "tool_result", "content": "가" * 500}]).endswith("…") and "\n" not in T([{"kind": "tool_result", "content": "a\nb\n" * 300}]))
check("위험 도구 판정: Bash·Write·mcp__ 는 위험, Read 는 아님", v.is_risky("Bash") and v.is_risky("Write") and v.is_risky("mcp__x__y") and not v.is_risky("Read"))
check("빈 목록은 빈 결과", v.render_events([]) == [] and v.summarize([])["events"] == 0)
sm = v.summarize(evs)
check("summarize: raw·도구 호출·권한 요청·질문·누적 비용", sm["raw"] == 1 and sm["tool_calls"] == 2 and sm["permission_requests"] == 1 and sm["questions"] == 1 and sm["cost_total"] == 0.0123, str(sm))
check("제한 모드 허용 동작은 산출물 보기뿐이다", v.RESTRICTED_OK_ACTIONS == ("host_artifacts",) and set(v.RESTRICTED_OK_ACTIONS) <= set(v.HOST_ACTIONS))
check("제한 모드 막을 동작 이름과 안내문이 있다", len(v.HOST_ACTIONS) >= 4 and "읽기만" in v.RESTRICTED_NOTICE)

# ---- 2. 녹화본 재생(llm-host 어댑터 경유) — 기대 줄
if os.path.isdir(FX):
    ev_main, err = v.load_events(os.path.join(FX, "main.jsonl"))
    check("main 녹화본: 읽힘·raw 0·턴 6·도구 3·질문 1", err is None and v.summarize(ev_main)["raw"] == 0 and v.summarize(ev_main)["turns"] == 6
          and v.summarize(ev_main)["tool_calls"] == 3 and v.summarize(ev_main)["questions"] == 1, str(err))
    tm = T(ev_main)
    for want in ("● 세션 시작 — claude 2.1.317  모델 claude-haiku-5-5  권한모드 default  도구 32개", "▸ Bash [위험]  command=echo s0-allow",
                 "  ↳ s0-allow", "  색상 선호 빨간색과 파란색 중 어느 쪽을 선호하시나요?", "    - 파란색 — 파란색을 선택합니다.",
                 "✔ 결과 실패(error_during_execution) · 이번 $0.0000 · 누적 $0.0096", "─ 턴 6 (사용자)"):
        check(f"main 렌더에 줄 포함: {want[:30]}", want in tm.split("\n"), want)
    check("main: 질문 요청 줄", "? 질문 [00000000-0000-4000-8000-000000000100]" in tm)
    ev_perm, err = v.load_events(os.path.join(FX, "perm.jsonl"))
    tp = T(ev_perm)
    check("perm 녹화본: 권한 요청 4건, 거부된 도구 결과가 오류로 보임·거부 건수 표시", v.summarize(ev_perm)["permission_requests"] == 4 and "  ↳ 오류: User denied this action in the TUI." in tp and "거부 1건" in tp)
    check("perm: Write 권한 요청 줄(위험 표시)", any(l.startswith("? 권한 요청 [") and "Write [위험]" in l for l in tp.split("\n")))
    ev_sub, err = v.load_events(os.path.join(FX, "sub.jsonl"))
    ts = T(ev_sub)
    check("sub 녹화본: 하위 작업·훅 줄이 보이고 raw 0", err is None and "⇢ 하위 작업" in ts and "(훅 " in ts and v.summarize(ev_sub)["raw"] == 0)
    ev_ni, err = v.load_events(os.path.join(FX, "noinit.jsonl"))
    check("noinit 녹화본(출력 없음)은 이벤트 0·오류 없음", ev_ni == [] and err is None, str(err))
    # 호스트 이벤트 로그 모양(kind 줄)도 읽힌다
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "log.jsonl")
        open(p, "w", encoding="utf-8").write("\n".join(json.dumps(e, ensure_ascii=False) for e in evs[:3]) + "\n")
        r, err = v.load_events(p)
        check("이벤트 로그(kind 줄)를 그대로 읽는다", err is None and len(r) == 3)
        open(p, "w").write("깨짐\n")
        check("깨진 파일은 오류 문구(예외 아님)", v.load_events(p)[1] is not None)
        open(p, "w").write('{"a":1}\n')
        check("모르는 모양은 오류 문구", "알 수 없는 파일 모양" in (v.load_events(p)[1] or ""))
    check("없는 파일은 오류 문구", "읽지 못함" in (v.load_events("/nonexistent/x.jsonl")[1] or ""))
    os.environ["LLMUI_HOST_FIXTURE"] = "/some/path.jsonl"
    check("LLMUI_HOST_FIXTURE 가 기본 녹화본보다 우선", v.default_fixture() == "/some/path.jsonl")
    del os.environ["LLMUI_HOST_FIXTURE"]
    check("기본 녹화본은 main.jsonl", (v.default_fixture() or "").endswith("fixtures/main.jsonl"))
else:
    print("llm-host 녹화본이 없어 재생 시험을 건너뜀")
finish("llmhost_view")
