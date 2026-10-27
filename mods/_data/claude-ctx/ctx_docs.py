#!/usr/bin/env python3
"""ctx_docs — 저장소에 올리지 않는 프로젝트 문서(계획·QA 기록·메모)를 ctx DB 에 둔다. `donghans doc` 의 본체.

왜(사용자 결정 2026-10-27): 계획서(`_plan/`)와 QA 문서(`.git/info/exclude` 로 추적 제외한 `docs/qa-*.md`·`.qa/` 같은 것)는
특정 컴퓨터·개인에게 묶인 내용이라 저장소(특히 호스트에 구애받지 않는 프레임워크 저장소·팀 저장소)에 둘 이유가 없다.
그렇다고 디스크에만 두면 그 컴퓨터를 벗어나면 읽을 수 없다 → 여러 머신이 같은 곳을 읽도록 DB(`project_docs`)에 둔다.
`instr`(프로젝트별 지침)와 같은 방식이지만 **캐시 파일이 없다**: 정본은 DB 하나이고 읽을 때마다 DB 를 본다.

종류(kind): plan(계획 — 상태 active·done·dropped·unknown) · qa(QA 절차·기록·인계) · note(그 밖의 메모).
이름(name)은 `/` 를 쓸 수 있는 상대 경로 꼴(`repo-restructure/README`).
규칙: 쓸 때 본문에 **등록된 비밀 값**이 있으면 거부한다. rev 는 낙관적 잠금(읽은 rev 가 아니면 거부). 텍스트만 — 이진 파일·너무 큰 파일은 건너뛴다.
`import` 는 멱등이다(같은 내용이면 rev 를 올리지 않는다). 원래 파일 경로(origin_path)를 남겨 어디서 왔는지 알 수 있게 한다.
순수 함수(`valid_name`·`name_from_path`·`read_text`)는 DB 없이 시험한다.
"""
from __future__ import annotations

import hashlib
import os
import re

KINDS = ("plan", "qa", "note")
STATUSES = ("active", "done", "dropped", "unknown")
MAX_BYTES = 2_000_000

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS project_docs (
      repo_url     text NOT NULL,
      kind         text NOT NULL CHECK (kind IN ('plan','qa','note')),
      name         text NOT NULL,
      body         text NOT NULL,
      status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','dropped','unknown')),
      rev          integer NOT NULL DEFAULT 1,
      origin_path  text,
      updated_host text NOT NULL,
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (repo_url, kind, name)
    )""",
    "CREATE INDEX IF NOT EXISTS project_docs_status ON project_docs (repo_url, kind, status)",
    "INSERT INTO schema_version (v) VALUES (4) ON CONFLICT DO NOTHING",
]


def ensure_schema(conn):
    for st in SCHEMA_STATEMENTS:
        conn.execute(st)
    conn.commit()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def valid_name(name: str) -> str | None:
    """이름이 올바르면 None, 아니면 이유."""
    if not name or not name.strip():
        return "이름이 비었다"
    if name.startswith("/") or ".." in name.split("/") or "\x00" in name:
        return "이름은 `..`·절대 경로를 쓸 수 없다"
    if len(name) > 300:
        return "이름이 너무 길다(300자 이하)"
    return None


def name_from_path(path: str, base: str, prefix: str = "") -> str:
    """파일 경로 → 문서 이름. base 기준 상대 경로에서 `.md` 만 뗀다(다른 확장자는 구분되도록 둔다)."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base)).replace(os.sep, "/")
    if rel.endswith(".md"):
        rel = rel[:-3]
    return (prefix.rstrip("/") + "/" if prefix else "") + rel


def read_text(path: str, max_bytes: int = MAX_BYTES):
    """(본문, None) 또는 (None, 건너뛴 이유). 이진·너무 큰·빈 파일은 올리지 않는다."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return None, f"읽을 수 없음({e.strerror})"
    if size == 0:
        return None, "빈 파일"
    if size > max_bytes:
        return None, f"{size:,}바이트 > 한도 {max_bytes:,}"
    raw = open(path, "rb").read()
    if b"\x00" in raw:
        return None, "이진 파일"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "UTF-8 이 아님(이진 파일)"


# ---------------------------------------------------------------- DB
def get(conn, repo_url, kind, name):
    row = conn.execute("SELECT body, status, rev, origin_path, updated_host, updated_at FROM project_docs WHERE repo_url=%s AND kind=%s AND name=%s",
                       (repo_url, kind, name)).fetchone()
    if not row:
        return None
    return dict(body=row[0], status=row[1], rev=row[2], origin_path=row[3], updated_host=row[4], updated_at=row[5])


def list_docs(conn, repo_url, kind=None, status=None, prefix=None):
    q, args = "SELECT kind, name, status, rev, length(body), updated_host, updated_at, origin_path FROM project_docs WHERE repo_url=%s", [repo_url]
    if kind:
        q += " AND kind=%s"; args.append(kind)
    if status:
        q += " AND status=%s"; args.append(status)
    if prefix:
        q += " AND name LIKE %s"; args.append(prefix.replace("%", r"\%").replace("_", r"\_") + "%")
    return conn.execute(q + " ORDER BY kind, name", args).fetchall()


def put(conn, repo_url, kind, name, body, host, masker=None, expect_rev=None, status=None, origin_path=None):
    """새 본문을 쓴다. (결과코드, 메시지, 동작) — 동작: created · updated · same · None(거부)."""
    if kind not in KINDS:
        return 1, f"kind 는 {' | '.join(KINDS)} 중 하나", None
    why = valid_name(name)
    if why:
        return 1, f"{name}: {why}", None
    if status is not None and status not in STATUSES:
        return 1, f"status 는 {' | '.join(STATUSES)} 중 하나", None
    if not body.strip():
        return 1, f"{kind}/{name}: 빈 본문은 올리지 않는다", None
    if masker is not None and masker.text(body) != body:
        return 1, f"{kind}/{name}: 본문에 등록된 비밀 값이 들어 있어 올리지 않는다 — 비밀은 `donghans secret` 으로 두고 문서에는 이름만 적는다", None
    cur = get(conn, repo_url, kind, name)
    if cur is None:
        if expect_rev not in (None, 0):
            return 1, f"{kind}/{name}: 없는 문서에 rev {expect_rev} 를 기대했다", None
        try:
            conn.execute("INSERT INTO project_docs (repo_url, kind, name, body, status, origin_path, updated_host) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (repo_url, kind, name, body, status or "active", origin_path, host))
        except Exception:
            conn.rollback()
            return 1, f"{kind}/{name}: 올리는 사이에 다른 기기가 먼저 만들었다 — 다시 시도", None
        return 0, f"{kind}/{name}: 만들었다(rev 1)", "created"
    if expect_rev is not None and cur["rev"] != expect_rev:
        return 1, f"{kind}/{name}: 읽은 뒤 rev {cur['rev']} 로 바뀌었다(기대 rev {expect_rev}) — 최신본(`donghans doc show {kind} {name}`)에서 다시 고친다", None
    if sha(body) == sha(cur["body"]):
        if status and status != cur["status"]:
            conn.execute("UPDATE project_docs SET status=%s, updated_host=%s, updated_at=now() WHERE repo_url=%s AND kind=%s AND name=%s", (status, host, repo_url, kind, name))
            return 0, f"{kind}/{name}: 본문은 같고 상태만 {cur['status']}→{status}", "same"
        return 0, f"{kind}/{name}: 이미 같은 내용(rev {cur['rev']})", "same"
    row = conn.execute("""UPDATE project_docs SET body=%s, rev=rev+1, status=coalesce(%s, status), origin_path=coalesce(%s, origin_path), updated_host=%s, updated_at=now()
                          WHERE repo_url=%s AND kind=%s AND name=%s AND rev=%s RETURNING rev""",
                       (body, status, origin_path, host, repo_url, kind, name, cur["rev"])).fetchone()
    if not row:
        return 1, f"{kind}/{name}: 올리는 사이에 다른 기기가 먼저 바꿨다 — 다시 시도", None
    return 0, f"{kind}/{name}: 올렸다(rev {row[0]})", "updated"


def set_status(conn, repo_url, kind, name, status, host):
    if status not in STATUSES:
        return 1, f"status 는 {' | '.join(STATUSES)} 중 하나"
    row = conn.execute("UPDATE project_docs SET status=%s, updated_host=%s, updated_at=now() WHERE repo_url=%s AND kind=%s AND name=%s RETURNING rev",
                       (status, host, repo_url, kind, name)).fetchone()
    return (0, f"{kind}/{name}: 상태 → {status}") if row else (1, f"{kind}/{name}: 없다")


def remove(conn, repo_url, kind, name):
    row = conn.execute("DELETE FROM project_docs WHERE repo_url=%s AND kind=%s AND name=%s RETURNING rev", (repo_url, kind, name)).fetchone()
    return (0, f"{kind}/{name}: 지웠다") if row else (1, f"{kind}/{name}: 없다")


def search(conn, repo_url, term, kind=None, limit=20):
    q = "SELECT kind, name, status, position(lower(%s) in lower(body)) FROM project_docs WHERE repo_url=%s AND (body ILIKE %s OR name ILIKE %s)"
    like = "%" + term.replace("%", r"\%").replace("_", r"\_") + "%"
    args = [term, repo_url, like, like]
    if kind:
        q += " AND kind=%s"; args.append(kind)
    return conn.execute(q + " ORDER BY kind, name LIMIT %s", args + [limit]).fetchall()


def snippet(body, term, width=60):
    i = body.lower().find(term.lower())
    if i < 0:
        return ""
    a, b = max(0, i - width), min(len(body), i + len(term) + width)
    return ("…" if a else "") + body[a:b].replace("\n", " ") + ("…" if b < len(body) else "")


def import_files(conn, repo_url, kind, files, base, host, masker=None, prefix="", status=None, dry_run=False):
    """파일 목록을 올린다. [(경로, 이름, 결과)] — 결과: created · updated · same · 건너뜀(이유) · 거부(이유). 멱등."""
    out = []
    for path in files:
        name = name_from_path(path, base, prefix)
        body, why = read_text(path)
        if body is None:
            out.append((path, name, f"건너뜀: {why}")); continue
        if dry_run:
            cur = get(conn, repo_url, kind, name)
            out.append((path, name, "created" if cur is None else ("same" if sha(cur["body"]) == sha(body) else "updated"))); continue
        code, msg, act = put(conn, repo_url, kind, name, body, host, masker=masker, status=status, origin_path=os.path.abspath(path))
        out.append((path, name, act if code == 0 else f"거부: {msg.split(': ', 1)[-1]}"))
    if not dry_run:
        conn.commit()
    return out
