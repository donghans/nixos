#!/usr/bin/env python3
"""ctx 의미 검색 — 청크 나누기·머리말·순위 결합(RRF)·임베딩 클라이언트·색인기·`search --semantic`.

계획: ctx `plan/ctx-의미검색-S2`(프로젝트 nixos). 표준 라이브러리만 쓴다(psycopg 는 호출하는 쪽이 연결 객체를 넘긴다).
설계 요점(계획 §3):
  - 메시지 전체를 먼저 비밀 치환한 뒤 그 위에서 청크로 나눈다(청크 경계에 걸친 비밀이 새지 않게). 위치 열 없이 치환된 청크 본문을 저장한다.
  - 임베딩 서버로는 치환된 텍스트만 간다. 질의에 등록된 비밀이 있으면 호출하는 쪽이 임베딩 요청 전에 거부한다.
  - 서버·테이블이 없으면 철자 유사만으로 결과를 내고 **반드시** 그 사실을 알린다(조용히 일부 결과만 주지 않는다).
"""
import json
import os
import re
import urllib.error
import urllib.request

MODEL = "bge-m3-q8_0"      # message_chunks.model — 같은 차원(DIM)의 모델만 같은 표에 넣는다
DIM = 1024
CHUNK_MAX = 260
RRF_K = 60
QUERY_TIMEOUT = 3.0        # 질의 임베딩 요청 제한(초)
BATCH_TIMEOUT = 30.0       # 색인 배치 요청 제한(초)
BATCH = 8
TOPK = 50
TRGM_THRESHOLD = 0.3
TRGM_TIMEOUT_MS = 5000
SKIP_NO = 0                # 건너뜀 행(embedding NULL)의 chunk_no
MASK = "[protected]"


class EmbedError(Exception):
    """임베딩 서버를 쓸 수 없다(설정 없음·연결 실패·시간 초과·응답 이상)."""


# ---------------------------------------------------------------- 청크
_SEP = re.compile(r"(?<=[.?!])\s+|\n+|(?<=[다요죠까네야])\s(?=[가-힣A-Za-z0-9])")


def sentence_spans(text):
    """공백 구분자로만 나눈 문장 구간 [(start, end)] — 구분자는 공백뿐이라 모든 비공백 글자가 어떤 구간에 들어간다."""
    out, pos = [], 0
    for m in _SEP.finditer(text):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    res = []
    for s, e in out:                      # 앞뒤 공백 제거
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            res.append((s, e))
    return res


def chunk_spans(text, maxlen=CHUNK_MAX):
    """text 를 maxlen 글자 안의 구간들로 나눈다: 문장 구간을 앞에서부터 합치고, maxlen 을 넘는 문장은 maxlen 씩 자른다.
    보장: 모든 비공백 글자가 어떤 구간에 들어가고, 각 구간은 maxlen 이하다."""
    if not text:
        return []
    pieces = []
    for s, e in sentence_spans(text):
        while e - s > maxlen:
            cut = s + maxlen
            for m in re.finditer(re.escape(MASK), text[s:cut + len(MASK)]):     # 치환 표지 한가운데에서 자르지 않는다
                if s + m.start() < cut < s + m.end() and s + m.start() > s:
                    cut = s + m.start()
                    break
            pieces.append((s, cut))
            s = cut
        pieces.append((s, e))
    spans, cur = [], None
    for s, e in pieces:
        if cur is None:
            cur = [s, e]
        elif e - cur[0] <= maxlen:
            cur[1] = e
        else:
            spans.append(tuple(cur))
            cur = [s, e]
    if cur is not None:
        spans.append(tuple(cur))
    return spans


def chunks(text, maxlen=CHUNK_MAX):
    return [text[s:e] for s, e in chunk_spans(text, maxlen)]


def meaningful(chunk):
    """치환 표지와 공백을 뺀 글자가 2개 미만이면 색인할 내용이 없다."""
    return len(re.sub(r"\s+", "", chunk.replace(MASK, ""))) >= 2


def build_input(date, topic, chunk):
    """임베딩 입력 = `[날짜 · 세션 주제: 앞 50자] 청크`(시험에서 본문만보다 20위 안 +2). topic 이 없으면 날짜만."""
    topic = (topic or "").strip().replace("\n", " ")[:50]
    head = f"{date} · 세션 주제: {topic}" if topic else f"{date}"
    return f"[{head}] {chunk}"


# ---------------------------------------------------------------- 순위 결합
def rrf(rankings, k=RRF_K):
    """rankings: {이름: [id, …(순위 순)]}. 반환 [(id, 점수, (출처 이름…))] — 점수 내림차순, 동률은 (가장 높은 순위, id 문자열)로 결정적."""
    score, best, src = {}, {}, {}
    for name in sorted(rankings):
        seen = set()
        for r, i in enumerate(rankings[name], 1):
            if i in seen:
                continue
            seen.add(i)
            score[i] = score.get(i, 0.0) + 1.0 / (k + r)
            best[i] = min(best.get(i, r), r)
            src.setdefault(i, []).append(name)
    return [(i, score[i], tuple(src[i])) for i in sorted(score, key=lambda x: (-score[x], best[x], str(x)))]


# ---------------------------------------------------------------- 임베딩 클라이언트
def vec_literal(v):
    return "[" + ",".join(format(float(x), ".7g") for x in v) + "]"


def config_path():
    return os.path.join(os.path.expanduser("~"), ".config", "claude-ctx", "embed")


def load_config():
    """(url, key|None) 또는 None(설정 없음). 환경변수 CTX_EMBED_URL·CTX_EMBED_KEY 가 우선, 없으면 ~/.config/claude-ctx/embed(JSON, 권한 600 —
    DB 접속 문자열 `dsn` 과 같은 방식). 키가 든 파일의 권한이 600 보다 넓으면 EmbedError."""
    url, key = os.environ.get("CTX_EMBED_URL"), os.environ.get("CTX_EMBED_KEY")
    if not url:
        p = config_path()
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            raise EmbedError(f"임베딩 설정 파일을 읽을 수 없다({p}): {e}")
        url, key = d.get("url"), d.get("key") or key
        if key and os.stat(p).st_mode & 0o077:
            raise EmbedError(f"임베딩 설정 파일의 권한이 넓다(600 이어야 한다): {p}")
    if not url:
        return None
    return url.rstrip("/"), key


def embed(texts, url, key=None, timeout=QUERY_TIMEOUT):
    """POST {url}/v1/embeddings {"input":[…],"model":"x"} → [[float×DIM], …](입력 순서). 이상하면 EmbedError."""
    if not texts:
        return []
    req = urllib.request.Request(url + "/v1/embeddings", data=json.dumps({"input": list(texts), "model": "x"}).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise EmbedError(f"임베딩 서버 응답 없음({type(e).__name__}: {e})")
    data = d.get("data") if isinstance(d, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbedError("임베딩 응답 형식 이상(data 개수 불일치)")
    data = sorted(data, key=lambda x: x.get("index", 0)) if all(isinstance(x, dict) for x in data) else data
    out = []
    for x in data:
        v = x.get("embedding") if isinstance(x, dict) else None
        if not isinstance(v, list) or len(v) != DIM:
            raise EmbedError(f"임베딩 차원 이상(기대 {DIM})")
        out.append(v)
    return out


def make_embedder(timeout=QUERY_TIMEOUT):
    """설정에서 만든 embed 함수(texts → 벡터들). 설정이 없으면 EmbedError."""
    cfg = load_config()
    if not cfg:
        raise EmbedError("임베딩 엔드포인트 설정 없음(~/.config/claude-ctx/embed 또는 CTX_EMBED_URL)")
    url, key = cfg
    return lambda texts: embed(texts, url, key, timeout)


# ---------------------------------------------------------------- 색인기
def _is_missing_table(e):
    return getattr(e, "sqlstate", None) == "42P01"


def _pending_sql(limit_sql=""):
    return f"""SELECT m.uuid, m.ts, m.session_id, m.text FROM messages m JOIN sessions s USING (session_id)
              WHERE m.kind = 'prompt' AND m.role = 'user' AND NOT m.is_sidechain AND s.excluded_at IS NULL
                AND coalesce(m.text, '') <> '' AND m.text !~ %s
                AND NOT EXISTS (SELECT 1 FROM message_chunks c WHERE c.uuid = m.uuid AND c.model = %s)
              ORDER BY m.ts {limit_sql}"""


def _date(ts):
    try:
        from zoneinfo import ZoneInfo
        return ts.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    except Exception:
        return ts.strftime("%Y-%m-%d")


def plan_message(masker, text, date, topic):
    """한 메시지의 색인 계획: (치환 후 청크 목록, 임베딩 입력 목록). 메시지 전체를 먼저 치환한 뒤 청크로 나눈다. 의미 있는 청크가 없으면 ([], [])."""
    masked = masker.text(text)
    cs = [c for c in chunks(masked) if meaningful(c)]
    return cs, [build_input(date, masker.text(topic or ""), c) for c in cs]


def index_messages(conn, masker, embedder, auto_re, limit=None, dry_run=False, model=MODEL, out=print, batch=BATCH):
    """대상 메시지(사용자 프롬프트, 아직 이 모델의 청크가 없는 것)를 청크로 나눠 임베딩하고 message_chunks 에 넣는다. 멱등.
    dry_run 이면 대상·청크 수만 센다. 반환 dict(messages, chunks, skipped, failed)."""
    import ctxdata as cd
    rows = conn.execute(_pending_sql("LIMIT %s" if limit else ""), [auto_re, model] + ([limit] if limit else [])).fetchall()
    titles = cd.session_titles(conn, {r[2] for r in rows}, masker, 50) if rows else {}
    stat = dict(messages=len(rows), chunks=0, skipped=0, failed=0)
    todo = []                          # (uuid, [치환 청크], [입력])
    for uuid, ts, sid, text in rows:
        cs, ins = plan_message(masker, text, _date(ts), titles.get(sid, ""))
        if not cs:
            stat["skipped"] += 1
            todo.append((uuid, [], []))
        else:
            stat["chunks"] += len(cs)
            todo.append((uuid, cs, ins))
    if dry_run:
        return stat
    buf = []                           # [(uuid, chunk_no, 치환 청크, 입력)]
    done = 0

    def flush():
        nonlocal buf
        if not buf:
            return
        vs = embedder([b[3] for b in buf])
        for (uuid, no, chunk, _i), v in zip(buf, vs):
            conn.execute("INSERT INTO message_chunks (uuid, chunk_no, chunk_text, model, embedding) VALUES (%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                         (uuid, no, chunk, model, vec_literal(v)))
        conn.commit()
        buf = []

    for uuid, cs, ins in todo:
        if not cs:
            conn.execute("INSERT INTO message_chunks (uuid, chunk_no, chunk_text, model, embedding) VALUES (%s,%s,'',%s,NULL) ON CONFLICT DO NOTHING", (uuid, SKIP_NO, model))
            continue
        for no, (c, i) in enumerate(zip(cs, ins)):
            buf.append((uuid, no, c, i))
            if len(buf) >= batch:
                try:
                    flush()
                except EmbedError as e:
                    stat["failed"] += len(buf)
                    buf = []
                    conn.rollback()
                    out(f"  임베딩 실패(이 배치는 건너뜀, 다음 실행에서 다시 시도): {e}")
        done += 1
        if done % 500 == 0:
            out(f"  {done}/{len(todo)} 메시지")
    try:
        flush()
    except EmbedError as e:
        stat["failed"] += len(buf)
        conn.rollback()
        out(f"  임베딩 실패: {e}")
    conn.commit()
    return stat


# ---------------------------------------------------------------- 의미 검색
def _filters(repo, session, days, include_excluded):
    sql, args = "", []
    if not include_excluded:
        sql += " AND s.excluded_at IS NULL"
    if repo:
        sql += " AND s.repo_url = %s"; args.append(repo)
    if session:
        sql += " AND m.session_id LIKE %s"; args.append(session + "%")
    if days:
        sql += " AND m.ts > now() - make_interval(days => %s)"; args.append(days)
    return sql, args


def semantic_search(conn, q, embedder, auto_re, repo=None, session=None, days=None, include_excluded=False, limit=15, model=MODEL):
    """철자 유사(+임베딩) 결합 검색. 반환 (결과 목록, 알림 목록).
    결과 = [{uuid, ts, session_id, host, repo_url, branch, text, chunk, score, sources}]. 모집단은 사용자 프롬프트(자동 메시지·서브에이전트 브리프 제외).
    임베딩 쪽이 안 되면(설정 없음·서버 불가·테이블 없음) 철자 유사만으로 결과를 내고 알림에 사유를 넣는다."""
    notices = []
    fsql, fargs = _filters(repo, session, days, include_excluded)
    base = f"""FROM messages m JOIN sessions s USING (session_id)
              WHERE m.kind = 'prompt' AND m.role = 'user' AND NOT m.is_sidechain AND coalesce(m.text, '') !~ %s{fsql}"""
    emb_ids, chunk_of = [], {}
    # ⓐ 임베딩(정확 검색). 저장소 쓰기 없음. savepoint 로 감싸 표가 없을 때 예외가 뒤 쿼리를 망치지 않게 한다.
    try:
        qv = vec_literal(embedder([q])[0])
        with conn.transaction():
            rows = conn.execute(f"""SELECT c.uuid, c.chunk_text, c.embedding <=> %s::vector AS d
                                    FROM message_chunks c JOIN messages m ON m.uuid = c.uuid JOIN sessions s USING (session_id)
                                    WHERE c.model = %s AND c.embedding IS NOT NULL AND m.kind = 'prompt' AND m.role = 'user' AND NOT m.is_sidechain
                                      AND coalesce(m.text, '') !~ %s{fsql}
                                    ORDER BY d LIMIT %s""", [qv, model, auto_re] + fargs + [TOPK]).fetchall()
        for u, ct, _d in rows:
            if u not in chunk_of:
                chunk_of[u] = ct
                emb_ids.append(u)
    except EmbedError as e:
        notices.append(f"[의미 검색 불가: {e}; 철자 유사만 사용]")
    except Exception as e:
        if _is_missing_table(e):
            notices.append("[의미 검색 불가: 색인 테이블(message_chunks) 없음; 철자 유사만 사용]")
        else:
            raise
    # ⓑ 철자 유사 — `<%%` 는 psycopg 매개변수와 같이 쓸 때의 이스케이프. 시간 제한을 걸고 초과하면 임베딩만 쓴다.
    trgm_ids = []
    try:
        with conn.transaction():
            conn.execute(f"SET LOCAL pg_trgm.word_similarity_threshold = {TRGM_THRESHOLD}")
            conn.execute(f"SET LOCAL statement_timeout = {TRGM_TIMEOUT_MS}")
            rows = conn.execute(f"""SELECT m.uuid {base} AND %s <%% m.text
                                    ORDER BY word_similarity(%s, m.text) DESC, m.ts DESC LIMIT %s""", [auto_re] + fargs + [q, q, TOPK]).fetchall()
            conn.execute("SET LOCAL statement_timeout = 0")
        trgm_ids = [r[0] for r in rows]
    except Exception as e:
        if getattr(e, "sqlstate", None) == "57014":
            notices.append("[철자 유사 시간 초과(5초) — 임베딩만 사용]")
        else:
            raise
    if not emb_ids and not trgm_ids and not notices:
        pass
    fused = rrf({"임베딩": emb_ids, "철자": trgm_ids})[:limit]
    if not fused:
        return [], notices
    ids = [f[0] for f in fused]
    det = {r[0]: r for r in conn.execute("""SELECT m.uuid, m.ts, m.session_id, s.host, s.repo_url, s.branch, m.text FROM messages m JOIN sessions s USING (session_id)
                                           WHERE m.uuid = ANY(%s)""", (ids,)).fetchall()}
    res = []
    for u, sc, sr in fused:
        if u in det:
            _u, ts, sid, host, rurl, br, text = det[u]
            res.append(dict(uuid=u, ts=ts, session_id=sid, host=host, repo_url=rurl, branch=br, text=text, chunk=chunk_of.get(u), score=sc, sources=sr))
    # 색인 대기 건수(표가 있을 때만) — 「없다」로 읽히지 않게
    try:
        with conn.transaction():
            n = conn.execute(f"SELECT count(*) FROM ({_pending_sql()}) t", [auto_re, model]).fetchone()[0]
        if n:
            notices.append(f"[색인 대기: {n}건 — `donghans ctx embed-index` 로 색인하면 의미 검색 범위에 들어온다]")
    except Exception as e:
        if not _is_missing_table(e):
            raise
    return res, notices
