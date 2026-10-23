#!/usr/bin/env python3
"""ctxdata 시험(임시 Postgres): 개요 집계 · 검색 · 저장소별 발언 대조 · 세션 맥락 · 비밀 관리 · 후보 승인."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
check, finish = checker()
try:
    import psycopg  # noqa: F401
except ImportError:
    print("psycopg 가 없어 건너뜀"); sys.exit(0)
import pgscratch
pg = pgscratch.start()
if not pg:
    print("postgres 바이너리를 못 찾아 건너뜀"); sys.exit(0)
try:
    os.environ.update(pg.env())
    import ctx_secrets as cs, ctxdata as cd, claude_ctx as cc
    conn = cc.connect()

    def seed(sid, repo, host, msgs):
        conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)", (sid, host, [host], repo, msgs[0][2], msgs[-1][2]))
        for i, (role, kind, ts, text) in enumerate(m[:4] for m in msgs):
            conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                         (f"{sid[:4]}-{i:04d}", sid, host, ts, role, kind, text, json.dumps({"i": i})))
    A, B = "https://github.com/x/alpha", "https://github.com/x/beta"
    seed("aaaa0001", A, "h1", [("user", "prompt", "2026-10-01T01:00:00Z", "alpha 배포는 금요일에 한다고 했다"), ("assistant", "response", "2026-10-01T01:00:10Z", "알겠습니다 금요일 배포"),
                               ("user", "prompt", "2026-10-02T01:00:00Z", "비번은 hunter2-pass 로 해줘"), ("assistant", "response", "2026-10-02T01:00:10Z", "hunter2-pass 로 설정")])
    seed("bbbb0001", B, "h2", [("user", "prompt", "2026-10-03T01:00:00Z", "beta 는 월요일에 배포한다"), ("assistant", "response", "2026-10-03T01:00:10Z", "배포 일정 확인"),
                               ("user", "prompt", "2026-10-04T01:00:00Z", "배포 금요일로 바꾸자"), ("assistant", "tool_use", "2026-10-04T01:00:20Z", "[tool_use Bash] ls")])
    seed("cccc0001", None, "h1", [("user", "prompt", "2026-10-05T01:00:00Z", "저장소 없는 세션의 배포 이야기")])
    conn.commit()

    ov = cd.overview(conn)
    check("overview: 합계(세션 3·메시지 9·프롬프트 5)", (ov["totals"]["sessions"], ov["totals"]["messages"], ov["totals"]["prompts"]) == (3, 9, 5), str(ov["totals"]))
    check("overview: DB 크기·표별 크기", ov["totals"]["db_bytes"] > 0 and any(t["name"] == "messages" and t["bytes"] > 0 for t in ov["tables"]))
    pj = {p["repo"]: p for p in ov["projects"]}
    check("overview: 저장소별 집계", pj[A]["messages"] == 4 and pj[A]["prompts"] == 2 and pj[A]["sessions"] == 1 and pj[B]["messages"] == 4 and pj[A]["hosts"] == ["h1"])
    check("overview: 저장소 없는 세션은 별도 항목", pj["(저장소 없음)"]["messages"] == 1)
    check("overview: 텍스트 글자수·저장 바이트 > 0", pj[A]["text_chars"] > 0 and pj[A]["stored_bytes"] > 0 and pj[A]["last_ts"] is not None)
    check("overview: 메시지 많은 순 정렬", [p["messages"] for p in ov["projects"]] == sorted((p["messages"] for p in ov["projects"]), reverse=True))
    check("human_bytes", cd.human_bytes(500) == "500 B" and cd.human_bytes(1536) == "1.5 KB" and cd.human_bytes(5 * 1024 ** 2) == "5.0 MB")

    r = cd.search(conn, "배포")
    check("search: 부분 일치(프롬프트·응답만, tool_use 제외)", len(r) == 6 and all(x["kind"] in ("prompt", "response") for x in r), str(len(r)))
    check("search: 최신순", [x["ts"] for x in r] == sorted((x["ts"] for x in r), reverse=True))
    check("search: 저장소 필터(부분 일치)", {x["repo"] for x in cd.search(conn, "배포", repo="alpha")} == {A})
    check("search: 역할 필터", all(x["role"] == "user" for x in cd.search(conn, "배포", role="user")))
    check("search: 정규식", len(cd.search(conn, r"금요일|월요일", regex=True)) == 4)
    try: cd.search(conn, "([a-", regex=True); check("search: 잘못된 정규식은 ValueError", False)
    except ValueError: check("search: 잘못된 정규식은 ValueError", True)
    check("search: LIKE 특수문자(%, _)는 글자 그대로", cd.search(conn, "100%") == [] and cd.search(conn, "_") == [])
    check("search: days 필터(오래된 데이터 제외)", cd.search(conn, "배포", days=1) == [])
    check("search: 스니펫에 검색어 포함", "금요일" in cd.search(conn, "금요일")[0]["snippet"])
    check("search: 빈 검색어는 최근 메시지", len(cd.search(conn, "", limit=3)) == 3)

    m = cs.Masker([dict(label="PW", kind="literal", value="hunter2-pass")])
    r = cd.search(conn, "설정", masker=m)
    check("search: masker 로 스니펫·전체 치환", "hunter2-pass" not in r[0]["snippet"] and "hunter2-pass" not in r[0]["full"] and "[protected]" in r[0]["full"])
    check("search: masker 없으면 원문", any("hunter2-pass" in x["full"] for x in cd.search(conn, "설정")))

    g = cd.phrase_by_repo(conn, "배포")
    byrepo = {x["repo"]: x for x in g}
    check("phrase_by_repo: 사용자 발언만 저장소별 건수", byrepo[A]["count"] == 1 and byrepo[B]["count"] == 2 and byrepo["(저장소 없음)"]["count"] == 1, str(g))
    check("phrase_by_repo: 많은 순 + 최근 시각 + 인용", g[0]["repo"] == B and g[0]["last"] is not None and "배포" in g[0]["quote"])
    check("phrase_by_repo: 응답은 대상 아님(role=user)", sum(x["count"] for x in g) == 4)

    s, msgs = cd.session_context(conn, "aaaa0001")
    check("session_context: 세션 요약·시간순 4개", s["repo"] == A and s["host"] == "h1" and [x["role"] for x in msgs] == ["user", "assistant", "user", "assistant"])
    s, msgs = cd.session_context(conn, "aaaa0001", around_uuid="aaaa-0002", window=1)
    check("session_context: around 는 앞뒤 window 만", [x["uuid"] for x in msgs] == ["aaaa-0001", "aaaa-0002", "aaaa-0003"])
    s, msgs = cd.session_context(conn, "aaaa0001", masker=m)
    check("session_context: 치환", all("hunter2-pass" not in x["text"] for x in msgs))
    check("session_context: 없는 세션", cd.session_context(conn, "nope")[0] is None)

    # --- 비밀 관리
    cd.adopt(conn, "hunter2-pass", "NAS_PW", "manual")
    rows = cd.secret_rows(conn)
    check("adopt/secret_rows: 등록되고 길이·fp 제공", rows[0]["label"] == "NAS_PW" and rows[0]["length"] == 12 and rows[0]["fp"] == cs.fingerprint("hunter2-pass") and rows[0]["enabled"])
    check("occurrences: 원문에 들어 있는 메시지 수", cd.occurrences(conn, "hunter2-pass") == 2)
    check("occurrences: LIKE 특수문자 안전", cd.occurrences(conn, "100%") == 0)
    check("set_enabled: 끄기", cd.set_enabled(conn, "NAS_PW", False) == 1 and not cd.secret_rows(conn)[0]["enabled"] and cs.load_secrets(conn) == [])
    cd.set_enabled(conn, "NAS_PW", True)
    check("set_enabled: 없는 이름은 0", cd.set_enabled(conn, "NOPE", True) == 0)
    try: cd.adopt(conn, "other-secret-x", "NAS_PW"); check("adopt: 중복 이름 거부", False)
    except ValueError: check("adopt: 중복 이름 거부", True)

    # --- 후보
    seed("dddd0001", A, "h1", [("user", "prompt", "2026-10-06T01:00:00Z", "키는 sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV 이고 DB_PASSWORD=Zx9#kLm2$pQ 야")])
    conn.commit()
    c = cd.scan_candidates(conn)
    pats = {x["pattern"] for x in c}
    check("scan_candidates: 키·비밀번호 후보, 이미 등록된 hunter2-pass 는 제외", {"anthropic_key", "assigned_secret"} <= pats and all(x["value"] != "hunter2-pass" for x in c), str(pats))
    key = next(x for x in c if x["pattern"] == "anthropic_key")
    check("scan_candidates: 횟수·세션·저장소", key["count"] == 1 and key["sessions"] == {"dddd0001"} and key["repos"] == {A})
    cd.adopt(conn, key["value"], "ANTHROPIC_KEY", key["pattern"])
    check("adopt 한 후보는 목록에서 빠짐", all(x["fp"] != key["fp"] for x in cd.scan_candidates(conn)))
    other = next(x for x in cd.scan_candidates(conn) if x["pattern"] == "assigned_secret")
    cd.ignore_fp(conn, other["fp"], other["pattern"])
    check("ignore 한 후보는 목록에서 빠짐", all(x["fp"] != other["fp"] for x in cd.scan_candidates(conn)) and other["fp"] in cd.ignored_fps(conn))
    check("scan_candidates: min_count 필터", cd.scan_candidates(conn, min_count=99) == [])
    check("delete_secret", cd.delete_secret(conn, "ANTHROPIC_KEY") == 1 and cd.delete_secret(conn, "ANTHROPIC_KEY") == 0)
    conn.close()
finally:
    pg.stop()
finish("ctxdata")
