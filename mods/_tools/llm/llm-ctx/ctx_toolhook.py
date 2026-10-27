#!/usr/bin/env python3
"""ctx_toolhook — 도구 호출마다 도는 가벼운 훅(PreToolUse·PostToolUse). DB·psycopg 없이 ctx_store 만 쓴다(매 호출의 지연을 줄이려고 llm_ctx.py 와 분리).

PreToolUse : `Edit`·`Write` 등이 읽기 뷰(`~/.cache/ctx-views/`)나 문서 저장소(`~/ctx/`)를 직접 고치려 하면 막고 `propose` 를 쓰라고 안내한다.
             Bash 명령 문자열은 막지 않는다 — 문자열 패턴은 정상 명령을 막고(오탐) 쓰기를 놓쳐(미탐) 역효과였다(plan2 05 §4-4-5).
PostToolUse: 이 세션의 뷰 파일이 직접 수정(기준 해시와 다름)됐으면 한 번 알린다(즉시 감시 `ctx doc watch` 가 안 떠 있어도 놓치지 않는 안전망).
훅은 입력을 막지 않는다 — 어떤 오류도 조용히 통과한다(차단은 명시적 deny 출력으로만).
사용: ctx_toolhook.py <PreToolUse|PostToolUse>   (stdin = 훅 JSON, stdout = 훅 응답 JSON 또는 없음)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctx_store as st

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TOLD_FILE = ".ctx-told.json"


def _under(path: str, root: str) -> bool:
    try:
        p, r = os.path.realpath(path), os.path.realpath(root)
    except OSError:
        return False
    return p == r or p.startswith(r + os.sep)


def pre(payload: dict) -> dict | None:
    tool = payload.get("tool_name")
    if tool not in WRITE_TOOLS:
        return None
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        return None
    where = "읽기 뷰" if _under(path, st.views_dir()) else ("문서 저장소" if _under(path, st.store_dir()) else None)
    if not where:
        return None
    reason = (f"{where}({path})는 직접 고치지 않는다. 문서를 고치려면 새 본문을 파일로 만든 뒤 `donghans ctx doc propose <kind> <name> --file <파일>` 을 쓴다 "
              "(동기화 담당이 읽은 판·비밀·머리말을 검사해 반영한다). 먼저 `donghans ctx doc read`/`path` 로 읽어 판을 기록해 둬야 한다.")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def post(payload: dict) -> dict | None:
    sid = payload.get("session_id")
    if not sid:
        return None
    root = st.view_root(st.views_dir(), sid)
    if not os.path.isdir(root):
        return None
    mods = st.modified_in_view(root)
    if not mods:
        return None
    told_p = os.path.join(root, TOLD_FILE)
    try:
        told = json.load(open(told_p))
    except (OSError, ValueError):
        told = {}
    fresh = []
    for rel, kind in mods:
        cur = st.file_hash(os.path.join(root, rel)) or "deleted"
        if told.get(rel) != cur:
            told[rel] = cur
            fresh.append((rel, kind))
    if not fresh:
        return None
    try:
        json.dump(told, open(told_p, "w"))
    except OSError:
        pass
    names = ", ".join(f"{r}({'수정' if k == 'modified' else '삭제'})" for r, k in fresh)
    msg = (f"[ctx 감시] 읽기 전용 뷰의 파일이 직접 바뀌었다: {names}. 뷰는 고쳐도 저장소에 반영되지 않고 다시 만들면 원본으로 돌아간다 "
           "(고친 내용은 `.ctx-rejected/` 에 보관된다). 반영하려면 `donghans ctx doc propose` 를 쓴다.")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}


def main(argv: list[str]) -> int:
    ev = argv[1] if len(argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = {"PreToolUse": pre, "PostToolUse": post}.get(ev, lambda p: None)(payload)
        if out:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
