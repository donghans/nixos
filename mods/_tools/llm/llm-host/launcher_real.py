#!/usr/bin/env python3
"""launcher.py 의 실제 claude-run 시험(계획서 llm-trust/11 §7-2·§9 S8). **비용이 든다**(항목당 약 $0.01, haiku) — run-tests.sh 에 넣지 않는다.
사용: python3 -I launcher_real.py --out <새 폴더> [--items a,b,c]
  a  claude-run 경유(표준입력 파이프) + sudo_ready 아님: 훅이 붙는가(hook 이벤트), sudo 환경이 없는가, 쓰기 없는 `sudo -n true` 가 실패하는가
  b  claude-run 경유 + sudo_ready: CLAUDE_SUDO_SOCK 이 보이고 PATH 앞이 래퍼이며 `sudo -n true` 가 성공하는가(사전에 사용자가 sudo-claude-auth 로 인증해 둔 상태여야 함 — 이 시험은 비밀번호를 읽지 않는다)
  c  래퍼는 있으나 중계 소켓이 없는 상태(인증 없는 상태의 흉내): `sudo true` 가 안내문과 함께 실패하고 호스트가 notice(sudo) 를 올리는가
조건: --model haiku, --no-session-persistence, 새 폴더, 호스트 프로세스의 PATH 에서 sudo 래퍼 디렉터리를 뺀다(llmui 환경과 같게), 쓰기 있는 명령 없음.
**주의**: 이 시험은 claude-run 의 훅 설정을 붙이므로 `donghans ctx hook` 이 ctx DB 의 hook_events·sessions 에 행을 남긴다(--no-session-persistence 여도, S8 확인). cwd 가 시험 폴더라 구분된다.
판정 함수(analyze_*)는 이벤트 목록만 보는 순수 함수라 tests/test_launcher.py 가 돈 없이 시험한다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import events as E  # noqa: E402
import launcher as L  # noqa: E402
from claude_adapter import ClaudeAdapter  # noqa: E402
from host import SessionHost  # noqa: E402
from integration_real import turn, drain, jsonable, kinds  # noqa: E402

CMD_PROBE = 'echo "SOCK=[$CLAUDE_SUDO_SOCK]"; echo "SUDO=$(command -v sudo)"; sudo -n true; echo "RC=$?"'
CMD_HINT = 'sudo true; echo "RC=$?"'


def prompt_for(cmd: str) -> str:
    return f"Run exactly this single bash command, do not change it, then reply with only its raw output:\n{cmd}"


def _tool_texts(evs: list) -> str:
    return "\n".join(L._text_of(e.content) for e in kinds(evs, "tool_result"))


def parse_probe(text: str) -> dict:
    sock = re.search(r"SOCK=\[(.*?)\]", text)
    sudo = re.search(r"^SUDO=(.*)$", text, re.M)
    rc = re.search(r"^RC=(\d+)$", text, re.M)
    return {"sock": sock.group(1) if sock else None, "sudo": sudo.group(1).strip() if sudo else None, "rc": int(rc.group(1)) if rc else None}


def hook_names(evs: list) -> list:
    return sorted({e.name for e in kinds(evs, "hook") if e.name})


def analyze_probe(evs: list, sudo_expected: bool, sock: str, sudo_bin_dir: str) -> tuple:
    """a/b 공용. 훅 이벤트가 있고(claude-run 이 --settings 를 붙였다는 증거), sudo 환경이 기대와 같은가."""
    d = parse_probe(_tool_texts(evs))
    d["hooks"] = hook_names(evs)
    d["raw"] = len(kinds(evs, "raw"))
    d["sudo_notices"] = [e.text for e in kinds(evs, "notice") if "sudo" in e.text]
    wrapper = os.path.join(sudo_bin_dir, "sudo")
    if sudo_expected:
        env_ok = d["sock"] == sock and d["sudo"] == wrapper and d["rc"] == 0
    else:
        env_ok = d["sock"] == "" and d["sudo"] not in (wrapper, None) and d["rc"] not in (0, None)
    ok = env_ok and bool(d["hooks"]) and d["raw"] == 0 and bool(kinds(evs, "turn_result"))
    d["env_ok"] = env_ok
    return ok, d


def analyze_hint(evs: list) -> tuple:
    d = parse_probe(_tool_texts(evs))
    hints = [e for e in kinds(evs, "notice") if (e.extra or {}).get("hint") == "sudo"]
    d["hint_notices"] = len(hints)
    d["tool_text"] = _tool_texts(evs)[:300]
    return bool(hints) and len(hints) == 1 and d["rc"] not in (0, None), d


def strip_sudo_wrapper(path: str, sudo_bin_dir: str) -> str:
    return os.pathsep.join(p for p in path.split(os.pathsep) if p and p != sudo_bin_dir)


class Ctx:
    def __init__(self, out: str):
        self.out, self.results = out, {}
        plan = L.prepare()                     # 탐색만(sudo_ready=False 라 sudo 는 부르지 않는다)
        self.run_bin, self.sudo_dir = plan.info["claude_run"], plan.info["sudo_bin_dir"]
        self.sock = L.sudo_sock_path()
        if not self.sudo_dir:
            raise SystemExit("claude-run 글에서 sudo 래퍼 위치를 못 읽음 — 이 시험은 진행할 수 없다")
        os.environ["PATH"] = strip_sudo_wrapper(os.environ["PATH"], self.sudo_dir)   # 호스트 프로세스 PATH 를 llmui 환경처럼

    def host(self, tag: str) -> SessionHost:
        return SessionHost(lambda hs: ClaudeAdapter(hs), max_sessions=2, registry_dir=os.path.join(self.out, "registry" + tag),
                           log_root=os.path.join(self.out, "logs" + tag), raw_dir=os.path.join(self.out, "raw" + tag), retention_days=None, term_wait=3.0)

    def spec(self, name: str, **kw) -> dict:
        cwd = os.path.join(self.out, "proj", name)
        os.makedirs(cwd, exist_ok=True)
        s = {"model": "haiku", "persist": False, "cwd": cwd, "max_budget_usd": 0.06, "label": f"s8-{name}"}
        s.update(kw)
        return s


def allow_all(ev):
    return ("allow", None)


async def run_one(c: Ctx, tag: str, spec: dict, cmd: str) -> list:
    async with c.host(tag) as h:
        s = await h.start_session(spec)
        evs = await turn(s, prompt_for(cmd), decide=allow_all)
        evs += await drain(s, 1.0)
        await s.close(5)
        evs += await drain(s, 0.3)
    return evs


async def item_a(c: Ctx) -> dict:
    spec, plan = L.launch_spec(c.spec("a"), sudo_ready=False)
    evs = await run_one(c, "-a", spec, CMD_PROBE)
    ok, d = analyze_probe(evs, False, c.sock, c.sudo_dir)
    notice_ok = any(e.text.startswith("sudo 중계 없음") for e in kinds(evs, "notice"))
    return {"ok": ok and notice_ok, "probe": d, "launch_notice": notice_ok, "plan": plan.info}


async def item_b(c: Ctx) -> dict:
    spec, plan = L.launch_spec(c.spec("b"), sudo_ready=True)
    if not plan.info["sudo"]:
        return {"ok": False, "why": "sudo_ready 를 줬는데 준비가 안 됨(사전 인증이 필요)", "plan": plan.info, "notices": plan.notices}
    evs = await run_one(c, "-b", spec, CMD_PROBE)
    ok, d = analyze_probe(evs, True, c.sock, c.sudo_dir)
    return {"ok": ok, "probe": d, "plan": plan.info}


async def item_c(c: Ctx) -> dict:
    bogus = os.path.join(c.out, "no-such-broker.sock")
    spec, plan = L.launch_spec(c.spec("c"), sudo_ready=False)
    spec["env_extra"] = {**spec["env_extra"], "CLAUDE_SUDO_SOCK": bogus, "PATH": c.sudo_dir + os.pathsep + os.environ["PATH"]}
    evs = await run_one(c, "-c", spec, CMD_HINT)
    ok, d = analyze_hint(evs)
    return {"ok": ok, "hint": d}


ITEMS = {"a": item_a, "b": item_b, "c": item_c}


async def main_async(a) -> int:
    os.makedirs(a.out, exist_ok=True)
    c = Ctx(os.path.abspath(a.out))
    rc = 0
    for it in a.items.split(","):
        t0 = time.time()
        try:
            r = await asyncio.wait_for(ITEMS[it](c), 240)
        except BaseException as e:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        r["seconds"] = round(time.time() - t0, 1)
        c.results[it] = jsonable(r)
        print(f"항목 {it}: {'통과' if r.get('ok') else '실패'}  ({r['seconds']}s)", flush=True)
        rc |= 0 if r.get("ok") else 1
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
    ap.add_argument("--items", default="a,c")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
