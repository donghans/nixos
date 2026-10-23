#!/usr/bin/env python3
"""donghans — Claude Code 대화·사용량 공유 저장소(Postgres) 클라이언트.

  donghans ctx hook <이벤트>        훅에서 호출(stdin = 훅 JSON). 실패해도 조용히 끝난다(Claude 입력을 막지 않는다).
  ingest [--days N|--all] [--no-otel]   트랜스크립트·OTel·한도 기록을 따라잡는다(오프셋 기반, 여러 번 돌려도 안전).
  search <검색어> [--repo URL|--here] [--role user|assistant] [--days N] [--limit N]
  recent [--repo URL|--here] [--limit N]   최근 세션 목록
  session <세션ID접두> [--n N] [--full]    한 세션의 대화
  usage [--days N]     모델·일별 토큰/비용(요청 단위 usage_events 기준)
  sql "<SELECT ...>"   읽기 전용 질의
  handoff-put/handoff-get   인수인계 문서를 DB 에 올리고 받는다(머신이 달라도 resume)
  instr list|get|sync|push|pull|diff   프로젝트별 지침(.claude/donghans-*.md)의 공유 정본 — SessionStart 훅이 sync 를 돌려 로컬 파일을 맞춘다(ctx_instr.py)
  secret add|list|rm|enable|disable|show|run|scan|adopt|ignore|scrub   비밀번호 등록표 · 출력 치환 · 주입 래퍼 · 후보 탐지 · 로컬 트랜스크립트 치환(ctx_secrets.py)
  (search|recent|session|sql|handoff get 의 출력은 등록된 비밀을 [protected] 로 바꾼다. --raw 는 사람이 TTY 에서만)

접속: 환경변수 CLAUDE_CTX_DSN > 서버 머신이면 unix 소켓(peer) > 서버 tailnet 이름(허용 IP, trust). 비밀번호·설정 파일 없음. 머신 식별: CLAUDE_CTX_HOST 또는 hostname.
멱등: 모든 쓰기는 자연키 ON CONFLICT, 파일 수집은 (host,path) 어드바이저리 락 + 오프셋 갱신을 같은 트랜잭션에서.
"""
import argparse, glob, hashlib, json, os, re, socket, subprocess, sys, time

import psycopg
from psycopg.types.json import Jsonb

import ctx_instr as ci
import ctx_secrets as cs

HOST = os.environ.get("CLAUDE_CTX_HOST") or socket.gethostname()


def _machine_tag():
    """같은 hostname 의 서로 다른 물리 머신이 오프셋(경로 문자열이 같다)을 공유해 데이터를 건너뛰는 것을 막는 식별자.
    /etc/machine-id 해시 앞 6자. OS 재설치로 바뀌면 처음부터 다시 읽을 뿐이고 uuid 중복 방지로 안전하다."""
    try:
        return hashlib.sha1(open("/etc/machine-id").read().strip().encode()).hexdigest()[:6]
    except Exception:
        return "nomid"


INGEST_HOST = f"{HOST}#{_machine_tag()}"  # ingest_state 의 host 칸과 락 키에만 쓴다(표시용 host 는 HOST 그대로)
HOME = os.path.expanduser("~")
OTEL = os.path.join(HOME, ".local/share/claude-otel")
MAX_RAW = 100_000      # 원본 한 줄이 이보다 크면 잘라서 보관(정본은 트랜스크립트)
MAX_TEXT = 20_000      # 검색용 평문 상한


def dsn():
    """접속 우선순위: 환경변수 > 서버 머신의 unix 소켓(peer) > 서버 tailnet 이름(허용 목록 IP 로 trust). 비밀번호·파일 없음."""
    d = os.environ.get("CLAUDE_CTX_DSN")
    if d:
        return d
    if os.path.exists("/run/postgresql/.s.PGSQL.5432"):
        return "host=/run/postgresql dbname=claude_ctx user=claude_ctx"
    return f"host={os.environ.get('CLAUDE_CTX_SERVER', 'beelink-ser7-co')} port=5432 dbname=claude_ctx user=claude_ctx"


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
    return int.from_bytes(hashlib.sha1(f"{INGEST_HOST}:{path}".encode()).digest()[:8], "big", signed=True)


def read_new(cur, path):
    """(host,path) 오프셋 이후의 '완전한 줄'만 읽는다. 파일이 줄었으면 처음부터."""
    cur.execute("SELECT byte_offset FROM ingest_state WHERE host=%s AND path=%s", (INGEST_HOST, path))
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
                       ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (INGEST_HOST, path, new))
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
                               ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (INGEST_HOST, p, new))
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
                               ON CONFLICT (host, path) DO UPDATE SET byte_offset=excluded.byte_offset, updated_at=now()""", (INGEST_HOST, p, new))
    return n


# ---------------------------------------------------------------- 명령
def _instr_hook(conn, cwd):
    """SessionStart: 프로젝트 지침 파일을 공유 정본과 맞춘다(ctx_instr). 알릴 것이 없으면 None. 실패는 훅 전체의 실패 기록으로 흘러간다."""
    g, r = git_meta(cwd), ci.roots(cwd)
    if not g.get("repo_url") or not r:
        return None
    notices = ci.sync(conn, g["repo_url"], r[0], r[1], HOST)
    return ("프로젝트 지침 동기화: " + "; ".join(m for _, _, m in notices)) if notices else None


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
            if a.event == "SessionStart":
                msg = _instr_hook(conn, p.get("cwd"))
                if msg:  # 파일이 바뀌었거나 사람이 볼 것이 있을 때만 짧게 알린다 — 지침 본문을 프롬프트에 주입하지 않는다
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}, ensure_ascii=False))
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


def _masker(a, c):
    """출력 치환기. 등록된 비밀을 [protected] 로 바꾼다(DB 원문은 그대로). --raw 는 사람이 TTY 에서 직접 실행할 때만 풀린다 —
    에이전트의 셸 도구는 TTY 가 아니고(Claude Code 는 CLAUDECODE 환경변수도 설정) 풀 수 없다."""
    if getattr(a, "raw", False):
        _human_only("--raw(치환 해제)")
        return cs.IDENTITY
    return cs.load_masker(c)


AGENT_ENV_MARKERS = ("CLAUDECODE", "GEMINI_CLI", "DONGHANS_AGENT")   # 에이전트 셸 도구가 설정하는 환경변수(보조 표식)


def is_agent_session():
    return any(os.environ.get(k) for k in AGENT_ENV_MARKERS)


def _human_only(what):
    """TTY 검사가 본체다: 에이전트의 셸 도구는 TTY 가 아니다. 환경변수 표식은 TTY 를 흉내 낸 실행(script·pty)까지 막는 보조 장치이고,
    다른 에이전트를 쓰게 되면 그 에이전트의 표식을 AGENT_ENV_MARKERS 에 추가하거나 래퍼에서 DONGHANS_AGENT=1 을 설정한다."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or is_agent_session():
        sys.exit(f"{what} 은(는) 사람이 터미널에서 직접 실행할 때만 쓸 수 있다")


def _repo_filter(a):
    if getattr(a, "here", False):
        return git_meta(os.getcwd()).get("repo_url")
    return norm_repo(getattr(a, "repo", None))


def cmd_search(a):
    repo = _repo_filter(a)
    q = " ".join(a.query)
    sql = """SELECT m.ts, m.session_id, m.role, m.kind, s.host, s.repo_url, s.branch, m.text
             FROM messages m JOIN sessions s USING (session_id)
             WHERE m.text ILIKE %s AND m.kind IN ('prompt','response')"""
    args = [f"%{q}%"]
    if repo:
        sql += " AND s.repo_url = %s"; args.append(repo)
    if a.role:
        sql += " AND m.role = %s"; args.append(a.role)
    if a.days:
        sql += " AND m.ts > now() - make_interval(days => %s)"; args.append(a.days)
    sql += " ORDER BY m.ts DESC LIMIT %s"; args.append(a.limit)
    with connect(readonly=True) as c:
        mk = _masker(a, c)
        if mk.hits(q):
            sys.exit("검색어에 등록된 비밀이 들어 있어 검색하지 않는다(존재 여부가 드러나므로)")
        for ts, sid, role, kind, host, rurl, br, text in c.execute(sql, args):
            t = mk.text(text or "")                         # 치환을 먼저 하고 자른다(경계에서 잘린 비밀 조각이 남지 않게)
            i = t.lower().find(q.lower())
            st = max((i if i >= 0 else 0) - 60, 0)
            print(mk.text(f"[{ts:%Y-%m-%d %H:%M}] {sid[:8]} {role}/{kind} @{host} {rurl or '-'}#{br or '-'}") + f"\n  {t[st:st + 240].strip()!r}")
    return 0


def cmd_recent(a):
    repo = _repo_filter(a)
    sql = """SELECT s.session_id, s.last_ts, s.host, s.cwd, s.repo_url, s.branch, count(m.uuid) FILTER (WHERE m.kind='prompt') AS prompts,
                    (SELECT text FROM messages x WHERE x.session_id=s.session_id AND x.kind='prompt' ORDER BY x.ts LIMIT 1) AS first_prompt
             FROM sessions s LEFT JOIN messages m USING (session_id) WHERE (%s::text IS NULL OR s.repo_url = %s)
             GROUP BY s.session_id ORDER BY s.last_ts DESC NULLS LAST LIMIT %s"""
    with connect(readonly=True) as c:
        mk = _masker(a, c)
        for sid, last, host, cwd, rurl, br, n, fp in c.execute(sql, (repo, repo, a.limit)):
            print(mk.text(f"{sid}  {last:%m-%d %H:%M}  @{host}  {rurl or '-'}#{br or '-'}  {cwd}  프롬프트 {n}\n    첫 프롬프트: {mk.text((fp or '')).strip()[:120]!r}"))
    return 0


def cmd_session(a):
    with connect(readonly=True) as c:
        r = c.execute("SELECT session_id, host, hosts, cwd, repo_url, branch, first_ts, last_ts FROM sessions WHERE session_id LIKE %s", (a.sid + "%",)).fetchall()
        if len(r) != 1:
            print("일치하는 세션:", len(r), [x[0] for x in r]); return 1
        sid, host, hosts, cwd, rurl, br, f, l = r[0]
        mk = _masker(a, c)
        print(mk.text(f"# {sid}  @{','.join(hosts or [host])}  {rurl or '-'}#{br or '-'}  {cwd}\n# {f} ~ {l}"))
        kinds = "('prompt','response','tool_use')" if a.full else "('prompt','response')"
        q, args = f"SELECT ts, role, kind, is_sidechain, text, uuid FROM messages WHERE session_id=%s AND kind IN {kinds}", [sid]
        for opt, op in ((a.from_uuid, ">="), (a.to_uuid, "<=")):  # 인수인계 인덱스에 적은 근거 범위(uuid 접두)만 읽는다
            if opt:
                q += f" AND ts {op} (SELECT ts FROM messages WHERE session_id=%s AND uuid LIKE %s ORDER BY ts LIMIT 1)"; args += [sid, opt + "%"]
        rows = c.execute(q + " ORDER BY ts", args).fetchall()
        if a.n:
            rows = rows[-a.n:]
        for ts, role, kind, side, text, uid in rows:
            print(f"\n[{ts:%m-%d %H:%M}] {uid[:8]} {role}{'(sub)' if side else ''}: {mk.text(text or '').strip()[: (None if a.full else 1500)]}")
    return 0


def cmd_usage(a):
    with connect(readonly=True) as c:
        for day, model, n, it, ot, cr, cost in c.execute(
            """SELECT date_trunc('day', ts)::date, model, count(*), sum(input_tokens), sum(output_tokens), sum(cache_read_tokens), sum(cost_usd)
               FROM usage_events WHERE ts > now() - make_interval(days => %s) GROUP BY 1,2 ORDER BY 1 DESC, 7 DESC""", (a.days,)):
            print(f"{day} {model or '?':22} 요청 {n:5}  in {it or 0:>9} out {ot or 0:>8} cache_read {cr or 0:>12}  ${cost or 0:.2f}")
    return 0


def cmd_sql(a):
    if re.search(r"(?:\bfrom|\bjoin|\bupdate|\binto|\btable|,|\()\s*(?:public\s*\.\s*)?\"?secrets\"?\b|\bsecret_ignores\b", a.query, re.I):
        _human_only("비밀 등록표(secrets) 조회")   # 값이 치환되더라도 substring 등으로 조각이 새므로 막는다(`donghans secret list` 로 이름·길이를 본다)
    with connect(readonly=True) as c:
        mk = _masker(a, c)
        cur = c.execute(a.query)
        print("\t".join(d.name for d in cur.description))
        for row in cur.fetchmany(a.limit):
            print("\t".join("" if v is None else mk.text(str(v))[:300] for v in row))   # 치환 후 자름
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
    with connect(readonly=True) as c:
        mk = _masker(a, c)
    text, note = mk.text(text), mk.text(note)
    details = mk.obj(details)
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


# ---------------------------------------------------------------- 프로젝트별 지침(ctx_instr)
def _instr_target(a, need_local=True):
    cwd = os.getcwd()
    g, r = git_meta(cwd), ci.roots(cwd)
    repo = norm_repo(getattr(a, "repo", None)) or g.get("repo_url")
    if not repo:
        sys.exit("저장소를 알 수 없다 — git 저장소 안에서 실행하거나 --repo 를 준다")
    if need_local and not r:
        sys.exit("git 저장소 안에서 실행해야 한다(로컬 파일 위치를 알아야 한다)")
    return repo, (r[0] if r else None), (r[1] if r else None)


def _instr_names(a):
    n = getattr(a, "name", None)
    if n and n not in ci.NAMES:
        sys.exit(f"이름은 {' | '.join(ci.NAMES)} 중 하나")
    return [n] if n else list(ci.NAMES)


def cmd_instr_list(a):
    repo, _, _ = _instr_target(a, need_local=False)
    with connect(readonly=True) as c:
        rows = c.execute("SELECT name, rev, updated_host, updated_at, length(body) FROM project_instructions WHERE repo_url=%s ORDER BY name", (repo,)).fetchall()
    print(f"저장소 {repo}")
    for n, rev, host, at, ln in rows:
        print(f"- {n}: rev {rev} · {ln}자 · {host} · {at:%F %T}")
    if not rows:
        print("(공유 저장소에 지침 없음 — 로컬 파일이 있으면 `donghans instr push` 또는 다음 세션 시작 때 자동 채택)")
    return 0


def cmd_instr_get(a):
    repo, _, _ = _instr_target(a, need_local=False)
    with connect(readonly=True) as c:
        row = c.execute("SELECT body FROM project_instructions WHERE repo_url=%s AND name=%s", (repo, a.name)).fetchone()
        if not row:
            print("없음"); return 1
        print(_masker(a, c).text(row[0]), end="")
    return 0


def cmd_instr_sync(a):
    repo, main, common = _instr_target(a)
    with connect() as c:
        notices = ci.sync(c, repo, main, common, HOST)
    for _, kind, msg in notices:
        print(("⚠ " if kind in ("ahead", "conflict") else "") + msg)
    if not notices and not a.quiet:
        print("지침: 변경 없음(공유 저장소와 일치)")
    return 0


def cmd_instr_push(a):
    repo, main, common = _instr_target(a)
    rc = 0
    with connect() as c:
        mk = cs.load_masker(c)
        for n in _instr_names(a):
            if ci.read_local(main, n) is None and not getattr(a, "name", None):
                continue
            code, msg = ci.push(c, repo, main, n, HOST, force=a.force, masker=mk)
            print(msg); rc = rc or code
        ci.ensure_excluded(common)
    return rc


def cmd_instr_pull(a):
    repo, main, common = _instr_target(a)
    rc = 0
    with connect() as c:
        for n in _instr_names(a):
            if n not in ci.db_rows(c, repo):
                continue
            code, msg = ci.pull(c, repo, main, n, force=a.force)
            print(msg); rc = rc or code
    return rc


def cmd_instr_diff(a):
    repo, main, _ = _instr_target(a)
    with connect(readonly=True) as c:
        out = "".join(ci.diff_text(c, repo, main, n) for n in _instr_names(a))
        print(_masker(a, c).text(out) if out else "차이 없음", end="" if out else "\n")
    return 0


DRAFT_PROMPT = """당신은 Claude Code 세션의 인수인계 초안 작성기다. 아래 [자료]만 근거로 한국어 인수인계 초안을 쓴다. 규칙:
- 자료에 없는 것은 쓰지 않는다. 확신이 없으면 「추정」 표시. 새로 지어내지 않는다.
- 사용자 발언(user)과 에이전트 발언(assistant)을 섞지 않는다. 에이전트의 제안·해석을 사용자 결정처럼 쓰지 않는다.
- 상시 지시는 표(지시 | 출처(날짜·메시지ID8자) | 확인[사용자 원문 / 에이전트 해석])로, 사용자 발언 원문에 근거가 있는 것만 「사용자 원문」으로 표시한다.
- 섹션: 0 상시 지시 · 1 현재 상태 · 2 미완 작업 · 3 다음 할 일 · 4 열린 결정(추천 답 포함) · 5 함정 · 6 확인하지 못한 것. 각 섹션 끝에 근거 대화 범위를 `<시작ID8>~<끝ID8>` 로 적는다.
- git 상태·파일 존재 같은 현재 사실은 이 자료로 알 수 없으므로 「확인 필요」로 남긴다(검증은 사람이 한다).
{focus}
[자료: 세션 {sid} · 저장소 {repo} · {n_user} 개 사용자 발언 중 최근 {n_user_used} 개, 에이전트 응답 최근 {n_resp} 개]
{body}
"""


def cmd_handoff_draft(a):
    """작은 모델이 DB 슬라이스만 읽고 초안을 쓴다 — 큰 세션 컨텍스트를 다시 읽지 않게 하려는 것. 본문 세션은 이 초안을 검증·보강한다."""
    sid = a.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        sys.exit("세션 ID 가 필요하다(--session 또는 CLAUDE_CODE_SESSION_ID)")
    conn = connect(timeout=10)
    for f in glob.glob(os.path.join(HOME, f".claude/projects/*/{sid}.jsonl")):  # 가장 최근 대화까지 반영
        for g in transcript_family(f):
            ingest_transcript(conn, g)
    conn.commit()
    sess = conn.execute("SELECT session_id, repo_url, cwd FROM sessions WHERE session_id LIKE %s", (sid + "%",)).fetchall()
    if len(sess) != 1:
        sys.exit(f"세션 일치 {len(sess)}건")
    sid, repo, cwd = sess[0]
    mk = _masker(a, conn)   # 초안 작성 모델에게 비밀이 가지 않게 한다
    users = conn.execute("""SELECT ts, left(uuid,8), text FROM messages WHERE session_id=%s AND kind='prompt' AND NOT is_sidechain
                            AND text NOT LIKE '<%%' AND text NOT LIKE '[Request interrupted%%' ORDER BY ts""", (sid,)).fetchall()
    resps = conn.execute("""SELECT ts, left(uuid,8), text FROM messages WHERE session_id=%s AND kind='response' AND NOT is_sidechain
                            ORDER BY ts DESC LIMIT %s""", (sid, a.responses)).fetchall()[::-1]
    budget, parts, used_u = a.max_chars, [], 0
    lines_u = [f"[user {t:%m-%d %H:%M} {u}] {mk.text(x).strip()[:a.prompt_chars]}" for t, u, x in users]
    lines_r = [f"[assistant {t:%m-%d %H:%M} {u}] {mk.text(x).strip()[:a.resp_chars]}" for t, u, x in resps]
    r_len = sum(len(x) for x in lines_r)
    keep = []
    for l in reversed(lines_u):             # 최근 발언부터 예산 안에서
        if sum(len(x) for x in keep) + len(l) + r_len > budget:
            break
        keep.append(l)
    keep = keep[::-1]
    body = "\n".join(keep) + "\n--- 에이전트 응답(최근) ---\n" + "\n".join(lines_r)
    focus = f"- 추가 지시(중점): {a.focus}" if a.focus else ""
    prompt = DRAFT_PROMPT.format(focus=focus, sid=sid, repo=repo or "-", n_user=len(users), n_user_used=len(keep), n_resp=len(lines_r), body=body)
    print(f"[draft] 모델 {a.model} · 입력 약 {len(prompt)}자(≈{len(prompt) // 3} 토큰) · 사용자 발언 {len(keep)}/{len(users)}", file=sys.stderr)
    if a.dry_run:
        print(prompt); return 0
    r = subprocess.run(["claude", "-p", "--model", a.model, "--no-session-persistence"], input=prompt, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"초안 생성 실패: {r.stderr.strip()[:300]}")
    out = a.out or os.path.join(cwd or ".", ".claude/handoffs", f"DRAFT-{sid}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(r.stdout)
    print(out)
    return 0


# ---------------------------------------------------------------- secret: 비밀번호 등록표 · 주입 래퍼 · 후보 탐지 · 로컬 치환
def _read_secret_value(a):
    if a.stdin:
        v = sys.stdin.read()
        return v[:-1] if v.endswith("\n") else v
    _human_only("비밀 등록(값을 대화에 남기지 않으려고 터미널에서 직접 입력해야 한다)")
    import getpass
    v = getpass.getpass(f"{a.label} 값(화면에 표시되지 않음): ")
    if getpass.getpass("한 번 더: ") != v:
        sys.exit("두 번 입력한 값이 다르다")
    return v


def cmd_secret_add(a):
    value = _read_secret_value(a)
    try:
        with connect() as c:
            cs.add_secret(c, a.label, "regex" if a.regex else "literal", value, a.note, a.replace, a.force)
    except ValueError as e:
        sys.exit(str(e))
    print(f"등록: {a.label} ({'regex' if a.regex else 'literal'}, {len(value)}자, fp {cs.fingerprint(value)}) — 이제 ctx 출력·주입 래퍼 출력에서 [protected] 로 바뀐다")
    return 0


def cmd_secret_list(a):
    with connect(readonly=True) as c:
        rows = cs.load_secrets(c, only_enabled=False)
    if not rows:
        print("등록된 비밀이 없다 (`donghans secret add <이름>` 또는 `donghans secret scan`)"); return 0
    for r in rows:
        shown = f"패턴 {r['value']}" if r["kind"] == "regex" else f"{len(r['value'])}자 fp {cs.fingerprint(r['value'])}"
        print(f"{r['label']:<24} {r['kind']:<7} {'켜짐' if r['enabled'] else '꺼짐':<3} {shown}")
    return 0


def cmd_secret_set(a):
    with connect() as c:
        cs.ensure_schema(c)
        if a.what == "rm":
            n = c.execute("DELETE FROM secrets WHERE label=%s", (a.label,)).rowcount
        else:
            n = c.execute("UPDATE secrets SET enabled=%s, updated_at=now() WHERE label=%s", (a.what == "enable", a.label)).rowcount
        c.commit()
    if not n:
        sys.exit(f"'{a.label}' 이(가) 없다")
    print({"rm": "삭제", "enable": "켬", "disable": "끔"}[a.what] + f": {a.label}")
    return 0


def cmd_secret_show(a):
    _human_only("비밀 값 보기")
    with connect(readonly=True) as c:
        r = [x for x in cs.load_secrets(c, only_enabled=False) if x["label"] == a.label]
    if not r:
        sys.exit(f"'{a.label}' 이(가) 없다")
    print(r[0]["value"])
    return 0


def cmd_secret_run(a):
    argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
    if not argv:
        sys.exit("사용: donghans secret run [--env 이름,이름] -- 명령 인자...   (인자의 {{secret:이름}} 은 실행 직전에 값으로, {{secret-file:이름}} 은 0600 임시 파일 경로로 바뀐다)")
    with connect(readonly=True) as c:
        secrets = cs.load_secrets(c)
    try:
        return cs.run_masked(argv, secrets, [x for x in a.env.split(",") if x])
    except KeyError as e:
        sys.exit(str(e.args[0]))


def _scan_rows(c, days=None):
    q = "SELECT m.session_id, s.repo_url, m.ts, m.text FROM messages m LEFT JOIN sessions s USING (session_id) WHERE m.text IS NOT NULL"
    args = []
    if days:
        q += " AND m.ts > now() - make_interval(days => %s)"; args.append(days)
    with c.cursor(name="ctx_scan") as cur:
        cur.itersize = 2000
        cur.execute(q, args)
        yield from cur


def _ignored(c):
    import psycopg.errors as pe
    try:
        return {r[0] for r in c.execute("SELECT fp FROM secret_ignores").fetchall()}
    except pe.UndefinedTable:
        c.rollback()
        return set()


def cmd_secret_scan(a):
    with connect(readonly=True) as c:
        found = cs.scan_messages(_scan_rows(c, a.days), cs.load_masker(c), _ignored(c))
    rows = sorted((d for d in found.values() if d["count"] >= a.min_count), key=lambda d: (-d["count"], d["fp"]))[: a.limit]
    if not rows:
        print("새 후보가 없다"); return 0
    reveal = False
    if a.reveal:
        _human_only("--reveal(후보 값 보기)"); reveal = True
    for d in rows:
        shown = d["value"] if reveal else cs.preview(d["value"])
        repos = ",".join(sorted(d["repos"]))[:60] or "-"
        print(f"{d['fp']}  {d['pattern']:<18} {shown:<28} ×{d['count']:<4} 세션 {len(d['sessions']):<3} {repos}  ~{d['last']:%Y-%m-%d}" if d["last"] else f"{d['fp']}  {d['pattern']:<18} {shown}")
    print(f"\n후보 {len(found)}개 중 {len(rows)}개 표시. 승인: donghans secret adopt <fp> <이름>   ·   오탐 숨기기: donghans secret ignore <fp>")
    return 0


def _find_by_fp(c, fp):
    for sid, repo, ts, text in _scan_rows(c):
        for name, val in cs.find_candidates(text):
            if cs.fingerprint(val) == fp:
                return name, val
    return None


def cmd_secret_adopt(a):
    with connect(readonly=True) as c:
        hit = _find_by_fp(c, a.fp)
    if not hit:
        sys.exit(f"fp {a.fp} 후보를 찾지 못했다(이미 등록됐거나 스캔 결과가 달라졌을 수 있다: donghans secret scan)")
    name, val = hit
    try:
        with connect() as c:
            cs.add_secret(c, a.label, "literal", val, a.note or f"scan 에서 승인({name})", False, a.force)
    except ValueError as e:
        sys.exit(str(e))
    print(f"등록: {a.label} ({len(val)}자, fp {a.fp}) — 값은 화면에 표시하지 않았다")
    return 0


def cmd_secret_ignore(a):
    with connect() as c:
        cs.ensure_schema(c)
        if a.undo:
            c.execute("DELETE FROM secret_ignores WHERE fp=%s", (a.fp,))
        else:
            c.execute("INSERT INTO secret_ignores (fp, note) VALUES (%s,%s) ON CONFLICT DO NOTHING", (a.fp, a.note))
        c.commit()
    print(("무시 해제: " if a.undo else "무시: ") + a.fp)
    return 0


SCRUB_STATE = os.path.join(HOME, ".local/state/claude-ctx/scrub-state.json")


def cmd_secret_scrub(a):
    """DB 에 적재된 로컬 트랜스크립트의 비밀을 [protected] 로 바꾼다(기본은 점검만; 원문은 DB 에 그대로 있다)."""
    conn = connect(timeout=10)
    secrets = cs.load_secrets(conn)
    if not secrets:
        if not a.quiet:
            print("등록된 비밀이 없다")
        return 0
    files = cs.transcript_files(HOME)
    state = {}
    if not a.no_cache:
        try:
            state = json.load(open(SCRUB_STATE))
        except Exception:
            state = {}
    state = {p: v for p, v in state.items() if os.path.exists(p)}   # 사라진 파일은 정리
    say = (lambda *x: None) if a.quiet else print
    say(f"{'적용' if a.apply else '점검(dry-run)'}: 트랜스크립트 {len(files)}개, 비밀 {len(secrets)}개, {a.idle_min}분 안에 수정된 파일은 진행 중으로 보고 건너뜀")
    sm = cs.scrub_local(sys.modules[__name__], conn, files, secrets, apply=a.apply, idle_secs=a.idle_min * 60, log=say, state=state)
    try:
        os.makedirs(os.path.dirname(SCRUB_STATE), exist_ok=True)
        tmp = SCRUB_STATE + ".tmp"
        json.dump(state, open(tmp, "w"))
        os.replace(tmp, SCRUB_STATE)
    except OSError:
        pass
    if a.quiet and not sm["changed"]:
        conn.commit(); return 0
    print(f"\n파일 {sm['files']}개(점검 생략 {sm['cached']}) 중 비밀 포함 {sm['hit_files']}개 · 치환 {sm['changed']} · 진행 중 건너뜀 {sm['skipped_active']} · "
          f"미적재 건너뜀 {sm['skipped_unsynced']} · 읽는 사이 변경 {sm['skipped_changed']} · JSON 이 깨져 못 바꾼 줄 {sm['skipped_lines']}")
    if sm["hits"]:
        print("이름별 횟수: " + ", ".join(f"{k}×{v}" for k, v in sorted(sm["hits"].items())))
    if not a.apply and sm["hit_files"]:
        print("적용하려면 --apply (원문은 DB 에 있고, 적용 전에 그 파일을 먼저 적재한다)")
    conn.commit()
    return 0


def main():
    ap = argparse.ArgumentParser(prog="donghans", description="donghans 도구 모음 — ctx(공유 컨텍스트 저장소)·handoff(인수인계 업/다운)")
    top = ap.add_subparsers(dest="group", required=True)
    ctx = top.add_parser("ctx", help="대화·사용량 공유 저장소").add_subparsers(dest="cmd", required=True)
    p = ctx.add_parser("hook"); p.add_argument("event"); p.set_defaults(f=cmd_hook)
    p = ctx.add_parser("ingest"); p.add_argument("--days", type=int, default=2); p.add_argument("--all", action="store_true"); p.add_argument("--no-otel", action="store_true"); p.set_defaults(f=cmd_ingest)
    p = ctx.add_parser("search"); p.add_argument("query", nargs="+"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--role"); p.add_argument("--days", type=int); p.add_argument("--limit", type=int, default=15); p.set_defaults(f=cmd_search)
    p = ctx.add_parser("recent"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--limit", type=int, default=10); p.set_defaults(f=cmd_recent)
    p = ctx.add_parser("session"); p.add_argument("sid"); p.add_argument("--n", type=int); p.add_argument("--full", action="store_true"); p.add_argument("--from", dest="from_uuid"); p.add_argument("--to", dest="to_uuid"); p.set_defaults(f=cmd_session)
    p = ctx.add_parser("usage"); p.add_argument("--days", type=int, default=7); p.set_defaults(f=cmd_usage)
    p = ctx.add_parser("sql"); p.add_argument("query"); p.add_argument("--limit", type=int, default=50); p.set_defaults(f=cmd_sql)
    ho = top.add_parser("handoff", help="인수인계 문서 업/다운").add_subparsers(dest="cmd", required=True)
    p = ho.add_parser("put"); p.add_argument("--session", required=True); p.add_argument("--doc", required=True); p.add_argument("--note", default=""); p.set_defaults(f=cmd_handoff_put)
    p = ho.add_parser("draft"); p.add_argument("--session"); p.add_argument("--focus"); p.add_argument("--model", default="haiku"); p.add_argument("--out"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-chars", type=int, default=60000); p.add_argument("--prompt-chars", type=int, default=700); p.add_argument("--resp-chars", type=int, default=900); p.add_argument("--responses", type=int, default=25); p.set_defaults(f=cmd_handoff_draft)
    p = ho.add_parser("get"); p.add_argument("session", nargs="?"); p.add_argument("--repo"); p.add_argument("--here", action="store_true"); p.add_argument("--out"); p.add_argument("--raw", action="store_true"); p.set_defaults(f=cmd_handoff_get)
    ins = top.add_parser("instr", help="프로젝트별 지침(.claude/donghans-*.md)의 공유 정본").add_subparsers(dest="cmd", required=True)
    p = ins.add_parser("list"); p.add_argument("--repo"); p.set_defaults(f=cmd_instr_list)
    p = ins.add_parser("get"); p.add_argument("name", choices=list(ci.NAMES)); p.add_argument("--repo"); p.add_argument("--raw", action="store_true"); p.set_defaults(f=cmd_instr_get)
    p = ins.add_parser("sync", help="로컬 파일을 공유 정본에 맞춘다(훅이 부른다)"); p.add_argument("--quiet", action="store_true"); p.set_defaults(f=cmd_instr_sync)
    p = ins.add_parser("push", help="로컬 파일을 공유 정본으로 올린다"); p.add_argument("name", nargs="?", choices=list(ci.NAMES)); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_instr_push)
    p = ins.add_parser("pull", help="공유 정본으로 로컬 파일을 덮는다"); p.add_argument("name", nargs="?", choices=list(ci.NAMES)); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_instr_pull)
    p = ins.add_parser("diff"); p.add_argument("name", nargs="?", choices=list(ci.NAMES)); p.add_argument("--raw", action="store_true"); p.set_defaults(f=cmd_instr_diff)
    se = top.add_parser("secret", help="비밀번호 등록표 · 주입 래퍼 · 후보 탐지 · 로컬 치환").add_subparsers(dest="cmd", required=True)
    p = se.add_parser("add"); p.add_argument("label"); p.add_argument("--regex", action="store_true"); p.add_argument("--note"); p.add_argument("--replace", action="store_true")
    p.add_argument("--force", action="store_true"); p.add_argument("--stdin", action="store_true", help="값을 표준입력에서 읽는다(기본은 터미널에서 숨겨 입력)"); p.set_defaults(f=cmd_secret_add)
    p = se.add_parser("list"); p.set_defaults(f=cmd_secret_list)
    for w in ("rm", "enable", "disable"):
        p = se.add_parser(w); p.add_argument("label"); p.set_defaults(f=cmd_secret_set, what=w)
    p = se.add_parser("show"); p.add_argument("label"); p.set_defaults(f=cmd_secret_show)
    p = se.add_parser("run", help="비밀을 끼워 명령을 실행하고 출력은 치환한다"); p.add_argument("--env", default=""); p.add_argument("argv", nargs=argparse.REMAINDER); p.set_defaults(f=cmd_secret_run)
    p = se.add_parser("scan"); p.add_argument("--days", type=int); p.add_argument("--limit", type=int, default=30); p.add_argument("--min-count", type=int, default=1); p.add_argument("--reveal", action="store_true"); p.set_defaults(f=cmd_secret_scan)
    p = se.add_parser("adopt"); p.add_argument("fp"); p.add_argument("label"); p.add_argument("--note"); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_secret_adopt)
    p = se.add_parser("ignore"); p.add_argument("fp"); p.add_argument("--note"); p.add_argument("--undo", action="store_true"); p.set_defaults(f=cmd_secret_ignore)
    p = se.add_parser("scrub"); p.add_argument("--apply", action="store_true"); p.add_argument("--idle-min", type=int, default=60)
    p.add_argument("--quiet", action="store_true", help="바꾼 것이 없으면 아무것도 출력하지 않는다(타이머용)"); p.add_argument("--no-cache", action="store_true", help="점검 캐시를 쓰지 않고 모든 파일을 다시 읽는다"); p.set_defaults(f=cmd_secret_scrub)
    for name in ("search", "recent", "session", "sql"):   # 사람이 TTY 에서만 쓸 수 있는 치환 해제
        ctx.choices[name].add_argument("--raw", action="store_true", help="치환 해제(사람이 터미널에서만)")
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
