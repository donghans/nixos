"""llmhost_view — llmui 9 「호스트」 탭의 순수 렌더링(이벤트 → 텍스트 줄). 화면·호스트·DB 와 무관해 단위 시험이 쉽다.

입력은 llm-host 규격(llm-trust 11, `events.to_json`)의 이벤트 dict 목록이다. 표준 라이브러리만 쓰고 llm-host 모듈을 import 하지 않는다
(llm-host 는 아직 nix 에 등록되지 않았다). 출력은 [(스타일, 글)] — 스타일은 STYLES 의 키이고 색은 호출자(llmui)가 정한다.

S0(읽기 전용): 녹화본·이벤트 로그를 읽어 그리기만 한다. 호스트 프로세스는 띄우지 않는다.
"""
from __future__ import annotations

import json
import os
import sys

STYLES = ("head", "text", "think", "tool", "result", "err", "perm", "ask", "info", "warn", "cost", "dim")

# 제한 모드(H-4)에서 막을 호스트 동작 이름. S0 에는 이 동작이 아직 없다 — S1 이후 추가하는 동작은 여기에 넣어 llmui.check_action 이 거르게 한다.
HOST_ACTIONS = ("host_start", "host_send", "host_answer", "host_interrupt")

RESTRICTED_NOTICE = ("제한 모드(LLM 세션 안에서 실행됨): 호스트 탭은 읽기만 한다 — 세션 구동·응답 전송·권한 허용은 사람이 터미널에서 직접 llmui 를 "
                     "실행했을 때만 쓸 수 있다(권한 위임·skip-permissions 와 닿는 탭이라 막아 둔다).")

# 위험 도구(11 D-5, 도구 이름 기준): 정책이 자동 허용하지 않는 것. 표시용이라 이름이 늘면 여기만 고친다.
RISKY_TOOLS = frozenset({"Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "Agent", "Task"})

_RESULT_MAX = 100       # 도구 결과·입력 요약의 한 줄 최대 글자


def is_risky(tool: str) -> bool:
    return tool in RISKY_TOOLS or tool.startswith("mcp__")


def _clip(s, n=_RESULT_MAX) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _money(v) -> str:
    return "-" if v is None else f"${float(v):.4f}"


def summarize_input(inp) -> str:
    """도구 입력을 한 줄로: 흔한 키(command·file_path·path·pattern·url·description)가 있으면 그 값, 없으면 JSON 요약."""
    if isinstance(inp, dict):
        for k in ("command", "file_path", "path", "pattern", "url", "description", "prompt", "query"):
            if inp.get(k):
                return _clip(f"{k}={inp[k]}")
        return _clip(json.dumps(inp, ensure_ascii=False))
    return _clip(inp if inp is not None else "")


def _content_text(c) -> str:
    """tool_result 의 content(문자열 또는 블록 목록)를 글로."""
    if isinstance(c, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return "" if c is None else str(c)


def _text_lines(text: str, style="text", indent="  "):
    out = []
    for ln in str(text).split("\n"):
        out.append((style, indent + ln))
    while out and not out[-1][1].strip():
        out.pop()
    return out


def render_events(events) -> list:
    """이벤트 dict 목록 → [(스타일, 글)]. 연속한 text_delta 는 한 덩어리로 잇고, `shown_as` 가 붙은 메시지 블록은 다시 그리지 않는다."""
    out: list = []
    buf: list[str] = []          # 이어 붙이는 text_delta

    def flush():
        if buf:
            out.extend(_text_lines("".join(buf)))
            buf.clear()

    shown_text = False           # 이번 턴에 글을 이미 그렸나(결과 문구가 그 글과 같아 반복되는 것을 막는다)
    for ev in events:
        k = ev.get("kind")
        if k == "text_delta":
            buf.append(ev.get("text", ""))
            shown_text = True
            continue
        flush()
        if k == "thinking":
            if not (out and out[-1][0] == "think"):
                out.append(("think", f"  … 생각 중(≈{ev.get('tokens_est')} 토큰)"))
            continue
        if k == "session_ready":
            out.append(("head", f"● 세션 시작 — {ev.get('backend', '?')} {ev.get('backend_version') or ''}  모델 {ev.get('model') or '?'}  권한모드 {ev.get('permission_mode') or '?'}  도구 {len(ev.get('tools') or [])}개"))
            out.append(("dim", f"  cwd {ev.get('cwd') or '?'}"))
        elif k == "session_info":
            out.append(("dim", "  (세션 정보 변경: " + ", ".join(sorted((ev.get("changed") or {}).keys())) + ")"))
        elif k == "turn_started":
            shown_text = False
            out.append(("head", f"─ 턴 {ev.get('turn', 0)} ({'사용자' if ev.get('source', 'user') == 'user' else '자동'})"))
        elif k == "message":
            for b in ev.get("blocks") or []:
                if b.get("shown_as") or not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text" and b.get("text"):
                    shown_text = True
                    out.extend(_text_lines(b["text"], "text" if ev.get("role") == "assistant" else "dim"))
                elif t == "tool_use":
                    out.append(("tool", f"▸ {b.get('name')}  {summarize_input(b.get('input'))}"))
                elif t == "tool_result":
                    out.append(("err" if b.get("is_error") else "result", f"  ↳ {_clip(_content_text(b.get('content')))}"))
        elif k == "tool_call":
            name = ev.get("name") or "?"
            out.append(("tool", f"▸ {name}{' [위험]' if is_risky(name) else ''}  {summarize_input(ev.get('input'))}"))
        elif k == "tool_result":
            bad = bool(ev.get("is_error"))
            out.append(("err" if bad else "result", f"  ↳ {'오류: ' if bad else ''}{_clip(_content_text(ev.get('content')))}"))
        elif k == "permission_request":
            tool = ev.get("tool") or "?"
            out.append(("perm", f"? 권한 요청 [{ev.get('req')}] {tool}{' [위험]' if is_risky(tool) else ''}: {_clip(ev.get('display') or summarize_input(ev.get('input')))}"))
            if ev.get("description"):
                out.append(("dim", f"    {_clip(ev['description'])}"))
        elif k == "question_request":
            out.append(("ask", f"? 질문 [{ev.get('req')}]"))
            for q in ev.get("questions") or []:
                out.append(("ask", ("  " + f"{q.get('header') or ''} {q.get('question', '')}".strip())))
                for o in q.get("options") or []:
                    out.append(("dim", f"    - {o.get('label')}" + (f" — {_clip(o['description'])}" if o.get("description") else "")))
        elif k == "request_resolved":
            out.append(("dim", f"  = [{ev.get('req')}] {ev.get('outcome')} (결정: {ev.get('by')})" + (f" — {_clip(ev['message'])}" if ev.get("message") else "")))
        elif k == "subtask":
            out.append(("info", f"  ⇢ 하위 작업 {ev.get('state')}: {_clip(ev.get('summary') or '')}".rstrip()))
        elif k == "hook":
            out.append(("dim", f"  (훅 {ev.get('name')} {ev.get('phase')})"))
        elif k == "turn_result":
            ok = ev.get("ok", True)
            out.append(("cost" if ok else "err", f"✔ 결과 {'성공' if ok else '실패'}" + (f"({ev.get('subtype')})" if ev.get("subtype") and not ok else "")
                        + f" · 이번 {_money(ev.get('cost_delta'))} · 누적 {_money(ev.get('cost_total'))}" + (f" · 거부 {len(ev['permission_denials'])}건" if ev.get("permission_denials") else "")))
            if ev.get("text") and not shown_text:
                out.extend(_text_lines(_clip(ev["text"], 200), "dim"))
            shown_text = False
        elif k == "rate_limit":
            out.append(("dim", f"  (한도 {ev.get('window') or ''} {ev.get('status') or ''})"))
        elif k == "notice":
            out.append(("warn" if ev.get("level") in ("warn", "error") else "info", f"  ! {ev.get('level', 'info')}: {_clip(ev.get('text'))}"))
        elif k == "session_ended":
            out.append(("head", f"■ 세션 끝 — {ev.get('reason')}" + (f" (종료 코드 {ev['exit_code']})" if ev.get("exit_code") is not None else "")))
        elif k == "raw":
            out.append(("warn", f"  ? 알 수 없는 줄({ev.get('vendor')})"))
        else:
            out.append(("warn", f"  ? 알 수 없는 이벤트 {k!r}"))
    flush()
    return out


def summarize(events) -> dict:
    """머리줄용 집계: 이벤트 수·raw 수(카나리아가 0 을 요구)·턴 수·마지막 누적 비용."""
    kinds: dict = {}
    for e in events:
        kinds[e.get("kind")] = kinds.get(e.get("kind"), 0) + 1
    cost = None
    for e in events:
        if e.get("kind") == "turn_result" and e.get("cost_total") is not None:
            cost = e["cost_total"]
    return {"events": len(events), "raw": kinds.get("raw", 0), "turns": kinds.get("turn_result", 0), "cost_total": cost,
            "tool_calls": kinds.get("tool_call", 0), "permission_requests": kinds.get("permission_request", 0), "questions": kinds.get("question_request", 0)}


def to_text(lines) -> str:
    return "\n".join(t for _, t in lines)


# ---------------------------------------------------------------- 읽기
def _host_dir() -> str | None:
    """llm-host 소스 폴더(소스 트리 ../llm-host). 배포본에는 없다 — 그러면 None."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm-host")
    return d if os.path.isfile(os.path.join(d, "claude_adapter.py")) else None


def default_fixture() -> str | None:
    """S0 기본 녹화본: 환경변수 LLMUI_HOST_FIXTURE, 없으면 소스 트리의 llm-host/tests/fixtures/main.jsonl."""
    p = os.environ.get("LLMUI_HOST_FIXTURE")
    if p:
        return p
    d = _host_dir()
    if d:
        q = os.path.join(d, "tests", "fixtures", "main.jsonl")
        return q if os.path.isfile(q) else None
    return None


def load_events(path: str) -> tuple[list, str | None]:
    """(이벤트 dict 목록, 오류 문구). 파일은 JSON 줄이며 두 모양을 받는다 — 호스트 이벤트 로그(`kind` 가 있는 줄)와
    S0 녹화본(`{"t","dir","line"}`; claude 의 날 줄이라 llm-host 의 어댑터가 있어야 번역된다)."""
    try:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except (OSError, ValueError) as e:
        return [], f"읽지 못함: {path} ({e.__class__.__name__})"
    if rows and all(isinstance(r, dict) and "kind" in r for r in rows):
        return rows, None
    if rows and all(isinstance(r, dict) and "line" in r and "dir" in r for r in rows):
        d = _host_dir()
        if not d:
            return [], "녹화본(claude 날 줄)을 번역하려면 소스 트리의 llm-host 가 필요하다(이 설치에는 없음). 이벤트 로그(kind 줄)를 지정하라"
        if d not in sys.path:
            sys.path.insert(0, d)
        try:
            import claude_adapter
            import events as E
        except Exception as e:                                  # noqa: BLE001 — 어댑터 읽기 실패는 화면 안내로
            return [], f"llm-host 어댑터를 읽지 못함: {e.__class__.__name__}"
        ad = claude_adapter.ClaudeAdapter(host_session="fixture")
        out: list = []
        for r in rows:
            ln = r["line"]
            if r["dir"] == "in" and isinstance(ln, dict) and ln.get("type") == "user":
                ad.note_sent()
            elif r["dir"] == "out":
                out.extend(json.loads(E.to_json(ev)) for ev in ad.decode(ln))
        return out, None
    return [], f"알 수 없는 파일 모양: {path}"
