#!/usr/bin/env python3
"""ctx_embed(의미 검색) 시험 — 계획: ctx plan/ctx-의미검색-S2 §6.
순수 함수(청크·머리말·RRF·벡터 표기·설정·임베딩 클라이언트·치환 순서)는 psycopg 없이 돈다. DB 부분(색인 멱등·건너뜀·서버/표 불가 대체·질의 비밀 거부)은
psycopg + postgres 17 이 있을 때만 돌고, 없으면 건너뛴다(통과로 세지 않는다 — 출력에 「건너뜀」).
알려진 한계(시험 범위 밖): 임시 Postgres 는 `initdb --no-locale`(C)이라 **한글 철자 유사(pg_trgm)가 0** 이다 — 철자 쪽 시험은 ASCII 데이터만 쓴다. 한글은 실데이터 평가에서 확인한다.
철자 유사의 statement_timeout(57014) 경로도 이 시험에서는 만들지 않았다(실서버 평가에서 확인)."""
import http.server, json, os, re, shutil, stat, subprocess, sys, tempfile, threading, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctx_embed as ce
import ctx_secrets as cs

# ---------------------------------------------------------------- 청크
def nonspace_idx(t):
    return {i for i, ch in enumerate(t) if not ch.isspace()}

samples = {
    "빈 문자열": "",
    "짧은 한 줄": "임시계약으로 처리하자.",
    "여러 문장": "첫 문장입니다. 두 번째 문장이에요? 세 번째! 네 번째 문장은 조금 더 길게 씁니다.",
    "줄바꿈": "첫째 줄\n둘째 줄\n\n셋째 줄 마지막",
    "구분자 없는 긴 글": "가" * 700,
    "문장 하나가 한도 초과": "나" * 300 + ". 짧은 문장.",
    "어미 공백 분리": "그렇게 하시죠 그리고 다음은 이렇게 진행하죠 마지막으로 확인합시다",
}
for name, t in samples.items():
    sp = ce.chunk_spans(t)
    covered = set()
    for s, e in sp:
        covered |= set(range(s, e))
    check(f"청크: 모든 비공백 글자가 구간에 들어간다 — {name}", nonspace_idx(t) <= covered, f"빠진 글자 {len(nonspace_idx(t) - covered)}개")
    check(f"청크: 각 구간이 한도({ce.CHUNK_MAX}자) 이하 — {name}", all(e - s <= ce.CHUNK_MAX for s, e in sp))
    check(f"청크: 구간이 순서대로·겹치지 않는다 — {name}", all(sp[i][1] <= sp[i + 1][0] for i in range(len(sp) - 1)))
    joined = re.sub(r"\s+", "", "".join(ce.chunks(t)))
    check(f"청크: 이어 붙이면 원문의 비공백 글자와 같다(마지막 청크 포함) — {name}", joined == re.sub(r"\s+", "", t))
check("청크: 빈 입력은 청크 없음", ce.chunks("") == [] and ce.chunks("   \n ") == [])
check("meaningful: 치환 표지만 있으면 내용 없음", not ce.meaningful(ce.MASK) and not ce.meaningful(f" {ce.MASK} ") and ce.meaningful("ab") and not ce.meaningful("a"))

# ---------------------------------------------------------------- 머리말
check("머리말: 날짜·세션 주제·청크", ce.build_input("2026-11-27", "프리랜서 가이드", "본문") == "[2026-11-27 · 세션 주제: 프리랜서 가이드] 본문")
check("머리말: 주제 없으면 날짜만", ce.build_input("2026-11-27", "", "본문") == "[2026-11-27] 본문")
check("머리말: 주제는 앞 50자", ce.build_input("d", "가" * 80, "x") == "[d · 세션 주제: " + "가" * 50 + "] x")

# ---------------------------------------------------------------- RRF
a = ["u1", "u2", "u3"]; b = ["u3", "u1", "u9"]
r1 = ce.rrf({"임베딩": a, "철자": b}); r2 = ce.rrf({"철자": b, "임베딩": a})
check("RRF: 입력 순서가 달라도 같은 결과(결정적)", r1 == r2)
check("RRF: 두 목록에 다 있는 것이 위 + 출처 표시", r1[0][0] in ("u1", "u3") and set(r1[0][2]) == {"임베딩", "철자"})
sc = {i: s for i, s, _ in r1}
check("RRF: 점수 = Σ 1/(60+순위)", abs(sc["u1"] - (1 / 61 + 1 / 62)) < 1e-12 and abs(sc["u9"] - 1 / 63) < 1e-12)
tie = ce.rrf({"x": ["b"], "y": ["a"]})
check("RRF: 동률은 id 문자열 순(결정적)", [t[0] for t in tie] == ["a", "b"])
check("RRF: 한 목록 안 중복 id 는 한 번만 센다", ce.rrf({"x": ["a", "a", "b"]})[0][1] == 1 / 61)
check("RRF: k 를 바꾸면 점수가 바뀐다", abs(ce.rrf({"x": ["a"]}, k=10)[0][1] - 1 / 11) < 1e-12)
check("벡터 표기", ce.vec_literal([1, 0.5, -2]) == "[1,0.5,-2]")

# ---------------------------------------------------------------- 설정
tmp = tempfile.mkdtemp(); oldhome = os.environ.get("HOME")
try:
    os.environ["HOME"] = tmp
    for k in ("CTX_EMBED_URL", "CTX_EMBED_KEY"):
        os.environ.pop(k, None)
    check("설정: 없으면 None", ce.load_config() is None)
    os.makedirs(os.path.join(tmp, ".config", "claude-ctx"))
    p = ce.config_path()
    open(p, "w").write(json.dumps({"url": "http://h:1/", "key": "k1"}))
    os.chmod(p, 0o644)
    try:
        ce.load_config(); ok = False
    except ce.EmbedError:
        ok = True
    check("설정: 키가 든 파일 권한이 600 보다 넓으면 거부", ok)
    os.chmod(p, 0o600)
    check("설정: 파일(600) → (url 끝 슬래시 제거, 키)", ce.load_config() == ("http://h:1", "k1"))
    open(p, "w").write(json.dumps({"url": "http://h:2"})); os.chmod(p, 0o644)
    check("설정: 키 없는 파일은 권한이 넓어도 허용", ce.load_config() == ("http://h:2", None))
    os.environ["CTX_EMBED_URL"] = "http://env:3"; os.environ["CTX_EMBED_KEY"] = "ek"
    check("설정: 환경변수가 우선", ce.load_config() == ("http://env:3", "ek"))
finally:
    for k in ("CTX_EMBED_URL", "CTX_EMBED_KEY"):
        os.environ.pop(k, None)
    if oldhome is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = oldhome
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- 임베딩 클라이언트(가짜 서버)
def fake_vec(text):
    v = [0.0] * ce.DIM
    for t in re.findall(r"\w+", text.lower()):
        v[zlib.crc32(t.encode()) % ce.DIM] += 1.0
    return v

class H(http.server.BaseHTTPRequestHandler):
    reqs = []; mode = "ok"
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        H.reqs.append((self.path, self.headers.get("Authorization"), body))
        if H.mode == "500":
            self.send_response(500); self.end_headers(); return
        if H.mode == "baddim":
            out = {"data": [{"index": i, "embedding": [0.0] * 3} for i, _ in enumerate(body["input"])]}
        elif H.mode == "short":
            out = {"data": []}
        else:
            out = {"data": [{"index": i, "embedding": fake_vec(t)} for i, t in reversed(list(enumerate(body["input"])))]}   # 일부러 역순
        raw = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
try:
    vs = ce.embed(["alpha beta", "gamma"], URL, "secret-key")
    check("임베딩 클라이언트: 입력 순서대로 벡터 반환(서버가 역순으로 줘도 index 로 정렬)", len(vs) == 2 and vs[0] == fake_vec("alpha beta") and vs[1] == fake_vec("gamma"))
    check("임베딩 클라이언트: 경로·키·본문", H.reqs[-1][0] == "/v1/embeddings" and H.reqs[-1][1] == "Bearer secret-key" and H.reqs[-1][2]["input"] == ["alpha beta", "gamma"])
    for mode, label in (("500", "HTTP 오류"), ("baddim", "차원 이상"), ("short", "개수 불일치")):
        H.mode = mode
        try:
            ce.embed(["x"], URL); ok = False
        except ce.EmbedError:
            ok = True
        check(f"임베딩 클라이언트: {label} 는 EmbedError", ok)
    H.mode = "ok"
    try:
        ce.embed(["x"], "http://127.0.0.1:9", timeout=1); ok = False
    except ce.EmbedError:
        ok = True
    check("임베딩 클라이언트: 연결 실패는 EmbedError", ok)

    # ---------------------------------------------------------- 치환 순서(비밀이 청크 경계에 걸쳐도 임베딩 입력에 없다)
    SECRET = "S3cr3tPassw0rdXYZ-ABC123"
    masker = cs.Masker([dict(label="t", kind="literal", value=SECRET)])
    pre = "가" * (ce.CHUNK_MAX - 8)          # 비밀이 첫 청크 한도(260자)를 가로지르게 앞에 채운다
    text = pre + SECRET + " 이후 문장입니다."
    naive = [masker.text(c) for c in ce.chunks(text)]   # 청크를 먼저 자르고 치환(잘못된 순서)
    leaks = [c for c in naive if "S3cr3t" in c or "ABC123" in c]
    check("치환 순서: (확인) 청크를 먼저 자르고 치환하면 비밀 조각이 남는다 — 이 시험이 잘못된 순서를 잡는다는 증거", bool(leaks))
    cs_, ins = ce.plan_message(masker, text, "2026-11-27", "주제")
    allout = "\n".join(cs_ + ins)
    check("치환 순서: 메시지 전체를 먼저 치환하면 청크·임베딩 입력에 비밀(조각 포함)이 없다", "S3cr3t" not in allout and "ABC123" not in allout and SECRET not in allout)
    check("치환 순서: 치환 표지는 남고 표지 한가운데에서 잘리지 않는다", ce.MASK in allout and all(("[protect" not in c) or (ce.MASK in c) for c in cs_) and all(not c.startswith("ed]") for c in cs_))
    cs2, ins2 = ce.plan_message(masker, "비밀 " + SECRET, "2026-11-27", SECRET + " 주제")
    check("치환 순서: 머리말의 세션 주제도 치환된다", all("S3cr3t" not in i for i in ins2) and ins2 != [])
    cs3, _ = ce.plan_message(masker, SECRET, "2026-11-27", "")
    check("치환 뒤 의미 있는 글자가 없으면 청크 없음(건너뜀 대상)", cs3 == [])

    # ---------------------------------------------------------- DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("psycopg 가 없어 DB 시험을 건너뜀(통과로 세지 않음)"); finish("ctx_embed")
    import pgscratch
    pg = pgscratch.start()
    if not pg:
        print("postgres 바이너리를 못 찾아 DB 시험을 건너뜀(통과로 세지 않음)"); finish("ctx_embed")
    try:
        os.environ.update(pg.env())
        import ctxdata as cd, llm_ctx as cc
        conn = cc.connect()
        check("스키마: 마이그레이션 8·message_chunks·부분 trgm 인덱스", conn.execute("SELECT count(*) FROM schema_version WHERE v=8").fetchone()[0] == 1
              and conn.execute("SELECT to_regclass('message_chunks')").fetchone()[0] is not None
              and conn.execute("SELECT count(*) FROM pg_indexes WHERE indexname='messages_trgm_userprompt'").fetchone()[0] == 1)

        def seed(sid, excluded=False, repo="https://github.com/x/alpha"):
            conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts, excluded_at) VALUES (%s,%s,%s,%s,now(),now(),%s)",
                         (sid, "h1", ["h1"], repo, "2026-10-01T00:00:00Z" if excluded else None))
        n = {"i": 0}

        def msg(sid, role, kind, text, side=False):
            n["i"] += 1
            conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, is_sidechain, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (f"{sid}-{n['i']:03d}", sid, "h1", f"2026-11-{n['i']:02d}T01:00:00Z", role, kind, side, text, json.dumps({})))
            return f"{sid}-{n['i']:03d}"
        seed("s1"); seed("s2", excluded=True)
        u_deploy = msg("s1", "user", "prompt", "we deploy the billing service on friday afternoon.")
        u_refund = msg("s1", "user", "prompt", "refund policy keeps ten percent fee. customers cancel before departure.")
        u_secret = msg("s1", "user", "prompt", "the token is " + SECRET + " keep it safe")
        u_masked = msg("s1", "user", "prompt", SECRET)                        # 전부 치환되면 건너뜀 행
        msg("s1", "assistant", "response", "assistant answer about friday deploy")   # 사용자 프롬프트가 아님
        msg("s1", "user", "prompt", "<task-notification> auto message friday deploy")  # 자동 메시지
        msg("s1", "user", "prompt", "subagent brief friday deploy", side=True)       # 서브에이전트 브리프
        msg("s2", "user", "prompt", "excluded session friday deploy")               # 제외 세션
        conn.commit()
        sent = []

        def emb_fake(texts):
            sent.extend(texts); return [fake_vec(t) for t in texts]
        st = ce.index_messages(conn, masker, emb_fake, cd.AUTO_RE, dry_run=True)
        check("색인 dry-run: 대상은 사용자 프롬프트 4건(자동·브리프·응답·제외 세션 제외)이고 임베딩 호출·쓰기 없음",
              st["messages"] == 4 and st["skipped"] == 1 and st["chunks"] == 3 and sent == []
              and conn.execute("SELECT count(*) FROM message_chunks").fetchone()[0] == 0, str(st))
        st = ce.index_messages(conn, masker, emb_fake, cd.AUTO_RE)
        rows = conn.execute("SELECT count(*), count(embedding) FROM message_chunks").fetchone()
        check("색인: 청크 3개 + 건너뜀 행 1개(embedding NULL)", rows == (4, 3) and st["failed"] == 0, f"{rows} {st}")
        check("색인: 임베딩 요청에 비밀이 없다(치환 뒤 전송)", sent and all(SECRET not in t and "S3cr3t" not in t for t in sent) and any(ce.MASK in t for t in sent))
        check("색인: 저장된 청크 본문에도 비밀이 없다", conn.execute("SELECT count(*) FROM message_chunks WHERE chunk_text LIKE %s", ("%S3cr3t%",)).fetchone()[0] == 0)
        check("색인: 머리말(날짜·세션 주제)이 요청에 들어간다", any(t.startswith("[2026-11-") and "세션 주제: we deploy" in t for t in sent))
        before = len(sent)
        st2 = ce.index_messages(conn, masker, emb_fake, cd.AUTO_RE)
        check("색인 멱등: 다시 돌려도 대상 0건·청크 수 불변·요청 없음(건너뜀 행도 다시 잡히지 않음)",
              st2["messages"] == 0 and len(sent) == before and conn.execute("SELECT count(*) FROM message_chunks").fetchone()[0] == 4, str(st2))

        # 검색 — 서버/표가 되는 경우
        res, notes = ce.semantic_search(conn, "billing deploy friday", emb_fake, cd.AUTO_RE)
        ids = [r["uuid"] for r in res]
        check("검색: 사용자 프롬프트만 나온다(응답·자동·브리프·제외 세션 없음)", ids and all(i.startswith("s1-") for i in ids) and u_deploy in ids)
        check("검색: 임베딩+철자 둘 다 잡은 것이 위", res[0]["uuid"] == u_deploy and set(res[0]["sources"]) == {"임베딩", "철자"}, str([(r['uuid'], r['sources']) for r in res]))
        check("검색: 색인 대기 알림이 없다(전부 색인됨)", not any("색인 대기" in x for x in notes), str(notes))
        # 서버 불가 → 철자 유사만 + 알림
        def emb_down(texts):
            raise ce.EmbedError("임베딩 서버 응답 없음(테스트)")
        res2, notes2 = ce.semantic_search(conn, "billing deploy friday", emb_down, cd.AUTO_RE)
        check("서버 불가: 철자 유사만으로 결과를 내고 알림(「의미 검색 불가」)을 준다", res2 and all(r["sources"] == ("철자",) for r in res2) and any("의미 검색 불가" in x and "철자 유사만" in x for x in notes2), str(notes2))
        # 색인 대기 알림: 새 프롬프트 추가
        msg("s1", "user", "prompt", "brand new prompt about billing friday")
        conn.commit()
        _r, notes3 = ce.semantic_search(conn, "billing", emb_fake, cd.AUTO_RE)
        check("색인 대기: 아직 색인 안 된 메시지가 있으면 알린다", any("색인 대기: 1건" in x for x in notes3), str(notes3))
        # 기본 검색 = 글자 일치 + 의미 검색 후보 블록(--literal·CTX_NO_SEMANTIC·호환 안 되는 옵션이면 생략)
        import argparse, io, contextlib
        os.environ["CTX_EMBED_URL"] = URL; os.environ.pop("CTX_NO_SEMANTIC", None)

        def ns2(**kw):
            d = dict(query=["x"], repo=None, here=False, role=None, session=None, kind=None, days=None, limit=15, include_excluded=False, count=False, by=None,
                     not_=None, semantic=False, literal=False, local=False, tz="Asia/Seoul", raw=False)
            d.update(kw); return argparse.Namespace(**d)

        def run(a_):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = cc.cmd_search(a_)
                except SystemExit as e:
                    rc = e.code
            return rc, out.getvalue(), err.getvalue()
        H.reqs.clear()
        rc, out, err = run(ns2(query=["deploy billing"]))
        check("기본 검색: 글자 일치가 없어도 의미 검색 후보 블록이 붙는다", "의미 검색 후보" in out and "billing service on friday" in out and H.reqs != [], out[:300] + err[:200])
        rc, out, err = run(ns2(query=["billing"]))
        keys = re.findall(r"^\[(.+?)\] (\S+)", out, flags=re.M)
        check("기본 검색: 글자 일치 결과와 의미 검색 후보가 겹치지 않는다(같은 메시지가 두 번 나오지 않음)", keys and len(set(keys)) == len(keys), str(keys))
        H.reqs.clear()
        rc, out, err = run(ns2(query=["deploy billing"], literal=True))
        check("--literal: 의미 검색 블록도 임베딩 요청도 없다", "의미 검색 후보" not in out and H.reqs == [] and rc == 0, out[:200])
        os.environ["CTX_NO_SEMANTIC"] = "1"
        rc, out, err = run(ns2(query=["deploy billing"]))
        check("CTX_NO_SEMANTIC=1: 의미 검색 블록도 임베딩 요청도 없다", "의미 검색 후보" not in out and H.reqs == [], out[:200])
        os.environ.pop("CTX_NO_SEMANTIC")
        rc, out, err = run(ns2(query=["billing"], kind="all"))
        check("호환 안 되는 옵션(--kind)이면 의미 검색을 생략하고 그 사실을 알린다", "의미 검색 생략" in err and "의미 검색 후보" not in out and H.reqs == [], err[:200])
        rc, out, err = run(ns2(query=["billing"], count=True))
        check("--count 에는 의미 검색을 붙이지 않는다", "의미 검색 후보" not in out and H.reqs == [])
        os.environ.pop("CTX_EMBED_URL", None)
        rc, out, err = run(ns2(query=["deploy billing"]))
        check("임베딩 설정이 없어도 글자 일치 검색은 정상이고 의미 검색 쪽은 사유를 알린다", rc == 0 and "의미 검색 불가" in err and "설정 없음" in err, err[:200])
        os.environ["CTX_EMBED_URL"] = URL
        # 표가 없는 서버 → 대체 + 알림 + 연결이 계속 쓸 수 있다
        conn.execute("DROP TABLE message_chunks"); conn.commit()
        res4, notes4 = ce.semantic_search(conn, "billing deploy friday", emb_fake, cd.AUTO_RE)
        check("표 없음: 철자 유사만으로 결과를 내고 알림(「색인 테이블」)을 준다", res4 and any("색인 테이블" in x for x in notes4), str(notes4))
        check("표 없음: 예외 뒤에도 같은 연결로 쿼리할 수 있다(savepoint)", conn.execute("SELECT 1").fetchone()[0] == 1)
        # CLI: 질의 비밀·옵션 거부
        import argparse
        cs.add_secret(conn, "q_secret", "literal", "qsecretvalue987654", force=True); conn.commit()
        H.reqs.clear(); os.environ["CTX_EMBED_URL"] = URL
        ns = dict(query=["qsecretvalue987654"], repo=None, here=False, role=None, session=None, kind=None, days=None, limit=15, include_excluded=False, count=False, by=None, not_=None, semantic=True, literal=False, local=False, tz="Asia/Seoul", raw=False)
        try:
            cc.cmd_search(argparse.Namespace(**ns)); ok = False
        except SystemExit as e:
            ok = "비밀" in str(e.code)
        check("질의에 등록된 비밀이 있으면 임베딩 요청 없이 거부한다", ok and H.reqs == [], str(H.reqs))
        for opt, val in (("kind", "all"), ("role", "user"), ("count", True), ("by", "day"), ("not_", ["x"])):
            try:
                cc.cmd_search(argparse.Namespace(**{**ns, "query": ["billing"], opt: val})); ok = False
            except SystemExit as e:
                ok = "--semantic" in str(e.code)
            check(f"--semantic 과 {opt} 를 같이 주면 거부한다", ok)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "embed-index", "--raw"], capture_output=True, text=True, env=pg.env())
        check("embed-index 는 --raw 를 받지 않는다(치환 해제 불가)", r.returncode != 0 and "unrecognized" in r.stderr, r.stderr[-200:])
        # DB(정본) 연결 불가 → 이 호스트의 로컬 기록으로 자동 폴백 / --local
        import ctx_local as cl
        pdir = os.path.join(pg.home, ".claude", "projects", "-tmp-proj"); os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "sess1234-0000.jsonl"), "w") as fh:
            for rec in (
                {"type": "user", "timestamp": "2026-11-20T01:00:00Z", "message": {"role": "user", "content": "zebra stripes question password=Abcdef123456xyz"}},
                {"type": "assistant", "timestamp": "2026-11-20T01:00:05Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "zebra answer"}, {"type": "tool_use", "name": "Bash", "input": {"command": "zebra"}}]}},
                {"type": "user", "timestamp": "2026-11-20T01:00:09Z", "message": {"role": "user", "content": [{"type": "tool_result", "content": "zebra tool output"}]}},
                {"type": "user", "timestamp": "2026-11-20T01:00:10Z", "message": {"role": "user", "content": "<task-notification> zebra auto"}},
            ):
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        good_dsn = os.environ["CLAUDE_CTX_DSN"]
        os.environ["CLAUDE_CTX_DSN"] = "host=/nonexistent port=1 dbname=x user=y"
        try:
            rc, out, err = run(ns2(query=["zebra"]))
        finally:
            os.environ["CLAUDE_CTX_DSN"] = good_dsn
        check("DB 연결 불가: 알리고(「정본(DB) 연결 불가」) 로컬 기록으로 대신 찾는다(종료 코드 0)", rc == 0 and "정본(DB) 연결 불가" in err and "이 호스트" in err and "zebra stripes question" in out and "zebra answer" in out, out[:200] + err[:200])
        check("로컬 폴백: 도구 결과·자동 메시지는 결과에 없다", "tool output" not in out and "zebra auto" not in out)
        check("로컬 폴백: 비밀 후보(password=값)는 가려진다", "Abcdef123456xyz" not in out and "[protected]" in out, out[:300])
        check("로컬 폴백: 한계(이 호스트만·없다는 뜻이 아님)를 항상 알린다", "다른 호스트" in err and "기록이 없다는 뜻이 아니다" in err)
        H.reqs.clear()
        rc, out, err = run(ns2(query=["zebra"], local=True))
        check("--local: DB·임베딩 서버 없이 로컬 기록만 본다", rc == 0 and "zebra stripes question" in out and H.reqs == [] and "정본(DB) 연결 불가" not in err)
        res_l, nf, to = cl.search_local("zebra", cd.AUTO_RE, here_cwd="/tmp/proj")
        check("로컬 폴백: --here 는 경로를 폴더 이름(`/`·`.` → `-`)으로 바꿔 그 프로젝트만 본다", len(res_l) == 2 and nf == 1)
        res_l, nf, to = cl.search_local("zebra", here_cwd="/other/place")
        check("로컬 폴백: 다른 경로의 --here 는 결과 없음(읽은 파일 0)", res_l == [] and nf == 0)
        res_l, _nf, _to = cl.search_local("zebra", cd.AUTO_RE, role="assistant")
        check("로컬 폴백: --role assistant 는 모델 응답만", len(res_l) == 1 and res_l[0]["role"] == "assistant")
        res_l, _nf, _to = cl.search_local("ZEBRA", cd.AUTO_RE)
        check("로컬 폴백: 대소문자 무시", len(res_l) == 2)
        res_l, nf, _to = cl.search_local("zebra", session="nomatch")
        check("로컬 폴백: --session 접두가 안 맞으면 파일을 읽지 않는다", res_l == [] and nf == 0)
        conn.close()
    finally:
        pg.stop()
finally:
    srv.shutdown()
finish("ctx_embed")
