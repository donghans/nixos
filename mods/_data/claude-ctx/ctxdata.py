#!/usr/bin/env python3
"""ctxdata — ctxui 가 쓰는 조회·관리 함수(DB). 화면 코드(ctxui.py)와 분리해 DB 만으로 시험한다.

모든 함수는 psycopg 연결(conn)을 받는다. 읽기 함수는 masker 를 받아 출력 문자열을 치환한다(기본은 치환 안 함 — ctxui 가 사람 화면이라 켜고 끄는 것은 화면이 정한다).
"""
from __future__ import annotations

import re

import ctx_secrets as cs


def human_bytes(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---------------------------------------------------------------- 개요
def overview(conn):
    """전체 합계 · 표별 크기 · 저장소(프로젝트)별 집계."""
    t = conn.execute("""SELECT (SELECT count(*) FROM sessions), (SELECT count(*) FROM messages),
                               (SELECT count(*) FROM messages WHERE kind='prompt'), (SELECT coalesce(sum(length(text)),0) FROM messages),
                               pg_database_size(current_database())""").fetchone()
    tables = conn.execute("""SELECT c.relname, pg_total_relation_size(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2 DESC""").fetchall()
    projects = conn.execute("""SELECT coalesce(s.repo_url, '(저장소 없음)') AS repo, count(DISTINCT s.session_id) AS sessions, count(m.uuid) AS messages,
                                      count(m.uuid) FILTER (WHERE m.kind = 'prompt') AS prompts,
                                      coalesce(sum(length(m.text)), 0) AS text_chars,
                                      coalesce(sum(pg_column_size(m.text) + pg_column_size(m.raw)), 0) AS stored_bytes,
                                      max(s.last_ts) AS last_ts, array_agg(DISTINCT s.host) AS hosts
                               FROM sessions s LEFT JOIN messages m USING (session_id) GROUP BY 1 ORDER BY 3 DESC""").fetchall()
    return dict(
        totals=dict(sessions=t[0], messages=t[1], prompts=t[2], text_chars=t[3], db_bytes=t[4]),
        tables=[dict(name=r[0], bytes=r[1]) for r in tables],
        projects=[dict(repo=r[0], sessions=r[1], messages=r[2], prompts=r[3], text_chars=r[4], stored_bytes=r[5], last_ts=r[6], hosts=[h for h in (r[7] or []) if h]) for r in projects],
    )


# ---------------------------------------------------------------- 검색 · 대조
def snippet(text: str, query: str, regex=False, width=240) -> str:
    if not text:
        return ""
    i = -1
    if query:
        if regex:
            m = re.search(query, text, re.I)
            i = m.start() if m else -1
        else:
            i = text.lower().find(query.lower())
    st = max((i if i >= 0 else 0) - 60, 0)
    return text[st:st + width].replace("\n", " ⏎ ").strip()


def search(conn, query="", *, regex=False, repo=None, role=None, kinds=("prompt", "response"), days=None, limit=200, masker=cs.IDENTITY):
    """메시지 검색. repo 는 URL 의 일부(부분 일치), role 은 user|assistant|None. 잘못된 정규식은 ValueError."""
    where, args = ["m.kind = ANY(%s)"], [list(kinds)]
    if query:
        if regex:
            try:
                re.compile(query)
            except re.error as e:
                raise ValueError(f"정규식 오류: {e}")
            where.append("m.text ~* %s"); args.append(query)
        else:
            where.append("m.text ILIKE %s"); args.append(_like(query))
    if repo:
        where.append("s.repo_url ILIKE %s"); args.append(_like(repo))
    if role:
        where.append("m.role = %s"); args.append(role)
    if days:
        where.append("m.ts > now() - make_interval(days => %s)"); args.append(days)
    sql = f"""SELECT m.ts, m.session_id, m.uuid, m.role, m.kind, s.repo_url, s.host, s.branch, m.text
              FROM messages m JOIN sessions s USING (session_id) WHERE {' AND '.join(where)} ORDER BY m.ts DESC LIMIT %s"""
    args.append(limit)
    out = []
    for ts, sid, uid, rl, kd, rurl, host, br, text in conn.execute(sql, args).fetchall():
        out.append(dict(ts=ts, session_id=sid, uuid=uid, role=rl, kind=kd, repo=rurl, host=host, branch=br,
                        snippet=snippet(masker.text(text or ""), query, regex), full=masker.text(text or "")))
    return out


def group_hits(hits):
    """search() 결과를 저장소별로 묶는다(저장소 이름이 정확히 같은 것끼리). 건수 많은 순."""
    groups = {}
    for h in hits:
        key = h["repo"] or "(저장소 없음)"
        g = groups.setdefault(key, dict(repo=key, count=0, sessions=set(), last=h["ts"], quote=h["snippet"], hits=[]))
        g["count"] += 1
        g["sessions"].add(h["session_id"])
        g["hits"].append(h)
    return sorted(({**g, "sessions": len(g["sessions"])} for g in groups.values()), key=lambda g: -g["count"])


def phrase_by_repo(conn, phrase, *, regex=False, role="user", days=None, masker=cs.IDENTITY):
    """같은 문구를 저장소(프로젝트)별로 묶어 건수·최근 시각·대표 인용을 낸다 — 「내가 그렇게 말했나」 교차검증용."""
    hits = search(conn, phrase, regex=regex, role=role, kinds=("prompt",) if role == "user" else ("prompt", "response"), days=days, limit=5000, masker=masker)
    return group_hits(hits)


def session_context(conn, session_id, around_uuid=None, window=12, kinds=("prompt", "response"), masker=cs.IDENTITY):
    """한 세션의 대화. around_uuid 가 있으면 그 메시지 앞뒤 window 개만. 반환: (세션 요약 dict, 메시지 목록)."""
    s = conn.execute("SELECT session_id, host, cwd, repo_url, branch, first_ts, last_ts FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
    if not s:
        return None, []
    rows = conn.execute("SELECT ts, uuid, role, kind, is_sidechain, text FROM messages WHERE session_id = %s AND kind = ANY(%s) ORDER BY ts, uuid", (session_id, list(kinds))).fetchall()
    msgs = [dict(ts=r[0], uuid=r[1], role=r[2], kind=r[3], side=r[4], text=masker.text(r[5] or "")) for r in rows]
    if around_uuid:
        idx = next((i for i, m in enumerate(msgs) if m["uuid"] == around_uuid), None)
        if idx is not None:
            msgs = msgs[max(idx - window, 0): idx + window + 1]
    return dict(session_id=s[0], host=s[1], cwd=s[2], repo=s[3], branch=s[4], first=s[5], last=s[6]), msgs


# ---------------------------------------------------------------- 비밀 등록표
def secret_rows(conn):
    rows = cs.load_secrets(conn, only_enabled=False)
    return [dict(label=r["label"], kind=r["kind"], enabled=r["enabled"], length=len(r["value"]), fp=cs.fingerprint(r["value"]), value=r["value"]) for r in rows]


def occurrences(conn, secret_value, kind="literal") -> int:
    """이 비밀이 DB 원문에 몇 개 메시지에 들어 있나(literal 은 trigram 인덱스, regex 는 순차 검색)."""
    if kind == "regex":
        return conn.execute("SELECT count(*) FROM messages WHERE text ~ %s", (secret_value,)).fetchone()[0]
    return conn.execute("SELECT count(*) FROM messages WHERE text LIKE %s", (_like(secret_value),)).fetchone()[0]


def set_enabled(conn, label, enabled: bool):
    cs.ensure_schema(conn)
    n = conn.execute("UPDATE secrets SET enabled = %s, updated_at = now() WHERE label = %s", (enabled, label)).rowcount
    conn.commit()
    return n


def delete_secret(conn, label):
    cs.ensure_schema(conn)
    n = conn.execute("DELETE FROM secrets WHERE label = %s", (label,)).rowcount
    conn.commit()
    return n


# ---------------------------------------------------------------- 후보
def ignored_fps(conn):
    import psycopg.errors as pe
    try:
        return {r[0] for r in conn.execute("SELECT fp FROM secret_ignores").fetchall()}
    except pe.UndefinedTable:
        conn.rollback()
        return set()


def scan_candidates(conn, days=None, min_count=1):
    """등록·무시되지 않은 후보 목록(횟수 많은 순). 각 항목에 value 가 들어 있으니 화면은 흐리게 보여야 한다."""
    q = "SELECT m.session_id, s.repo_url, m.ts, m.text FROM messages m LEFT JOIN sessions s USING (session_id) WHERE m.text IS NOT NULL"
    args = []
    if days:
        q += " AND m.ts > now() - make_interval(days => %s)"; args.append(days)

    def rows():
        with conn.cursor(name="ctxui_scan") as cur:
            cur.itersize = 2000
            cur.execute(q, args)
            yield from cur

    found = cs.scan_messages(rows(), cs.load_masker(conn), ignored_fps(conn))
    conn.rollback()  # 이름 있는 커서를 닫는다
    return sorted((d for d in found.values() if d["count"] >= min_count), key=lambda d: (-d["count"], d["fp"]))


def ignore_fp(conn, fp, pattern=None, note=None):
    cs.ensure_schema(conn)
    conn.execute("INSERT INTO secret_ignores (fp, pattern, note) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (fp, pattern, note))
    conn.commit()


def adopt(conn, value, label, pattern=None, note=None, force=False):
    cs.add_secret(conn, label, "literal", value, note or (f"ctxui 후보 승인({pattern})" if pattern else "ctxui 후보 승인"), False, force)
