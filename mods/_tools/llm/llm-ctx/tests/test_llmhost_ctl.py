#!/usr/bin/env python3
"""llmhost_ctl(llmui 9 호스트 탭 S1 의 호스트 구동 어댑터) 시험. 비용 0: 실제 claude 를 띄우지 않고 llm-host 의 fake_claude.py(녹화본 시나리오)만 쓴다.
확인하는 것: 세션 시작·텍스트 스트림·결과·비용이 이벤트로 오는가 / 명령이 호출한 스레드를 막지 않는가 / 권한·질문 요청을 자동 거부하는가 /
거부 사유(실행 중·폴더 없음·bypass·세션 없음·빈 지시·claude-run 없음) / 닫기·shutdown 뒤 자식 프로세스가 0개인가.
실제 claude 시험은 llmhost_real.py(비용 있음, run-tests.sh 에 넣지 않는다). 화면 쪽은 test_llmui.py."""
import json, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import llmhost_ctl as hc

HOSTDIR = hc.find_host_dir()
if not HOSTDIR:
    print("llm-host 를 찾지 못해 건너뜀"); sys.exit(0)
FAKE = os.path.join(HOSTDIR, "fake_claude.py")
FX = os.path.join(HOSTDIR, "tests", "fixtures")
TMP = tempfile.mkdtemp(prefix="llmhost-s1-")
HELLO = "Say hello in one short sentence."
ASK = None          # 아래 rows() 정의 뒤에 채운다
WRITE_DENY = None


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def rows(name):
    return [json.loads(l) for l in open(os.path.join(FX, name + ".jsonl"), encoding="utf-8") if l.strip()]


def scenario(name, start, end, deny_at=None, extra_sleep=0.0, resp=None):
    """녹화본 [start, end) 를 시나리오로. in(control_response) 한 줄은 「resp 응답이 왔다」 기대로 바꾼다(기본 {"behavior":"deny"} — 문구는 우리 것이라 바이트 비교 불가).
    in(interrupt control_request) 한 줄은 id 가 우리 것(host-int-N)이라 subtype 만 보는 기대로 바꾼다."""
    steps = []
    for i, e in enumerate(rows(name)[start:end], start):
        ln = e["line"]
        if e["dir"] == "in":
            if ln.get("type") == "control_response":
                steps.append({"expect": {"control_response": resp or {"behavior": "deny"}}})
            elif ln.get("type") == "control_request":
                steps.append({"expect": {"control_request": {"subtype": ln["request"]["subtype"]}}})
            else:
                steps.append({"expect": {"stdin_type": "user", "line": dump(ln)}})
                if extra_sleep:
                    steps.append({"sleep": extra_sleep})
        elif steps and "emit" in steps[-1]:
            steps[-1]["emit"].append(ln)
        else:
            steps.append({"emit": [ln]})
    p = os.path.join(TMP, f"sc{len(os.listdir(TMP))}.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(dump(s) + "\n")
    return [sys.executable, FAKE, p, "--timeout", "8"]


ASK = rows("main")[73]["line"]["message"]["content"]
WRITE_DENY = rows("perm")[54]["line"]["message"]["content"]


def bridge(**kw):
    return hc.HostBridge(log_root=kw.pop("log_root", None), use_launcher=False, **kw)


def collect(b, pred, timeout=8.0):
    got = []
    t0 = time.time()
    while time.time() - t0 < timeout:
        got += b.drain()
        if pred(got):
            return got
        time.sleep(0.02)
    return got + b.drain()


def kinds(evs, k):
    return [e for e in evs if e.get("kind") == k]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---- 1. 사용 가능 여부
ok, why = hc.availability()
check("llm-host 를 찾으면 사용 가능", ok and why == HOSTDIR, why)
_orig = hc.find_host_dir
hc.find_host_dir = lambda: None
ok2, why2 = hc.availability()
check("llm-host 가 없으면 사유와 함께 사용 불가(예외 없음)", not ok2 and "LLMUI_HOST_DIR" in why2, why2)
try:
    hc.HostBridge()
    check("llm-host 가 없으면 HostBridge 를 만들지 못한다", False)
except RuntimeError:
    check("llm-host 가 없으면 HostBridge 를 만들지 못한다", True)
hc.find_host_dir = _orig

# ---- 2. hello: 시작 → 텍스트 스트림 → 결과·비용, 호출은 막지 않는다
b = bridge()
t0 = time.time()
err = b.start(TMP, "haiku", exe=scenario("main", 0, 15, extra_sleep=0.6))
check("start 는 거부 사유 없이 바로 돌아온다", err is None and time.time() - t0 < 0.5, f"{err} {time.time() - t0:.2f}s")
check("start 직후 상태는 starting 또는 idle", b.state in ("starting", "idle"), b.state)
pre = collect(b, lambda e: b.running or kinds(e, "notice"))
t1 = time.time()
err = b.send(HELLO)
check("send 도 막지 않고 돌아온다(가짜 백엔드가 0.6초 쉬어도)", err is None and time.time() - t1 < 0.3, f"{err} {time.time() - t1:.2f}s")
check("send 직후 상태는 busy", b.state == "busy", b.state)
evs = pre + collect(b, lambda e: kinds(e, "turn_result"))
ks = [e["kind"] for e in evs]
check("사용자 지시가 화면용 user_input 으로 먼저 온다", kinds(evs, "user_input") and kinds(evs, "user_input")[0]["text"] == HELLO, str(ks[:5]))
check("session_ready·turn_started·text_delta·turn_result 가 순서대로 온다", all(k in ks for k in ("session_ready", "turn_started", "text_delta", "turn_result")) and ks.index("session_ready") < ks.index("text_delta") < ks.index("turn_result"), str(ks))
txt = "".join(e["text"] for e in kinds(evs, "text_delta"))
tr = kinds(evs, "turn_result")[0]
check("스트림 글이 결과 글과 일치", txt and txt.strip() == (tr.get("text") or "").strip(), f"{txt!r} / {tr.get('text')!r}")
check("결과 ok·비용 기록(누적 = 녹화본 값 0.00420193)", tr["ok"] is True and abs((tr["cost_total"] or 0) - 0.00420193) < 1e-8 and b.cost_total == tr["cost_total"] and b.turns == 1, f"{tr.get('cost_total')} {b.cost_total} {b.turns}")
check("turn_result 뒤 상태는 idle, raw 줄 0", b.state == "idle" and not kinds(evs, "raw"), f"{b.state} raw={len(kinds(evs, 'raw'))}")
pid = b.child_pids()[0]
check("실행 중에는 자식 프로세스가 살아 있다", alive(pid))
b.close()
ended = collect(b, lambda e: kinds(e, "session_ended"))
check("close 하면 session_ended(closed)·running False", kinds(ended, "session_ended") and kinds(ended, "session_ended")[0]["reason"] == "closed" and not b.running and b.state == "closed", str([e["kind"] for e in ended]))
time.sleep(0.2)
check("닫은 뒤 자식 프로세스 0개", not alive(pid))
b.shutdown()

# ---- 3. 권한 요청 — 대기 표에 두고 사람이 답한다(S2). 자동 거부하지 않는다
ALLOW_PROMPT = rows("perm")[0]["line"]["message"]["content"]
ALLOW_RESP = rows("perm")[24]["line"]["response"]["response"]          # {"behavior":"allow","updatedInput":{원래 input}}
QUESTION_RESP = rows("main")[103]["line"]["response"]["response"]      # {"behavior":"allow","updatedInput":{questions, answers}}
b = bridge()
b.start(TMP, "haiku", exe=scenario("perm", 0, 54, resp=ALLOW_RESP))
collect(b, lambda e: b.running)
b.send(ALLOW_PROMPT)
evs = collect(b, lambda e: kinds(e, "permission_request"))
pr = kinds(evs, "permission_request")
time.sleep(0.3)
pend = b.pending_requests()
check("권한 요청이 오면 대기 표에 남고 자동 거부되지 않는다(0.3초 뒤에도 미해결)", pr and len(pend) == 1 and pend[0]["req"] == pr[0]["req"] and pend[0]["kind"] == "permission" and pend[0]["tool"] == "Write" and not kinds(b.drain(), "request_resolved"), str(pend))
check("대기 중 상태는 waiting 이고 남은 시간은 상한(1800초) 이하", b.state == "waiting" and 0 < pend[0]["left"] <= 1800 and pend[0]["input"], f"{b.state} {pend[0]['left']}")
check("허용 → 호스트가 allow+updatedInput(원래 input)을 받는다(가짜 백엔드가 바이트 대신 부분집합으로 검사)", b.allow(pr[0]["req"]) is None)
evs = collect(b, lambda e: kinds(e, "turn_result"))
rs = kinds(evs, "request_resolved")
check("허용 경로: request_resolved(allow, user)·대기 표 비워짐·턴 정상 종료(백엔드 기대 불일치 없음)", rs and rs[0]["outcome"] == "allow" and rs[0]["by"] == "user" and b.pending_requests() == [] and kinds(evs, "turn_result") and kinds(evs, "turn_result")[0]["ok"] and b.state == "idle", f"{rs} {b.state}")
check("허용 뒤 같은 요청에 다시 답하면 거부 사유 문자열(이중 응답 방지)", "이미 처리" in (b.allow(pr[0]["req"]) or ""))
b.shutdown()

b = bridge()
b.start(TMP, "haiku", exe=scenario("perm", 54, 103))
collect(b, lambda e: b.running)
b.send(WRITE_DENY)
evs = collect(b, lambda e: kinds(e, "permission_request"))
pr = kinds(evs, "permission_request")
check("거부 → deny+message 가 호스트에 간다", b.deny(pr[0]["req"], "이 폴더 밖은 안 된다") is None)
evs = collect(b, lambda e: kinds(e, "turn_result"))
rs = kinds(evs, "request_resolved")
check("거부 경로: request_resolved(deny, user)·사용자 이유가 모델 문구에 그대로 들어간다·세션 유지", rs and rs[0]["outcome"] == "deny" and rs[0]["by"] == "user" and "이 폴더 밖은 안 된다" in (rs[0].get("message") or "") and kinds(evs, "turn_result") and b.running and b.state == "idle", str(rs[:1]))
check("거부 문구에는 S1 한계 같은 낡은 말이 없다", "S1" not in (rs[0].get("message") or ""))
b.shutdown()

# 시간 초과: 시계를 주입해 30분을 건너뛴다. 정책 판정(decide_request)이 deny 이면 어댑터가 자동 거부하고 notice 로 알린다
T = [1000.0]
b = bridge(clock=lambda: T[0], poll=0.02)
b.start(TMP, "haiku", exe=scenario("perm", 54, 103))
collect(b, lambda e: b.running)
b.send(WRITE_DENY)
evs = collect(b, lambda e: kinds(e, "permission_request"))
pr = kinds(evs, "permission_request")
T[0] += 1799.0
time.sleep(0.2)
check("상한 1초 전(1799초)에는 아직 대기 중이고 남은 시간이 1초 안팎", len(b.pending_requests()) == 1 and 0 <= b.pending_requests()[0]["left"] <= 1.5, str(b.pending_requests()))
T[0] += 2.0
evs = collect(b, lambda e: kinds(e, "turn_result"))
rs = kinds(evs, "request_resolved")
check("시간 초과 경로: 1801초 뒤 자동 거부(request_resolved deny)·대기 표 비워짐·턴 종료(백엔드는 deny 응답을 받았다)", rs and rs[0]["outcome"] == "deny" and not b.pending_requests() and kinds(evs, "turn_result"), str([e["kind"] for e in evs]))
check("시간 초과 문구는 모델용(30분·사용자 부재·보고)", "30분" in (rs[0].get("message") or "") and "보고" in (rs[0].get("message") or ""), str(rs[:1]))
nt = [e for e in kinds(evs, "notice") if "자동 거부" in e.get("text", "")]
check("자동 거부를 사용자에게 notice(warn)로 알린다", nt and nt[0]["level"] == "warn" and pr[0]["req"] in nt[0]["text"], str(nt))
b.shutdown()

# ---- 4. 질문(AskUserQuestion): 선택지를 보고 answers 로 답한다. 비어 있는 답은 보내지 않는다
b = bridge()
b.start(TMP, "haiku", exe=scenario("main", 73, 121, resp=QUESTION_RESP))
collect(b, lambda e: b.running)
b.send(ASK)
evs = collect(b, lambda e: kinds(e, "question_request"))
q = kinds(evs, "question_request")
time.sleep(0.2)
pend = b.pending_requests()
check("질문 요청이 대기 표에 질문 목록과 함께 남는다(자동 거부 없음)", q and len(pend) == 1 and pend[0]["kind"] == "question" and pend[0]["questions"][0]["options"][0]["label"] == "빨간색", str(pend))
check("빈 답은 보내지 않는다", "비어" in (b.answer_question(q[0]["req"], {}) or "") and len(b.pending_requests()) == 1)
qtext = q[0]["questions"][0]["question"]
check("답하기 → updatedInput.answers 가 호스트에 간다", b.answer_question(q[0]["req"], {qtext: "빨간색"}) is None)
evs = collect(b, lambda e: kinds(e, "turn_result"))
rs = kinds(evs, "request_resolved")
check("질문 답 경로: request_resolved(answered, user)·턴 정상 종료(백엔드가 answers 를 확인했다)", rs and rs[0]["outcome"] == "answered" and rs[0]["by"] == "user" and kinds(evs, "turn_result") and kinds(evs, "turn_result")[0]["ok"] and not b.pending_requests(), f"{rs} {[e['kind'] for e in evs]}")
b.shutdown()

# ---- 4-2. 중단: 진행 중인 턴만 멈추고 세션은 산다 — 다음 지시가 정상 처리된다
COUNT = rows("main")[121]["line"]["message"]["content"]
b = bridge()
b.start(TMP, "haiku", exe=scenario("main", 121, 163))
collect(b, lambda e: b.running)
check("턴이 없을 때 interrupt 는 거부 사유 문자열", "진행 중인 턴이 없다" in (b.interrupt() or ""))
b.send(COUNT)
collect(b, lambda e: kinds(e, "text_delta"))
check("진행 중에는 interrupt 가 받아들여진다", b.interrupt() is None)
evs = collect(b, lambda e: kinds(e, "turn_result"))
tr = kinds(evs, "turn_result")
check("중단 경로: 턴이 결과로 끝나고(ok 아님 — error_during_execution) 세션은 살아 있다", tr and tr[0]["ok"] is False and b.running and b.state == "idle", f"{tr[:1]} {b.state}")
b.send("Reply with the single word: done.")
evs = collect(b, lambda e: kinds(e, "turn_result"))
check("중단 뒤 다음 지시가 정상 처리된다(ok)", kinds(evs, "turn_result") and kinds(evs, "turn_result")[0]["ok"] is True and b.state == "idle", str([e["kind"] for e in evs]))
b.shutdown()

# ---- 4-3. 요청 응답 중 세션이 끝나면 대기 표가 비워진다
b = bridge()
b.start(TMP, "haiku", exe=scenario("perm", 54, 103))
collect(b, lambda e: b.running)
b.send(WRITE_DENY)
collect(b, lambda e: kinds(e, "permission_request"))
check("(준비) 요청 대기 중", len(b.pending_requests()) == 1)
b.close()
collect(b, lambda e: kinds(e, "session_ended"))
check("세션이 끝나면 대기 표가 비고, 이후 응답은 거부 사유 문자열", b.pending_requests() == [] and (b.allow("x") or "") != "", str(b.pending_requests()))
b.shutdown()

# ---- 5. 거부 사유(예외가 아니라 문자열 — 화면이 flash 로 보여 준다)
b = bridge()
check("세션 없이 send → 안내", "세션이 없다" in (b.send("hi") or ""))
check("빈 지시 거부", "빈 지시" in (b.send("   ") or ""))
check("없는 폴더 거부", "폴더가 없다" in (b.start(os.path.join(TMP, "nope"), "haiku") or ""))
check("bypass 모드 시작 거부(소비자 책임: check_start)", "시작하지 않음" in (b.start(TMP, "haiku", permission_mode="bypassPermissions") or ""))
check("거부된 시작은 상태를 바꾸지 않는다", b.state == "none", b.state)
b.start(TMP, "haiku", exe=scenario("main", 0, 15))
collect(b, lambda e: b.running)
check("실행 중 두 번째 시작 거부", "이미 세션이 실행 중" in (b.start(TMP, "haiku") or ""))
b.shutdown()

# ---- 6. claude-run 을 못 찾으면 훅 없이 시작하지 않는다(launcher 의 거부가 notice 로)
saved = {k: os.environ.get(k) for k in ("PATH", "HOME", "CLAUDE_RUN_BIN")}
os.environ.update(PATH="/nonexistent-bin", HOME=os.path.join(TMP, "nohome"))
os.environ.pop("CLAUDE_RUN_BIN", None)
try:
    b = hc.HostBridge(log_root=None, use_launcher=True)
    err = b.start(TMP, "haiku")
    evs = collect(b, lambda e: kinds(e, "notice"), timeout=4)
    n = kinds(evs, "notice")
    check("claude-run 이 없으면 세션을 시작하지 않고 error notice", err is None and n and n[0]["level"] == "error" and "시작하지 못함" in n[0]["text"] and b.state == "none" and not b.running, f"{err} {n} {b.state}")
    b.shutdown()
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# ---- 7. shutdown 은 실행 중 세션도 정리한다(앱 종료)
b = bridge()
b.start(TMP, "haiku", exe=scenario("main", 0, 15))
collect(b, lambda e: b.running)
b.send(HELLO)
pid = None
collect(b, lambda e: kinds(e, "session_ready"))
pid = b.child_pids()[0]
b.shutdown()
time.sleep(0.2)
check("shutdown 뒤 자식 프로세스 0개", not alive(pid))

# ---- 8. 이벤트 로그: log_root 를 주면 세션 로그가 0600 으로 남고 text_delta 는 제외
lr = os.path.join(TMP, "logs")
b = bridge(log_root=lr)
b.start(TMP, "haiku", exe=scenario("main", 0, 15))
collect(b, lambda e: b.running)
b.send(HELLO)
collect(b, lambda e: kinds(e, "turn_result"))
b.shutdown()
logs = [os.path.join(dp, f) for dp, _, fs in os.walk(lr) for f in fs]
check("log_root 아래 events.jsonl 이 생기고 0600", len(logs) == 1 and (os.stat(logs[0]).st_mode & 0o777) == 0o600, str(logs))
body = open(logs[0]).read() if logs else ""
check("로그에 turn_result 줄이 있고 text_delta 줄은 없다(머리줄의 제외 목록 글자는 제외하고 kind 로 본다)", '"kind":"turn_result"' in body and '"kind":"text_delta"' not in body)

shutil.rmtree(TMP, ignore_errors=True)
finish("llmhost_ctl")
