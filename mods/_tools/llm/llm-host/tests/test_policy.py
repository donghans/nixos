#!/usr/bin/env python3
"""llm-host policy.py(S4) 시험. 비용 0, 순수 함수. 표 기반: 도구 × (구독자 유무 × 대기 시간) 조합, 상한 초과 거부, bypass 거부, max_auto_turns, 문구 덤프.
skip-permissions 를 실제 claude 로 돌리는 시험은 하지 않는다(사용자 허락 필요, 계획 §6-1-5·user_needed)."""
import os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import policy as P

# ---- normalize_policy
d = P.normalize_policy(None)
check("기본값: 30분·자동 허용 없음·자동 턴 3·bypass 불허", (d.request_timeout, d.auto_allow, d.max_auto_turns, d.allow_bypass) == (1800.0, frozenset(), 3, False))
p = P.normalize_policy({"auto_allow": ["Read", "Grep", "Bash", "Write", "mcp__x__y", "Agent", "Edit"], "request_timeout": 60})
check("읽기 전용 밖 이름(Bash·Write·MCP·Agent·Edit)은 허용 목록에 못 들어가고 ignored 에 남는다",
      p.auto_allow == {"Read", "Grep"} and p.ignored == ("Agent", "Bash", "Edit", "Write", "mcp__x__y"))
check("Policy 를 다시 넣어도 그대로", P.normalize_policy(p) is p)
for bad in ({"request_timeout": 0}, {"request_timeout": -1}, {"request_timeout": "30"}, {"request_timeout": True}, {"max_auto_turns": -1},
            {"max_auto_turns": 1.5}, {"auto_allow": "Read"}, {"auto_allow": [1]}, {"allow_bypass": "yes"}, {"oops": 1}, "x", 5):
    try:
        P.normalize_policy(bad); ok = False
    except ValueError:
        ok = True
    check(f"잘못된 정책 거부 {bad!r}", ok)

# ---- decide_request 표: (도구, 정책, 구독자, 대기초, 질문?) → (action, by)
RO = {"auto_allow": ["Read", "Glob"], "request_timeout": 100}
NO = {"request_timeout": 100}
TABLE = [
    # 자동 허용은 읽기 전용 목록에 있을 때만, 구독자·대기와 무관
    ("Read", RO, 0, 0, "allow", "policy"), ("Read", RO, 3, 50, "allow", "policy"), ("Glob", RO, 0, 500, "allow", "policy"),
    ("Grep", RO, 0, 0, "wait", "user"),              # 목록에 없음
    ("Read", NO, 0, 0, "wait", "user"),              # 기본 정책은 아무것도 자동 허용 안 함
    # 위험 도구는 목록에 적어도 항상 사람 (대기 → 상한 후 거부)
    *[(t, {"auto_allow": [t], "request_timeout": 100}, s, w, a, b)
      for t in ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "Agent", "mcp__srv__tool", "SomethingNew")
      for (s, w, a, b) in ((0, 0, "wait", "user"), (2, 99.9, "wait", "user"), (0, 100, "deny", "timeout"), (2, 1000, "deny", "timeout"))],
    # 구독자 없음: 상한 전까지는 대기 표에 둔다
    ("Write", NO, 0, 0, "wait", "user"), ("Write", NO, 0, 99.99, "wait", "user"),
    ("Write", NO, 0, 100, "deny", "timeout"), ("Write", NO, 0, 101, "deny", "timeout"),
    # 구독자 있음: 같은 상한이 적용(응답 없는 화면이 영원히 붙잡지 못함)
    ("Write", NO, 1, 99, "wait", "user"), ("Write", NO, 1, 100, "deny", "timeout"),
    # 질문은 자동 허용 대상 아님(목록에 AskUserQuestion 을 적어도 무시됨)
    ("AskUserQuestion", {"auto_allow": ["AskUserQuestion"], "request_timeout": 100}, 1, 0, "wait", "user"),
    ("AskUserQuestion", {"auto_allow": ["AskUserQuestion"], "request_timeout": 100}, 0, 100, "deny", "timeout"),
]
for t, pol, subs, w, ea, eb in TABLE:
    dec = P.decide_request(pol, t, subscribers=subs, waited=w)
    check(f"{t} subs={subs} waited={w} → {ea}/{eb}", (dec.action, dec.by) == (ea, eb), repr(dec))
# is_question 플래그: 도구 이름이 달라도 질문 취급
dq = P.decide_request({"auto_allow": ["Read"], "request_timeout": 10}, "Read", subscribers=0, waited=10, is_question=True)
check("is_question=True 면 Read 라도 자동 허용 없이 질문용 거부 문구", dq.action == "deny" and "질문" in dq.message)
dw = P.decide_request(NO, "Write", subscribers=0, waited=40)
check("wait 는 상한까지 남은 초를 준다", dw.action == "wait" and abs(dw.wait_left - 60) < 1e-9 and dw.message is None)
dd = P.decide_request(NO, "Write", subscribers=0, waited=100)
check("상한 거부는 timeout 문구(분 표시·재시도 금지·보고)를 담는다", "분 안에" in dd.message and "다시 시도하거나" in dd.message and dd.wait_left is None)
check("기본 상한 거부 문구는 30분", "30분" in P.decide_request(None, "Write", subscribers=0, waited=1800).message)
try:
    P.decide_request(None, "Write", subscribers=0, waited=-1); neg = False
except ValueError:
    neg = True
check("waited 음수는 오류", neg)

# ---- check_start: bypass
tmp = tempfile.mkdtemp(prefix="llmhost-s4-")
sand = os.path.join(tmp, "sand"); os.makedirs(sand); open(os.path.join(sand, P.SANDBOX_MARKER), "w").close()
plain = os.path.join(tmp, "plain"); os.makedirs(plain)
S = lambda **k: dict({"cwd": plain}, **k)
check("평범한 spec 통과", P.check_start(S(permission_mode="default", extra_args=["--add-dir", "/x"])) == [] and P.check_start(None) == [] and P.check_start({}) == [])
BYP = [S(permission_mode="bypassPermissions"), S(permission_mode="BypassPermissions"), S(permission_mode="bypass"),
       S(extra_args=["--dangerously-skip-permissions"]), S(extra_args=["--allow-dangerously-skip-permissions"]),
       S(extra_args=["--permission-mode", "bypassPermissions"]), S(extra_args=["--permission-mode=bypassPermissions"]),
       S(extra_args=["--dangerously-skip-permissions=1"]), S(extra_args=["--model", "haiku", "--dangerously-skip-permissions"])]
for s in BYP:
    r = P.check_start(s)
    check(f"bypass 거부 {s.get('permission_mode') or s.get('extra_args')}", len(r) == 1 and "allow_bypass" in r[0], repr(r))
for s in BYP:   # allow_bypass 만으로는 부족: 샌드박스 표시 없는 폴더
    r = P.check_start(dict(s, policy={"allow_bypass": True}))
    check(f"allow_bypass 만으로는 거부 {s.get('permission_mode') or s.get('extra_args')}", len(r) == 1 and P.SANDBOX_MARKER in r[0], repr(r))
for s in BYP:   # 둘 다 있으면 통과
    check(f"allow_bypass + 샌드박스는 통과 {s.get('permission_mode') or s.get('extra_args')}", P.check_start(dict(s, cwd=sand, policy={"allow_bypass": True})) == [])
check("샌드박스 표시만 있고 allow_bypass 없으면 거부", len(P.check_start(dict(BYP[0], cwd=sand))) == 1)
check("cwd 가 없으면 allow_bypass 여도 거부", len(P.check_start({"permission_mode": "bypassPermissions", "policy": {"allow_bypass": True}})) == 1)
check("표시 파일이 폴더이면(파일 아님) 거부", (os.makedirs(os.path.join(plain, P.SANDBOX_MARKER)), len(P.check_start(dict(BYP[0], policy={"allow_bypass": True}))) == 1)[1])
try:
    P.check_start({"policy": {"request_timeout": 0}}); bad = False
except ValueError:
    bad = True
check("check_start 는 잘못된 policy 를 숨기지 않는다", bad)

# ---- max_auto_turns
n = 0; seq = []
for _ in range(5):
    ok, n, why = P.next_auto_turn(None, n); seq.append((ok, n, bool(why)))
check("기본 상한 3: 3번 허용 뒤 거부, 거부 때 count 는 늘지 않는다", seq == [(True, 1, False), (True, 2, False), (True, 3, False), (False, 3, True), (False, 3, True)], repr(seq))
check("사람 메시지 뒤 count=0 이면 다시 허용", P.next_auto_turn(None, 0)[0] is True)
check("max_auto_turns=0 은 자동 턴을 막는다", P.next_auto_turn({"max_auto_turns": 0}, 0)[0] is False)
check("max_auto_turns=5", [P.next_auto_turn({"max_auto_turns": 5}, c)[0] for c in (0, 4, 5, 6)] == [True, True, False, False])
for bad in (-1, 1.0, True, "1"):
    try:
        P.next_auto_turn(None, bad); ok = False
    except ValueError:
        ok = True
    check(f"count 잘못된 값 {bad!r} 거부", ok)

# ---- 모델 입력 문구(§6-3): 모든 문구 덤프를 속성으로 점검 + 사용자 이유 그대로
msgs = dict(P.all_messages())
check("호스트가 낼 수 있는 문구 5종이 모두 덤프된다", set(msgs) == {"user_denied", "user_denied_reason", "timeout", "question_timeout", "session_end"} and set(msgs) == (set(P.MESSAGES)) )
for k in ("user_denied", "user_denied_reason", "timeout"):
    m = msgs[k]
    check(f"{k}: 누가(사용자)·재시도 금지·보고 지시를 담는다", "사용자" in m and "다시 시도" in m and "보고" in m)
check("question_timeout: 답을 추측하지 말 것·보고", "추측" in msgs["question_timeout"] and "보고" in msgs["question_timeout"])
check("session_end: 실행되지 않았다고만 말한다(재시도 금지·보고 지시 없음 — 사용자 거부가 아니다)", "실행되지 않았다" in msgs["session_end"] and "사용자가 거부" not in msgs["session_end"])
for k, m in msgs.items():
    check(f"{k}: 성공·완료를 암시하는 낱말이 없다", not any(w in m for w in ("성공", "완료했", "허용했")))
    check(f"{k}: 치환되지 않은 자리표시자({{…}})가 없다", "{" not in m and "}" not in m)
reason = "그 파일은 건드리지 마.\n대신 /tmp 에 써 {x}"
rm = P.deny_message("user_denied", user_reason=reason)
check("사용자 이유는 그대로(줄바꿈·중괄호 포함) 전달", reason in rm and "다시 시도" in rm)
check("공백뿐인 이유는 이유 없는 문구", P.deny_message("user_denied", user_reason="  \n ") == P.MESSAGES["user_denied"] and P.deny_message("user_denied", user_reason=None) == P.MESSAGES["user_denied"])
check("타임아웃 분 표시: 90초=1.5분, 600초=10분", "1.5분" in P.deny_message("timeout", request_timeout=90) and "10분" in P.deny_message("timeout", request_timeout=600))
try:
    P.deny_message("nope"); bad = False
except ValueError:
    bad = True
check("모르는 거부 종류는 오류", bad)
# 문구가 바뀌면 이 시험이 잡도록 길이 상한(과장·장황 방지)
check("문구는 모두 400자 이하(짧게)", all(len(m) <= 400 for m in msgs.values()), repr({k: len(v) for k, v in msgs.items()}))

shutil.rmtree(tmp, ignore_errors=True)
finish("llm-host policy")
