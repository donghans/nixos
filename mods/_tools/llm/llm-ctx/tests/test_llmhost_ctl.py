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


def scenario(name, start, end, deny_at=None, extra_sleep=0.0):
    """녹화본 [start, end) 를 시나리오로. deny_at(요청 줄 번호) 가 있으면 그 줄 뒤의 in(응답) 한 줄은 「deny 응답이 왔다」 기대로 바꾼다(문구는 우리 것이라 바이트 비교 불가)."""
    steps = []
    for i, e in enumerate(rows(name)[start:end], start):
        ln = e["line"]
        if e["dir"] == "in":
            if ln.get("type") == "control_response":
                steps.append({"expect": {"control_response": {"behavior": "deny"}}})
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

# ---- 3. 권한 요청 자동 거부(S1: 사용자가 답할 화면이 없다) — 세션은 계속 산다
b = bridge()
b.start(TMP, "haiku", exe=scenario("perm", 54, 103, deny_at=80))
collect(b, lambda e: b.running)
b.send(WRITE_DENY)
evs = collect(b, lambda e: kinds(e, "turn_result"))
pr = kinds(evs, "permission_request")
rs = kinds(evs, "request_resolved")
check("권한 요청이 이벤트로 오고 자동 거부된다(request_resolved deny)", pr and rs and rs[0]["outcome"] == "deny" and rs[0]["req"] == pr[0]["req"], str([e["kind"] for e in evs]))
nt = [e for e in kinds(evs, "notice") if "자동 거부" in e.get("text", "")]
check("자동 거부를 사용자에게 notice(warn)로 알린다", nt and nt[0]["level"] == "warn" and pr[0]["req"] in nt[0]["text"], str(nt))
check("거부 문구는 모델용(재시도 금지·보고)이고 S1 한계를 말한다", "deny" == rs[0]["outcome"] and (rs[0].get("message") or "") != "" and "S1" in (rs[0].get("message") or ""), str(rs[:1]))
check("거부 뒤에도 턴이 끝나고(turn_result) 세션은 살아 있다", kinds(evs, "turn_result") and b.running and b.state == "idle", b.state)
b.shutdown()

# ---- 4. 질문 요청도 자동 거부
b = bridge()
b.start(TMP, "haiku", exe=scenario("main", 73, 103))
collect(b, lambda e: b.running)
b.send(ASK)
evs = collect(b, lambda e: kinds(e, "request_resolved"))
q = kinds(evs, "question_request")
rs = kinds(evs, "request_resolved")
check("질문 요청이 오고 자동 거부된다", q and rs and rs[0]["outcome"] == "deny" and rs[0]["req"] == q[0]["req"], str([e["kind"] for e in evs]))
check("질문 거부 notice 는 '질문' 으로 표시", any("질문" in e.get("text", "") and "자동 거부" in e.get("text", "") for e in kinds(evs, "notice")))
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
