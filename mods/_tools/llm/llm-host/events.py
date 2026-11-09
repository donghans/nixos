"""llm-host 내부 이벤트·명령 규격(v0). 벤더(claude 등)를 모른다. Python 3 표준 라이브러리만.
설계: ctx 문서 plan llm-trust/11-p5prime-2-session-host §4-2·§4-3. 규격 설명: README.md.

- 이벤트(호스트 → 소비자): 공통 필드 seq·ts·host_session·backend_session·run·kind + kind 별 필드.
- 명령(소비자 → 호스트): 공통 필드 cmd + 명령별 필드.
- JSON 줄 한 개 = dict 하나. `to_json(obj)` / `event_from_json(s)` / `command_from_json(s)`.
- 알 수 없는 kind(또는 필드가 깨진 줄)는 버리지 않고 `Raw` 이벤트로 돌려준다(프로토콜 변경 탐지용).
- 알려진 kind 에 모르는 필드가 오면 `extra` 에 보존해 다시 직렬화할 때 그대로 나간다(앞으로 호환).
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Optional

SPEC_VERSION = 0

_EVENT_COMMON = ("seq", "ts", "host_session", "backend_session", "run", "kind")


@dataclass(kw_only=True)
class Event:
    """모든 이벤트의 공통 필드. seq: 세션 안 증가 번호 · ts: 호스트 수신 시각(epoch 초) · run: 서브에이전트 실행 id(주 대화는 None)."""
    kind: ClassVar[str] = ""
    seq: int = 0
    ts: float = 0.0
    host_session: str = ""
    backend_session: Optional[str] = None
    run: Optional[str] = None
    extra: dict = field(default_factory=dict)   # 모르는 필드 보존용

    def to_dict(self) -> dict:
        return _to_dict(self, "kind", self.kind)


@dataclass(kw_only=True)
class SessionReady(Event):
    """첫 send 뒤의 첫 system/init(메시지 전에는 오지 않는다). 이후 턴의 init 은 SessionInfo 로 낮춘다."""
    kind: ClassVar[str] = "session_ready"
    backend: str = ""
    backend_version: Optional[str] = None
    model: Optional[str] = None
    cwd: Optional[str] = None
    capabilities: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    slash: list = field(default_factory=list)
    mcp: list = field(default_factory=list)
    permission_mode: Optional[str] = None


@dataclass(kw_only=True)
class SessionInfo(Event):
    """매 턴 다시 오는 init 에서 바뀐 값만(changed: {필드: 새 값})."""
    kind: ClassVar[str] = "session_info"
    changed: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class TurnStarted(Event):
    kind: ClassVar[str] = "turn_started"
    turn: int = 0
    source: str = "user"          # user | auto


@dataclass(kw_only=True)
class TextDelta(Event):
    kind: ClassVar[str] = "text_delta"
    block: int = 0
    text: str = ""


@dataclass(kw_only=True)
class Thinking(Event):
    kind: ClassVar[str] = "thinking"
    tokens_est: Optional[int] = None


@dataclass(kw_only=True)
class Message(Event):
    """완결 메시지. blocks 원소: {type: text|tool_use|tool_result|image, ...}."""
    kind: ClassVar[str] = "message"
    role: str = "assistant"       # assistant | user
    blocks: list = field(default_factory=list)


@dataclass(kw_only=True)
class ToolCall(Event):
    """실행 전 도구 호출."""
    kind: ClassVar[str] = "tool_call"
    call: str = ""
    name: str = ""
    input: Any = None


@dataclass(kw_only=True)
class ToolResult(Event):
    kind: ClassVar[str] = "tool_result"
    call: str = ""
    content: Any = None
    is_error: bool = False


@dataclass(kw_only=True)
class PermissionRequest(Event):
    """권한 요청. S1 결정: description 과 suggestions 를 넣는다(S0 실측: can_use_tool 의 description·permission_suggestions).
    suggestions 는 백엔드가 제안한 규칙·모드 변경(예: setMode acceptEdits)을 벤더 형식 그대로 담는다 — 소비자는 표시만 하고,
    allow 응답에 되돌려 보낼 때(answer_permission 의 updated_permissions)만 쓴다."""
    kind: ClassVar[str] = "permission_request"
    req: str = ""
    tool: str = ""
    display: Optional[str] = None
    input: Any = None
    call: Optional[str] = None
    description: Optional[str] = None
    suggestions: list = field(default_factory=list)


@dataclass(kw_only=True)
class QuestionRequest(Event):
    """질문(AskUserQuestion). questions 원소: {question, header, options:[{label, description}], multiSelect}."""
    kind: ClassVar[str] = "question_request"
    req: str = ""
    questions: list = field(default_factory=list)
    call: Optional[str] = None


@dataclass(kw_only=True)
class RequestResolved(Event):
    """호스트가 보낸 답의 기록(감사용)."""
    kind: ClassVar[str] = "request_resolved"
    req: str = ""
    outcome: str = ""             # allow | deny | answered
    by: str = ""                  # user | policy | timeout | session_end
    message: Optional[str] = None


@dataclass(kw_only=True)
class Subtask(Event):
    kind: ClassVar[str] = "subtask"
    state: str = ""               # started | progress | updated | done
    summary: Optional[str] = None


@dataclass(kw_only=True)
class Hook(Event):
    kind: ClassVar[str] = "hook"
    name: str = ""
    phase: str = ""


@dataclass(kw_only=True)
class TurnResult(Event):
    """한 턴의 끝. S1 결정: terminal_reason·stop_reason·num_turns·model_usage 를 넣는다(S0 실측: result 의 terminal_reason·
    model_usage_since_last_result). model_usage 는 백엔드의 model_usage_since_last_result 를 그대로 담는 후보 필드이며,
    cost_delta 와의 일치는 S2 에서 녹화본으로 확인한다."""
    kind: ClassVar[str] = "turn_result"
    ok: bool = True
    subtype: Optional[str] = None
    text: Optional[str] = None
    cost_total: Optional[float] = None
    cost_delta: Optional[float] = None
    permission_denials: list = field(default_factory=list)
    terminal_reason: Optional[str] = None
    stop_reason: Optional[str] = None
    num_turns: Optional[int] = None
    model_usage: Optional[dict] = None


@dataclass(kw_only=True)
class RateLimit(Event):
    kind: ClassVar[str] = "rate_limit"
    status: Optional[str] = None
    resets_at: Optional[float] = None
    window: Optional[str] = None


@dataclass(kw_only=True)
class Notice(Event):
    kind: ClassVar[str] = "notice"
    level: str = "info"           # info | warn | error
    text: str = ""


@dataclass(kw_only=True)
class SessionEnded(Event):
    kind: ClassVar[str] = "session_ended"
    reason: str = ""              # closed | crashed | killed | eof
    exit_code: Optional[int] = None


@dataclass(kw_only=True)
class Raw(Event):
    """번역표에 없는 줄·깨진 줄. payload 는 원문(JSON 으로 해석되면 그 값, 아니면 문자열)을 그대로 둔다."""
    kind: ClassVar[str] = "raw"
    vendor: Optional[str] = None
    payload: Any = None


EVENT_TYPES: dict[str, type] = {c.kind: c for c in (
    SessionReady, SessionInfo, TurnStarted, TextDelta, Thinking, Message, ToolCall, ToolResult, PermissionRequest,
    QuestionRequest, RequestResolved, Subtask, Hook, TurnResult, RateLimit, Notice, SessionEnded, Raw)}


# ---------------------------------------------------------------- 명령

@dataclass(kw_only=True)
class Command:
    cmd: ClassVar[str] = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _to_dict(self, "cmd", self.cmd)


@dataclass(kw_only=True)
class Start(Command):
    """spec: cwd·model·permission_mode·policy·resume(백엔드 세션 id)·persist(기본 True)·extra_args·env_extra·label."""
    cmd: ClassVar[str] = "start"
    spec: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class Send(Command):
    """text 또는 blocks 중 하나. 생성 중이면 백엔드 대기열."""
    cmd: ClassVar[str] = "send"
    text: Optional[str] = None
    blocks: Optional[list] = None


@dataclass(kw_only=True)
class Interrupt(Command):
    cmd: ClassVar[str] = "interrupt"


@dataclass(kw_only=True)
class AnswerPermission(Command):
    cmd: ClassVar[str] = "answer_permission"
    req: str = ""
    allow: bool = False
    message: Optional[str] = None          # deny 때 모델에 가는 문구
    updated_input: Any = None
    updated_permissions: Optional[list] = None   # PermissionRequest.suggestions 중 채택한 것


@dataclass(kw_only=True)
class AnswerQuestion(Command):
    """answers: {질문 문자열: label 또는 label 목록(multiSelect)}."""
    cmd: ClassVar[str] = "answer_question"
    req: str = ""
    answers: dict = field(default_factory=dict)
    free_text: Optional[str] = None


@dataclass(kw_only=True)
class SetPolicy(Command):
    cmd: ClassVar[str] = "set_policy"
    policy: Any = None


@dataclass(kw_only=True)
class Close(Command):
    cmd: ClassVar[str] = "close"
    grace: Optional[float] = None


@dataclass(kw_only=True)
class Kill(Command):
    cmd: ClassVar[str] = "kill"


COMMAND_TYPES: dict[str, type] = {c.cmd: c for c in (
    Start, Send, Interrupt, AnswerPermission, AnswerQuestion, SetPolicy, Close, Kill)}


# ---------------------------------------------------------------- 직렬화

def _to_dict(obj, tag_key: str, tag: str) -> dict:
    d: dict = {tag_key: tag}
    for f in fields(obj):
        if f.name == "extra":
            continue
        d[f.name] = getattr(obj, f.name)
    for k, v in obj.extra.items():       # 알려진 필드를 덮어쓰지 못하게
        d.setdefault(k, v)
    return d


def _build(cls, d: dict, tag_key: str):
    """dict → cls. 모르는 키는 extra 로. 알려진 필드의 형이 명백히 틀리면 TypeError."""
    names = {f.name for f in fields(cls)} - {"extra"}
    kw = {k: v for k, v in d.items() if k in names}
    extra = {k: v for k, v in d.items() if k not in names and k != tag_key}
    if isinstance(d.get("extra"), dict):
        extra = {**d["extra"], **extra}
    obj = cls(**kw, extra=extra)
    _check_types(obj)
    return obj


_SCALAR = {"int": int, "float": (int, float), "str": str, "bool": bool}


def _check_types(obj) -> None:
    for f in fields(obj):
        if f.name == "extra":
            continue
        v = getattr(obj, f.name)
        t = str(f.type).replace("typing.", "")
        opt = t.startswith("Optional[")
        base = t[9:-1] if opt else t
        if v is None:
            if opt or base in ("Any",):
                continue
            raise TypeError(f"{f.name}: None 불가")
        if base in ("Any",):
            continue
        if base in ("list", "dict"):
            if not isinstance(v, {"list": list, "dict": dict}[base]):
                raise TypeError(f"{f.name}: {base} 아님")
            continue
        py = _SCALAR.get(base)
        if py is None:
            continue
        if isinstance(v, bool) and base != "bool":
            raise TypeError(f"{f.name}: bool 은 {base} 아님")
        if not isinstance(v, py):
            raise TypeError(f"{f.name}: {base} 아님")


def to_json(obj) -> str:
    """이벤트·명령 → JSON 한 줄(개행 없음, 비 ASCII 보존)."""
    return json.dumps(obj.to_dict(), ensure_ascii=False, separators=(",", ":"))


def event_from_dict(d: Any) -> Event:
    """dict → Event. 알 수 없는 kind·깨진 필드·dict 가 아닌 값은 Raw 로(payload 에 원문)."""
    if not isinstance(d, dict):
        return Raw(vendor="malformed", payload=d)
    cls = EVENT_TYPES.get(d.get("kind"))
    if cls is None:
        return _raw_from(d, vendor=d.get("vendor") if d.get("kind") == "raw" else "unknown-kind")
    try:
        return _build(cls, d, "kind")
    except (TypeError, ValueError):
        return _raw_from(d, vendor="malformed")


def _raw_from(d: dict, vendor: Optional[str]) -> Raw:
    """알 수 없는 kind 의 원문 dict 를 payload 로 보존하되, 공통 필드는 Raw 의 공통 필드로 옮긴다(가능한 것만)."""
    common: dict = {}
    for k, py in (("seq", int), ("ts", (int, float)), ("host_session", str)):
        if isinstance(d.get(k), py) and not isinstance(d.get(k), bool):
            common[k] = d[k]
    for k in ("backend_session", "run"):
        if isinstance(d.get(k), str):
            common[k] = d[k]
    if d.get("kind") == "raw" and "payload" in d:
        return Raw(vendor=vendor, payload=d["payload"], **common)
    return Raw(vendor=vendor, payload=d, **common)


def event_from_json(s: str) -> Event:
    try:
        d = json.loads(s)
    except (ValueError, TypeError):
        return Raw(vendor="malformed", payload=s)
    return event_from_dict(d)


def command_from_dict(d: Any) -> Command:
    """dict → Command. 알 수 없는 cmd·깨진 필드는 ValueError(명령은 조용히 통과시키지 않는다)."""
    if not isinstance(d, dict):
        raise ValueError("명령은 JSON 객체여야 한다")
    cls = COMMAND_TYPES.get(d.get("cmd"))
    if cls is None:
        raise ValueError(f"알 수 없는 명령: {d.get('cmd')!r}")
    try:
        obj = _build(cls, d, "cmd")
    except TypeError as e:
        raise ValueError(f"{d.get('cmd')} 명령 필드 오류: {e}") from e
    if isinstance(obj, Send) and (obj.text is None) == (obj.blocks is None):
        raise ValueError("send 는 text 와 blocks 중 정확히 하나가 필요하다")
    return obj


def command_from_json(s: str) -> Command:
    try:
        d = json.loads(s)
    except (ValueError, TypeError) as e:
        raise ValueError(f"JSON 해석 실패: {e}") from e
    return command_from_dict(d)
