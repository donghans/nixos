#!/usr/bin/env python3
"""ctx 로컬 폴백 검색 — 정본(DB)에 못 붙을 때(또는 `search --local`) 이 호스트의 Claude Code 트랜스크립트(~/.claude/projects/**/*.jsonl)에서 직접 찾는다.

DB 없이 돈다(표준 라이브러리 + ctx_secrets/ctxdata 의 정규식만). 한계는 항상 같이 알린다: **이 호스트에서 한 대화만** — 다른 호스트의 대화·접속이 끊긴 사이 적재분은 없다.
검색어는 DB 검색처럼 글자 그대로 일치(부분 문자열, 대소문자 무시)다. 표시 전에 비밀 후보(StrictMasker)를 가린다(등록표는 DB 에 있어 오프라인에서는 못 읽는다).
"""
import glob
import json
import os
import re
import time


def default_base():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def project_dirs(here_cwd=None, base=None):
    """검색할 프로젝트 폴더들. here_cwd 가 있으면 그 경로(와 그 아래 워크트리)에 해당하는 폴더만 — Claude Code 는 경로의 `/`·`.` 를 `-` 로 바꿔 폴더 이름을 만든다."""
    base = base or default_base()
    if not here_cwd:
        return sorted(glob.glob(os.path.join(base, "*/")))
    name = re.sub(r"[/.]", "-", here_cwd.rstrip("/"))
    return sorted(d for d in glob.glob(os.path.join(base, name + "*/")))


def _text_of(m):
    """transcript 한 줄(dict)에서 (role, kind, text). 사람 프롬프트·모델 응답 글만 — 도구 호출·결과는 뺀다."""
    t = m.get("type")
    c = (m.get("message") or {}).get("content")
    if t == "user" and isinstance(c, str):
        return "user", "prompt", c
    if t == "assistant" and isinstance(c, list):
        txt = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip()
        if txt:
            return "assistant", "response", txt
    return None


def search_local(q, auto_re=None, here_cwd=None, days=None, role=None, session=None, limit=15, base=None, deadline_s=120):
    """반환 (결과 목록, 읽은 파일 수, 시간 초과 여부). 결과 = [{ts, session_id, role, kind, text, file}] 최근 것 먼저."""
    qb = q.lower().encode("utf-8")
    auto = re.compile(auto_re) if auto_re else None
    cutoff = time.time() - days * 86400 if days else None
    files = []
    for d in project_dirs(here_cwd, base):
        files += glob.glob(os.path.join(d, "*.jsonl"))
    files.sort(key=lambda f: -os.path.getmtime(f))
    out, nfiles, t0, timed_out = [], 0, time.time(), False
    for f in files:
        if cutoff and os.path.getmtime(f) < cutoff:
            continue
        sid = os.path.basename(f)[:-6]
        if session and not sid.startswith(session):
            continue
        if time.time() - t0 > deadline_s:
            timed_out = True
            break
        nfiles += 1
        try:
            with open(f, "rb") as fh:
                for line in fh:
                    if qb not in line.lower():          # 싼 선거름: JSON 으로 읽기 전에 바이트로 거른다
                        continue
                    try:
                        m = json.loads(line)
                    except ValueError:
                        continue
                    r = _text_of(m)
                    if not r:
                        continue
                    rl, kd, tx = r
                    if role and rl != role:
                        continue
                    if rl == "user" and auto and auto.search(tx):
                        continue
                    if q.lower() not in tx.lower():
                        continue
                    out.append(dict(ts=m.get("timestamp") or "", session_id=sid, role=rl, kind=kd, text=tx, file=f))
        except OSError:
            continue
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit], nfiles, timed_out


def snippet(text, q, width=240, before=60):
    i = text.lower().find(q.lower())
    st = max((i if i >= 0 else 0) - before, 0)
    return text[st:st + width].strip()
