#!/usr/bin/env python3
"""ctxdata — ctxui 가 쓰는 조회·관리 함수(DB). 화면 코드(ctxui.py)와 분리해 DB 만으로 시험한다.

모든 함수는 psycopg 연결(conn)을 받는다. 읽기 함수는 masker 를 받아 출력 문자열을 치환한다(기본은 치환 안 함 — ctxui 가 사람 화면이라 켜고 끄는 것은 화면이 정한다).
"""
from __future__ import annotations

import re

import ctx_instr as ci
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


# ---------------------------------------------------------------- 통계
# 합계가 필요한 토큰·비용은 요청 단위인 usage_events 로만 센다(messages 의 usage 는 resume/fork 로 이중 계산되므로 쓰지 않는다 — schema.sql 참고).
# 한계: usage_events 는 OTel 수집을 켠 시점부터만 있다(coverage() 로 시작 시각을 화면에 보인다).
BUCKETS = {"hour": "시간", "day": "일", "week": "주", "month": "월"}
BREAKDOWNS = {"model": "모델", "repo": "저장소", "host": "머신", "source": "출처", "effort": "effort"}
_BREAK_SQL = {"model": "coalesce(u.model, '(모름)')", "repo": "coalesce(s.repo_url, '(저장소 없음)')", "host": "u.host",
              "source": "coalesce(u.query_source, '(모름)')", "effort": "coalesce(u.effort, '(모름)')"}


def local_tz() -> str:
    """로컬 시간대 이름(IANA). 못 구하면 UTC — 일·시간 묶음이 사용자의 하루 경계와 맞도록 DB 쪽에서 이 값으로 자른다."""
    import os
    p = os.path.realpath("/etc/localtime")
    return p.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in p else "UTC"


def _usage_where(days, repo, host, model):
    where, args = [], []
    if days:
        where.append("u.ts > now() - make_interval(days => %s)"); args.append(days)
    if repo:
        where.append("s.repo_url ILIKE %s"); args.append(_like(repo))
    if host:
        where.append("u.host ILIKE %s"); args.append(_like(host))
    if model:
        where.append("u.model ILIKE %s"); args.append(_like(model))
    return (" WHERE " + " AND ".join(where)) if where else "", args


_USAGE_COLS = """count(*) AS requests, coalesce(sum(u.cost_usd), 0) AS cost, coalesce(sum(u.input_tokens), 0) AS input,
                 coalesce(sum(u.output_tokens), 0) AS output, coalesce(sum(u.cache_read_tokens), 0) AS cache_read,
                 coalesce(sum(u.cache_create_tokens), 0) AS cache_create"""
_USAGE_KEYS = ("requests", "cost", "input", "output", "cache_read", "cache_create")


def coverage(conn):
    """(usage_events 첫·마지막 시각, 세션 첫 시각) — 비용 통계가 어디부터 있는지 화면에 알린다."""
    u = conn.execute("SELECT min(ts), max(ts) FROM usage_events").fetchone()
    s = conn.execute("SELECT min(first_ts) FROM sessions").fetchone()
    return dict(usage_first=u[0], usage_last=u[1], sessions_first=s[0])


def usage_trend(conn, *, days=None, bucket="day", repo=None, host=None, model=None, tz=None):
    """기간별 토큰·비용 추이(오래된 것부터). bucket: hour|day|week|month. 필터는 부분 일치, days=None 이면 전체 기간."""
    if bucket not in BUCKETS:
        raise ValueError(f"bucket 은 {'|'.join(BUCKETS)} 중 하나")
    where, args = _usage_where(days, repo, host, model)
    where += (" AND " if where else " WHERE ") + "u.ts IS NOT NULL"
    sql = f"""SELECT date_trunc('{bucket}', u.ts AT TIME ZONE %s) AS b, {_USAGE_COLS}
              FROM usage_events u LEFT JOIN sessions s USING (session_id){where} GROUP BY 1 ORDER BY 1"""
    return [dict(bucket=r[0], **dict(zip(_USAGE_KEYS, r[1:]))) for r in conn.execute(sql, [tz or local_tz(), *args]).fetchall()]


def usage_breakdown(conn, by="model", *, days=None, repo=None, host=None, model=None):
    """분류(모델·저장소·머신·출처·effort)별 합계(비용 큰 순)와 전체 합계. 반환: (행 목록, 합계 dict)."""
    if by not in _BREAK_SQL:
        raise ValueError(f"by 는 {'|'.join(_BREAK_SQL)} 중 하나")
    where, args = _usage_where(days, repo, host, model)
    rows = conn.execute(f"""SELECT {_BREAK_SQL[by]} AS k, {_USAGE_COLS} FROM usage_events u LEFT JOIN sessions s USING (session_id){where}
                            GROUP BY 1 ORDER BY 3 DESC, 2 DESC""", args).fetchall()
    out = [dict(key=r[0], **dict(zip(_USAGE_KEYS, r[1:]))) for r in rows]
    tot = {k: sum(r[k] for r in out) for k in _USAGE_KEYS}
    return out, tot


def _session_filters(days, repo, host, model, session_id=None):
    """세션 통계 공통 필터. days 는 「그 기간에 활동(메시지·요청)이 있는 세션」, model 은 그 모델 요청이 있는 세션."""
    where, args = [], []
    if session_id:
        where.append("s.session_id = %s"); args.append(session_id)
    if repo:
        where.append("s.repo_url ILIKE %s"); args.append(_like(repo))
    if host:
        where.append("(s.host ILIKE %s OR EXISTS (SELECT 1 FROM unnest(s.hosts) h WHERE h ILIKE %s))"); args += [_like(host)] * 2
    if model:
        where.append("EXISTS (SELECT 1 FROM usage_events x WHERE x.session_id = s.session_id AND x.model ILIKE %s)"); args.append(_like(model))
    if days:
        where.append("s.last_ts > now() - make_interval(days => %s)"); args.append(days)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def session_stats(conn, *, days=None, repo=None, host=None, model=None, session_id=None, order="cost", limit=300, masker=cs.IDENTITY):
    """세션별 통계 표. order: cost|last|prompts|tools|duration. title 은 그 세션 첫 사용자 프롬프트(앞부분).
    prompts/tools 는 서브에이전트(sidechain) 제외, subagent_msgs 는 서브에이전트 쪽 메시지 수, turn_ms 는 턴 소요 시간 합(turn_duration)."""
    orders = {"cost": "cost DESC NULLS LAST", "last": "s.last_ts DESC NULLS LAST", "prompts": "prompts DESC", "tools": "tools DESC", "duration": "duration_s DESC NULLS LAST"}
    if order not in orders:
        raise ValueError(f"order 는 {'|'.join(orders)} 중 하나")
    where, args = _session_filters(days, repo, host, model, session_id)
    sql = f"""
      WITH m AS (
        SELECT session_id,
               count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain) AS prompts,
               count(*) FILTER (WHERE kind = 'response' AND NOT is_sidechain) AS responses,
               count(*) FILTER (WHERE kind = 'tool_use' AND NOT is_sidechain) AS tools,
               count(*) FILTER (WHERE is_sidechain) AS subagent_msgs,
               coalesce(sum((raw->>'durationMs')::bigint) FILTER (WHERE raw->>'subtype' = 'turn_duration' AND NOT is_sidechain), 0) AS turn_ms,
               count(*) FILTER (WHERE raw->>'subtype' = 'compact_boundary') AS compacts
        FROM messages GROUP BY session_id),
      u AS (
        SELECT session_id, count(*) AS requests, sum(cost_usd) AS cost, sum(input_tokens + cache_read_tokens + cache_create_tokens) AS input,
               sum(output_tokens) AS output, array_agg(DISTINCT model) FILTER (WHERE model IS NOT NULL) AS models
        FROM usage_events GROUP BY session_id),
      t AS (
        SELECT DISTINCT ON (session_id) session_id, text FROM messages WHERE kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') <> ''
        ORDER BY session_id, ts)
      SELECT s.session_id, s.repo_url, s.host, s.branch, s.cwd, s.first_ts, s.last_ts, extract(epoch FROM s.last_ts - s.first_ts) AS duration_s,
             coalesce(m.prompts, 0) AS prompts, coalesce(m.responses, 0), coalesce(m.tools, 0) AS tools, coalesce(m.subagent_msgs, 0), coalesce(m.turn_ms, 0), coalesce(m.compacts, 0),
             coalesce(u.requests, 0), u.cost, coalesce(u.input, 0), coalesce(u.output, 0), coalesce(u.models, '{{}}'), left(t.text, 200)
      FROM sessions s LEFT JOIN m USING (session_id) LEFT JOIN u USING (session_id) LEFT JOIN t USING (session_id){where}
      ORDER BY {orders[order]} LIMIT %s"""
    keys = ("session_id", "repo", "host", "branch", "cwd", "first", "last", "duration_s", "prompts", "responses", "tools", "subagent_msgs",
            "turn_ms", "compacts", "requests", "cost", "input", "output", "models", "title")
    out = []
    for r in conn.execute(sql, [*args, limit]).fetchall():
        d = dict(zip(keys, r))
        d["title"] = masker.text((d["title"] or "").replace("\n", " ").strip())
        out.append(d)
    return out


def session_summary(conn, *, days=None, repo=None, host=None, model=None, tz=None):
    """세션 통계 요약: 개수·세션당 평균·중앙값, 시간대별(0~23시)·요일별(월~일) 사용자 프롬프트 수. 필터는 session_stats 와 같다."""
    where, args = _session_filters(days, repo, host, model)
    tz = tz or local_tz()
    row = conn.execute(f"""
      WITH base AS (SELECT s.session_id, s.first_ts, s.last_ts FROM sessions s{where}),
           m AS (SELECT session_id, count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain) AS prompts,
                        count(*) FILTER (WHERE kind = 'tool_use' AND NOT is_sidechain) AS tools FROM messages WHERE session_id IN (SELECT session_id FROM base) GROUP BY 1),
           u AS (SELECT session_id, sum(cost_usd) AS cost FROM usage_events WHERE session_id IN (SELECT session_id FROM base) GROUP BY 1)
      SELECT count(*), coalesce(sum(m.prompts), 0), coalesce(sum(m.tools), 0), coalesce(sum(u.cost), 0),
             coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM b.last_ts - b.first_ts)), 0),
             coalesce(avg(extract(epoch FROM b.last_ts - b.first_ts)), 0), coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY m.prompts), 0)
      FROM base b LEFT JOIN m USING (session_id) LEFT JOIN u USING (session_id)""", args).fetchone()
    mwhere = ["m.kind = 'prompt'", "NOT m.is_sidechain", "m.ts IS NOT NULL", "m.session_id IN (SELECT session_id FROM sessions s" + where + ")"]
    margs = list(args)
    if days:
        mwhere.append("m.ts > now() - make_interval(days => %s)"); margs.append(days)
    hours, wdays = [0] * 24, [0] * 7
    for h, wd, n in conn.execute(f"""SELECT extract(hour FROM m.ts AT TIME ZONE %s)::int, extract(isodow FROM m.ts AT TIME ZONE %s)::int, count(*)
                                     FROM messages m WHERE {' AND '.join(mwhere)} GROUP BY 1, 2""", [tz, tz, *margs]).fetchall():
        hours[h] += n
        wdays[wd - 1] += n
    return dict(sessions=row[0], prompts=row[1], tools=row[2], cost=float(row[3]), median_duration_s=float(row[4]), avg_duration_s=float(row[5]),
                median_prompts=float(row[6]), by_hour=hours, by_weekday=wdays)


def session_tools(conn, session_id, top=6):
    """그 세션에서 많이 쓴 도구 [(이름, 횟수)] — tool_use 텍스트 앞머리 `[tool_use 이름]` 에서 읽는다(서브에이전트 제외)."""
    rows = conn.execute("""SELECT substring(text FROM '^\\[tool_use (\\S+)\\]') AS tool, count(*) FROM messages
                           WHERE session_id = %s AND kind = 'tool_use' AND NOT is_sidechain GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""", (session_id, top)).fetchall()
    return [(r[0] or "(모름)", r[1]) for r in rows]


def session_links(conn, session_id, masker=cs.IDENTITY):
    """resume/fork 로 이어진 세션. 새 트랜스크립트는 옛 메시지를 같은 uuid 로 복사하므로, 이 세션 메시지의 parent_uuid 가 다른 세션의 메시지를 가리키면 그 세션이 앞(parents),
    다른 세션 메시지의 parent_uuid 가 이 세션을 가리키면 뒤(children)다. 각 항목: session_id·first·last·title(첫 프롬프트), 오래된 순."""
    def titled(rows):
        out = []
        for sid, first, last in rows:
            t = conn.execute("""SELECT left(text, 120) FROM messages WHERE session_id = %s AND kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') <> ''
                                ORDER BY ts LIMIT 1""", (sid,)).fetchone()
            out.append(dict(session_id=sid, first=first, last=last, title=masker.text(((t[0] if t else "") or "").replace("\n", " ").strip())))
        return out
    parents = conn.execute("""SELECT s.session_id, s.first_ts, s.last_ts FROM sessions s WHERE s.session_id IN
                                (SELECT DISTINCT p.session_id FROM messages m JOIN messages p ON p.uuid = m.parent_uuid WHERE m.session_id = %s AND p.session_id <> %s)
                              ORDER BY s.first_ts""", (session_id, session_id)).fetchall()
    children = conn.execute("""SELECT s.session_id, s.first_ts, s.last_ts FROM sessions s WHERE s.session_id IN
                                 (SELECT DISTINCT m.session_id FROM messages m JOIN messages p ON p.uuid = m.parent_uuid WHERE p.session_id = %s AND m.session_id <> %s)
                               ORDER BY s.first_ts""", (session_id, session_id)).fetchall()
    return dict(parents=titled(parents), children=titled(children))


def filter_choices(conn):
    """필터 입력 힌트용: 머신·모델 목록."""
    hosts = [r[0] for r in conn.execute("SELECT DISTINCT host FROM sessions ORDER BY 1").fetchall()]
    models = [r[0] for r in conn.execute("SELECT DISTINCT model FROM usage_events WHERE model IS NOT NULL ORDER BY 1").fetchall()]
    return dict(hosts=hosts, models=models)


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
    titles = session_titles(conn, {h["session_id"] for h in out}, masker)
    for h in out:
        h["title"] = titles.get(h["session_id"], "")
    return out


def session_titles(conn, session_ids, masker=cs.IDENTITY, width=120):
    """{세션 ID: 첫 사용자 프롬프트 앞부분} — 세션 목록·검색 결과에서 어느 대화인지 알아보는 제목으로 쓴다."""
    ids = sorted(session_ids)
    if not ids:
        return {}
    rows = conn.execute("""SELECT DISTINCT ON (session_id) session_id, left(text, %s) FROM messages
                           WHERE session_id = ANY(%s) AND kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') <> '' ORDER BY session_id, ts""", (width, ids)).fetchall()
    return {sid: masker.text((t or "").replace("\n", " ").strip()) for sid, t in rows}


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


# ---------------------------------------------------------------- 프로젝트 지침(ctx_instr) — ctxui 「지침」 탭
def instr_rows(conn):
    """공유 정본의 모든 저장소 지침 목록(저장소·이름 순). 로컬 캐시와 무관하게 DB 만 본다."""
    rows = conn.execute("SELECT repo_url, name, rev, updated_host, updated_at, length(body) FROM project_instructions ORDER BY repo_url, name").fetchall()
    return [dict(repo=r[0], name=r[1], rev=r[2], host=r[3], at=r[4], length=r[5]) for r in rows]


def instr_body(conn, repo, name, masker=cs.IDENTITY):
    """(rev, 본문) — 본문은 masker 로 치환한 화면용. 없으면 None. 편집용 원문은 instr_raw 를 쓴다(치환한 글자가 저장되면 안 된다)."""
    row = conn.execute("SELECT rev, body FROM project_instructions WHERE repo_url = %s AND name = %s", (repo, name)).fetchone()
    return None if not row else (row[0], masker.text(row[1]))


def instr_raw(conn, repo, name):
    """(rev, 원문 본문) — 편집기에 넘길 값. 없으면 None."""
    row = conn.execute("SELECT rev, body FROM project_instructions WHERE repo_url = %s AND name = %s", (repo, name)).fetchone()
    return None if not row else (row[0], row[1])


def instr_sections(body):
    """본문의 `## ` 절 제목 목록(머리말 길이 포함 안 함) — 화면 위쪽 요약용."""
    return [s.split("\n", 1)[0][3:].strip() for s in ci.split_sections(body)[1]]


def instr_save(conn, repo, name, body, host, expect_rev, masker=None):
    """편집 결과를 DB 에만 쓴다(로컬 캐시·상태는 건드리지 않음) — (결과코드, 메시지). 낡은 rev·비밀·빈 본문은 ci.set_body 가 거부한다."""
    return ci.set_body(conn, repo, None, name, body, host, masker=masker, expect_rev=expect_rev)
