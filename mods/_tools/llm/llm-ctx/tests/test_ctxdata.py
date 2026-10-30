#!/usr/bin/env python3
"""ctxdata 시험(임시 Postgres): 개요 집계 · 검색 · 저장소별 발언 대조 · 세션 맥락 · 비밀 관리 · 후보 승인."""
import os, sys, json
from datetime import timezone
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
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
    import ctx_secrets as cs, ctxdata as cd, llm_ctx as cc
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
    # --- 통계(usage_events 기준): 시간대 경계 · 필터 · 분류 · 세션 통계/요약
    seed("eeee0001", A, "h1", [("user", "prompt", "2026-10-07T01:00:00Z", "비번 hunter2-pass 로 정리해줘"), ("assistant", "response", "2026-10-07T01:00:05Z", "네")])
    def usage(rid, sid, host, ts, model, cost, src="repl_main_thread", effort="medium"):
        conn.execute("""INSERT INTO usage_events (request_id, host, ts, session_id, model, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, cost_usd, query_source, effort)
                        VALUES (%s,%s,%s,%s,%s,100,10,1000,50,%s,%s,%s)""", (rid, host, ts, sid, model, cost, src, effort))
    usage("u1", "aaaa0001", "h1", "2026-10-01T01:00:00Z", "claude-sonnet-5-5", 1.0)
    usage("u2", "aaaa0001", "h1", "2026-10-01T15:30:00Z", "claude-haiku-5-5", 0.5, "agent_summary", "low")   # UTC 로는 10-01, KST 로는 10-02 00:30
    usage("u3", "bbbb0001", "h2", "2026-10-03T01:00:00Z", "claude-sonnet-5-5", 2.0)
    usage("u4", "zzzz9999", "h2", "2026-10-03T02:00:00Z", "claude-sonnet-5-5", 4.0)                         # sessions 에 없는 세션
    conn.execute("""INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens)
                    VALUES ('u5', 'h1', now() - interval '1 hour', 'cccc0001', 'claude-sonnet-5-5', 0.25, 1, 1, 0, 0)""")
    for i, (kind, side, raw, text) in enumerate([("tool_use", False, {}, "[tool_use Bash] a"), ("tool_use", False, {}, "[tool_use Bash] b"), ("tool_use", False, {}, "[tool_use Read] c"),
                                                 ("tool_use", True, {}, "[tool_use Grep] x"), ("tool_result", True, {}, "ok"),
                                                 ("other", False, {"subtype": "turn_duration", "durationMs": 5000}, ""), ("other", False, {"subtype": "compact_boundary"}, "")]):
        conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, is_sidechain, text, raw) VALUES (%s,'aaaa0001','h1','2026-10-02T02:00:00Z','assistant',%s,%s,%s,%s)",
                     (f"aaaa-x{i:03d}", kind, side, text, json.dumps(raw)))
    conn.commit()

    check("local_tz: IANA 이름 또는 UTC", isinstance(cd.local_tz(), str) and cd.local_tz())
    cov = cd.coverage(conn)
    check("coverage: usage 첫 시각 = 가장 오래된 요청", cov["usage_first"].astimezone(timezone.utc).isoformat().startswith("2026-10-01T01:00") and cov["usage_last"] > cov["usage_first"])
    tr = cd.usage_trend(conn, bucket="day", tz="UTC")
    check("usage_trend(일, UTC): 구간·비용 합계(10-01=1.5, 10-03=6.0, 오늘=0.25)", [round(r["cost"], 2) for r in tr] == [1.5, 6.0, 0.25] and tr[0]["requests"] == 2, str([(str(r["bucket"]), r["cost"]) for r in tr]))
    check("usage_trend: 오래된 것부터", [r["bucket"] for r in tr] == sorted(r["bucket"] for r in tr))
    tk = cd.usage_trend(conn, bucket="day", tz="Asia/Seoul")
    check("usage_trend: 시간대에 따라 하루 경계가 달라짐(KST 는 10-02 가 따로 생김)", [round(r["cost"], 2) for r in tk][:3] == [1.0, 0.5, 6.0], str([(str(r["bucket"]), r["cost"]) for r in tk]))
    check("usage_trend: 토큰 합(입력 100·출력 10·캐시읽기 1000·캐시생성 50)", (tr[0]["input"], tr[0]["output"], tr[0]["cache_read"], tr[0]["cache_create"]) == (200, 20, 2000, 100))
    check("usage_trend(월): 10월 한 구간(오늘 것 포함)", len(cd.usage_trend(conn, bucket="month", tz="UTC")) == 1)
    check("usage_trend: 저장소 필터(부분 일치)", round(sum(r["cost"] for r in cd.usage_trend(conn, repo="alpha")), 2) == 1.5)
    check("usage_trend: 머신 필터", round(sum(r["cost"] for r in cd.usage_trend(conn, host="h2")), 2) == 6.0)
    check("usage_trend: 모델 필터", round(sum(r["cost"] for r in cd.usage_trend(conn, model="haiku")), 2) == 0.5)
    check("usage_trend: 필터 조합(머신 h1 + 모델 sonnet)", round(sum(r["cost"] for r in cd.usage_trend(conn, host="h1", model="sonnet")), 2) == 1.25)
    check("usage_trend: 기간 필터(최근 1일은 u5 만)", [round(r["cost"], 2) for r in cd.usage_trend(conn, days=1)] == [0.25])
    check("usage_trend: 일치 없음은 빈 목록", cd.usage_trend(conn, repo="없는저장소") == [])
    try: cd.usage_trend(conn, bucket="year"); check("usage_trend: 잘못된 단위는 ValueError", False)
    except ValueError: check("usage_trend: 잘못된 단위는 ValueError", True)
    try: cd.usage_trend(conn, bucket="day; DROP TABLE messages"); check("usage_trend: 단위에 SQL 주입 불가", False)
    except ValueError: check("usage_trend: 단위에 SQL 주입 불가", True)
    check("usage_trend: 필터 값의 LIKE/따옴표 안전", cd.usage_trend(conn, repo="%") == [] and cd.usage_trend(conn, model="'; --") == [])

    rows_m, tot = cd.usage_breakdown(conn, "model")
    check("usage_breakdown(모델): 비용 큰 순·합계", [(r["key"], round(r["cost"], 2)) for r in rows_m] == [("claude-sonnet-5-5", 7.25), ("claude-haiku-5-5", 0.5)] and round(tot["cost"], 2) == 7.75 and tot["requests"] == 5)
    rows_r, _ = cd.usage_breakdown(conn, "repo")
    check("usage_breakdown(저장소): 세션 없는 요청은 (저장소 없음)", {r["key"]: round(r["cost"], 2) for r in rows_r} == {A: 1.5, B: 2.0, "(저장소 없음)": 4.25})
    check("usage_breakdown(머신·출처·effort)", {r["key"] for r in cd.usage_breakdown(conn, "host")[0]} == {"h1", "h2"} and {r["key"] for r in cd.usage_breakdown(conn, "source")[0]} == {"repl_main_thread", "agent_summary", "(모름)"}
          and {r["key"] for r in cd.usage_breakdown(conn, "effort")[0]} == {"medium", "low", "(모름)"})
    check("usage_breakdown: 필터 적용", [r["key"] for r in cd.usage_breakdown(conn, "model", host="h2")[0]] == ["claude-sonnet-5-5"])
    try: cd.usage_breakdown(conn, "x"); check("usage_breakdown: 잘못된 분류는 ValueError", False)
    except ValueError: check("usage_breakdown: 잘못된 분류는 ValueError", True)

    ss = cd.session_stats(conn)
    by = {x["session_id"]: x for x in ss}
    a = by["aaaa0001"]
    check("session_stats: 프롬프트·도구(서브에이전트 제외)·서브에이전트 메시지·턴시간·compact", (a["prompts"], a["tools"], a["subagent_msgs"], a["turn_ms"], a["compacts"]) == (2, 3, 2, 5000, 1), str(a))
    check("session_stats: 비용·요청·모델·토큰", round(a["cost"], 2) == 1.5 and a["requests"] == 2 and a["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"] and a["input"] == 2 * 1150 and a["output"] == 20)
    check("session_stats: 제목은 첫 사용자 프롬프트", a["title"].startswith("alpha 배포는") and by["bbbb0001"]["title"].startswith("beta 는"))
    check("session_stats: 사용 기록 없는 세션은 비용 None·요청 0", by["dddd0001"]["cost"] is None and by["dddd0001"]["requests"] == 0)
    check("session_stats: 기본은 비용 큰 순(없는 세션은 뒤)", [x["session_id"] for x in ss][:3] == ["bbbb0001", "aaaa0001", "cccc0001"], str([x["session_id"] for x in ss]))
    check("session_stats: 최근순(마지막 활동이 늦은 세션이 먼저)", [x["last"] for x in cd.session_stats(conn, order="last")] == sorted((x["last"] for x in ss), reverse=True))
    check("session_stats: 프롬프트순", cd.session_stats(conn, order="prompts")[0]["prompts"] >= cd.session_stats(conn, order="prompts")[-1]["prompts"])
    check("session_stats: 저장소 필터", {x["repo"] for x in cd.session_stats(conn, repo="alpha")} == {A})
    check("session_stats: 머신 필터", {x["host"] for x in cd.session_stats(conn, host="h2")} == {"h2"})
    check("session_stats: 모델 필터(그 모델 요청이 있는 세션만)", {x["session_id"] for x in cd.session_stats(conn, model="haiku")} == {"aaaa0001"})
    check("session_stats: 기간 필터(기간 안에 요청·메시지가 있는 세션만 — 마지막 활동이 오래돼도 1시간 전 요청이 있으면 포함)", {x["session_id"] for x in cd.session_stats(conn, days=1)} == {"cccc0001"})
    check("session_stats: limit", len(cd.session_stats(conn, limit=2)) == 2)
    masked = {x["session_id"]: x for x in cd.session_stats(conn, masker=cs.load_masker(conn))}
    check("session_stats: 제목도 치환(등록된 비밀은 [protected])", "hunter2-pass" not in masked["eeee0001"]["title"] and "protected" in masked["eeee0001"]["title"], masked["eeee0001"]["title"])
    check("session_stats: 치환 안 하면 원문", "hunter2-pass" in by["eeee0001"]["title"])
    try: cd.session_stats(conn, order="x"); check("session_stats: 잘못된 정렬은 ValueError", False)
    except ValueError: check("session_stats: 잘못된 정렬은 ValueError", True)

    sm = cd.session_summary(conn, repo="alpha", tz="UTC")
    check("session_summary: 세션·프롬프트·도구·비용", (sm["sessions"], int(sm["prompts"]), int(sm["tools"]), round(sm["cost"], 2)) == (3, 4, 3, 1.5), str(sm))
    check("session_summary: 시간대·요일 분포 합 = 프롬프트 수", sum(sm["by_hour"]) == 4 and sum(sm["by_weekday"]) == 4 and len(sm["by_hour"]) == 24 and len(sm["by_weekday"]) == 7)
    check("session_summary: 프롬프트 01시 UTC 4건(10-01 목·10-02 금·10-06 화·10-07 수)", sm["by_hour"][1] == 4 and sm["by_weekday"][3] == 1 and sm["by_weekday"][4] == 1 and sm["by_weekday"][1] == 1 and sm["by_weekday"][2] == 1, str(sm["by_hour"]))
    check("session_summary: 15분 단위 96칸(by_slot) 합 = 프롬프트 수, 01:00 UTC 대는 칸 4(01:00~01:15)에 모인다", len(sm["by_slot"]) == 96 and sum(sm["by_slot"]) == 4 and sum(sm["by_slot"][4:8]) == 4 and all(sm["by_hour"][h] == sum(sm["by_slot"][4 * h:4 * h + 4]) for h in range(24)), str(sm["by_slot"][:12]))
    sk = cd.session_summary(conn, repo="alpha", tz="Asia/Seoul")
    check("session_summary: 시간대 적용(KST 는 10시)", sk["by_hour"][10] == 4 and sk["by_hour"][1] == 0)
    check("session_summary: 중앙값·평균 길이는 0 이상", sm["median_duration_s"] >= 0 and sm["avg_duration_s"] >= 0)
    check("session_summary: 일치 없음", cd.session_summary(conn, repo="없는저장소")["sessions"] == 0 and sum(cd.session_summary(conn, repo="없는저장소")["by_hour"]) == 0)
    fc = cd.filter_choices(conn)
    check("filter_choices: 머신·모델 목록", fc["hosts"] == ["h1", "h2"] and "claude-haiku-5-5" in fc["models"])

    # --- 기간·필터가 세션 비용·프롬프트에도 적용된다(추이·분류 합계와 같은 요청 집합): 오래된 요청과 최근 요청이 섞인 세션 하나로 확인
    seed("ffff0001", A, "h9", [("user", "prompt", "2026-10-01T01:00:00Z", "오래된 프롬프트"), ("user", "prompt", "2026-10-01T02:00:00Z", "오래된 둘째")])
    conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES ('ffff-new', 'ffff0001', 'h9', now() - interval '30 minutes', 'user', 'prompt', '최근 프롬프트', '{}')")
    conn.execute("UPDATE sessions SET last_ts = now() - interval '30 minutes' WHERE session_id = 'ffff0001'")
    usage("f1", "ffff0001", "h9", "2026-10-01T01:00:00Z", "claude-sonnet-5-5", 10.0)
    conn.execute("""INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens)
                    VALUES ('f2', 'h9', now() - interval '1 hour', 'ffff0001', 'claude-haiku-5-5', 3.0, 1, 1, 0, 0)""")
    conn.execute("""INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens)
                    VALUES ('f3', 'h9', now() - interval '2 hours', 'nosession-1', 'claude-sonnet-5-5', 0.5, 1, 1, 0, 0)""")        # 세션 행이 없는 최근 사용
    all_ = {x["session_id"]: x for x in cd.session_stats(conn)}
    day = {x["session_id"]: x for x in cd.session_stats(conn, days=1)}
    check("session_stats: 기간을 주면 비용·요청·프롬프트가 그 기간의 것만(전체 $13 → 1일 $3, 프롬프트 3 → 1)", round(all_["ffff0001"]["cost"], 2) == 13.0 and round(day["ffff0001"]["cost"], 2) == 3.0
          and (all_["ffff0001"]["prompts"], day["ffff0001"]["prompts"], day["ffff0001"]["requests"]) == (3, 1, 1), (day["ffff0001"]["cost"], day["ffff0001"]["prompts"]))
    tr = sum(r["cost"] for r in cd.usage_trend(conn, days=1))
    brk_tot = cd.usage_breakdown(conn, "model", days=1)[1]["cost"]
    orph = cd.orphan_usage(conn, days=1)
    check("합계 일치: 기간 1일의 세션 비용 합 + 세션 기록 없는 사용 = 추이 합 = 분류 합", abs(sum((x["cost"] or 0) for x in day.values()) + orph[1] - tr) < 1e-6 and abs(tr - brk_tot) < 1e-6 and orph == (1, 0.5), (sum((x["cost"] or 0) for x in day.values()), orph, tr))
    sm1 = cd.session_summary(conn, days=1)
    check("session_summary: 기간을 주면 비용도 그 기간(세션 표 합과 같다)·세션 기록 없는 사용을 알린다", abs(sm1["cost"] - sum((x["cost"] or 0) for x in day.values())) < 1e-6 and sm1["orphan"] == (1, 0.5), (sm1["cost"], sm1["orphan"]))
    hm = {x["session_id"]: x for x in cd.session_stats(conn, days=1, model="haiku")}
    check("필터: 모델을 주면 비용에도 같은 모델 요청만(추이와 같은 집합)", set(hm) == {"ffff0001"} and round(hm["ffff0001"]["cost"], 2) == 3.0 and abs(hm["ffff0001"]["cost"] - cd.usage_trend(conn, days=1, model="haiku")[0]["cost"]) < 1e-6)
    check("필터: 저장소 필터가 있으면 세션 기록 없는 사용은 0(저장소를 모른다)", cd.orphan_usage(conn, days=1, repo="alpha") == (0, 0.0) and cd.orphan_usage(conn, days=None)[0] >= 2)
    check("session_stats: session_id 지정은 기간 없이 세션 전체 누적 그대로(SessionScreen)", round(cd.session_stats(conn, session_id="ffff0001")[0]["cost"], 2) == 13.0)
    conn.execute("DELETE FROM usage_events WHERE request_id IN ('f1','f2','f3')")
    conn.execute("DELETE FROM messages WHERE session_id = 'ffff0001'")
    conn.execute("DELETE FROM sessions WHERE session_id = 'ffff0001'")

    one = cd.session_stats(conn, session_id="aaaa0001")
    check("session_stats: session_id 로 한 세션만", len(one) == 1 and one[0]["session_id"] == "aaaa0001" and one[0]["prompts"] == 2)
    check("session_stats: 없는 session_id 는 빈 목록", cd.session_stats(conn, session_id="nope") == [])
    check("session_tools: 도구별 횟수(서브에이전트 제외, 많은 순)", cd.session_tools(conn, "aaaa0001") == [("Bash", 2), ("Read", 1)], str(cd.session_tools(conn, "aaaa0001")))
    check("session_tools: top 제한", cd.session_tools(conn, "aaaa0001", top=1) == [("Bash", 2)] and cd.session_tools(conn, "cccc0001") == [])
    st = cd.session_titles(conn, ["aaaa0001", "bbbb0001", "nope"])
    check("session_titles: 첫 사용자 프롬프트 앞부분, 없는 ID 는 생략", set(st) == {"aaaa0001", "bbbb0001"} and st["aaaa0001"].startswith("alpha 배포는"))
    check("session_titles: 빈 입력", cd.session_titles(conn, []) == {})
    check("session_titles: 치환 적용", "hunter2-pass" not in cd.session_titles(conn, ["eeee0001"], cs.load_masker(conn))["eeee0001"])
    hits = cd.search(conn, "배포")
    check("search: 결과마다 세션 제목", all(h["title"] for h in hits) and {h["title"][:7] for h in hits if h["session_id"] == "aaaa0001"} == {"alpha 배포는"[:7]}, str([h["title"] for h in hits][:2]))
    check("search: 일치 없으면 빈 목록(제목 조회도 안전)", cd.search(conn, "일치하는것없음zzz") == [])

    conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES ('ffff0001','h1','{h1}',%s,'2026-10-08T01:00:00Z','2026-10-08T02:00:00Z')", (A,))
    conn.execute("INSERT INTO messages (uuid, session_id, host, parent_uuid, ts, role, kind, text, raw) VALUES ('ffff-0000','ffff0001','h1','aaaa-0001','2026-10-08T01:00:00Z','user','prompt','이어서 하자','{}')")
    conn.commit()
    lk = cd.session_links(conn, "aaaa0001")
    check("session_links: 뒤로 이어진 세션(children)", [c["session_id"] for c in lk["children"]] == ["ffff0001"] and lk["children"][0]["title"] == "이어서 하자" and lk["parents"] == [], str(lk))
    check("session_links: 앞 세션(parents)", [p["session_id"] for p in cd.session_links(conn, "ffff0001")["parents"]] == ["aaaa0001"] and cd.session_links(conn, "ffff0001")["children"] == [])
    check("session_links: 이어짐 없는 세션은 둘 다 빈 목록", cd.session_links(conn, "bbbb0001") == dict(parents=[], children=[]))

    # --- 지침(ctxui 「지침」 탭 질의): 모든 저장소 목록 · 본문(치환) · 원문 · 절 목록 · DB 만 저장
    conn.commit()
    for repo, nm, body, host in [(A, "instructions", "# 알파 지침\n\n## QA 할 때\nqa 본문\n\n## 배포\n배포 본문 hunter2-pass 포함\n", "h1"), (A, "override", "알파 오버라이드\n", "h2"), (B, "instructions", "베타 지침\n", "h2")]:
        conn.execute("INSERT INTO project_instructions (repo_url, name, body, rev, updated_host) VALUES (%s,%s,%s,1,%s)", (repo, nm, body, host))
    conn.commit()
    ir = cd.instr_rows(conn)
    check("instr_rows: 모든 저장소의 지침(저장소·이름 순)·rev·수정 머신·길이", [(r["repo"], r["name"]) for r in ir] == [(A, "instructions"), (A, "override"), (B, "instructions")] and ir[0]["rev"] == 1 and ir[0]["host"] == "h1" and ir[2]["length"] == len("베타 지침\n"), str(ir))
    rev, body = cd.instr_body(conn, A, "instructions")
    check("instr_body: (rev, 본문) — 치환기를 안 주면 원문", rev == 1 and "hunter2-pass" in body)
    rev, body = cd.instr_body(conn, A, "instructions", cs.load_masker(conn))
    check("instr_body: 치환기를 주면 화면용으로 [protected]", "hunter2-pass" not in body and "[protected]" in body and "## QA 할 때" in body, body)
    check("instr_body: 없는 항목은 None", cd.instr_body(conn, A, "nope") is None and cd.instr_body(conn, "x", "override") is None)
    check("instr_raw: 편집용은 치환 없이 원문", cd.instr_raw(conn, A, "instructions")[1].count("hunter2-pass") == 1 and cd.instr_raw(conn, A, "nope") is None)
    check("instr_sections: `## ` 절 제목 목록(### 와 머리말 제외)", cd.instr_sections("# 제목\n\n## QA 할 때\nx\n### 하위\ny\n## 배포\nz\n") == ["QA 할 때", "배포"] and cd.instr_sections("절 없음\n") == [])
    code, msg = cd.instr_save(conn, A, "override", "알파 오버라이드 v2\n", "h9", 1, masker=cs.load_masker(conn))
    row = next(r for r in cd.instr_rows(conn) if (r["repo"], r["name"]) == (A, "override"))
    check("instr_save: DB 에만 쓰고 rev·수정 머신이 바뀐다", code == 0 and row["rev"] == 2 and row["host"] == "h9" and cd.instr_raw(conn, A, "override") == (2, "알파 오버라이드 v2\n"), msg)
    code, msg = cd.instr_save(conn, A, "override", "낡은 기대값\n", "h9", 1, masker=cs.load_masker(conn))
    check("instr_save: 낡은 rev 는 거부하고 본문을 바꾸지 않는다(낙관적 잠금)", code == 1 and cd.instr_raw(conn, A, "override") == (2, "알파 오버라이드 v2\n"), msg)
    code, msg = cd.instr_save(conn, A, "override", "비번은 hunter2-pass\n", "h9", 2, masker=cs.load_masker(conn))
    check("instr_save: 등록된 비밀이 든 본문은 거부", code == 1 and "비밀" in msg and cd.instr_raw(conn, A, "override")[0] == 2, msg)
    code, msg = cd.instr_save(conn, A, "override", "  \n", "h9", 2, masker=cs.load_masker(conn))
    check("instr_save: 빈 본문은 거부", code == 1 and cd.instr_raw(conn, A, "override")[0] == 2, msg)
    conn.commit()

    # --- 자동 메시지 분류(donghans ctx doc read --project nixos plan ctx-message-kinds)
    CMD = "<command-message>donghans-resume</command-message>\n<command-name>/donghans-resume</command-name>\n<command-args>c9bf\n7759</command-args>"
    TASK = "<task-notification>\n<task-id>x1</task-id>\n<status>completed</status>\n<summary>배포 끝났다</summary>\n</task-notification>"
    cl = cd.classify
    check("classify: 스킬 호출 → /이름 인자(개행은 공백)", cl("user", "prompt", CMD) == ("command", "/donghans-resume c9bf 7759"), str(cl("user", "prompt", CMD)))
    check("classify: command-message 로 시작해도 command-name 이 이름(슬래시 없으면 붙임)", cl("user", "prompt", "<command-message>x</command-message><command-name>foo</command-name>")[1] == "/foo")
    check("classify: 작업 알림 → [상태] 요약", cl("user", "prompt", TASK) == ("task", "[completed] 배포 끝났다"))
    check("classify: 앞 공백·개행 뒤 태그도 인식, 유니코드 공백(NBSP)으로 시작하면 사람", cl("user", "prompt", "\n\t <local-command-stdout>ok</local-command-stdout>")[0] == "localcmd" and cl("user", "prompt", "\u00a0<task-notification>x")[0] == "human")
    check("classify: 사람·붙여넣기·셸 입력·알 수 없는 태그·assistant", cl("user", "prompt", "그냥 말")[0] == "human" and cl("user", "prompt", "<pasted_content>x</pasted_content>")[0] == "pasted"
          and cl("user", "prompt", "<bash-input>ls</bash-input>") == ("shell", "! ls") and cl("user", "prompt", "<div>x</div>")[0] == "unknown" and cl("assistant", "response", "<task-notification>")[0] == "human")
    check("classify: 태그 이름이 접두만 같으면(<task-notificationx>) 알려진 태그가 아님", cl("user", "prompt", "<task-notificationx>a")[0] == "unknown")
    check("classify: meta 는 시작 문구로 세분하고 자동", cl("user", "meta", "Base directory for this skill: /x")[1].startswith("스킬 본문") and cd.is_auto("user", "meta", "x") and not cd.is_auto("user", "prompt", CMD) and cd.is_auto("user", "prompt", TASK))
    mm = cs.Masker([dict(label="PW", kind="literal", value="hunter2-pass")])
    tt = cd.title_text("ab hunter2-pass cd", mm, 8)
    check("title_text: 치환을 먼저 하고 자른다(경계에서 비밀 조각이 남지 않음)", "hunt" not in tt and "[prot" in tt, tt)
    seed("gggg0101", A, "h1", [("user", "prompt", "2026-10-08T01:00:00Z", CMD), ("user", "prompt", "2026-10-08T01:01:00Z", TASK),
                               ("user", "prompt", "2026-10-08T01:02:00Z", "진짜 사람 말 배포"), ("user", "prompt", "2026-10-08T01:03:00Z", "<pasted_content>붙임 배포</pasted_content>")])
    seed("hhhh0102", B, "h1", [("user", "prompt", "2026-10-09T01:00:00Z", TASK), ("user", "prompt", "2026-10-09T01:01:00Z", CMD.replace("c9bf\n7759", "hunter2-pass"))])
    conn.commit()
    ti = cd.session_titles(conn, ["gggg0101", "hhhh0102"])
    check("제목: 첫 순수 사람 프롬프트(스킬 호출·작업 알림은 뒤로 밀림)", ti["gggg0101"] == "진짜 사람 말 배포", str(ti))
    check("제목: 사람 프롬프트가 없으면 첫 스킬 호출 요약(작업 알림 아님)", ti["hhhh0102"] == "/donghans-resume hunter2-pass", str(ti))
    check("제목: masker 가 요약 안의 비밀도 치환", cd.session_titles(conn, ["hhhh0102"], mm)["hhhh0102"] == "/donghans-resume [protected]")
    st = {x["session_id"]: x for x in cd.session_stats(conn, limit=50)}
    check("세션 통계: 프롬프트 수는 자동 제외(스킬 호출·붙여넣기·사람 = 3), 자동 1 별도", st["gggg0101"]["prompts"] == 3 and st["gggg0101"]["autos"] == 1 and st["hhhh0102"]["prompts"] == 1 and st["hhhh0102"]["autos"] == 1, str((st["gggg0101"]["prompts"], st["gggg0101"]["autos"])))
    check("세션 통계 제목도 같은 규칙", st["gggg0101"]["title"] == "진짜 사람 말 배포" and st["hhhh0102"]["title"].startswith("/donghans-resume"))
    r_user, r_all = cd.search(conn, "배포 끝", role="user"), cd.search(conn, "배포 끝")
    check("검색 role=user(F2·대조·CLI): 작업 알림 제외, 전체 검색에는 cat=task 로 나옴", not r_user and any(x["cat"] == "task" for x in r_all), str((len(r_user), [x["cat"] for x in r_all])))
    check("검색 role=user: 사람·붙여넣기는 그대로 나옴", {x["cat"] for x in cd.search(conn, "배포", role="user") if x["session_id"] == "gggg0101"} == {"human", "pasted"})
    sm = cd.session_summary(conn)
    ov2 = cd.overview(conn)
    check("요약·개요: 자동 건수(2)와 개요 합계의 프롬프트에서 제외", sm["autos"] == 2 and ov2["totals"]["auto_prompts"] == 2 and sm["unknown_tags"] == 0, str((sm["autos"], ov2["totals"])))
    # SQL(~)과 파이썬(re) 판별이 같은 패턴이라 건수가 같아야 한다 — 개행·탭·앞 공백 케이스 포함
    for i, tx in enumerate(["\n<task-notification>a", "\t <bash-stdout>b", "<system-reminder>c", "<local-command-caveat>\nd", "  <command-name>/x</command-name>", "<foo bar>x", "\u00a0<task-notification>n", "x <task-notification>"]):
        conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"mkf-{i}", "gggg0101", "h1", f"2026-10-10T01:0{i}:00Z", "user", "prompt", tx, "{}"))
    conn.commit()
    rows = conn.execute("SELECT text, text ~ %s, text ~ %s FROM messages WHERE kind = 'prompt'", (cd.AUTO_RE, cd.UNKNOWN_RE)).fetchall()
    import re as _re
    check("SQL 정규식과 Python 정규식 판별이 모든 프롬프트에서 일치(자동·알 수 없는 태그)", all(bool(_re.search(cd.AUTO_RE, t)) == a and bool(_re.search(cd.UNKNOWN_RE, t)) == u for t, a, u in rows) and len(rows) > 12, str(len(rows)))
    check("알 수 없는 태그 건수가 요약에 잡힘(<foo bar>)", cd.session_summary(conn)["unknown_tags"] == 1)
    # --- 계정별 비용(요청별 계정 열) + 백필
    base_unk = {r["key"]: r["cost"] for r in cd.usage_breakdown(conn, "account", repo="alpha")[0]}.get("(계정 불명)", 0.0)     # 앞선 시험이 남긴 계정 없는 행
    for rid, acct, email, cost in (("acc-1", "uuidA", "a@x.test", 1.0), ("acc-2", "uuidA", "a@x.test", 2.0), ("acc-3", "uuidB", "b@x.test", 4.0), ("acc-4", None, None, 8.0)):
        conn.execute("INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, account_id, account_email) VALUES (%s,'h1','2026-10-12T01:00:00Z','gggg0101','m',%s,%s,%s)", (rid, cost, acct, email))
    conn.commit()
    brk, tot = cd.usage_breakdown(conn, "account", repo="alpha")
    bk = {r["key"]: r["cost"] for r in brk}
    check("분류별 계정: 이메일별 합계와 (계정 불명) 행(NULL)이 따로 나옴", bk.get("a@x.test") == 3.0 and bk.get("b@x.test") == 4.0 and abs(bk.get("(계정 불명)") - (base_unk + 8.0)) < 1e-9, str(bk))
    check("분류별 계정: 비용 큰 순", [r["cost"] for r in brk] == sorted((r["cost"] for r in brk), reverse=True), str([(r["key"], r["cost"]) for r in brk]))
    check("BREAKDOWNS 에 계정이 있고 g 순환 대상", "account" in cd.BREAKDOWNS and cd.BREAKDOWNS["account"] == "계정")
    # 백필: 원본(events.jsonl)으로 NULL 행만 채운다
    import tempfile
    otel = os.path.join(tempfile.mkdtemp(prefix="otel-"), "events.jsonl")
    def rec(rid, acct, email):
        attrs = [{"key": "request_id", "value": {"stringValue": rid}}] + ([{"key": "user.account_uuid", "value": {"stringValue": acct}}, {"key": "user.email", "value": {"stringValue": email}}] if acct else [])
        return json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": {"stringValue": "claude_code.api_request"}, "attributes": attrs}]}]}]})
    with open(otel, "w") as f:
        f.write("\n".join([rec("acc-4", "uuidC", "c@x.test"), rec("acc-1", "uuidZ", "z@x.test"), rec("nope-1", "uuidC", "c@x.test"), rec("acc-x", None, None), "깨진 줄"]) + "\n")
    dry = cc.backfill_accounts(conn, otel)
    check("백필 dry-run: 원본 api_request 4건 중 계정 3건, DB 에서 계정이 비어 있던 일치 행은 acc-4 한 건, 아무것도 쓰지 않음", dry["read"] == 4 and dry["with_account"] == 3 and dry["matched"] == 1 and dry["updated"] == 0
          and conn.execute("SELECT account_id FROM usage_events WHERE request_id='acc-4'").fetchone()[0] is None, str(dry))
    done = cc.backfill_accounts(conn, otel, apply=True)
    check("백필 apply: NULL 이던 행만 갱신(이미 계정이 있는 acc-1 은 그대로), 원본에 없는 요청은 건드리지 않음", done["updated"] == 1 and conn.execute("SELECT account_id, account_email FROM usage_events WHERE request_id='acc-4'").fetchone() == ("uuidC", "c@x.test")
          and conn.execute("SELECT account_id FROM usage_events WHERE request_id='acc-1'").fetchone()[0] == "uuidA", str(done))
    check("백필 재실행은 멱등(갱신 0건)", cc.backfill_accounts(conn, otel, apply=True)["updated"] == 0)
    check("백필: 원본 파일이 없으면 0건(예외 없음)", cc.backfill_accounts(conn, "/nonexistent-zzz")["read"] == 0)
    conn.execute("DELETE FROM usage_events WHERE request_id LIKE 'acc-%'")
    conn.commit()

    # --- 한도 창: 계정 열이 빈 샘플은 같은 창의 계정에 합친다
    for n, (aid, email, f, rs) in enumerate([("A", "a@x.test", 30, 1), ("A", "a@x.test", 50, 2), (None, None, 70, 2), (None, None, 20, 3), ("A", "a@x.test", 10, 4), ("B", "b@x.test", 40, 4), (None, None, 99, 4)]):
        conn.execute("INSERT INTO limit_samples (host, ts, session_id, five_hour_pct, account_id, account_email, five_hour_resets_at) VALUES ('h1', now() - make_interval(secs => %s), 'lw', %s, %s, %s, date_trunc('hour', now()) + make_interval(hours => %s))", (n, f, aid, email, rs * 5))
    conn.commit()
    lw = {a["account"]: [round(v) for _, v in a["windows"]] for a in cd.limit_windows(conn)["5h"]}
    check("limit_windows: 계정이 빈 샘플은 같은 창의 계정에 합쳐 최고값을 쓴다(A: 30, 70, 10)", lw.get("A", [])[:2] == [30, 70], lw)
    check("limit_windows: 같은 창에 계정이 없는 샘플은 '?' 로 남는다", 20 in lw.get("?", []), lw)
    check("limit_windows: 같은 창에 계정이 둘이면 모호하므로 '?' 에 둔다(A 10 · B 40 · ? 99)", lw.get("A", [])[-1:] == [10] and lw.get("B") == [40] and 99 in lw.get("?", []), lw)
    sa = next(a for a in cd.limit_windows(conn)["5h"] if a["account"] == "A")
    check("limit_windows: 창 안 시계열(series)이 시각순이고 창(리셋 시각)에 속한다", [x[0] for x in sa["series"]] == sorted(x[0] for x in sa["series"]) and {x[2] for x in sa["series"]} <= {r for r, _ in sa["windows"]} and len(sa["series"]) >= 3, sa["series"][:3])
    check("limit_windows: 시계열에도 계정 없는 샘플이 같은 창의 계정에 합쳐진다(A 의 둘째 창 최고 70)", max(v for _, v, r in sa["series"] if r == sa["windows"][1][0]) == 70, sa["series"])
    conn.execute("DELETE FROM limit_samples WHERE session_id = 'lw'"); conn.commit()

    check("delete_secret", cd.delete_secret(conn, "ANTHROPIC_KEY") == 1 and cd.delete_secret(conn, "ANTHROPIC_KEY") == 0)
    conn.close()
finally:
    pg.stop()
finish("ctxdata")
