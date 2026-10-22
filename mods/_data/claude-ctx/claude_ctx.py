#!/usr/bin/env python3
"""claude-ctx — Claude Code 대화·사용량 공유 저장소(Postgres) 클라이언트.

  hook <이벤트>        훅에서 호출(stdin = 훅 JSON). 실패해도 조용히 끝난다(Claude 입력을 막지 않는다).
  ingest [--days N|--all] [--no-otel]   트랜스크립트·OTel·한도 기록을 따라잡는다(오프셋 기반, 여러 번 돌려도 안전).
  search <검색어> [--repo URL|--here] [--role user|assistant] [--days N] [--limit N]
  recent [--repo URL|--here] [--limit N]   최근 세션 목록
  session <세션ID접두> [--n N] [--full]    한 세션의 대화
  usage [--days N]     모델·일별 토큰/비용(요청 단위 usage_events 기준)
  sql "<SELECT ...>"   읽기 전용 질의
  handoff-put/handoff-get   인수인계 문서를 DB 에 올리고 받는다(머신이 달라도 resume)

접속: 환경변수 CLAUDE_CTX_DSN 또는 ~/.config/claude-ctx/dsn (권한 600). 머신 식별: CLAUDE_CTX_HOST 또는 hostname.
멱등: 모든 쓰기는 자연키 ON CONFLICT, 파일 수집은 (host,path) 어드바이저리 락 + 오프셋 갱신을 같은 트랜잭션에서.
"""
import argparse, glob, hashlib, json, os, re, socket, subprocess, sys, time

import psycopg
from psycopg.types.json import Jsonb

HOST = os.environ.get("CLAUDE_CTX_HOST") or socket.gethostname()
HOME = os.path.expanduser("~")
OTEL = os.path.join(HOME, ".local/share/claude-otel")
MAX_RAW = 100_000      # 원본 한 줄이 이보다 크면 잘라서 보관(정본은 트랜스크립트)
MAX_TEXT = 20_000      # 검색용 평문 상한


def dsn():
    d = os.environ.get("CLAUDE_CTX_DSN")
    if d:
        return d
    p = os.path.join(HOME, ".config/claude-ctx/dsn")
    return open(p).read().strip() if os.path.isfile(p) else sys.exit("DSN 없음: ~/.config/claude-ctx/dsn 또는 CLAUDE_CTX_DSN")


def connect(timeout=5, readonly=False):
    c = psycopg.connect(dsn(), connect_timeout=timeout, autocommit=False)
    if readonly:
        c.read_only = True
    return c


# ---------------------------------------------------------------- git 메타(작업 위치 식별)
_git_cache = {}


def _git(cwd, *a):
    try:
        r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def norm_repo(url):
    """ssh/https/.git 표기 차이를 없애 머신이 달라도 같은 저장소로 묶는다."""
    if not url:
        return None
    u = url.strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", u)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    u = re.sub(r"^(https?://)[^@/]+@", r"\1", u)  # 토큰/사용자 정보 제거
    return re.sub(r"\.git/?$", "", u).rstrip("/")


def git_meta(cwd):
    if not cwd:
        return {}
    if cwd in _git_cache:
        return _git_cache[cwd]
    m = {}
    if os.path.isdir(cwd):
        m = {"repo_url": norm_repo(_git(cwd, "remote", "get-url", "origin")),
             "repo_root": _git(cwd, "rev-parse", "--show-toplevel") or None,
             "branch": _git(cwd, "branch", "--show-current") or None,
             "head_sha": _git(cwd, "rev-parse", "--short", "HEAD") or None}
    _git_cache[cwd] = m
    return m


# ---------------------------------------------------------------- 쓰기: 세션
UPSERT_SESSION = """
INSERT INTO sessions (session_id, host, hosts, cwd, repo_url, repo_root, branch, head_sha, transcript, client_ver, first_ts, last_ts)
VALUES (%(sid)s, %(host)s, ARRAY[%(host)s], %(cwd)s, %(repo_url)s, %(repo_root)s, %(branch)s, %(head_sha)s, %(transcript)s, %(ver)s, %(first)s, %(last)s)
ON CONFLICT (session_id) DO UPDATE SET
  hosts = (SELECT array_agg(DISTINCT h) FROM unnest(sessions.hosts || %(host)s) h),
  cwd = coalesce(excluded.cwd, sessions.cwd), repo_url = coalesce(excluded.repo_url, sessions.repo_url),
  repo_root = coalesce(excluded.repo_root, sessions.repo_root), branch = coalesce(excluded.branch, sessions.branch),
  head_sha = coalesce(excluded.head_sha, sessions.head_sha), transcript = coalesce(sessions.transcript, excluded.transcript),
  client_ver = coalesce(excluded.client_ver, sessions.client_ver),
  first_ts = least(sessions.first_ts, excluded.first_ts), last_ts = greatest(sessions.last_ts, excluded.last_ts),
  updated_at = now()
"""


def upsert_session(cur, sid, cwd, transcript=None, ver=None, first=None, last=None, branch=None):
    g = git_meta(cwd)
    cur.execute(UPSERT_SESSION, dict(sid=sid, host=HOST, cwd=cwd, repo_url=g.get("repo_url"), repo_root=g.get("repo_root"),
                                     branch=g.get("branch") or branch, head_sha=g.get("head_sha"), transcript=transcript,
                                     ver=ver, first=first, last=last))


# ---------------------------------------------------------------- 트랜스크립트 파싱
def blocks_text(content):
    """메시지 content → (kind 후보, 평문)."""
    if isinstance(content, str):
        return "text", content
    parts, kinds = [], set()
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            kinds.add("text"); parts.append(b.get("text", ""))
        elif t == "tool_use":
            kinds.add("tool_use"); parts.append(f"[tool_use {b.get('name')}] " + json.dumps(b.get("input"), ensure_ascii=False)[:1500])
        elif t == "tool_result":
            kinds.add("tool_result")
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            parts.append("[tool_result] " + str(c or "")[:4000])
    k = "text" if "text" in kinds else ("tool_use" if "tool_use" in kinds else ("tool_result" if "tool_result" in kinds else "other"))
    return k, "\n".join(p for p in parts if p)


def parse_line(line, agent_id):
    line = line.replace("\\u0000", "")  # Postgres jsonb/text 는 NUL 을 못 담는다
    try:
        d = json.loads(line)
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("uuid") or d.get("type") not in ("user", "assistant", "system"):
        return None
    msg = d.get("message") or {}
    role = d["type"]
    k, text = blocks_text(msg.get("content")) if msg else ("other", d.get("content") if isinstance(d.get("content"), str) else "")
    if role == "user":
        kind = "meta" if d.get("isMeta") else ("tool_result" if k == "tool_result" else "prompt")
    elif role == "assistant":
        kind = "response" if k == "text" else ("tool_use" if k == "tool_use" else "other")
    else:
        kind = "other"
    u = msg.get("usage") or {}
    raw = line if len(line) <= MAX_RAW else None
    return dict(uuid=d["uuid"], sid=d.get("sessionId"), parent=d.get("parentUuid"), ts=d.get("timestamp"), role=role, kind=kind,
                side=bool(d.get("isSidechain")), agent=agent_id or d.get("agentId"), pid=d.get("promptId") or d.get("requestId"),
                cwd=d.get("cwd"), branch=d.get("gitBranch"), model=msg.get("model"), ver=d.get("version"),
                it=u.get("input_tokens"), ot=u.get("output_tokens"), cr=u.get("cache_read_input_tokens"), cc=u.get("cache_creation_input_tokens"),
                text=(text or "")[:MAX_TEXT].replace("\x00", ""),
                raw=Jsonb(json.loads(raw)) if raw else Jsonb({"truncated": True, "size": len(line), "head": line[:2000]}))


INSERT_MSG = """
INSERT INTO messages (uuid, session_id, host, parent_uuid, ts, role, kind, is_sidechain, agent_id, prompt_id, cwd, branch, model,
                      input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, text, raw, source)
VALUES (%(uuid)s, %(sid)s, %(host)s, %(parent)s, %(ts)s, %(role)s, %(kind)s, %(side)s, %(agent)s, %(pid)s, %(cwd)s, %(branch)s, %(model)s,
        %(it)s, %(ot)s, %(cr)s, %(cc)s, %(text)s, %(raw)s, 'transcript')
ON CONFLICT (uuid) DO NOTHING
"""


def lock_key(path):
    return int.from_bytes(hashlib.sha1(f"{HOST}:{path}".encode()).digest()[:8], "big", signed=True)


def read_new(cur, path):
    """(host,path) 오프셋 이후의 '완전한 줄'만 읽는다. 파일이 줄었으면 처음부터."""
    cur.execute("SELECT byte_offset FROM ingest_state WHERE host=%s AND path=%s", (HOST, path))
    row = cur.fetchone()
    off = row[0] if row else 0
    size = os.path.getsize(path)
    if size < off:
        off = 0
    if size == off:
        return off, off, []
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return off, off, []
    chunk = data[: end + 1]
    return off, off + len(chunk), chunk.decode("utf-8", "replace").splitlines()


def ingest_transcript(conn, path):
    """한 트랜스크립트 파일의 새 줄을 넣는다. 반환: 넣으려 한 메시지 수(-1 = 다른 프로세스가 처리 중이라 건너뜀)."""
    agent = None
    m = re.search(r"/subagents/(?:agent-)?([^/]+)\.jsonl$", path)
    if m:
        agent = m.group(1)
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key(path),))
        if not cur.fetchone()[0]:
            return -1
        old, new, lines = read_new(cur, path)
        rows = [r for r in (parse_line(l, agent) for l in lines) if r]
        by_sid = {}
        for r in rows:
            r["host"] = HOST
            if not r["sid"]:
                continue
            s = by_sid.setdefault(r["sid"], dict(cwd=None, ver=None, first=r["ts"], last=r["ts"], branch=None))
            s["cwd"] = r["cwd"] or s["cwd"]; s["ver"] = r["ver"] or s["ver"]; s["branch"] = r["branch"] or s["branch"]
            if r["ts"]:
                s["first"] = min(filter(None, [s["first"], r["ts"]])); s["last"] = max(filter(None, [s["last"], r["ts"]]))
        for sid, s in by_sid.items():
            upsert_session(cur, sid, s["cwd"], path if not agent else None, s["ver"], s["first"], s["last"], s["branch"])
        rows = [r for r in rows if r["sid"]]
        if rows:
            cur.executemany(INSERT_MSG, rows)
        cur.execute("""INSERT INTO ingest_state (host, path, byte_offset) VALUES (%s,%s,%s)
                       ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (HOST, path, new))
        return len(rows)


def transcript_family(path):
    """본 트랜스크립트 + 서브에이전트 기록."""
    base = path[:-6] if path.endswith(".jsonl") else path
    return [path] + sorted(glob.glob(base + "/subagents/*.jsonl"))


# ---------------------------------------------------------------- OTel / 한도
def ingest_otel(conn):
    n = 0
    p = os.path.join(OTEL, "events.jsonl")
    if os.path.isfile(p):
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key(p),))
            if cur.fetchone()[0]:
                old, new, lines = read_new(cur, p)
                rows = []
                for l in lines:
                    try:
                        d = json.loads(l)
                    except Exception:
                        continue
                    for rl in d.get("resourceLogs", []):
                        for sl in rl.get("scopeLogs", []):
                            for r in sl.get("logRecords", []):
                                if (r.get("body") or {}).get("stringValue") != "claude_code.api_request":
                                    continue
                                a = {x["key"]: next(iter(x["value"].values()), None) for x in r.get("attributes", [])}
                                if not a.get("request_id"):
                                    continue
                                f = lambda k: float(a[k]) if a.get(k) not in (None, "") else None
                                i = lambda k: int(a[k]) if a.get(k) not in (None, "") else None
                                rows.append(dict(rid=a["request_id"], host=HOST, ts=a.get("event.timestamp"), sid=a.get("session.id"), pid=a.get("prompt.id"),
                                                 model=a.get("model"), it=i("input_tokens"), ot=i("output_tokens"), cr=i("cache_read_tokens"),
                                                 cc=i("cache_creation_tokens"), cost=f("cost_usd"), dur=i("duration_ms"), qs=a.get("query_source"),
                                                 eff=a.get("effort"), spd=a.get("speed")))
                if rows:
                    cur.executemany("""INSERT INTO usage_events (request_id, host, ts, session_id, prompt_id, model, input_tokens, output_tokens,
                        cache_read_tokens, cache_create_tokens, cost_usd, duration_ms, query_source, effort, speed)
                        VALUES (%(rid)s,%(host)s,%(ts)s,%(sid)s,%(pid)s,%(model)s,%(it)s,%(ot)s,%(cr)s,%(cc)s,%(cost)s,%(dur)s,%(qs)s,%(eff)s,%(spd)s)
                        ON CONFLICT (request_id) DO NOTHING""", rows)
                cur.execute("""INSERT INTO ingest_state (host, path, byte_offset) VALUES (%s,%s,%s)
                               ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (HOST, p, new))
                n += len(rows)
    p = os.path.join(OTEL, "limits.jsonl")
    if os.path.isfile(p):
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key(p),))
            if cur.fetchone()[0]:
                old, new, lines = read_new(cur, p)
                rows = []
                for l in lines:
                    try:
                        d = json.loads(l)
                    except Exception:
                        continue
                    rows.append(dict(host=HOST, ts=d.get("ts"), sid=d.get("session_id") or "", f=(d.get("five_hour") or {}).get("used_percentage"),
                                     w=(d.get("seven_day") or {}).get("used_percentage"), cost=d.get("cost_usd"), model=d.get("model"), ctx=d.get("context_used_pct")))
                if rows:
                    cur.executemany("""INSERT INTO limit_samples (host, ts, session_id, five_hour_pct, seven_day_pct, cost_usd, model, ctx_pct)
                        VALUES (%(host)s,%(ts)s,%(sid)s,%(f)s,%(w)s,%(cost)s,%(model)s,%(ctx)s) ON CONFLICT DO NOTHING""", rows)
                cur.execute("""INSERT INTO ingest_state (host, path, byte_offset) VALUES (%s,%s,%s)
                               ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (HOST, p, new))
    return n


# ---------------------------------------------------------------- 명령
def cmd_hook(a):
    raw = sys.stdin.read()
    try:
        p = json.loads(raw)
    except Exception:
        return 0
    try:
        conn = connect(timeout=3)
        with conn:
            with conn.transaction():
                cur = conn.cursor()
                sid, cwd = p.get("session_id"), p.get("cwd")
                body = json.dumps(p, ensure_ascii=False, sort_keys=True)
                cur.execute("""INSERT INTO hook_events (host, session_id, event, prompt_id, cwd, payload, payload_md5)
                               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (HOST, sid, a.event, p.get("prompt_id"), cwd, Jsonb(p), hashlib.md5(body.encode()).hexdigest()))
                if sid:
                    upsert_session(cur, sid, cwd, p.get("transcript_path"))
            tp = p.get("transcript_path")
            if tp and os.path.isfile(tp) and a.event in ("Stop", "SubagentStop", "SessionEnd", "PreCompact", "UserPromptSubmit"):
                for f in transcript_family(tp):
                    ingest_transcript(conn, f)
            if a.event in ("Stop", "SessionEnd"):
                ingest_otel(conn)
    except Exception as e:  # 훅은 절대 입력을 막지 않는다 — 놓친 것은 ingest 가 따라잡는다
        try:
            open(os.path.join(OTEL, "claude-ctx-hook.err"), "a").write(f"{time.strftime('%F %T')} {a.event} {type(e).__name__}: {e}\n")
        except Exception:
            pass
    return 0


def cmd_ingest(a):
    conn = connect(timeout=10)
    files = glob.glob(os.path.join(HOME, ".claude/projects/*/*.jsonl")) + glob.glob(os.path.join(HOME, ".claude/projects/*/*/subagents/*.jsonl"))
    if not a.all:
        cut = time.time() - a.days * 86400
        files = [f for f in files if os.path.getmtime(f) >= cut]
    files.sort(key=os.path.getmtime)
    tot = 0
    for i, f in enumerate(files, 1):
        try:
            n = ingest_transcript(conn, f)
        except Exception as e:
            print(f"! {f}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        tot += max(n, 0)
        if i % 25 == 0:
            print(f"  {i}/{len(files)} 파일, 메시지 {tot}", flush=True)
    print(f"트랜스크립트 {len(files)}개, 처리 메시지 {tot}")
    if not a.no_otel:
        print("OTel/한도 행:", ingest_otel(conn))
    conn.commit()
    return 0


def _repo_filter(a):
    if getattr(a, "here", False):
        return git_meta(os.getcwd()).get("repo_url")
    return norm_repo(getattr(a, "repo", None))


def cmd_search(a):
    repo = _repo_filter(a)
    q = " ".join(a.query)
    sql = """SELECT m.ts, m.session_id, m.role, m.kind, s.host, s.repo_url, s.branch,
                    substring(m.text from greatest(position(lower(%s) in lower(m.text)) - 60, 1) for 240) AS snip
             FROM messages m JOIN sessions s USING (session_id)
             WHERE m.text ILIKE %s AND m.kind IN ('prompt','response')"""
    args = [q, f"%{q}%"]
    if repo:
        sql += " AND s.repo_url = %s"; args.append(repo)
    if a.role:
        sql += " AND m.role = %s"; args.append(a.role)
    if a.days:
        sql += " AND m.ts > now() - make_interval(days => %s)"; args.append(a.days)
    sql += " ORDER BY m.ts DESC LIMIT %s"; args.append(a.limit)
    with connect(readonly=True) as c:
        for ts, sid, role, kind, host, rurl, br, snip in c.execute(sql, args):
            print(f"[{ts:%Y-%m-%d %H:%M}] {sid[:8]} {role}/{kind} @{host} {rurl or '-'}#{br or '-'}\n  {snip.strip()!r}")
    return 0


def cmd_recent(a):
    repo = _repo_filter(a)
    sql = """SELECT s.session_id, s.last_ts, s.host, s.cwd, s.repo_url, s.branch, count(m.uuid) FILTER (WHERE m.kind='prompt') AS prompts,
                    (SELECT text FROM messages x WHERE x.session_id=s.session_id AND x.kind='prompt' ORDER BY x.ts LIMIT 1) AS first_prompt
             FROM sessions s LEFT JOIN messages m USING (session_id) WHERE (%s::text IS NULL OR s.repo_url = %s)
             GROUP BY s.session_id ORDER BY s.last_ts DESC NULLS LAST LIMIT %s"""
    with connect(readonly=True) as c:
        for sid, last, host, cwd, rurl, br, n, fp in c.execute(sql, (repo, repo, a.limit)):
            print(f"{sid}  {last:%m-%d %H:%M}  @{host}  {rurl or '-'}#{br or '-'}  {cwd}  프롬프트 {n}\n    첫 프롬프트: {(fp or '').strip()[:120]!r}")
    return 0


def cmd_session(a):
    with connect(readonly=True) as c:
        r = c.execute("SELECT session_id, host, hosts, cwd, repo_url, branch, first_ts, last_ts FROM sessions WHERE session_id LIKE %s", (a.sid + "%",)).fetchall()
        if len(r) != 1:
            print("일치하는 세션:", len(r), [x[0] for x in r]); return 1
        sid, host, hosts, cwd, rurl, br, f, l = r[0]
        print(f"# {sid}  @{','.join(hosts or [host])}  {rurl or '-'}#{br or '-'}  {cwd}\n# {f} ~ {l}")
        kinds = "('prompt','response','tool_use')" if a.full else "('prompt','response')"
        rows = c.execute(f"SELECT ts, role, kind, is_sidechain, text FROM messages WHERE session_id=%s AND kind IN {kinds} ORDER BY ts", (sid,)).fetchall()
        if a.n:
            rows = rows[-a.n:]
        for ts, role, kind, side, text in rows:
            print(f"\n[{ts:%m-%d %H:%M}] {role}{'(sub)' if side else ''}: {(text or '').strip()[: (None if a.full else 1500)]}")
    return 0


def cmd_usage(a):
    with connect(readonly=True) as c:
        for day, model, n, it, ot, cr, cost in c.execute(
            """SELECT date_trunc('day', ts)::date, model, count(*), sum(input_tokens), sum(output_tokens), sum(cache_read_tokens), sum(cost_usd)
               FROM usage_events WHERE ts > now() - make_interval(days => %s) GROUP BY 1,2 ORDER BY 1 DESC, 7 DESC""", (a.days,)):
            print(f"{day} {model or '?':22} 요청 {n:5}  in {it or 0:>9} out {ot or 0:>8} cache_read {cr or 0:>12}  ${cost or 0:.2f}")
    return 0


def cmd_sql(a):
    with connect(readonly=True) as c:
        cur = c.execute(a.query)
        print("\t".join(d.name for d in cur.description))
        for row in cur.fetchmany(a.limit):
            print("\t".join("" if v is None else str(v)[:300] for v in row))
    return 0


def cmd_handoff_put(a):
    doc = os.path.abspath(a.doc)
    base = os.path.splitext(doc)[0].replace("HANDOFF-", "")
    ddir = os.path.join(os.path.dirname(doc), a.session)
    details = {}
    if os.path.isdir(ddir):
        for fn in sorted(os.listdir(ddir)):
            fp = os.path.join(ddir, fn)
            if os.path.isfile(fp):
                details[fn] = open(fp, errors="ignore").read()
    cwd = os.path.dirname(doc)
    top = _git(cwd, "rev-parse", "--show-toplevel") or cwd
    g = git_meta(top)
    with connect() as c:
        c.execute("""INSERT INTO handoffs (session_id, host, repo_url, repo_root, head_sha, branch, note, doc_name, doc_text, details)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (session_id) DO UPDATE SET repo_url=excluded.repo_url, repo_root=excluded.repo_root, head_sha=excluded.head_sha,
                       branch=excluded.branch, note=excluded.note, doc_name=excluded.doc_name, doc_text=excluded.doc_text, details=excluded.details,
                       created_at=now()""",
                  (a.session, HOST, g.get("repo_url"), g.get("repo_root"), g.get("head_sha"), g.get("branch"), a.note, os.path.basename(doc),
                   open(doc, errors="ignore").read(), Jsonb(details)))
    print(f"handoff 저장: {a.session} (상세 {len(details)}개) repo={g.get('repo_url')}")
    return 0


def cmd_handoff_get(a):
    with connect(readonly=True) as c:
        if a.session:
            rows = c.execute("SELECT session_id, host, repo_url, repo_root, head_sha, branch, note, doc_name, doc_text, details, created_at FROM handoffs WHERE session_id LIKE %s", (a.session + "%",)).fetchall()
        else:
            rep = _repo_filter(a) or git_meta(os.getcwd()).get("repo_url")
            rows = c.execute("SELECT session_id, host, repo_url, repo_root, head_sha, branch, note, doc_name, doc_text, details, created_at FROM handoffs WHERE repo_url=%s ORDER BY created_at DESC LIMIT 1", (rep,)).fetchall()
    if len(rows) != 1:
        print("handoff 일치:", len(rows)); return 1
    sid, host, rurl, root, head, br, note, name, text, details, created = rows[0]
    out = a.out
    if out:
        os.makedirs(os.path.join(out, sid), exist_ok=True)
        open(os.path.join(out, name), "w").write(text)
        for fn, body in (details or {}).items():
            open(os.path.join(out, sid, fn), "w").write(body)
    print(json.dumps(dict(id=sid, host=host, repo_url=rurl, repo_root=root, head=head, branch=br, note=note, doc=name, created=str(created), details=list((details or {}).keys())), ensure_ascii=False))
    if not out:
        print(text)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="claude-ctx")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("hook"); p.add_argument("event"); p.set_defaults(f=cmd_hook)
    p = sp.add_parser("ingest"); p.add_argument("--days", type=int, default=30); p.add_argument("--all", action="store_true"); p.add_argument("--no-otel", action="store_true"); p.set_defaults(f=cmd_ingest)
    p = sp.add_parser("search"); p.add_argument("query", nargs="+"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--role"); p.add_argument("--days", type=int); p.add_argument("--limit", type=int, default=15); p.set_defaults(f=cmd_search)
    p = sp.add_parser("recent"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--limit", type=int, default=10); p.set_defaults(f=cmd_recent)
    p = sp.add_parser("session"); p.add_argument("sid"); p.add_argument("--n", type=int); p.add_argument("--full", action="store_true"); p.set_defaults(f=cmd_session)
    p = sp.add_parser("usage"); p.add_argument("--days", type=int, default=7); p.set_defaults(f=cmd_usage)
    p = sp.add_parser("sql"); p.add_argument("query"); p.add_argument("--limit", type=int, default=50); p.set_defaults(f=cmd_sql)
    p = sp.add_parser("handoff-put"); p.add_argument("--session", required=True); p.add_argument("--doc", required=True); p.add_argument("--note", default=""); p.set_defaults(f=cmd_handoff_put)
    p = sp.add_parser("handoff-get"); p.add_argument("session", nargs="?"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--out"); p.set_defaults(f=cmd_handoff_get)
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
