#!/usr/bin/env python3
"""ctxdata — ctxui 가 쓰는 조회·관리 함수(DB). 화면 코드(ctxui.py)와 분리해 DB 만으로 시험한다.

모든 함수는 psycopg 연결(conn)을 받는다. 읽기 함수는 masker 를 받아 출력 문자열을 치환한다(기본은 치환 안 함 — ctxui 가 사람 화면이라 켜고 끄는 것은 화면이 정한다).
"""
from __future__ import annotations

import re

import ctx_instr as ci
import ctx_secrets as cs


# ---------------------------------------------------------------- 메시지 종류(자동 메시지 vs 사람) — 설계: _plan/ctx-message-kinds.md
# Claude Code 가 `user`·`prompt` 로 저장하는 자동 메시지는 `<태그>` 로 시작한다. 분류는 **행 단위, 메시지의 첫 태그 기준**이고 SQL(`~`)과 파이썬(`re`)이
# **같은 패턴 문자열**을 쓴다(공백은 `[ \t\r\n]` 만, 유니코드 공백·BOM 으로 시작하면 사람으로 둔다 — 알려진 한계).
AUTO_TAGS = ("task-notification", "local-command-stdout", "local-command-caveat", "bash-stdout", "system-reminder")   # 사람 말이 아님 — 통계·F2·대조에서 뺀다
CMD_TAGS = ("command-message", "command-name")      # 스킬·슬래시 명령 호출(사람이 호출) — 통계에는 들어가되 제목 후보로는 뒤로 민다
SHELL_TAGS = ("bash-input",)                         # `!명령` 입력(사람)
HUMAN_TAGS = ("pasted_content",)                     # 사람이 붙여 넣은 내용(사람)
KNOWN_TAGS = AUTO_TAGS + CMD_TAGS + SHELL_TAGS + HUMAN_TAGS
_AFTER = "[ >\r\n]"


def _tag_re(tags) -> str:
    return "^[ \t\r\n]*<(" + "|".join(tags) + ")" + _AFTER


AUTO_RE = _tag_re(AUTO_TAGS)                         # 첫 태그가 자동
NOTPLAIN_RE = _tag_re(AUTO_TAGS + CMD_TAGS + SHELL_TAGS)   # 제목 후보에서 밀리는 것(자동·명령·셸 입력)
UNKNOWN_RE = "^[ \t\r\n]*<(?!(?:" + "|".join(KNOWN_TAGS) + ")" + _AFTER + ")[a-zA-Z_][a-zA-Z0-9_-]*" + _AFTER   # 알려지지 않은 태그로 시작
_FIRST = re.compile("^[ \t\r\n]*<([a-zA-Z_][a-zA-Z0-9_-]*)" + _AFTER)
CAT_LABEL = {"human": "", "command": "스킬 호출", "shell": "셸 입력", "pasted": "붙여넣기", "task": "작업 알림", "localcmd": "명령 출력",
             "reminder": "시스템 알림", "meta": "주입", "unknown": "태그"}
META_LABEL = (("Base directory", "스킬 본문"), ("Another Claude", "다른 세션 메시지"), ("[Cross-session", "교차 세션"), ("[Image", "이미지 표지"),
              ("<local-command", "명령 출력"), ("<system-remind", "시스템 알림"))


def _inner(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else ""


def classify(role: str, kind: str, text: str | None):
    """(분류, 한 줄 요약) — 분류는 CAT_LABEL 의 키. 요약이 빈 문자열이면 원문을 그대로 보이면 된다.
    자동·meta 인지(통계·F2·대조에서 뺄지)는 `is_auto` 로 본다."""
    t = text or ""
    if kind == "meta":
        head = t.lstrip()
        sub = next((lb for pre, lb in META_LABEL if head.startswith(pre)), "")
        return "meta", sub + (": " if sub else "") + " ".join(head.split())[:100]
    if kind != "prompt" or role != "user":
        return "human", ""
    m = _FIRST.match(t)
    if not m:
        return "human", ""
    tag = m.group(1)
    if tag == "task-notification":
        st, sm = _inner(t, "status"), _inner(t, "summary")
        return "task", f"[{st or '작업'}] {sm}".strip() if sm or st else ""
    if tag in ("local-command-stdout", "local-command-caveat", "bash-stdout"):
        return "localcmd", (" ".join(_inner(t, tag).split())[:100] or "(빈 출력)")
    if tag == "system-reminder":
        return "reminder", " ".join(_inner(t, tag).split())[:100]
    if tag in CMD_TAGS:
        return "command", command_summary(t)
    if tag == "bash-input":
        return "shell", "! " + " ".join(_inner(t, tag).split())[:100]
    if tag == "pasted_content":
        return "pasted", " ".join(_inner(t, tag).split())[:300]      # 태그를 벗긴 본문(펼치면 원문)
    return "unknown", ""


def command_summary(text: str) -> str:
    """스킬 호출 메시지 → `/이름 인자`. 이름은 `<command-name>` 내용(슬래시 없으면 붙임), 인자는 `<command-args>` 내용(개행→공백, 120자)."""
    name = _inner(text, "command-name") or _inner(text, "command-message")
    if not name:
        return ""
    args = " ".join(_inner(text, "command-args").split())[:120]
    return ("" if name.startswith("/") else "/") + name + (" " + args if args else "")


def is_auto(role: str, kind: str, text: str | None) -> bool:
    """통계·F2·대조에서 사람 발언으로 세지 않는 메시지(자동 메시지·meta)."""
    return kind == "meta" or classify(role, kind, text)[0] in ("task", "localcmd", "reminder")


def title_text(raw: str | None, masker=cs.IDENTITY, width=120) -> str:
    """세션 제목용 텍스트. **치환을 먼저 하고 자른다**(자르는 경계에서 비밀이 반쯤 남는 것을 막음). 스킬 호출이면 `/이름 인자` 로 바꾼다."""
    t = masker.text(raw or "")
    if _FIRST.match(t) and _FIRST.match(t).group(1) in CMD_TAGS:
        t = command_summary(t) or t
    return t.replace("\n", " ").strip()[:width]


TITLE_RANK_SQL = "(CASE WHEN coalesce(text, '') ~ %s THEN 2 WHEN coalesce(text, '') ~ %s THEN 1 ELSE 0 END)"   # 파라미터: AUTO_RE, NOTPLAIN_RE
TITLE_RANK_ARGS = (AUTO_RE, NOTPLAIN_RE)
TITLE_RAW = 2000          # 제목 후보로 SQL 에서 받아 오는 앞부분 길이(치환 후 자름)


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
                               (SELECT count(*) FROM messages WHERE kind='prompt' AND coalesce(text,'') !~ %s), (SELECT coalesce(sum(length(text)),0) FROM messages),
                               pg_database_size(current_database()), (SELECT count(*) FROM messages WHERE kind='prompt' AND text ~ %s)""", (AUTO_RE, AUTO_RE)).fetchone()
    tables = conn.execute("""SELECT c.relname, pg_total_relation_size(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2 DESC""").fetchall()
    projects = conn.execute("""SELECT coalesce(s.repo_url, '(저장소 없음)') AS repo, count(DISTINCT s.session_id) AS sessions, count(m.uuid) AS messages,
                                      count(m.uuid) FILTER (WHERE m.kind = 'prompt' AND coalesce(m.text, '') !~ %s) AS prompts,
                                      coalesce(sum(length(m.text)), 0) AS text_chars,
                                      coalesce(sum(pg_column_size(m.text) + pg_column_size(m.raw)), 0) AS stored_bytes,
                                      max(s.last_ts) AS last_ts, array_agg(DISTINCT s.host) AS hosts
                               FROM sessions s LEFT JOIN messages m USING (session_id) GROUP BY 1 ORDER BY 3 DESC""", (AUTO_RE,)).fetchall()
    return dict(
        totals=dict(sessions=t[0], messages=t[1], prompts=t[2], text_chars=t[3], db_bytes=t[4], auto_prompts=t[5]),
        tables=[dict(name=r[0], bytes=r[1]) for r in tables],
        projects=[dict(repo=r[0], sessions=r[1], messages=r[2], prompts=r[3], text_chars=r[4], stored_bytes=r[5], last_ts=r[6], hosts=[h for h in (r[7] or []) if h]) for r in projects],
    )


# ---------------------------------------------------------------- 통계
# 합계가 필요한 토큰·비용은 요청 단위인 usage_events 로만 센다(messages 의 usage 는 resume/fork 로 이중 계산되므로 쓰지 않는다 — schema.sql 참고).
# 한계: usage_events 는 OTel 수집을 켠 시점부터만 있다(coverage() 로 시작 시각을 화면에 보인다).
BUCKETS = {"hour": "시간", "day": "일", "week": "주", "month": "월"}
BREAKDOWNS = {"model": "모델", "repo": "저장소", "account": "계정", "host": "머신", "source": "출처", "effort": "effort"}
_BREAK_SQL = {"model": "coalesce(u.model, '(모름)')", "repo": "coalesce(s.repo_url, '(저장소 없음)')", "host": "u.host",
              "source": "coalesce(u.query_source, '(모름)')", "effort": "coalesce(u.effort, '(모름)')",
              "account": "coalesce(u.account_email, u.account_id, '(계정 불명)')"}      # 요청별 계정(OTel user.email) — 수집 전·원본 없는 기록은 「(계정 불명)」


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


def limit_windows(conn, *, days=None, host=None, last=48):
    """계정별 한도 창(5h·7d)마다 찍은 최고 %. {kind: [{account, label, plan, windows:[(리셋시각, 최고%)…오래된 것부터 last 개]}…]}.
    계정은 account_id(없으면 '?'), 창은 리셋 시각으로 가른다. 라벨은 이메일."""
    out = {}
    for kind, pct, rs in (("5h", "five_hour_pct", "five_hour_resets_at"), ("7d", "seven_day_pct", "seven_day_resets_at")):
        where, args = f"{pct} IS NOT NULL AND {rs} IS NOT NULL", []
        if days:
            where += " AND ts > now() - make_interval(days => %s)"; args.append(days)
        if host:
            where += " AND host ILIKE %s"; args.append(_like(host))
        rows = conn.execute(f"""SELECT coalesce(account_id, '?'), max(account_email), max(account_plan), {rs}, max({pct})
                  FROM limit_samples WHERE {where} GROUP BY 1, {rs} ORDER BY 1, {rs}""", args).fetchall()
        accts = {}
        for aid, email, plan, r, mx in rows:
            a = accts.setdefault(aid, dict(account=aid, label=email or ("계정 불명" if aid == "?" else aid[:8]), plan=plan, windows=[]))
            a["plan"] = a["plan"] or plan
            a["windows"].append((r, float(mx)))
        for a in accts.values():
            a["windows"] = a["windows"][-last:]
        out[kind] = sorted(accts.values(), key=lambda a: a["account"])
    return out


def usage_breakdown(conn, by="model", *, days=None, repo=None, host=None, model=None):
    """분류(모델·저장소·계정·머신·출처·effort)별 합계(비용 큰 순)와 전체 합계. 반환: (행 목록, 합계 dict)."""
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
               count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') !~ %s) AS prompts,
               count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain AND text ~ %s) AS autos,
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
        SELECT DISTINCT ON (session_id) session_id, left(text, {TITLE_RAW}) AS text FROM messages WHERE kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') <> ''
        ORDER BY session_id, {TITLE_RANK_SQL}, ts)
      SELECT s.session_id, s.repo_url, s.host, s.branch, s.cwd, s.first_ts, s.last_ts, extract(epoch FROM s.last_ts - s.first_ts) AS duration_s,
             coalesce(m.prompts, 0) AS prompts, coalesce(m.responses, 0), coalesce(m.tools, 0) AS tools, coalesce(m.subagent_msgs, 0), coalesce(m.turn_ms, 0), coalesce(m.compacts, 0),
             coalesce(u.requests, 0), u.cost, coalesce(u.input, 0), coalesce(u.output, 0), coalesce(u.models, '{{}}'), t.text, coalesce(m.autos, 0)
      FROM sessions s LEFT JOIN m USING (session_id) LEFT JOIN u USING (session_id) LEFT JOIN t USING (session_id){where}
      ORDER BY {orders[order]} LIMIT %s"""
    keys = ("session_id", "repo", "host", "branch", "cwd", "first", "last", "duration_s", "prompts", "responses", "tools", "subagent_msgs",
            "turn_ms", "compacts", "requests", "cost", "input", "output", "models", "title", "autos")
    out = []
    for r in conn.execute(sql, [AUTO_RE, AUTO_RE, *TITLE_RANK_ARGS, *args, limit]).fetchall():
        d = dict(zip(keys, r))
        d["title"] = title_text(d["title"], masker, 200)
        out.append(d)
    return out


def session_summary(conn, *, days=None, repo=None, host=None, model=None, tz=None):
    """세션 통계 요약: 개수·세션당 평균·중앙값, 시간대별(0~23시)·요일별(월~일) 사용자 프롬프트 수. 필터는 session_stats 와 같다."""
    where, args = _session_filters(days, repo, host, model)
    tz = tz or local_tz()
    row = conn.execute(f"""
      WITH base AS (SELECT s.session_id, s.first_ts, s.last_ts FROM sessions s{where}),
           m AS (SELECT session_id, count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') !~ %s) AS prompts,
                        count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain AND text ~ %s) AS autos,
                        count(*) FILTER (WHERE kind = 'prompt' AND NOT is_sidechain AND text ~ %s) AS unknowns,
                        count(*) FILTER (WHERE kind = 'tool_use' AND NOT is_sidechain) AS tools FROM messages WHERE session_id IN (SELECT session_id FROM base) GROUP BY 1),
           u AS (SELECT session_id, sum(cost_usd) AS cost FROM usage_events WHERE session_id IN (SELECT session_id FROM base) GROUP BY 1)
      SELECT count(*), coalesce(sum(m.prompts), 0), coalesce(sum(m.tools), 0), coalesce(sum(u.cost), 0),
             coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM b.last_ts - b.first_ts)), 0),
             coalesce(avg(extract(epoch FROM b.last_ts - b.first_ts)), 0), coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY m.prompts), 0),
             coalesce(sum(m.autos), 0), coalesce(sum(m.unknowns), 0)
      FROM base b LEFT JOIN m USING (session_id) LEFT JOIN u USING (session_id)""", [*args, AUTO_RE, AUTO_RE, UNKNOWN_RE]).fetchone()
    mwhere = ["m.kind = 'prompt'", "NOT m.is_sidechain", "m.ts IS NOT NULL", "m.session_id IN (SELECT session_id FROM sessions s" + where + ")"]
    margs = list(args)
    if days:
        mwhere.append("m.ts > now() - make_interval(days => %s)"); margs.append(days)
    mwhere.append("coalesce(m.text, '') !~ %s"); margs.append(AUTO_RE)
    hours, wdays = [0] * 24, [0] * 7
    for h, wd, n in conn.execute(f"""SELECT extract(hour FROM m.ts AT TIME ZONE %s)::int, extract(isodow FROM m.ts AT TIME ZONE %s)::int, count(*)
                                     FROM messages m WHERE {' AND '.join(mwhere)} GROUP BY 1, 2""", [tz, tz, *margs]).fetchall():
        hours[h] += n
        wdays[wd - 1] += n
    return dict(sessions=row[0], prompts=row[1], tools=row[2], cost=float(row[3]), median_duration_s=float(row[4]), avg_duration_s=float(row[5]),
                median_prompts=float(row[6]), autos=int(row[7]), unknown_tags=int(row[8]), by_hour=hours, by_weekday=wdays)


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
            out.append(dict(session_id=sid, first=first, last=last, title=session_titles(conn, [sid], masker).get(sid, "")))
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
    if role == "user":      # 「사용자 발언」 검색(F2·대조·CLI --role user)은 자동 메시지(작업 알림 등)를 사람 말로 세지 않는다
        where.append("NOT (m.kind = 'prompt' AND coalesce(m.text, '') ~ %s)"); args.append(AUTO_RE)
    if days:
        where.append("m.ts > now() - make_interval(days => %s)"); args.append(days)
    sql = f"""SELECT m.ts, m.session_id, m.uuid, m.role, m.kind, s.repo_url, s.host, s.branch, m.text
              FROM messages m JOIN sessions s USING (session_id) WHERE {' AND '.join(where)} ORDER BY m.ts DESC LIMIT %s"""
    args.append(limit)
    out = []
    for ts, sid, uid, rl, kd, rurl, host, br, text in conn.execute(sql, args).fetchall():
        cat = classify(rl, kd, text)[0]
        out.append(dict(ts=ts, session_id=sid, uuid=uid, role=rl, kind=kd, repo=rurl, host=host, branch=br, cat=cat,
                        snippet=snippet(masker.text(text or ""), query, regex), full=masker.text(text or "")))
    titles = session_titles(conn, {h["session_id"] for h in out}, masker)
    for h in out:
        h["title"] = titles.get(h["session_id"], "")
    return out


def group_sessions(hits, title_query=None, regex=False):
    """search() 결과(최근순)를 세션 단위로 묶는다 — 세션 기준 검색 목록용. 반환: 가장 최근 일치가 있는 세션이 앞인 리스트
    [{session_id, repo, host, title, last(가장 최근 일치 시각), count, hits(최근순)}].
    title_query 가 있으면 제목(첫 프롬프트 앞부분)에 일치하는 세션만 남긴다(「제목만」 보기)."""
    groups = {}
    for h in hits:
        g = groups.setdefault(h["session_id"], dict(session_id=h["session_id"], repo=h["repo"], host=h["host"], title=h.get("title", ""), last=h["ts"], count=0, hits=[]))
        g["count"] += 1
        g["hits"].append(h)
    out = list(groups.values())
    if title_query:
        try:
            rx = re.compile(title_query if regex else re.escape(title_query), re.I)
        except re.error:
            rx = None
        if rx:
            out = [g for g in out if rx.search(g["title"] or "")]
    return out


def session_titles(conn, session_ids, masker=cs.IDENTITY, width=120):
    """{세션 ID: 제목} — 세션 목록·검색 결과에서 어느 대화인지 알아보는 제목. 첫 「순수 사람」 프롬프트(자동 메시지·스킬 호출·셸 입력은 뒤로 밀림), 없으면 첫 스킬 호출(`/이름 인자`).
    치환을 먼저 하고 자른다."""
    ids = sorted(session_ids)
    if not ids:
        return {}
    rows = conn.execute(f"""SELECT DISTINCT ON (session_id) session_id, left(text, {TITLE_RAW}) FROM messages
                            WHERE session_id = ANY(%s) AND kind = 'prompt' AND NOT is_sidechain AND coalesce(text, '') <> '' ORDER BY session_id, {TITLE_RANK_SQL}, ts""", (ids, *TITLE_RANK_ARGS)).fetchall()
    return {sid: title_text(t, masker, width) for sid, t in rows}


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


def session_rows(conn, session_id, kinds=("prompt", "response")):
    """한 세션의 메시지 **원문**(치환 안 함) 전부와 세션 요약. 화면이 보일 창만 골라 치환하도록 치환과 분리했다
    (예전엔 대화 화면이 열릴 때마다 세션 전체를 치환해 메시지 수만 개짜리 세션에서 느렸다). 반환: (세션 요약 dict | None, 메시지 목록)."""
    s = conn.execute("SELECT session_id, host, cwd, repo_url, branch, first_ts, last_ts FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
    if not s:
        return None, []
    rows = conn.execute("SELECT ts, uuid, role, kind, is_sidechain, text FROM messages WHERE session_id = %s AND kind = ANY(%s) ORDER BY ts, uuid", (session_id, list(kinds))).fetchall()
    return (dict(session_id=s[0], host=s[1], cwd=s[2], repo=s[3], branch=s[4], first=s[5], last=s[6]),
            [dict(ts=r[0], uuid=r[1], role=r[2], kind=r[3], side=r[4], text=r[5] or "") for r in rows])


def session_context(conn, session_id, around_uuid=None, window=12, kinds=("prompt", "response"), masker=cs.IDENTITY):
    """한 세션의 대화. around_uuid 가 있으면 그 메시지 앞뒤 window 개만. 반환: (세션 요약 dict, 메시지 목록)."""
    summary, raw = session_rows(conn, session_id, kinds)
    if summary is None:
        return None, []
    msgs = [dict(m, text=masker.text(m["text"])) for m in raw]
    if around_uuid:
        idx = next((i for i, m in enumerate(msgs) if m["uuid"] == around_uuid), None)
        if idx is not None:
            msgs = msgs[max(idx - window, 0): idx + window + 1]
    return summary, msgs


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
