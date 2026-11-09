#!/usr/bin/env python3
"""protocolhook — 출력 규약 파일럿의 Claude Code 훅(UserPromptSubmit 주입·Stop 검사). 호출: `protocolcheck hook prompt|stop`(protocolcheck.main 이 게이트를 먼저 본다).
설계: ctx 문서 plan llm-trust/10-p5prime-1-protocol-pilot §6-1·§7-2·§8, 문구·규칙: note llm-trust/wf-10-s1-frozen-protocol.

게이트: 환경변수 LLM_PROTOCOL_PILOT=1 일 때만 동작(없으면 아무것도 하지 않고 종료 코드 0). 모든 훅은 어떤 오류에도 exit 0 으로 끝난다(실패 시 통과).
저장 위치: $LLM_PROTOCOL_HOME(기본 ~/.cache/llm-protocol) — registry `pilot-registry.tsv`, 슬롯 `pilot-slots.json`, 산출물 폴더 `<프로젝트>/<session_id 앞 8자>/`.
PreToolUse 는 쓰지 않는다(T-5). 팔(G/F)은 registry 에서 읽는다 — 모델은 팔을 모른다.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import protocolcheck as pc  # noqa: E402
import protocol_text as T  # noqa: E402

PROJECT = os.environ.get("LLM_PROTOCOL_PROJECT", "nixos")
REG_COLS = ("작업번호", "종류", "팔", "session_id", "시작", "종료", "정정분류", "비고", "슬롯종류")
PROMPT_REWIND_MAX = 1
SESSION_REWIND_MAX = 3
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CLASS_LINE = re.compile(r"^\s*분류\s*[:：]\s*(결정|계획|검증·QA|구현 결과|모름)\s*$", re.M)


def home() -> str:
    return os.environ.get("LLM_PROTOCOL_HOME") or os.path.expanduser("~/.cache/llm-protocol")


def session_dir(sid: str) -> str:
    return os.path.join(home(), PROJECT, sid[:8])


# ---------------------------------------------------------------- registry
class Registry:
    """pilot-registry.tsv(세션 행) + pilot-slots.json(종류별 미리 동결한 팔 슬롯). 갱신은 파일 잠금 아래서 통째로 다시 쓴다."""

    def __init__(self, base: str):
        self.path = os.path.join(base, "pilot-registry.tsv")
        self.slots_path = os.path.join(base, "pilot-slots.json")
        self.lock_path = os.path.join(base, ".registry.lock")
        os.makedirs(base, mode=0o700, exist_ok=True)

    def _lock(self):
        f = open(self.lock_path, "a")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    def rows(self) -> list:
        try:
            lines = open(self.path, encoding="utf-8").read().split("\n")
        except OSError:
            return []
        out = []
        for ln in lines[1:]:
            if not ln.strip():
                continue
            v = ln.split("\t")
            v += [""] * (len(REG_COLS) - len(v))
            out.append(dict(zip(REG_COLS, v)))
        return out

    def _write(self, rows: list) -> None:
        clean = lambda x: str(x).replace("\t", " ").replace("\n", " ")
        text = "\t".join(REG_COLS) + "\n" + "".join("\t".join(clean(r.get(c, "")) for c in REG_COLS) + "\n" for r in rows)
        tmp = self.path + f".tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, self.path)

    def get(self, sid: str):
        for r in self.rows():
            if r["session_id"] == sid:
                return r
        return None

    def slots(self) -> dict:
        try:
            return json.load(open(self.slots_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def add_session(self, sid: str, start: str) -> dict:
        lk = self._lock()
        try:
            rows = self.rows()
            for r in rows:
                if r["session_id"] == sid:
                    return r
            n = 1 + max([int(r["작업번호"]) for r in rows if r["작업번호"].isdigit()] or [0])
            row = {"작업번호": str(n), "종류": "", "팔": "", "session_id": sid, "시작": start, "종료": "", "정정분류": "", "비고": "", "슬롯종류": ""}
            rows.append(row)
            self._write(rows)
            return row
        finally:
            lk.close()

    def classify(self, sid: str, kind: str) -> dict | None:
        """`분류: <종류>` 처리. 첫 확정이면 그 종류의 다음 슬롯 팔을 기록, 재분류는 종류만 갱신(팔 유지, 슬롯 소모 없음). 모름은 팔·슬롯을 쓰지 않는다."""
        lk = self._lock()
        try:
            rows = self.rows()
            row = next((r for r in rows if r["session_id"] == sid), None)
            if row is None:
                return None
            prev = row["종류"]
            if prev and prev != kind:
                row["정정분류"] = (row["정정분류"] + ";" if row["정정분류"] else "") + f"{prev}→{kind}"
            row["종류"] = kind
            if not row["팔"] and kind != "모름":
                slots = self.slots().get(kind) or []
                used = sum(1 for r in rows if r["슬롯종류"] == kind)
                if used < len(slots) and slots[used] in ("G", "F"):
                    row["팔"] = slots[used]
                    row["슬롯종류"] = kind
                else:
                    row["비고"] = (row["비고"] + ";" if row["비고"] else "") + ("슬롯 파일 없음" if not slots else "슬롯 소진")
            self._write(rows)
            return row
        finally:
            lk.close()


# ---------------------------------------------------------------- 폴더·facts 생성
def _git(cwd: str, *args):
    return pc.git(cwd, *args)


def make_folder(sid: str, cwd: str, prompt: str) -> str:
    d = session_dir(sid)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    os.makedirs(os.path.join(d, "facts"), mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(d, ".check"), mode=0o700, exist_ok=True)
    pc.write_tool_file(os.path.join(d, "FORMAT.md"), T.FORMAT_MD)
    items = [ln.rstrip() for ln in prompt.split("\n") if re.match(r"^\s*\d+[.)]", ln)]
    pc.write_tool_file(os.path.join(d, "facts", "request-items.txt"), pc.head_text() + ("\n".join(items) + "\n" if items else "(번호 항목 없음)\n"))
    head = (_git(cwd, "rev-parse", "HEAD") or "").strip() if cwd and os.path.isdir(cwd) else ""
    status = (_git(cwd, "status", "--short") or "") if head else ""
    top = ((_git(cwd, "rev-parse", "--show-toplevel") or cwd) if head else cwd).strip()
    lines = [pc.head_text(), f"시작 시각: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}", f"저장소 HEAD: {head or '없음'}", f"작업 폴더: {cwd}", f"세션: {sid}"]
    dirty = [s for s in status.split("\n") if s.strip()]
    lines += [f"상태: {s}" for s in dirty] or ["상태: (깨끗함)"]
    for s in dirty[:200]:
        rel = s[3:].strip().split(" -> ")[-1].strip('"')
        h = pc.sha256_file(os.path.join(top, rel))
        if h:
            lines.append(f"해시: {h} {rel}")
    pc.write_tool_file(os.path.join(d, "facts", "base.txt"), "\n".join(lines) + "\n")
    pc.register_sha(d, ["facts/request-items.txt", "facts/base.txt"])
    return d


def git_sig(cwd: str) -> str:
    if not cwd or not os.path.isdir(cwd):
        return ""
    return f"{(_git(cwd, 'rev-parse', 'HEAD') or '').strip()}\n{_git(cwd, 'status', '--short') or ''}"


# ---------------------------------------------------------------- UserPromptSubmit
def hook_prompt(payload: dict) -> str | None:
    sid = payload.get("session_id") or ""
    if not re.fullmatch(r"[0-9A-Za-z-]{8,}", sid):
        return None
    prompt = payload.get("prompt") or ""
    cwd = payload.get("cwd") or os.getcwd()
    reg = Registry(home())
    row = reg.get(sid)
    first = row is None
    d = session_dir(sid)
    if first:
        d = make_folder(sid, cwd, prompt)
        reg.add_session(sid, time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        text = T.A_TEMPLATE.replace("{DIR}", d)
    else:
        text = T.B_TEMPLATE.replace("{DIR}", d)
    m = CLASS_LINE.search(prompt)
    if m:
        reg.classify(sid, m.group(1))
    return text


# ---------------------------------------------------------------- Stop
def last_user_index(entries: list) -> int:
    idx = -1
    for i, e in enumerate(entries):
        if e.get("type") != "user":
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            idx = i
        elif isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            idx = i
    return idx


def wrote_files(transcript_path: str, protocol_dir: str):
    """이번 프롬프트 이후 변경 도구(Edit·Write 등, 규약 폴더 밖 대상) 호출이 있었나. 읽을 수 없으면 None."""
    try:
        entries = [json.loads(l) for l in open(transcript_path, encoding="utf-8") if l.strip()]
    except (OSError, ValueError, TypeError):
        return None
    start = last_user_index(entries) + 1
    for e in entries[start:]:
        c = (e.get("message") or {}).get("content")
        if e.get("type") != "assistant" or not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in WRITE_TOOLS:
                ti = b.get("input") or {}
                p = ti.get("file_path") or ti.get("notebook_path") or ""
                if not p or not os.path.realpath(p).startswith(os.path.realpath(protocol_dir) + os.sep):
                    return True
    return False


def changed_this_prompt(payload: dict, d: str, cwd: str) -> bool:
    """변경 도구 호출 판별(계획 §7-2 (c)): transcript 의 변경 도구 호출, 또는 마지막 Stop 이후 git 상태 변화(Bash 로 바꾼 것 포함)."""
    sigp = os.path.join(d, ".check", "git-sig.txt")
    last = pc.read(sigp)
    if last is None:
        base = pc.parse_base(pc.Folder(d))
        last = f"{base['head'] or ''}\n" + "".join(s + "\n" for s in base["status"] if s != "(깨끗함)")
    cur = git_sig(cwd)
    try:
        pc.write_tool_file(sigp, cur)
    except OSError:
        pass
    wf = wrote_files(payload.get("transcript_path") or "", d)
    git_changed = bool(cur) and norm_sig(cur) != norm_sig(last)
    return bool(wf) or git_changed


def norm_sig(s: str) -> list:
    return sorted(l.rstrip() for l in s.split("\n") if l.strip())


def log_stop(d: str, rec: dict) -> None:
    p = os.path.join(d, ".check", "stop-log.jsonl")
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_log(d: str) -> list:
    out = []
    for ln in (pc.read(os.path.join(d, ".check", "stop-log.jsonl")) or "").split("\n"):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def rewind_state(d: str) -> dict:
    try:
        return json.loads(pc.read(os.path.join(d, ".check", "rewind.json")) or "{}")
    except ValueError:
        return {}


def hook_stop(payload: dict) -> dict | None:
    sid = payload.get("session_id") or ""
    if not re.fullmatch(r"[0-9A-Za-z-]{8,}", sid):
        return None
    reg = Registry(home())
    row = reg.get(sid)
    d = session_dir(sid)
    if row is None or not os.path.isdir(d):
        return None
    cwd = payload.get("cwd") or pc.parse_base(pc.Folder(d))["cwd"] or os.getcwd()
    active = bool(payload.get("stop_hook_active"))
    pid = payload.get("prompt_id") or ""
    arm = row["팔"]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": sid[:8], "prompt_id": pid, "arm": arm, "kind": row["종류"],
           "stop_hook_active": active, "attempt": False, "first_attempt": False}
    if not arm:
        rec.update(event="팔 없는 Stop", level="INFO", action="log")
        log_stop(d, rec)
        return None
    fo = pc.Folder(d)
    state = fo.state()
    rec["state"] = state
    if fo.index is None:
        if not changed_this_prompt(payload, d, cwd):
            rec.update(event="변경 없음", action="log")
            log_stop(d, rec)
            return None
        mode = "attempt"
    elif state == "작업중":
        mode = "working"
    else:
        mode = "attempt"
        if fo.index is not None:
            changed_this_prompt(payload, d, cwd)   # git 서명 갱신만(결과는 안 쓴다)
    if mode == "attempt":
        pc.refresh_diff_stat(d)
    res = pc.run_checks(d, mode)
    pc.write_result(d, res)
    attempt = mode == "attempt"
    prev = read_log(d)
    rec.update(event="마감 시도" if attempt else "작업중 Stop", mode=mode, attempt=attempt,
               first_attempt=attempt and not any(r.get("attempt") for r in prev),
               counts=res["counts"], fail=[f"{i['id']} {i['file']}: {i['reason']}" for i in pc.fails(res)])
    cand = pc.rewindable(res) if attempt else []
    action = "log"
    out = None
    if arm == "F" and cand:
        st = rewind_state(d)
        prompts = st.get("prompts", [])
        if active:
            action = "pass-active"
        elif st.get("session", 0) >= SESSION_REWIND_MAX:
            action = "pass-cap"
        elif pid and pid in prompts:
            action = "pass-prompt-once"
        else:
            action = "block"
            out = {"decision": "block", "reason": pc.block_reason(res)}
            st = {"session": st.get("session", 0) + 1, "prompts": prompts + [pid]}
            pc.write_tool_file(os.path.join(d, ".check", "rewind.json"), json.dumps(st, ensure_ascii=False) + "\n")
    elif active and cand:
        action = "pass-active"
    rec["action"] = action
    rec["rewinds_session"] = rewind_state(d).get("session", 0)
    log_stop(d, rec)
    return out


# ---------------------------------------------------------------- 진입
def main(args) -> int:
    which = args[0] if args else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if which == "prompt":
            text = hook_prompt(payload)
            if text:
                sys.stdout.write(text + "\n")
        elif which == "stop":
            out = hook_stop(payload)
            if out:
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    except Exception:   # 실패 시 통과 — 어떤 오류도 응답을 막지 않는다
        return 0
    return 0


if __name__ == "__main__":
    if os.environ.get("LLM_PROTOCOL_PILOT") != "1":
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
