"""권한·질문 정책(순수 함수). 설계: ctx 문서 plan llm-trust/11-p5prime-2-session-host §6-1·§6-3·§14.
입출력이 값뿐이다(시계·프로세스·세션을 모른다). 호출하는 쪽(session.py/host.py, S5 이후)이 현재 시각·구독자 수를 세어 넘긴다.

먼저 알아 둘 것(S0 확인, §6-1-4): claude 는 사용자 설정 규칙(permissions.allow·ask, 훅 설정)과 권한 모드를 **먼저** 평가한다.
규칙이 허용한 호출은 호스트에 can_use_tool 요청이 아예 오지 않는다(tool_result_meta.permission_decision.source 가 config).
그러므로 이 정책은 「결정이 안 난 요청」만 본다. 호스트가 허용 목록을 새로 만드는 곳이 아니다.

정책(policy dict, Start.spec["policy"]·SetPolicy 로 들어옴; 없으면 기본값):
- request_timeout  요청 대기 상한(초). 기본 1800(30분, D-3). 0 이하·숫자 아님은 ValueError.
- auto_allow       자동 허용 도구 이름 목록. 기본 빈 목록. 읽기 전용 허용 가능 집합(READ_ONLY_ALLOWABLE) 밖의 이름은 무시하고 ignored 에 남긴다.
- max_auto_turns   사람 메시지 없이 연속 가능한 자동 턴 수. 기본 3(D-12).
- allow_bypass     skip-permissions 허용 의사 표시. 기본 False. True 여도 cwd 에 SANDBOX_MARKER 파일이 있어야 통과한다.
위험 도구(Bash·Write·Edit·NotebookEdit·WebFetch·MCP·Agent·알 수 없는 도구)는 어떤 정책으로도 자동 허용하지 않는다. AskUserQuestion 도 정책이 답하지 않는다.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_REQUEST_TIMEOUT = 1800.0
DEFAULT_MAX_AUTO_TURNS = 3
SANDBOX_MARKER = ".llm-host-sandbox"
READ_ONLY_ALLOWABLE = frozenset({"Read", "Glob", "Grep", "LS"})
QUESTION_TOOL = "AskUserQuestion"
BYPASS_MODES = frozenset({"bypasspermissions", "bypass"})
BYPASS_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")


@dataclass(frozen=True)
class Policy:
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    auto_allow: frozenset = frozenset()
    max_auto_turns: int = DEFAULT_MAX_AUTO_TURNS
    allow_bypass: bool = False
    ignored: tuple = ()          # auto_allow 에서 받아들이지 않은 이름(위험 도구 등)


def normalize_policy(p: Optional[dict]) -> Policy:
    """policy dict(또는 None) → Policy. 잘못된 값은 ValueError(조용히 기본값으로 바꾸지 않는다)."""
    if p is None:
        return Policy()
    if isinstance(p, Policy):
        return p
    if not isinstance(p, dict):
        raise ValueError(f"policy 는 dict 여야 한다: {type(p).__name__}")
    unknown = sorted(set(p) - {"request_timeout", "auto_allow", "max_auto_turns", "allow_bypass"})
    if unknown:
        raise ValueError(f"알 수 없는 policy 키: {unknown}")
    rt = p.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
    if isinstance(rt, bool) or not isinstance(rt, (int, float)) or rt <= 0:
        raise ValueError(f"request_timeout 은 0 보다 큰 숫자(초)여야 한다: {rt!r}")
    mat = p.get("max_auto_turns", DEFAULT_MAX_AUTO_TURNS)
    if isinstance(mat, bool) or not isinstance(mat, int) or mat < 0:
        raise ValueError(f"max_auto_turns 는 0 이상의 정수여야 한다: {mat!r}")
    aa = p.get("auto_allow", [])
    if not isinstance(aa, (list, tuple, set, frozenset)) or not all(isinstance(x, str) for x in aa):
        raise ValueError("auto_allow 는 도구 이름 문자열 목록이어야 한다")
    ab = p.get("allow_bypass", False)
    if not isinstance(ab, bool):
        raise ValueError(f"allow_bypass 는 bool 이어야 한다: {ab!r}")
    ok = frozenset(x for x in aa if x in READ_ONLY_ALLOWABLE)
    ignored = tuple(sorted(set(aa) - ok))
    return Policy(float(rt), ok, mat, ab, ignored)


# ---------------------------------------------------------------- 모델이 읽는 문구(§6-3)
# 형식: ① 누가·왜 ② 다시 요청하지 말 것 ③ 대신 할 일. 이 문구는 모델 입력이다 — 바꾸면 tests/test_policy.py 의 문구 덤프 시험과 검토 기록을 함께 갱신한다.
_TAIL_STOP = "같은 도구 호출을 다시 시도하거나 다른 방법으로 같은 결과를 얻으려 하지 말고, 이 작업은 하지 않은 것으로 두고 지금까지의 결과와 막힌 지점을 사용자에게 보고하라."
MESSAGES = {
    "user_denied": "사용자가 이 도구 호출을 거부했다. " + _TAIL_STOP,
    "user_denied_reason": "사용자가 이 도구 호출을 거부했고 이유를 남겼다. 이유(사용자 입력 그대로): {reason}\n" + _TAIL_STOP,
    "timeout": "사용자가 {minutes}분 안에 이 도구 호출을 승인하지 않아 자동으로 거부했다(사용자가 자리에 없을 수 있다). 지금은 아무도 승인할 수 없다고 보라. " + _TAIL_STOP,
    "question_timeout": "사용자가 {minutes}분 안에 질문에 답하지 않았다(사용자가 자리에 없을 수 있다). 질문의 답을 추측해 진행하지 말고, 질문에 답이 필요한 부분은 하지 않은 것으로 두고 무엇을 물으려 했는지와 지금까지의 결과를 최종 응답으로 보고하라.",
    "session_end": "세션이 끝나거나 턴이 취소되어 이 요청은 취소되었다. 이 도구 호출은 실행되지 않았다.",
}
# 정책 거부(위험 도구 자동 거부 등)는 만들지 않는다: 위험 도구는 거부가 아니라 사람에게 묻는다(wait). 그래서 정책 거부 문구는 없다.


def _minutes(seconds: float) -> str:
    m = seconds / 60.0
    return str(int(m)) if m == int(m) else f"{m:.1f}"


def deny_message(kind: str, *, user_reason: Optional[str] = None, request_timeout: float = DEFAULT_REQUEST_TIMEOUT, question: bool = False) -> str:
    """kind: user_denied | timeout | session_end. 사용자 이유가 있으면(공백만이 아니면) 그대로 전달한다.
    question=True 인 timeout 은 질문용 문구."""
    if kind == "user_denied":
        r = (user_reason or "").strip()
        return MESSAGES["user_denied_reason"].format(reason=r) if r else MESSAGES["user_denied"]
    if kind == "timeout":
        key = "question_timeout" if question else "timeout"
        return MESSAGES[key].format(minutes=_minutes(request_timeout))
    if kind == "session_end":
        return MESSAGES["session_end"]
    raise ValueError(f"알 수 없는 거부 종류: {kind}")


def all_messages(request_timeout: float = DEFAULT_REQUEST_TIMEOUT) -> list:
    """호스트가 모델에게 줄 수 있는 모든 문구(검토용 덤프). [(id, 본문)]"""
    return [
        ("user_denied", deny_message("user_denied")),
        ("user_denied_reason", deny_message("user_denied", user_reason="<사용자가 입력창에 쓴 이유>")),
        ("timeout", deny_message("timeout", request_timeout=request_timeout)),
        ("question_timeout", deny_message("timeout", request_timeout=request_timeout, question=True)),
        ("session_end", deny_message("session_end")),
    ]


# ---------------------------------------------------------------- 요청 결정
@dataclass(frozen=True)
class Decision:
    action: str                  # allow | deny | wait
    by: str = ""                 # policy | timeout | (wait 이면 "user": 사람 답을 기다림)
    message: Optional[str] = None
    wait_left: Optional[float] = None   # wait 일 때 상한까지 남은 초


def decide_request(policy, tool: str, *, subscribers: int, waited: float, is_question: bool = False) -> Decision:
    """결정이 안 난 요청 하나에 대한 호스트 정책.
    tool: 도구 이름. subscribers: 지금 이벤트를 구독 중인 화면 수. waited: 요청이 온 뒤 흐른 초.
    규칙(순서대로):
    1. 질문(AskUserQuestion 이거나 is_question)은 정책이 대신 답하지 않는다 — 상한 전이면 wait, 넘으면 deny(질문용 문구).
    2. 자동 허용 목록(읽기 전용 집합 안의 것만)에 있으면 allow(by=policy). 위험 도구는 목록에 있어도 여기 못 온다(normalize 가 걸러냄).
    3. 그 밖: 상한(request_timeout) 전이면 wait(사람이 있든 없든 — 구독자가 없으면 붙기를 기다린다), 상한에 닿으면 deny(by=timeout).
    subscribers 는 결정에 영향을 주지 않고 wait_left 해석(표시)용이다: 구독자가 없어도 상한까지는 요청을 대기 표에 둔다."""
    pol = normalize_policy(policy)
    if waited < 0:
        raise ValueError("waited 는 0 이상")
    question = is_question or tool == QUESTION_TOOL
    if not question and tool in pol.auto_allow:
        return Decision("allow", "policy")
    left = pol.request_timeout - waited
    if left > 0:
        return Decision("wait", "user", None, left)
    return Decision("deny", "timeout", deny_message("timeout", request_timeout=pol.request_timeout, question=question))


# ---------------------------------------------------------------- 시작 spec 검사(bypass 거부)
def check_start(spec: Optional[dict]) -> list:
    """Start.spec 을 검사해 거부 사유 목록을 돌려준다(빈 목록이면 통과). bypass 계열 permission_mode·플래그는
    spec.policy.allow_bypass=True **이고** cwd 에 SANDBOX_MARKER 파일이 있을 때만 통과.
    한계: --settings 파일 안의 defaultMode 같은 간접 지정은 읽지 않는다(extra_args 의 값만 본다)."""
    spec = spec or {}
    reasons = []
    pol = normalize_policy(spec.get("policy"))
    found = []
    mode = spec.get("permission_mode")
    if isinstance(mode, str) and mode.strip().lower() in BYPASS_MODES:
        found.append(f"permission_mode={mode}")
    args = [str(a) for a in (spec.get("extra_args") or [])]
    for i, a in enumerate(args):
        if a in BYPASS_FLAGS or any(a.startswith(f + "=") for f in BYPASS_FLAGS):
            found.append(a)
        elif a == "--permission-mode" and i + 1 < len(args) and args[i + 1].strip().lower() in BYPASS_MODES:
            found.append(f"--permission-mode {args[i + 1]}")
        elif a.startswith("--permission-mode=") and a.split("=", 1)[1].strip().lower() in BYPASS_MODES:
            found.append(a)
    if not found:
        return reasons
    if not pol.allow_bypass:
        reasons.append(f"skip-permissions 계열 지정({', '.join(found)})은 거부: spec.policy.allow_bypass=True 를 소비자가 명시해야 한다")
        return reasons
    cwd = spec.get("cwd")
    if not (isinstance(cwd, str) and cwd and os.path.isfile(os.path.join(cwd, SANDBOX_MARKER))):
        reasons.append(f"skip-permissions 계열 지정({', '.join(found)})은 cwd 에 {SANDBOX_MARKER} 표시 파일이 있는 샌드박스 폴더에서만 허용: cwd={cwd!r}")
    return reasons


# ---------------------------------------------------------------- 자동 턴 상한
def next_auto_turn(policy, count: int) -> tuple:
    """사람 메시지 없이 자동 턴을 하나 더 시작해도 되는가. count: 지금까지 연속 자동 턴 수(사람 메시지가 오면 호출하는 쪽이 0 으로).
    반환 (허용 여부, 새 count, 사유|None). 상한에 닿으면 (False, count, 사유) — count 는 늘리지 않는다."""
    pol = normalize_policy(policy)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count 는 0 이상의 정수")
    if count >= pol.max_auto_turns:
        return False, count, f"자동 턴 상한({pol.max_auto_turns}) 도달: 사람 메시지가 올 때까지 더 보내지 않는다"
    return True, count + 1, None


if __name__ == "__main__":
    if sys.argv[1:] == ["--dump-messages"]:
        for k, v in all_messages():
            print(f"[{k}]\n{v}\n")
    else:
        print("사용: python3 policy.py --dump-messages", file=sys.stderr)
        sys.exit(2)
