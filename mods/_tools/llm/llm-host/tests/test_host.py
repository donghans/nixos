#!/usr/bin/env python3
"""llm-host host.py(S5) 시험: 동시 상한·레지스트리·종료 4단계·고아 탐지·세션 격리. 비용 0: 가짜 백엔드만 띄운다.
시험이 죽이는 것은 시험이 직접 띄운 자식(호스트가 띄운 가짜, 시험이 띄운 호스트 흉내 프로세스)뿐이다. 이름·패턴 종료는 쓰지 않는다."""
import asyncio, json, os, shutil, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
import host as H
from claude_adapter import ClaudeAdapter

FAKE = os.path.join(ROOT, "fake_claude.py")
TMP = tempfile.mkdtemp(prefix="llmhost-s5-")
_n = [0]


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def scenario(steps):
    _n[0] += 1
    p = os.path.join(TMP, f"sc{_n[0]}.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(dump(s) + "\n")
    return p


def spec_for(steps, **kw):
    d = {"exe": [sys.executable, FAKE, scenario(steps), "--timeout", "8"], "cwd": TMP, "persist": False}
    d.update(kw)
    return d


def new_host(max_sessions=4, reg=None, **kw):
    return H.SessionHost(lambda hs: ClaudeAdapter(host_session=hs), max_sessions=max_sessions,
                         registry_dir=reg or os.path.join(TMP, f"reg{_n[0]}"), **kw)


def run(coro, t=120):
    return asyncio.run(asyncio.wait_for(coro, t))


def procs_with_marker(host_id):
    """/proc 환경에서 LLM_HOST_ID=<host_id> 표지를 가진(좀비 아닌) 프로세스 pid 들 = 그 호스트의 자식(과 그 후손)."""
    out = []
    needle = f"LLM_HOST_ID={host_id}".encode()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/environ", "rb") as f:
                hit = needle in f.read().split(b"\0")
        except OSError:
            continue
        if hit and H.proc_starttime(int(d)) is not None:
            out.append(int(d))
    return out


IDLE = []                                                   # 시나리오 없음 = 유휴(입력 EOF 에서 종료 코드 0)
STUBBORN = [{"ignore_sigterm": True}, {"emit": [{"type": "brand_new"}]}, {"sleep": 120}]   # SIGTERM 도 EOF 도 무시

# ---------------------------------------------------------------- 1. 상한·시작·종료·레지스트리
async def t_basic():
    h = new_host(max_sessions=2)
    a = await h.start_session(spec_for(IDLE, label="a"))
    b = await h.start_session(spec_for(IDLE, label="b"))
    reg_live = {(r["pid"], r["host_session"]) for r in h.registry.entries()}
    try:
        await h.start_session(spec_for(IDLE)); full = False
    except H.HostFull:
        full = True
    active_before = h.active
    await h.close_session(a.host_session, grace=5)
    c = await h.start_session(spec_for(IDLE))                # 하나 끝나면 자리가 난다
    await h.close_all(grace=5)
    try:
        await h.start_session(spec_for(IDLE)); closed_refuse = False
    except H.HostClosed:
        closed_refuse = True
    return h, a, b, c, reg_live, full, active_before, closed_refuse
h, a, b, c, reg_live, full, active_before, closed_refuse = run(t_basic())
check("동시 상한: 2개 뒤 세 번째는 HostFull, 하나 끝나면 다시 시작 가능", full and active_before == 2 and c.end_reason == "closed")
async def t_refuse():
    h = new_host(max_sessions=2)
    got = {}
    for name, sp in (("mode", spec_for(IDLE, permission_mode="bypassPermissions")),
                     ("flag", spec_for(IDLE, extra_args=["--dangerously-skip-permissions"]))):
        try:
            await h.start_session(sp); got[name] = None
        except H.StartRefused as e:
            got[name] = e.reasons
    state = (h.active, h.registry.entries(), len(h._sessions))
    ok = await h.start_session(spec_for(IDLE, permission_mode="default"))      # 평범한 spec 은 통과
    await h.close_all(grace=5)
    return got, state, ok
got, state, okses = run(t_refuse())
check("시작 정책: skip-permissions 계열은 StartRefused 로 거부되고 아무 상태도 남지 않는다", all(got.get(k) for k in ("mode", "flag")) and state == (0, [], 0), f"{got} {state}")
check("시작 정책: permission_mode=default 는 통과", okses.pid is not None)
check("시작한 세션은 레지스트리에 (pid, host_session) 으로 올라간다", reg_live == {(a.pid, a.host_session), (b.pid, b.host_session)})
check("close_all 뒤 레지스트리는 비고 자식 표지 프로세스 0개, 이후 시작은 HostClosed", h.registry.entries() == [] and procs_with_marker(h.host_id) == [] and closed_refuse)
check("유휴 가짜는 stdin 닫기만으로 종료 코드 0(eof 아닌 closed: 우리가 닫음)", a.exit_code == 0 and a.end_reason == "closed")

async def t_ids():
    h = new_host(max_sessions=3)
    s1 = await h.start_session(spec_for(IDLE, resume="BK-1"))
    try:
        await h.start_session(spec_for(IDLE, resume="BK-1")); dup = False
    except H.DuplicateResume:
        dup = True
    other = await h.start_session(spec_for(IDLE, resume="BK-2"), host_session="named")
    try:
        await h.start_session(spec_for(IDLE), host_session="named"); dupname = False
    except H.DuplicateSession:
        dupname = True
    n_active = h.active
    await h.close_session(s1.host_session, grace=5)
    again = await h.start_session(spec_for(IDLE, resume="BK-1"))   # 끝나면 같은 resume id 를 다시 쓸 수 있다
    env_marker = None
    for _ in range(100):                                     # fork 직후 exec 전에는 부모 환경 사본이라 표지가 안 보인다 → 잠깐 기다린다
        env_marker = H._env_has_marker(again.pid, h.host_id)
        if env_marker:
            break
        await asyncio.sleep(0.05)
    await h.close_all(grace=5)
    return dup, dupname, n_active, again, env_marker
dup, dupname, n_active, again, env_marker = run(t_ids())
check("같은 resume id 동시 사용 거부, 끝난 뒤에는 허용", dup and again.state == "closed" and again.end_reason == "closed")
check("host_session 이름 중복 거부, 거부된 시도는 상한 자리를 잡지 않는다", dupname and n_active == 2)
check("자식 환경에 LLM_HOST_ID 표지가 들어간다", env_marker is True)

async def t_fail():
    h = new_host(max_sessions=1)
    s = await h.start_session({"exe": ["/nonexistent/claude-xyz"], "cwd": TMP})
    ok = await h.start_session(spec_for(IDLE))              # 기동 실패는 자리를 차지하지 않는다
    await h.close_all(grace=5)
    return h, s, ok
h, s, ok = run(t_fail())
check("백엔드 기동 실패: crashed, 레지스트리 미등록, 상한 자리 반환", s.end_reason == "crashed" and ok.end_reason == "closed" and h.registry.entries() == [])

# ---------------------------------------------------------------- 2. 100회 시작·종료 후 자식 0개
async def t_100():
    h = new_host(max_sessions=4)
    started = 0
    t0 = time.monotonic()
    for _ in range(25):                                     # 4개씩 병렬 x 25 = 100
        ss = await asyncio.gather(*(h.start_session(spec_for(IDLE)) for _ in range(4)))
        started += len(ss)
        for s in ss[:2]:
            await s.send("hi")                              # 입력이 있어도 종료는 같다(가짜는 입력을 버린다)
        await asyncio.gather(*(s.close(5) for s in ss))
        await asyncio.sleep(0)
        for s in ss:
            h.release(s.host_session)
    await asyncio.sleep(0.2)
    return h, started, time.monotonic() - t0
h, started, dt = run(t_100(), 300)
left = procs_with_marker(h.host_id)
check(f"100회 시작·종료({dt:.0f}초) 뒤 남은 자식 0개, 레지스트리 빔, 호스트 표 빔", started == 100 and left == [] and h.registry.entries() == [] and h.sessions == {})

# ---------------------------------------------------------------- 3. SIGTERM·EOF 를 무시하는 가짜: 4단계 끝의 SIGKILL
async def t_kill_path():
    h = new_host(term_wait=0.5, keep_history=True)
    s = await h.start_session(spec_for(STUBBORN))
    await send_wait(s)
    gpid = s.pid
    t0 = time.monotonic()
    await h.close_session(s.host_session, grace=0.5)
    dt = time.monotonic() - t0
    return h, s, gpid, dt
async def send_wait(s):
    await s.collect_until(lambda e: e.kind == "raw", 8)      # 가짜가 SIGTERM 무시를 설정한 뒤에야 낸다
h, s, gpid, dt = run(t_kill_path())
texts = [e.text for e in s.history if e.kind == "notice"]
check("종료 4단계: grace 뒤 SIGTERM(무시됨) → term_wait 뒤 SIGKILL, 종료 코드 -9", s.exit_code == -9 and s.end_reason == "closed"
      and any("SIGTERM" in t for t in texts) and any("SIGKILL" in t for t in texts))
check(f"종료 시간은 grace+term_wait 근처({dt:.1f}초), 자식·레지스트리 정리됨", 0.9 <= dt < 5 and procs_with_marker(h.host_id) == [] and h.registry.entries() == [])

async def t_kill_all():
    h = new_host(max_sessions=3)
    ss = [await h.start_session(spec_for(STUBBORN)) for _ in range(3)]
    for s in ss:
        await send_wait(s)
    await h.kill_all()
    return h, ss
h, ss = run(t_kill_all())
check("kill_all: 모두 SIGKILL(killed), 자식 0개, 레지스트리 빔", all(s.end_reason == "killed" and s.exit_code == -9 for s in ss)
      and procs_with_marker(h.host_id) == [] and h.registry.entries() == [])

# ---------------------------------------------------------------- 4. 호스트 강제 종료 후 재시작: 고아는 알리되 죽이지 않는다
HOST_SCRIPT = r'''
import asyncio, json, os, sys
sys.path.insert(0, %(root)r)
import host as H
from claude_adapter import ClaudeAdapter
async def main():
    h = H.SessionHost(lambda hs: ClaudeAdapter(host_session=hs), max_sessions=4, registry_dir=%(reg)r)
    pids = []
    for sc in %(scs)r:
        s = await h.start_session({"exe": [sys.executable, %(fake)r, sc, "--timeout", "8"], "cwd": %(tmp)r, "persist": False, "label": "orph"})
        pids.append(s.pid)
    print(json.dumps({"host_id": h.host_id, "pids": pids}), flush=True)
    await asyncio.sleep(3600)
asyncio.run(main())
'''
async def t_orphans():
    reg = os.path.join(TMP, "reg-orph")
    long_sc = scenario([{"sleep": 120}])                       # EOF 도 무시하고 산다(호스트가 죽어도 자식은 산다)
    quick_sc = scenario([{"exit": 0}])                          # 곧 끝난다(이미 죽은 자식)
    code = HOST_SCRIPT % {"root": ROOT, "reg": reg, "scs": [long_sc, long_sc, quick_sc], "fake": FAKE, "tmp": TMP}
    p = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    info = json.loads(p.stdout.readline())
    await asyncio.sleep(0.5)                                    # quick 가 끝나도록
    live_before = [pid for pid in info["pids"] if H.proc_starttime(pid) is not None]
    p.send_signal(signal.SIGKILL)                               # 시험이 직접 띄운 호스트 흉내 프로세스만
    p.wait()
    h2 = new_host(reg=reg)                                      # 같은 레지스트리로 재시작
    h2.registry.add({"pid": info["pids"][2], "starttime": 12345, "host_id": info["host_id"], "host_pid": 1, "host_starttime": 1, "host_session": "stale"})  # 죽은 자식·재사용 pid 흉내
    st0 = H.proc_starttime(info["pids"][0])
    h2.registry.add({"pid": info["pids"][0], "starttime": st0 + 1, "host_id": info["host_id"], "host_pid": 1, "host_starttime": 1, "host_session": "reused"})  # 살아 있는 pid 인데 starttime 이 다름(pid 재사용 흉내)
    n_entries = len(h2.registry.entries())
    orphans = h2.scan_orphans()
    still = [o.pid for o in orphans if H.proc_starttime(o.pid) is not None]
    orphans_again = h2.scan_orphans()                           # 두 번 불러도 같고, 죽이지 않았다
    # 정리는 시험이 직접 띄운 자식에게만
    for pid in info["pids"]:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while any(H.proc_starttime(pid) is not None for pid in info["pids"]) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    after = h2.scan_orphans()
    return info, live_before, n_entries, orphans, still, orphans_again, after, h2
info, live_before, n_entries, orphans, still, orphans_again, after, h2 = run(t_orphans())
check("호스트 강제 종료 뒤 레지스트리에 살아 있는 자식 2개와 가짜로 넣은 죽은 항목이 남는다(끝난 자식 quick 은 호스트가 살아 있을 때 스스로 지웠다)", n_entries == 4 and len(live_before) == 2)
check("재시작 호스트: 살아 있는 두 자식만 고아로 보고(죽은 자식은 제외), 표지 확인됨", sorted(o.pid for o in orphans) == sorted(live_before)
      and all(o.marker_verified is True and o.host_id == info["host_id"] for o in orphans))
check("고아 탐지는 죽이지 않는다: 보고 뒤에도 두 자식 모두 살아 있고 두 번째 탐지도 같다", sorted(still) == sorted(live_before) and len(orphans_again) == 2)
check("고아 notice 에 procctl 안내가 있고 호스트 notice 로 쌓인다", len(h2.notices) >= 2 and all(n.kind == "notice" and "procctl" in n.text and n.host_session == "host" for n in h2.notices))
check("자식이 모두 죽으면 다음 탐지는 고아 0·레지스트리 비움", after == [] and h2.registry.entries() == [])

async def t_orphan_edges():
    reg = os.path.join(TMP, "reg-edge")
    hA = new_host(reg=reg)
    sA = await hA.start_session(spec_for(IDLE))
    hB = new_host(reg=reg)                                      # 같은 레지스트리의 살아 있는 형제 호스트
    sib = hB.scan_orphans()
    # pid 재사용 흉내: 살아 있는 pid 인데 starttime 이 다른 항목, 환경 표지가 다른 항목, 띄운 호스트가 죽은(pid 없음) 항목
    me = os.getpid(); st = H.proc_starttime(me)
    hB.registry.add({"pid": me, "starttime": st + 1, "host_id": "deadhost", "host_pid": 1, "host_starttime": 1, "host_session": "x"})
    hB.registry.add({"pid": me, "starttime": st, "host_id": "deadbeef", "host_pid": 2 ** 22 - 3, "host_starttime": 1, "host_session": "y"})
    edge = hB.scan_orphans()
    left = [(r["pid"], r["host_session"]) for r in hB.registry.entries()]
    await hA.close_all(grace=5)
    return sib, edge, left, sA
sib, edge, left, sA = run(t_orphan_edges())
check("살아 있는 형제 호스트의 자식은 고아가 아니다", sib == [])
check("starttime 이 다른 재사용 pid·환경 표지가 다른 pid 는 고아가 아니고 레지스트리에서 정리된다", edge == [] and (sA.pid, sA.host_session) in left or left == [])

# 잘린 줄이 있어도 읽힌다(쓰는 도중 호스트가 죽은 경우)
async def t_truncated():
    reg = os.path.join(TMP, "reg-trunc")
    h = new_host(reg=reg)
    s = await h.start_session(spec_for(IDLE))
    with open(h.registry.path, "a") as f:
        f.write('{"op":"add","pid":99999999,"starttim')       # 잘린 줄
    n = len(h.registry.entries())
    await h.close_all(grace=5)
    return n, h.registry.entries()
n, rest = run(t_truncated())
check("레지스트리의 잘린 줄은 무시하고 나머지를 읽는다", n == 1 and rest == [])

# ---------------------------------------------------------------- 5. 동시 세션 격리
def turn(tag):
    return [{"expect": {"stdin_type": "user"}},
            {"emit": [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"reply-{tag}"}]}, "session_id": f"bk-{tag}"},
                      {"type": "result", "subtype": "success", "is_error": False, "result": f"reply-{tag}", "total_cost_usd": 0.001, "num_turns": 1, "session_id": f"bk-{tag}"}]}]

async def t_isolation():
    h = new_host(max_sessions=4, keep_history=True)
    A = await h.start_session(spec_for(turn("A")))
    B = await h.start_session(spec_for(turn("B")))
    C = await h.start_session(spec_for([{"expect": {"stdin_type": "user"}}, {"exit": 3}]))          # 크래시
    D = await h.start_session(spec_for(IDLE))
    await asyncio.gather(A.send("a"), B.send("b"), C.send("c"))
    await asyncio.gather(A.collect_until(lambda e: e.kind == "turn_result", 10), B.collect_until(lambda e: e.kind == "turn_result", 10),
                         C.wait_closed(10))
    d_alive = D.running
    await B.kill()                                           # B 만 강제 종료
    await asyncio.sleep(0.2)
    a_alive, d_alive2 = A.running, D.running
    await D.send("still here")
    await h.close_all(grace=5)
    return h, A, B, C, D, d_alive, a_alive, d_alive2
h, A, B, C, D, d_alive, a_alive, d_alive2 = run(t_isolation())
def texts_of(s):
    return [b.get("text") for e in s.history if e.kind == "message" for b in e.blocks if isinstance(b, dict)] + [e.text for e in s.history if e.kind == "turn_result"]
check("세션마다 자기 응답만 받는다(A 는 reply-A, B 는 reply-B 만)", "reply-A" in texts_of(A) and "reply-B" not in texts_of(A)
      and "reply-B" in texts_of(B) and "reply-A" not in texts_of(B))
check("이벤트의 host_session 이 모두 자기 세션 것이다", all(e.host_session == s.host_session for s in (A, B, C, D) for e in s.history))
check("한 세션의 크래시(C)·강제 종료(B)가 다른 세션(A·D)에 영향이 없다", C.end_reason == "crashed" and C.exit_code == 3
      and B.end_reason == "killed" and d_alive and d_alive2 and A.end_reason in (None, "closed") or (a_alive and d_alive2))
check("격리 시험 뒤 자식 0개·레지스트리 빔", procs_with_marker(h.host_id) == [] and h.registry.entries() == [])

# ---------------------------------------------------------------- 6. 동시 시작의 상한 경쟁
async def t_race():
    h = new_host(max_sessions=3)
    res = await asyncio.gather(*(h.start_session(spec_for(IDLE)) for _ in range(8)), return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    full = [r for r in res if isinstance(r, H.HostFull)]
    await h.close_all(grace=5)
    return h, ok, full
h, ok, full = run(t_race())
check("동시에 8개를 시작해도 상한 3 을 넘지 않는다(3 성공·5 HostFull)", len(ok) == 3 and len(full) == 5 and procs_with_marker(h.host_id) == [])

shutil.rmtree(TMP, ignore_errors=True)
finish("llm-host host")
