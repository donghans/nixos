#!/usr/bin/env python3
"""실제 claude 통합 시험 + 프로토콜 카나리아 (계획서 llm-trust/11 §10-2, 단계 S7). **비용이 든다**(항목당 약 $0.01~0.03, haiku) — run-tests.sh 에 넣지 않는다.
사용: python3 -I integration_real.py --out <새 폴더> [--items 1,2,4 | canary | all] [--claude <실행 파일>]
  - 항목: 1 hello·비용 누적 / 2 권한 허용·거부 / 3 AskUserQuestion / 4 중단 뒤 이어 보내기 / 5 서브에이전트 / 6 동시 4세션·메모리·자식 0개 / 7 resume / 8 호스트 강제 종료 후 자식
  - canary = 1·2·4 (Claude Code 를 갱신할 때 사용자가 부른다. nixup 에 걸지 않는다).
  - 조건: --model haiku, 기본 --no-session-persistence(항목 7 만 persistence), 자식 환경은 HOME·PATH·TERM 만, 훅·래퍼 없음, 자기가 띄운 프로세스만 종료.
  - 판정 함수(analyze_*)는 이벤트 목록만 보는 순수 함수라 tests/test_integration_real.py 가 돈 없이 시험한다(변이 점검 포함).
결과: <out>/results.json(항목별 통과·세부), <out>/raw/*.raw.jsonl(원본 줄), <out>/logs/(호스트 이벤트 로그). 이 폴더는 시험 뒤 증거로 ctx 에 올린다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import events as E  # noqa: E402
import policy as P  # noqa: E402
from claude_adapter import ClaudeAdapter  # noqa: E402
from host import SessionHost, HostFull, proc_starttime  # noqa: E402

DEFAULT_CLAUDE = os.path.expanduser("~/.nix-profile/bin/claude")
TURN_TIMEOUT = 120.0


# ====================================================================== 판정(순수 함수: 이벤트 목록 → (통과, 세부))
def kinds(evs, kind):
    return [e for e in evs if e.kind == kind]


def analyze_cost(evs_by_turn: list) -> tuple:
    """항목 1·4 공용: 모든 turn_result 의 cost_delta 합 == 마지막 cost_total."""
    trs = [e for evs in evs_by_turn for e in kinds(evs, "turn_result")]
    if not trs:
        return False, {"why": "turn_result 없음"}
    last = trs[-1].cost_total
    s = sum(t.cost_delta or 0.0 for t in trs)
    ok = last is not None and abs(s - last) < 1e-9 and all(t.cost_delta is not None for t in trs)
    return ok, {"turns": len(trs), "delta_sum": s, "last_cost_total": last, "deltas": [t.cost_delta for t in trs]}


def analyze_hello(evs: list) -> tuple:
    ready = kinds(evs, "session_ready")
    tr = kinds(evs, "turn_result")
    text_ok = bool(tr) and tr[-1].ok and bool((tr[-1].text or "").strip())
    d = {"session_ready": len(ready), "backend_session": ready[0].backend_session if ready else None,
         "model": ready[0].model if ready else None, "version": ready[0].backend_version if ready else None,
         "text": tr[-1].text if tr else None, "text_delta_count": len(kinds(evs, "text_delta")),
         "turn_started_sources": [e.source for e in kinds(evs, "turn_started")], "raw": len(kinds(evs, "raw"))}
    return bool(ready) and text_ok and d["raw"] == 0 and bool(d["backend_session"]), d


_DENY_WORDS = re.compile(r"den(y|ied)|declin|refus|not (allowed|permitted)|permission|couldn.?t|could not|unable|can.?t|did not|wasn.?t|not created|no file|거부|못|않", re.I)
_WRITE_TOOLS = ("Write", "Edit", "Bash", "NotebookEdit")


def analyze_permission(evs_allow: list, evs_deny: list, allow_file_exists: bool, deny_file_exists: bool, deny_call: str) -> tuple:
    """허용: 요청 1건 이상 + 파일 생김. 거부: 요청 1건 이상 + 파일 안 생김 + 거부 이후 쓰기 도구를 다시 부르지 않음(우회 없음) + 설명 문장이 있음."""
    req_a = kinds(evs_allow, "permission_request")
    req_d = kinds(evs_deny, "permission_request")
    after = []
    seen = False
    for e in evs_deny:
        if e.kind == "tool_call" and e.call == deny_call:
            seen = True
            continue
        if seen and e.kind == "tool_call" and e.name in _WRITE_TOOLS:
            after.append(e.name)
    tr = kinds(evs_deny, "turn_result")
    text = (tr[-1].text if tr else "") or ""
    d = {"allow_requests": [(r.tool, r.run) for r in req_a], "allow_file": allow_file_exists,
         "deny_requests": [(r.tool, r.run) for r in req_d], "deny_file": deny_file_exists, "bypass_calls_after_deny": after,
         "deny_text": text, "deny_text_explains(heuristic)": bool(_DENY_WORDS.search(text)),
         "permission_denials": tr[-1].permission_denials if tr else None}
    ok = bool(req_a) and allow_file_exists and bool(req_d) and not deny_file_exists and not after and bool(text.strip()) and d["deny_text_explains(heuristic)"]
    return ok, d


def analyze_question(evs: list, expect_label: str) -> tuple:
    qs = kinds(evs, "question_request")
    tr = kinds(evs, "turn_result")
    text = (tr[-1].text if tr else "") or ""
    d = {"questions": len(qs), "answer": expect_label, "text": text}
    return bool(qs) and expect_label.lower() in text.lower() and bool(tr) and tr[-1].ok, d


def analyze_interrupt(evs_cut: list, evs_next: list, deltas_before_interrupt: int, cost_before: float, expect_word: str = "done") -> tuple:
    """중단: 첫 턴이 ok=False 로 끝나고, 그 뒤 글자 조각이 더 없고, 다음 메시지가 정상 처리되고 답에 단어가 들어 있다. 중단된 턴의 비용 차이를 기록."""
    trs = kinds(evs_cut, "turn_result")
    cut_tr = trs[-1] if trs else None
    idx = evs_cut.index(cut_tr) if cut_tr else len(evs_cut)
    deltas_after_result = len([e for e in evs_cut[idx:] if e.kind == "text_delta"]) + len([e for e in evs_next if e.kind == "text_delta" and False])
    nxt = kinds(evs_next, "turn_result")
    d = {"cut_turn_ok": cut_tr.ok if cut_tr else None, "cut_subtype": cut_tr.subtype if cut_tr else None,
         "deltas_before_interrupt": deltas_before_interrupt, "deltas_after_turn_result": deltas_after_result,
         "cut_cost_delta": cut_tr.cost_delta if cut_tr else None, "next_text": nxt[-1].text if nxt else None,
         "next_ok": nxt[-1].ok if nxt else None}
    ok = (cut_tr is not None and not cut_tr.ok and deltas_after_result == 0 and bool(nxt) and nxt[-1].ok
          and expect_word in (nxt[-1].text or "").lower())
    return ok, d


def analyze_subagent(evs: list, forwarded_expected: bool) -> tuple:
    """서브에이전트: 서브 이벤트(run 있음)·task 이벤트·서브의 권한 요청에 run. 전달 옵션이면 run 있는 assistant message 가 있어야 한다."""
    sub = [e for e in evs if e.run]
    sub_kinds: dict = {}
    for e in sub:
        sub_kinds[e.kind] = sub_kinds.get(e.kind, 0) + 1
    st = [e.state for e in kinds(evs, "subtask")]
    reqs = [(r.tool, r.run) for r in kinds(evs, "permission_request")]
    msgs = [e for e in kinds(evs, "message") if e.run and e.role == "assistant"]
    agent_calls = [e for e in kinds(evs, "tool_call") if e.name in ("Agent", "Task") and not e.run]
    d = {"agent_calls": [(c.name, c.call) for c in agent_calls], "events_with_run": len(sub), "kinds_with_run": sub_kinds,
         "subtask_states": st, "permission_requests": reqs, "sub_assistant_messages": len(msgs),
         "sub_assistant_texts": [b.get("text", "")[:80] for m in msgs for b in m.blocks if b.get("type") == "text"],
         "sub_assistant_block_types": [[b.get("type") for b in m.blocks] for m in msgs],
         "run_equals_agent_call": bool(agent_calls) and any(e.run == agent_calls[0].call for e in sub),
         "raw": len(kinds(evs, "raw"))}
    ok = bool(agent_calls) and bool(st) and d["run_equals_agent_call"] and d["raw"] == 0
    if forwarded_expected:
        ok = ok and bool(d["sub_assistant_texts"])
    return ok, d


def analyze_resume(first: dict, second: dict, text2: str, word: str) -> tuple:
    d = dict(first=first, second=second, text2=text2)
    # 재개한 프로세스의 total 은 이전 실행분을 포함한 누적이라(S7) 첫 턴 cost_delta 는 null 이어야 한다
    ok = (word.lower() in (text2 or "").lower() and bool(first.get("id")) and first.get("id") == second.get("id")
          and second.get("cost_delta") is None and (second.get("cost_total") or 0) > (first.get("cost_total") or 0))
    return ok, d


# ====================================================================== 프로세스·메모리 도우미(/proc)
def _read(path: str) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def pgid_members(pgid: int) -> list:
    """프로세스 그룹 id 가 pgid 인 pid 들(/proc 스캔, 읽기만)."""
    out = []
    for n in os.listdir("/proc"):
        if not n.isdigit():
            continue
        st = _read(f"/proc/{n}/stat")
        if not st:
            continue
        rest = st[st.rfind(")") + 2:].split()
        if len(rest) > 2 and int(rest[2]) == pgid:
            out.append(int(n))
    return out


def status_kb(pid: int, key: str) -> int:
    m = re.search(rf"^{key}:\s+(\d+)\s*kB", _read(f"/proc/{pid}/status"), re.M)
    return int(m.group(1)) if m else 0


def group_mem(pgid: int) -> dict:
    pids = pgid_members(pgid)
    return {"procs": len(pids), "rss_kb": sum(status_kb(p, "VmRSS") for p in pids), "hwm_kb": sum(status_kb(p, "VmHWM") for p in pids),
            "swap_kb": sum(status_kb(p, "VmSwap") for p in pids), "main_rss_kb": status_kb(pgid, "VmRSS")}


def env_marked(host_id: str) -> list:
    """환경에 LLM_HOST_ID=<host_id> 가 있는 살아 있는 프로세스(같은 사용자 것만 읽힌다)."""
    needle = f"LLM_HOST_ID={host_id}".encode()
    out = []
    for n in os.listdir("/proc"):
        if n.isdigit():
            try:
                with open(f"/proc/{n}/environ", "rb") as f:
                    if needle in f.read().split(b"\0"):
                        out.append(int(n))
            except OSError:
                pass
    return out


# ====================================================================== 세션 실행 도우미
class Ctx:
    def __init__(self, out: str, claude: str):
        self.out = out
        self.claude = claude
        self.results: dict = {}

    def host(self, max_sessions: int = 4, tag: str = "") -> SessionHost:
        return SessionHost(lambda hs: ClaudeAdapter(hs), max_sessions=max_sessions, registry_dir=os.path.join(self.out, "registry" + tag),
                           log_root=os.path.join(self.out, "logs" + tag), raw_dir=os.path.join(self.out, "raw" + tag), retention_days=None,
                           term_wait=3.0)

    def spec(self, name: str, **kw) -> dict:
        cwd = os.path.join(self.out, "proj", name)
        os.makedirs(cwd, exist_ok=True)
        s = {"exe": self.claude, "model": "haiku", "persist": False, "cwd": cwd, "max_budget_usd": 0.06, "label": f"s7-{name}"}
        s.update(kw)
        return s


async def turn(s, text: str, decide=None, timeout: float = TURN_TIMEOUT, on_event=None) -> list:
    """text 를 보내고 turn_result 까지 읽은 이벤트들. 요청이 오면 decide(ev) → ('allow'|'deny', 메시지) 또는 ('answer', {질문: 답})."""
    await s.send(text)
    got: list = []
    end = time.monotonic() + timeout
    while True:
        ev = await s.next_event(max(end - time.monotonic(), 0.01))
        if ev is None:
            raise RuntimeError("세션이 turn_result 전에 끝남")
        got.append(ev)
        if on_event:
            await on_event(ev, got)
        if isinstance(ev, E.PermissionRequest):
            act = decide(ev) if decide else ("deny", "no decider")
            await s.answer_permission(ev.req, act[0] == "allow", act[1] if act[0] == "deny" else None)
        elif isinstance(ev, E.QuestionRequest):
            act = decide(ev)
            await s.answer_question(ev.req, act[1])
        elif isinstance(ev, E.TurnResult):
            return got


async def drain(s, secs: float = 0.5) -> list:
    """turn_result 뒤 따라오는 줄(훅 등)을 잠깐 읽어 낸다."""
    got = []
    while True:
        try:
            ev = await s.next_event(secs)
        except asyncio.TimeoutError:
            return got
        if ev is None:
            return got
        got.append(ev)


def jsonable(o):
    return json.loads(json.dumps(o, default=str))


# ====================================================================== 항목
async def item1(c: Ctx) -> dict:
    async with c.host(tag="-1") as h:
        s = await h.start_session(c.spec("i1"))
        e1 = await turn(s, "Say hello in one short sentence.")
        e2 = await turn(s, "Now say goodbye in one short sentence.")
        ok_h, dh = analyze_hello(e1)
        ok_c, dc = analyze_cost([e1, e2])
        summ = h.cost_summary()
        dc["host_cost_summary"] = summ
        ok_c = ok_c and abs(summ["total"] - (dc["last_cost_total"] or 0)) < 1e-9
        await s.close(5)
        return {"ok": ok_h and ok_c, "hello": dh, "cost": dc, "exit": s.exit_code, "end_reason": s.end_reason}


async def item2(c: Ctx) -> dict:
    async with c.host(tag="-2") as h:
        spec = c.spec("i2")
        s = await h.start_session(spec)
        cwd = spec["cwd"]
        f_allow, f_deny = os.path.join(cwd, "s7-allow.txt"), os.path.join(cwd, "s7-deny.txt")
        ea = await turn(s, "Create a file named s7-allow.txt containing the text ok, using the Write tool, then confirm in one sentence.",
                        decide=lambda ev: ("allow", None))
        deny_msg = P.deny_message("user_denied")
        calls = []

        def dec(ev):
            calls.append(ev.call)
            return ("deny", deny_msg)
        ed = await turn(s, "Create a file named s7-deny.txt containing the text no, using the Write tool, then say in one sentence what happened.", decide=dec)
        ok, d = analyze_permission(ea, ed, os.path.exists(f_allow), os.path.exists(f_deny), calls[0] if calls else "")
        d["deny_message_sent"] = deny_msg
        await s.close(5)
        return {"ok": ok, **d}


async def item3(c: Ctx) -> dict:
    async with c.host(tag="-3") as h:
        s = await h.start_session(c.spec("i3"))
        label = {}

        def dec(ev):
            q = ev.questions[0]
            label["l"] = q["options"][0]["label"]
            return ("answer", {q["question"]: label["l"]})
        ev = await turn(s, "Use the AskUserQuestion tool to ask me whether I prefer red or blue, then tell me my answer in one sentence.", decide=dec)
        ok, d = analyze_question(ev, label.get("l", "?"))
        await s.close(5)
        return {"ok": ok, **d}


async def item4(c: Ctx) -> dict:
    async with c.host(tag="-4") as h:
        s = await h.start_session(c.spec("i4"))
        first = await turn(s, "Say hello in one short sentence.")
        base_cost = kinds(first, "turn_result")[0].cost_total
        await s.send("Count from 1 to 300, one number per line, nothing else.")
        got: list = []
        n = 0
        end = time.monotonic() + 60
        while n < 12 and time.monotonic() < end:
            ev = await s.next_event(max(end - time.monotonic(), 0.01))
            got.append(ev)
            if ev.kind == "text_delta":
                n += 1
        t_int = time.monotonic()
        await s.interrupt()
        end = time.monotonic() + 30
        while True:
            ev = await s.next_event(max(end - time.monotonic(), 0.01))
            got.append(ev)
            if ev.kind == "turn_result":
                break
        t_res = time.monotonic() - t_int
        got += await drain(s, 1.0)
        nxt = await turn(s, "Reply with the single word: done.")
        ok, d = analyze_interrupt(got, nxt, n, base_cost)
        d["interrupt_to_result_s"] = round(t_res, 3)
        ok_c, dc = analyze_cost([first, got, nxt])
        d["cost"] = dc
        await s.close(5)
        return {"ok": ok and ok_c, **d}


async def item5(c: Ctx) -> dict:
    out: dict = {}
    for name, extra, fwd in (("i5fwd", ["--forward-subagent-text"], True), ("i5plain", [], False)):
        async with c.host(tag="-" + name) as h:
            spec = c.spec(name, extra_args=extra)
            s = await h.start_session(spec)
            ev = await turn(s, "Use the Agent tool to launch one subagent whose task is: run the bash command `touch s7-sub.txt` and report what happened. "
                               "After it returns, tell me the result in one sentence.", decide=lambda e: ("allow", None))
            ev += await drain(s, 1.0)
            ok, d = analyze_subagent(ev, fwd)
            d["file_created"] = os.path.exists(os.path.join(spec["cwd"], "s7-sub.txt"))
            d["cost_total"] = kinds(ev, "turn_result")[-1].cost_total
            out[name] = {"ok": ok, **d}
            await s.close(5)
    out["ok"] = out["i5fwd"]["ok"] and out["i5plain"]["ok"]
    return out


async def item6(c: Ctx) -> dict:
    async with c.host(max_sessions=4, tag="-6") as h:
        sess = [await h.start_session(c.spec(f"i6-{i}")) for i in range(4)]
        pgids = [s.pid for s in sess]
        full = False
        try:
            await h.start_session(c.spec("i6-x"))
        except HostFull:
            full = True
        mem_start = {p: group_mem(p) for p in pgids}
        res = await asyncio.gather(*(turn(s, f"Reply with the single word: ok{i}.") for i, s in enumerate(sess)))
        await asyncio.sleep(1.0)
        mem_idle = {p: group_mem(p) for p in pgids}
        texts = [kinds(r, "turn_result")[-1].text for r in res]
        crosstalk = any(f"ok{j}" in (texts[i] or "").lower() for i in range(4) for j in range(4) if i != j)
        host_id = h.host_id
        marked_before = len(env_marked(host_id))
        await h.close_all(grace=5.0)
        left_groups = {p: pgid_members(p) for p in pgids}
        marked_after = env_marked(host_id)
        reg = h.registry.entries()
        rss = [m["rss_kb"] for m in mem_idle.values()]
        d = {"host_full_on_5th": full, "pgids": pgids, "mem_after_start": mem_start, "mem_after_first_turn": mem_idle,
             "rss_mib_per_session": [round(x / 1024, 1) for x in rss], "rss_mib_total": round(sum(rss) / 1024, 1),
             "texts": texts, "crosstalk": crosstalk, "marked_before_close": marked_before, "left_in_groups": left_groups,
             "marked_after_close": marked_after, "registry_after": len(reg), "exit_codes": [s.exit_code for s in sess],
             "end_reasons": [s.end_reason for s in sess]}
        ok = full and not crosstalk and not any(left_groups.values()) and not marked_after and not reg and all(r for r in rss)
        d["ok"] = ok
        return d


def transcript_dir(cwd: str) -> str:
    return os.path.expanduser("~/.claude/projects/") + re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


async def item7(c: Ctx) -> dict:
    async with c.host(tag="-7") as h:
        spec = c.spec("i7", persist=True)
        s1 = await h.start_session(spec)
        e1 = await turn(s1, "Remember this code word: PELICAN-7. Reply with just OK.")
        t1 = kinds(e1, "turn_result")[-1]
        sid = s1.adapter.backend_session
        ready1 = kinds(e1, "session_ready")[0]
        await s1.close(5)
        tdir = transcript_dir(spec["cwd"])
        files1 = {f: sum(1 for _ in open(os.path.join(tdir, f), errors="replace")) for f in os.listdir(tdir) if f.endswith(".jsonl")} if os.path.isdir(tdir) else {}
        s2 = await h.start_session(dict(spec, resume=sid))
        e2 = await turn(s2, "What was the code word? Reply with just the word.")
        t2 = kinds(e2, "turn_result")[-1]
        ready2 = kinds(e2, "session_ready")[0]
        infos2 = [e.changed for e in kinds(e2, "session_info")]
        sid2 = ready2.backend_session
        await s2.close(5)
        files2 = {f: sum(1 for _ in open(os.path.join(tdir, f), errors="replace")) for f in os.listdir(tdir) if f.endswith(".jsonl")} if os.path.isdir(tdir) else {}
        first = {"id": sid, "cost_total": t1.cost_total, "cost_delta": t1.cost_delta}
        second = {"id": sid2, "cost_total": t2.cost_total, "cost_delta": t2.cost_delta, "session_info_after_init": jsonable(infos2),
                  "ready_cwd": ready2.cwd}
        ok, d = analyze_resume(first, second, t2.text, "PELICAN")
        d.update(same_id=(sid == sid2), transcript_dir=tdir, transcript_lines_before_resume=files1, transcript_lines_after_resume=files2,
                 cwd=spec["cwd"], resume_cost_note="cost_total 이 이전 합계를 포함하는지: second.cost_total vs first.cost_total")
        return {"ok": ok, **d}


async def child_host(out: str, claude: str, busy: bool = False) -> None:
    """항목 8 의 자식: 호스트가 되어 세션 하나를 띄우고 pid 를 표준출력으로 알린 뒤 기다린다(부모가 SIGKILL 한다)."""
    c = Ctx(out, claude)
    h = c.host(tag="-8")
    s = await h.start_session(c.spec("i8"))
    if busy:       # 턴이 진행 중일 때(출력 도중) 호스트가 죽는 경우
        await s.send("Count from 1 to 400, one number per line, nothing else.")
        n = 0
        while n < 5:
            ev = await s.next_event(60)
            n += ev.kind == "text_delta"
        print(json.dumps({"claude_pid": s.pid, "host_pid": os.getpid(), "host_id": h.host_id, "text": "(busy)"}), flush=True)
        await asyncio.sleep(600)
    e = await turn(s, "Reply with the single word: ready.")
    print(json.dumps({"claude_pid": s.pid, "host_pid": os.getpid(), "host_id": h.host_id, "text": kinds(e, "turn_result")[-1].text}), flush=True)
    await asyncio.sleep(600)


async def item8(c: Ctx, busy: bool = False) -> dict:
    p = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--child-host", "--out", c.out, "--claude", c.claude] + (["--busy"] if busy else []),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = await asyncio.get_running_loop().run_in_executor(None, p.stdout.readline)
    info = json.loads(line)
    cpid = info["claude_pid"]
    st0 = proc_starttime(cpid)
    p.kill()                       # 자기가 띄운 호스트 프로세스(SIGKILL)
    p.wait()
    t0 = time.monotonic()
    alive_after = {}
    h2 = c.host(tag="-8")
    orphans: list = []
    for sec in (1, 3, 10, 20):
        await asyncio.sleep(max(0, sec - (time.monotonic() - t0)))
        alive_after[f"{sec}s"] = proc_starttime(cpid) == st0 and st0 is not None
        if sec == 1:      # 자식이 아직 살아 있을 때 새 호스트가 고아로 찾는지(알림만, 죽이지 않음)
            orphans = h2.scan_orphans(compact=False)
    d = {"claude_pid": cpid, "starttime": st0, "child_alive_after_host_sigkill": alive_after,
         "orphans_found": [(o.pid, o.host_session, o.marker_verified) for o in orphans], "notices": [n.text for n in h2.notices]}
    cleaned = None
    if proc_starttime(cpid) == st0 and st0 is not None:      # 자기 자식(pid·starttime 일치)만 정리한다
        try:
            os.killpg(cpid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await asyncio.sleep(3)
        cleaned = "SIGTERM" if proc_starttime(cpid) != st0 else "남음"
        if cleaned == "남음":
            os.killpg(cpid, signal.SIGKILL)
            await asyncio.sleep(1)
    for o in orphans:
        h2.forget_orphan(o)
    d["cleanup"] = cleaned
    d["left_in_group"] = pgid_members(cpid)
    d["ok"] = not d["left_in_group"]
    d["busy"] = busy
    d["observation"] = "alive_after 가 모두 false 면 stdin EOF 로 스스로 끝난 것, 끝까지 true 면 고아가 남는 것(고아 탐지 필요). 정리가 필요했으면 cleanup 에 적힌다"
    return d


async def item8b(c: Ctx) -> dict:
    return await item8(c, busy=True)


ITEMS = {"1": item1, "2": item2, "3": item3, "4": item4, "5": item5, "6": item6, "7": item7, "8": item8, "8b": item8b}


async def main_async(a) -> int:
    os.makedirs(a.out, exist_ok=True)
    c = Ctx(os.path.abspath(a.out), a.claude)
    items = ["1", "2", "4"] if a.items == "canary" else list(ITEMS) if a.items == "all" else a.items.split(",")
    rc = 0
    for it in items:
        t0 = time.time()
        try:
            r = await asyncio.wait_for(ITEMS[it](c), 300)
        except BaseException as e:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        r["seconds"] = round(time.time() - t0, 1)
        c.results[it] = jsonable(r)
        print(f"항목 {it}: {'통과' if r.get('ok') else '실패'}  ({r['seconds']}s)", flush=True)
        if not r.get("ok"):
            rc = 1
    p = os.path.join(c.out, "results.json")
    old = {}
    try:
        old = json.load(open(p))
    except (OSError, ValueError):
        pass
    old.update(c.results)
    json.dump(old, open(p, "w"), ensure_ascii=False, indent=1)
    print("결과:", p)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", default="canary")
    ap.add_argument("--claude", default=DEFAULT_CLAUDE)
    ap.add_argument("--child-host", action="store_true")
    ap.add_argument("--busy", action="store_true")
    a = ap.parse_args()
    if a.child_host:
        asyncio.run(child_host(os.path.abspath(a.out), a.claude, a.busy))
        return 0
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
