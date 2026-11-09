#!/usr/bin/env python3
"""llmhost_ctl 의 실제 claude 시험(계획서 llm-trust/13 §4 S1). **비용이 든다**(haiku, 항목당 약 $0.01~0.02) — run-tests.sh 에 넣지 않는다.
사용: python3 -I llmhost_real.py --out <새 폴더> [--items a,b] [--claude 실행파일]
  a  세션 시작 → 한 문장 지시 → 텍스트 스트림(text_delta)·turn_result·비용이 오는가, raw 0, 닫은 뒤 자식 0개
  b  쓰기 도구를 쓰게 하는 지시 → 권한 요청이 오면 b.deny() 로 거부(S2) → 턴이 끝나며 파일이 생기지 않는가
  c  같은 지시 → 권한 요청이 오면 b.allow() 로 허용(S2) → 파일이 실제로 생기고 턴이 정상 종료하는가
조건: 실행 파일은 claude 직접(env 는 ClaudeAdapter.env 의 HOME·PATH·TERM 뿐 — env -i 와 같다), --model haiku, persist=False(--no-session-persistence), 새 폴더(--out 아래 proj), 훅 없음(use_launcher=False)이라 ctx DB 에 시험 세션이 남지 않는다.
시험 뒤 `donghans ctx recent` 로 cwd 에 이 폴더 이름이 있는 세션이 없는지 확인한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llmhost_ctl as hc  # noqa: E402


def collect(b, pred, timeout):
    got, t0 = [], time.time()
    while time.time() - t0 < timeout:
        got += b.drain()
        if pred(got):
            break
        time.sleep(0.05)
    return got + b.drain()


def kinds(evs, k):
    return [e for e in evs if e.get("kind") == k]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_item(name, prompt, out, claude, expect_file=None, respond=None):
    proj = os.path.join(out, "proj-" + name)
    os.makedirs(proj, exist_ok=True)
    b = hc.HostBridge(log_root=os.path.join(out, "logs"), use_launcher=False)
    r: dict = {}
    err = b.start(proj, "haiku", exe=[claude], extra_spec={"persist": False})
    r["start_err"] = err
    evs = collect(b, lambda e: b.running, 10)
    t0 = time.time()
    r["send_err"] = b.send(prompt)
    r["send_seconds"] = round(time.time() - t0, 3)
    t1, got = time.time(), []
    while time.time() - t1 < 90:                      # 권한 요청이 오면 respond(b, req) 로 답한다(없으면 그냥 기다린다 — 30분 상한이 있어도 시험은 90초에서 끊는다)
        got += b.drain()
        if kinds(got, "turn_result"):
            break
        for p in b.pending_requests():
            if respond is not None and p["req"] not in r.setdefault("answered", []):
                r["answered"].append(p["req"])
                r["respond_err"] = respond(b, p["req"])
        time.sleep(0.05)
    evs += got + b.drain()
    pid = (b.child_pids() or [None])[0]
    b.close()
    evs += collect(b, lambda e: kinds(e, "session_ended"), 20)
    time.sleep(0.3)
    b.shutdown()
    ks = [e["kind"] for e in evs]
    tr = (kinds(evs, "turn_result") or [{}])[0]
    r.update(kinds=ks.count, events=len(evs), raw=len(kinds(evs, "raw")), deltas=len(kinds(evs, "text_delta")), cost_total=tr.get("cost_total"), ok_turn=tr.get("ok"),
             text=(tr.get("text") or "")[:200], resolved=[(e["outcome"], e["by"]) for e in kinds(evs, "request_resolved")],
             notices=[e["text"][:160] for e in kinds(evs, "notice")], ended=[e.get("reason") for e in kinds(evs, "session_ended")],
             child_alive_after=bool(pid and alive(pid)), file_created=bool(expect_file and os.path.exists(os.path.join(proj, expect_file))))
    r.pop("kinds", None)
    json.dump(evs, open(os.path.join(out, f"events-{name}.json"), "w"), ensure_ascii=False, indent=1, default=str)
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", default="a")
    ap.add_argument("--claude", default="/home/donghans/.nix-profile/bin/claude")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    res, rc = {}, 0
    if "a" in a.items.split(","):
        r = run_item("a", "Say hello in one short sentence.", out, a.claude)
        r["ok"] = (r["start_err"] is None and r["send_err"] is None and r["send_seconds"] < 0.5 and r["deltas"] > 0 and r["ok_turn"] is True and bool(r["text"])
                   and (r["cost_total"] or 0) > 0 and r["raw"] == 0 and r["ended"] == ["closed"] and not r["child_alive_after"])
        res["a"] = r
    if "b" in a.items.split(","):
        r = run_item("b", "Create a file named s2-deny.txt containing the text no, using the Write tool, then say in one sentence what happened.", out, a.claude, "s2-deny.txt",
                     respond=lambda b, req: b.deny(req, "시험: 거부한다"))
        r["ok"] = (r["start_err"] is None and r["ok_turn"] is True and ("deny", "user") in [tuple(x) for x in r["resolved"]] and not r["file_created"]
                   and r.get("respond_err") is None and len(r.get("answered", [])) == 1 and r["raw"] == 0 and not r["child_alive_after"])
        res["b"] = r
    if "c" in a.items.split(","):
        r = run_item("c", "Create a file named s2-allow.txt containing the text ok, using the Write tool, then say in one sentence what happened.", out, a.claude, "s2-allow.txt",
                     respond=lambda b, req: b.allow(req))
        r["ok"] = (r["start_err"] is None and r["ok_turn"] is True and ("allow", "user") in [tuple(x) for x in r["resolved"]] and r["file_created"]
                   and r.get("respond_err") is None and len(r.get("answered", [])) == 1 and r["raw"] == 0 and not r["child_alive_after"])
        res["c"] = r
    for k, v in res.items():
        print(f"항목 {k}: {'통과' if v['ok'] else '실패'}  비용누적 {v['cost_total']}")
        rc |= 0 if v["ok"] else 1
    json.dump(res, open(os.path.join(out, "results.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
