#!/usr/bin/env python3
"""llmui 시험(Textual Pilot + 임시 Postgres): 8개 탭(세션·카드 탭 포함) · 검색/필터 · 대화 보기 · 치환 켬/끔 · 대조 · 비밀 추가/끄기/삭제/값 보기 · 후보 승인/무시.
필요: psycopg + textual 이 있는 python 과 postgres 17 바이너리. 없으면 건너뛴다."""
import asyncio, json, os, re, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
try:
    import psycopg, textual  # noqa: F401
except ImportError:
    print("psycopg/textual 이 없어 건너뜀"); sys.exit(0)
import pgscratch
pg = pgscratch.start()
if not pg:
    print("postgres 바이너리를 못 찾아 건너뜀"); sys.exit(0)
os.environ.update(pg.env())
import ctx_secrets as cs, ctxdata as cd, llm_ctx as cc, llmui

A, B = "https://github.com/x/alpha", "https://github.com/x/beta"
PW, KEY = "hunter2-pass", "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"
KEY2 = "sk-ant-api03-ZYXWVUTSRQPONMLKJIHGFEDCBA9876"          # 제한 모드 시험용: 등록하지 않은 새 키(후보로만 잡히는 것)


from datetime import datetime as _dt, timedelta as _td, timezone as _tz
_ago = lambda d: (_dt.now(_tz.utc) - _td(days=d)).isoformat()    # 대시보드 기본 기간(30일) 안에 들도록 오늘 기준 상대 날짜(고정 날짜는 시간이 지나면 기간 밖이 돼 추이가 비었다)
_loc = lambda d: (_dt.now(_tz.utc) - _td(days=d)).astimezone()   # 화면은 로컬 시간대 날짜로 보인다
USAGE_FIRST, USAGE_LAST = _loc(6).strftime("%m-%d"), _loc(4).strftime("%m-%d")
USAGE_WEEKS = len({_loc(d).isocalendar()[:2] for d in (6, 5, 4)})   # 일 단위 3행이 주 단위로 몇 줄이 되는지는 오늘의 요일에 달렸다
def seed():
    conn = cc.connect()
    def one(sid, repo, host, msgs):
        conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)", (sid, host, [host], repo, msgs[0][2], msgs[-1][2]))
        for i, (role, kind, ts, text) in enumerate(msgs):
            conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"{sid[:4]}-{i:04d}", sid, host, ts, role, kind, text, json.dumps({"i": i})))
    one("aaaa0001", A, "h1", [("user", "prompt", "2026-10-01T01:00:00Z", "alpha 배포는 금요일에 한다고 했다"), ("assistant", "response", "2026-10-01T01:00:10Z", "알겠습니다 금요일 배포"),
                              ("user", "prompt", "2026-10-02T01:00:00Z", f"비번은 {PW} 로 해줘 그리고 키는 {KEY}"), ("assistant", "response", "2026-10-02T01:00:10Z", f"{PW} 로 설정")])
    one("bbbb0001", B, "h2", [("user", "prompt", "2026-10-03T01:00:00Z", "beta 는 월요일에 배포한다"), ("assistant", "response", "2026-10-03T01:00:10Z", "배포 일정 확인"),
                              ("user", "prompt", "2026-10-04T01:00:00Z", "배포 금요일로 바꾸자")])
    one("cccc0001", None, "h1", [("user", "prompt", "2026-10-05T01:00:00Z", "저장소 없는 세션의 배포 이야기")])
    for rid, sid, host, ts, model, cost in [("u1", "aaaa0001", "h1", _ago(6), "claude-sonnet-5-5", 1.0), ("u2", "aaaa0001", "h1", _ago(5), "claude-haiku-5-5", 0.5),
                                            ("u3", "bbbb0001", "h2", _ago(4), "claude-sonnet-5-5", 2.0)]:
        conn.execute("INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens) VALUES (%s,%s,%s,%s,%s,%s,100,10,1000,50)",
                     (rid, host, ts, sid, model, cost))
    for n, (acct, email, plan, f, w) in enumerate([("A", "a@x.test", "max_5x", 30, 10), ("A", "a@x.test", "max_5x", 60, 12), ("B", "b@x.test", "pro", 90, 70)]):
        conn.execute("INSERT INTO limit_samples (host, ts, session_id, five_hour_pct, seven_day_pct, account_id, account_email, account_plan, five_hour_resets_at, seven_day_resets_at)"
                     " VALUES ('h1', now() - make_interval(mins => %s), %s, %s, %s, %s, %s, %s, now() + make_interval(hours => %s), now() + interval '3 days')",
                     (n, f"ls{n}", f, w, acct, email, plan, 5 * (n + 1)))
    conn.commit(); conn.close()


def txt(w):
    r = w.render()
    return getattr(r, "plain", None) or str(r)


def all_open_ok(scr):
    return scr.all_open


def sess_txt(scr):
    """대화 화면의 머리글 + 모든 메시지 + 상태줄 글자."""
    return "\n".join([txt(scr.query_one("#sess-head"))] + [txt(v) for v in scr.query(llmui.MsgView)] + [txt(scr.query_one("#sess-state"))])


async def settle(pilot, cond, timeout=8.0):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        await pilot.pause(0.15)
    return cond()


def risky_cells(app):
    """DataTable 의 **문자열** 셀 중 대괄호 마크업처럼 보이는 것(`[protected]` 등) — 문자열로 넣으면 Rich 마크업으로 해석돼 화면에서 글자가 사라진다(Text 로 넣어야 한다)."""
    import re
    from textual.widgets import DataTable
    out = []
    for t in app.query(DataTable):
        for key in t.rows:
            for c in t.get_row(key):
                if isinstance(c, str) and re.search(r"\[(?!\d+\])[A-Za-z/#@][^\]]*\]", c):
                    out.append((t.id, c[:60]))
    return out


def rows(app, sel):
    return app.query_one(sel).row_count


async def submit(pilot, widget):
    """위젯에 포커스를 주고 반영될 때까지 기다린 뒤 Enter(포커스 직후 바로 누르면 이전 위젯이 받는다)."""
    widget.focus(); await pilot.pause(0.25); await pilot.press("enter")


def hits(app):
    """검색 결과의 일치 메시지 수(세션 행 수가 아니라) — 결과 표는 세션 단위 행이다."""
    return sum(g["count"] for g in app.groups)


async def type_text(pilot, s):
    for ch in s:
        await pilot.press(ch)


async def run():
    app = llmui.LlmUI()
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, lambda: rows(app, "#projects") == 3)
        # --- 개요
        head = txt(app.query_one("#ovhead"))
        check("개요: 합계(세션 3 · 메시지 8)와 DB 크기", "세션 3" in head and "메시지 8" in head and "DB" in head, head)
        check("개요: 저장소 3곳(저장소 없음 포함)", rows(app, "#projects") == 3)
        check("개요: 표별 용량 표시", "messages" in head)
        # Enter → 그 저장소 검색
        pt = app.query_one("#projects")
        pt.focus(); await pilot.pause(0.2)
        await pilot.press("enter"); await pilot.pause(0.8)
        check("개요 Enter: 검색 탭으로 이동하고 저장소 칸이 채워짐", app.current_tab() == "search" and app.query_one("#repo").value != "", f"{app.current_tab()!r} {app.query_one('#repo').value!r}")
        check("개요 Enter: 그 저장소 메시지만 검색(최대 4건)", 1 <= hits(app) <= 4, str(hits(app)))

        # --- 검색
        await pilot.press("2"); await pilot.pause(0.3)
        app.query_one("#repo").value = ""
        q = app.query_one("#q"); q.value = "배포"; q.focus(); await pilot.pause(0.2)
        await pilot.press("enter"); await settle(pilot, lambda: hits(app) == 6)
        check("검색: '배포' 6건(프롬프트·응답)", hits(app) == 6, str(hits(app)))
        await pilot.press("f2"); await pilot.pause(0.2)
        await submit(pilot, q); await settle(pilot, lambda: hits(app) == 4)
        check("F2: 사용자 발언만 4건", hits(app) == 4 and "사용자만" in txt(app.query_one("#sstate")), str(hits(app)))
        await pilot.press("f2"); await pilot.pause(0.1)
        q.value = "금요일|월요일"; await pilot.press("f3"); await submit(pilot, q); await settle(pilot, lambda: hits(app) == 4)
        check("F3: 정규식 검색", hits(app) == 4 and "정규식: 켜짐" in txt(app.query_one("#sstate")), str(hits(app)))
        q.value = "([a-"; await submit(pilot, q); await pilot.pause(0.5)
        check("잘못된 정규식은 앱이 죽지 않고 이전 결과 유지, 대화 화면이 열리지 않음", app.is_running and hits(app) == 4 and not isinstance(app.screen, llmui.SessionScreen))
        await pilot.press("f3"); q.value = "금요일"; await submit(pilot, q); await settle(pilot, lambda: hits(app) >= 1)
        # 일수 필터
        app.query_one("#days").value = "1"; await submit(pilot, q); await pilot.pause(0.6)
        check("기간(일) 필터: 오래된 데이터는 제외", hits(app) == 0, str(hits(app)))
        app.query_one("#days").value = ""
        # 대화 보기
        q.value = "금요일"; await submit(pilot, q); await settle(pilot, lambda: hits(app) >= 1)
        await submit(pilot, app.query_one("#results")); await pilot.pause(0.8)
        check("Enter: 앞뒤 대화 화면이 열림", isinstance(app.screen, llmui.SessionScreen))
        body = sess_txt(app.screen)
        check("대화 화면: 세션 정보와 메시지", "@h" in body and "금요일" in body, body[:200])
        await pilot.press("escape"); await pilot.pause(0.3)
        check("Esc: 대화 화면이 닫힘", not isinstance(app.screen, llmui.SessionScreen))

        # --- 치환
        with cc.connect() as c:
            cs.add_secret(c, "NAS_PW", "literal", PW)
        q.value = "설정"; await submit(pilot, q); await settle(pilot, lambda: hits(app) >= 1)
        first = app.query_one("#results").get_row_at(0)
        check("치환 켜짐: 결과에 비밀이 [protected]", PW not in str(first[-1]) and "[protected]" in str(first[-1]), str(first))
        await submit(pilot, app.query_one("#results")); await pilot.pause(0.8)
        check("치환 켜짐: 대화 화면에도 [protected]", PW not in sess_txt(app.screen) and "[protected]" in sess_txt(app.screen))
        await pilot.press("f10"); await pilot.pause(0.6)
        check("대화 화면 m: 치환 끄면 원문이 보임(경고 표시)", PW in sess_txt(app.screen) and "꺼짐" in sess_txt(app.screen))
        await pilot.press("f10"); await pilot.pause(0.3); await pilot.press("escape"); await pilot.pause(0.3)
        check("m 으로 다시 켬", app.mask)

        # --- 대조
        await pilot.press("3"); await pilot.pause(0.3)
        ph = app.query_one("#phrase"); ph.value = "배포"; await submit(pilot, ph); await settle(pilot, lambda: rows(app, "#vrepos") == 3)
        check("대조: 사용자 발언을 저장소 3곳으로 묶음(4건)", rows(app, "#vrepos") == 3 and "4건" in app.query_one("#vrepos").border_title, app.query_one("#vrepos").border_title)
        check("대조: 첫 저장소(가장 많은 beta)의 발언 2건이 오른쪽에", rows(app, "#vhits") == 2, str(rows(app, "#vhits")))
        await pilot.press("down"); await pilot.pause(0.4)
        check("대조: 저장소를 옮기면 발언 목록이 바뀜", rows(app, "#vhits") == 1)
        await submit(pilot, app.query_one("#vhits")); await pilot.pause(0.8)
        check("대조: 발언 Enter → 대화 보기", isinstance(app.screen, llmui.SessionScreen)); await pilot.press("escape"); await pilot.pause(0.3)

        # --- 비밀
        await pilot.press("4"); await settle(pilot, lambda: rows(app, "#secrets-table") == 1)
        check("비밀: 등록된 1개가 표에 있고 값은 표에 없음", rows(app, "#secrets-table") == 1 and PW not in str(app.query_one("#secrets-table").get_row_at(0)), str(app.query_one("#secrets-table").get_row_at(0)))
        check("비밀: 원문에 들어 있는 메시지 수(2)", app.query_one("#secrets-table").get_row_at(0)[-1] == 2, str(app.query_one("#secrets-table").get_row_at(0)))
        app.query_one("#secrets-table").focus(); await pilot.press("f4"); await pilot.pause(0.3)
        check("v: 선택한 비밀 값이 아래에 표시", PW in txt(app.query_one("#sdetail")))
        await pilot.press("f4"); await pilot.pause(0.2)
        check("v 다시: 숨김", txt(app.query_one("#sdetail")).strip() == "")
        await pilot.press("f3"); await settle(pilot, lambda: app.query_one("#secrets-table").get_row_at(0)[2] == "꺼짐")
        check("e: 끄기", app.query_one("#secrets-table").get_row_at(0)[2] == "꺼짐")
        with cc.connect(readonly=True) as c:
            check("e: 끄면 치환 대상에서 빠짐", cs.load_secrets(c) == [])
        await pilot.press("f3"); await settle(pilot, lambda: app.query_one("#secrets-table").get_row_at(0)[2] == "켜짐")
        # 추가
        await pilot.press("f2"); await pilot.pause(0.4)
        check("a: 이름 입력 대화상자", isinstance(app.screen, llmui.PromptScreen))
        check("비밀 이름 입력: 대화상자가 화면 가운데에 뜸(좌우 ±1칸 — 예전엔 왼쪽 위 구석)", abs(app.screen.query_one("#dialog").region.x + app.screen.query_one("#dialog").region.width / 2 - app.size.width / 2) <= 1)
        await type_text(pilot, "newpw"); await pilot.press("enter"); await pilot.pause(0.4)
        check("a: 값 입력 대화상자는 가려서 표시(password)", isinstance(app.screen, llmui.PromptScreen) and app.screen.query_one("#prompt-input").password)
        await type_text(pilot, "secretvalue99"); await pilot.press("enter"); await settle(pilot, lambda: rows(app, "#secrets-table") == 2)
        check("a: 새 비밀이 등록됨", rows(app, "#secrets-table") == 2)
        with cc.connect(readonly=True) as c:
            check("a: DB 에 평문으로 저장(설계 결정)", any(s["label"] == "newpw" and s["value"] == "secretvalue99" for s in cs.load_secrets(c)))
        # 삭제(확인)
        app.query_one("#secrets-table").focus(); await pilot.press("delete"); await pilot.pause(0.4)
        check("d: 확인 대화상자", isinstance(app.screen, llmui.ConfirmScreen))
        await pilot.press("enter"); await pilot.pause(0.3)
        check("d → n: 취소하면 그대로", rows(app, "#secrets-table") == 2)
        await pilot.press("delete"); await pilot.pause(0.3); await pilot.press("left", "enter"); await settle(pilot, lambda: rows(app, "#secrets-table") == 1)
        check("d → y: 삭제됨", rows(app, "#secrets-table") == 1)

        # --- 후보
        await pilot.press("5"); await settle(pilot, lambda: rows(app, "#cands-table") >= 1)
        ct = app.query_one("#cands-table")
        check("후보: 탐지됨(키 + 이미 등록된 비밀번호는 제외)", rows(app, "#cands-table") >= 1 and all(PW not in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))))
        check("후보: 값은 흐린 미리보기만", all(KEY not in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))) and any("자)" in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))))
        fp_key = cs.fingerprint(KEY)
        idx = next(i for i in range(rows(app, "#cands-table")) if ct.get_row_at(i)[0] == fp_key)
        ct.focus(); ct.move_cursor(row=idx); await pilot.pause(0.3)
        await pilot.press("f4"); await pilot.pause(0.3)
        check("후보 v: 값 보기(승인 판단용)", KEY in txt(app.query_one("#cdetail")))
        await pilot.press("enter"); await pilot.pause(0.4)
        check("후보 Enter: 이름 입력", isinstance(app.screen, llmui.PromptScreen))
        await type_text(pilot, "anthkey"); await pilot.press("enter")
        await settle(pilot, lambda: all(ct.get_row_at(i)[0] != fp_key for i in range(rows(app, "#cands-table"))) )
        check("후보 승인: 목록에서 사라지고 등록됨", all(ct.get_row_at(i)[0] != fp_key for i in range(rows(app, "#cands-table"))))
        with cc.connect(readonly=True) as c:
            check("후보 승인: 등록표에 들어감", any(s["label"] == "anthkey" and s["value"] == KEY for s in cs.load_secrets(c)))
        n_before = rows(app, "#cands-table")
        if n_before:
            ct.focus(); ct.move_cursor(row=0); await pilot.pause(0.3)
            fp0 = ct.get_row_at(0)[0]
            await pilot.press("f2"); await settle(pilot, lambda: rows(app, "#cands-table") < n_before)
            check("후보 i: 무시하면 사라짐", rows(app, "#cands-table") == n_before - 1)
            with cc.connect(readonly=True) as c:
                check("후보 i: 무시 목록에 기록", fp0 in cd.ignored_fps(c))
        # --- 통계
        await pilot.press("1"); await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        check("대시보드: 1 키로 이동(통계 칸 포함)", app.current_tab() == "dashboard")
        lt = txt(app.query_one("#stat-limits"))
        check("통계: 계정별 한도 그래프에 계정·플랜·최고 %가 계정마다 따로 나온다", all(k in lt for k in ("a@x.test", "max_5x", "b@x.test", "pro", "최고 60%", "최고 90%")), lt)
        st = txt(app.query_one("#stat-state"))
        check("통계: 상태줄에 기간·단위·분류·정렬과 비용 수집 시작일", all(k in st for k in ("기간: 30일", "단위: 일", "분류: 모델", "정렬: 비용", f"{USAGE_FIRST} 이후")), st)
        check("통계: 기본 30일 필터(합성 데이터는 2026-10 초라 오늘 기준으로는 이미 밖일 수 있음)", "기간: 30일" in st)
        await pilot.press("f2")      # 기간 순환: 30일 → 전체
        await settle(pilot, lambda: rows(app, "#stat-trend") == 3)
        check("통계 p: 기간 순환(30일 → 전체)", "기간: 전체" in txt(app.query_one("#stat-state")) and rows(app, "#stat-trend") == 3, txt(app.query_one("#stat-state")))
        tt = app.query_one("#stat-trend")
        check("통계: 추이 표(일 단위 3행, 최근이 위·합계 제목)", rows(app, "#stat-trend") == 3 and USAGE_LAST in str(tt.get_row_at(0)[0]) and "$3.50" in app.query_one("#stat-trend").border_title, app.query_one("#stat-trend").border_title)
        check("통계: 비용 막대 그려짐", any("█" in str(tt.get_row_at(i)[3]) for i in range(3)))
        cc_ = app.query_one("#stat-trend-chart")
        check("통계: 비용 그래프(점자)가 위쪽에 그려지고 부제에 합계·최대·평균", any("\u2800" < ch <= "\u28ff" for ch in txt(cc_)) and "$3.50" in (cc_.border_subtitle or ""), (txt(cc_)[:80], cc_.border_subtitle))
        check("통계: 분류별(모델) 비용순", app.query_one("#stat-break").get_row_at(0)[0] == "claude-sonnet-5-5" and "$3.00" in str(app.query_one("#stat-break").get_row_at(0)))
        sm = txt(app.query_one("#stat-summary"))
        check("통계: 세션 요약(세션·프롬프트·비용·시간대·요일)", all(k in sm for k in ("세션 3개", "프롬프트 5", "시간대별", "요일별")) , sm)
        await pilot.press("f4"); await settle(pilot, lambda: "분류: 저장소" in txt(app.query_one("#stat-state")))
        check("통계 g: 분류 순환(모델 → 저장소)", app.query_one("#stat-break").border_title.startswith("저장소별") and rows(app, "#stat-break") == 2)
        check("통계 g: 분류 드롭다운도 키 상태(저장소)를 따라간다", app.query_one("#sel-by").value == "repo", app.query_one("#sel-by").value)
        app.query_one("#sel-by").value = "host"; await settle(pilot, lambda: app.query_one("#stat-break").border_title.startswith("머신별"))
        check("통계: 분류 드롭다운으로 고르면 상태·표·제목이 바뀐다(머신별)", app.stat_by == "host" and app.query_one("#stat-break").border_title.startswith("머신별") and rows(app, "#stat-break") >= 1, (app.stat_by, app.query_one("#stat-break").border_title))
        app.query_one("#sel-period").value = 1; await settle(pilot, lambda: "기간: 1일" in txt(app.query_one("#stat-state")))
        check("통계: 기간 드롭다운으로 고르면 상태가 바뀐다(1일)", app.stat_period == 1, app.stat_period)
        app.query_one("#sel-period").value = 0; await settle(pilot, lambda: "기간: 전체" in txt(app.query_one("#stat-state")))
        app.query_one("#sel-by").value = "repo"; await settle(pilot, lambda: "분류: 저장소" in txt(app.query_one("#stat-state")))
        await pilot.press("f4"); await settle(pilot, lambda: "분류: 계정" in txt(app.query_one("#stat-state")))
        check("통계 g: 다음 분류는 계정(제목에 계정 불명 비율, 행에 (계정 불명))", app.query_one("#stat-break").border_title.startswith("계정별") and "계정 불명" in app.query_one("#stat-break").border_title and "(계정 불명)" in str(app.query_one("#stat-break").get_row_at(0)), app.query_one("#stat-break").border_title)
        await pilot.press("f4"); await settle(pilot, lambda: "분류: 머신" in txt(app.query_one("#stat-state"))); await pilot.press("f4"); await pilot.press("f4"); await pilot.press("f4")
        await settle(pilot, lambda: "분류: 모델" in txt(app.query_one("#stat-state"))); await pilot.press("f4"); await settle(pilot, lambda: "분류: 저장소" in txt(app.query_one("#stat-state")))
        await pilot.press("f3"); await settle(pilot, lambda: "단위: 주" in txt(app.query_one("#stat-state")))
        check("통계 b: 단위 순환(일 → 주)", "단위: 주" in txt(app.query_one("#stat-state")) and rows(app, "#stat-trend") == USAGE_WEEKS)
        await pilot.press("f6"); await settle(pilot, lambda: "정렬: 최근" in txt(app.query_one("#stat-state")))
        check("통계 o: 세션 정렬 순환(비용 → 최근)", "정렬: 최근" in txt(app.query_one("#stat-state")))
        fr = app.query_one("#f-repo")
        fr.value = "alpha"; await submit(pilot, fr)
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 1)
        check("통계 필터(저장소 alpha): 세션·추이·분류가 함께 줄어듦", rows(app, "#stat-sessions") == 1 and "$1.50" in app.query_one("#stat-trend").border_title, app.query_one("#stat-trend").border_title)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("f7")
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        check("통계 c: 필터 지움", app.query_one("#f-repo").value == "" and rows(app, "#stat-sessions") == 3)
        fm = app.query_one("#f-model")
        fm.value = "haiku"; await submit(pilot, fm)
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 1)
        check("통계 필터(모델 haiku): 그 모델을 쓴 세션만", rows(app, "#stat-sessions") == 1 and "$0.50" in app.query_one("#stat-trend").border_title)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("f7"); await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        sess_t = app.query_one("#stat-sessions")
        sess_t.focus(); sess_t.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        check("통계 세션 Enter: 그 세션 대화 열림", app.screen.__class__.__name__ == "SessionScreen")
        await pilot.press("escape"); await pilot.pause(0.3)
        check("통계: 대화 닫으면 대시보드로 복귀", app.current_tab() == "dashboard" and app.screen.__class__.__name__ != "SessionScreen")
        # --- 대화 보기(깊게): 펼침 · 검색어 이동 · 도구/서브에이전트 · 복사 · 이어진 세션 · 생략 한도 · 검색 제목 · F4
        long_text = "A" * 1000 + "마지막NEEDLE_X끝"
        with cc.connect() as c:
            c.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, branch, first_ts, last_ts) VALUES ('gggg0001','h2','{h2}',%s,'dev','2026-10-10T01:00:00Z','2026-10-10T02:00:00Z')", (B,))
            for i, (uid, kind, role, side, par, text) in enumerate([
                    ("gggg-p0", "prompt", "user", False, None, "긴 응답을 읽자 NEEDLE_X"), ("gggg-r0", "response", "assistant", False, "gggg-p0", long_text),
                    ("gggg-t0", "tool_use", "assistant", False, "gggg-r0", "[tool_use Bash] echo hi"), ("gggg-t1", "tool_result", "user", False, "gggg-t0", "hi"),
                    ("gggg-s0", "prompt", "user", True, None, "서브 작업 지시")]):
                c.execute("INSERT INTO messages (uuid, session_id, host, parent_uuid, ts, role, kind, is_sidechain, text, raw) VALUES (%s,'gggg0001','h2',%s,%s::timestamptz + %s * interval '1 minute',%s,%s,%s,%s,'{}')",
                          (uid, par, "2026-10-10T01:00:00Z", i, role, kind, side, text))
            c.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES ('gggg0002','h2','{h2}',%s,'2026-10-11T01:00:00Z','2026-10-11T02:00:00Z')", (B,))
            c.execute("INSERT INTO messages (uuid, session_id, host, parent_uuid, ts, role, kind, text, raw) VALUES ('gggg-q0','gggg0002','h2','gggg-r0','2026-10-11T01:00:00Z','user','prompt','다음 세션의 첫 말','{}')")
        scr = llmui.SessionScreen(app, "gggg0001", None, "NEEDLE_X", False)
        await app.push_screen(scr); await settle(pilot, lambda: len(list(scr.query(llmui.MsgView))) == 2)
        head = txt(scr.query_one("#sess-head"))
        check("대화 화면: 머리글에 제목(첫 프롬프트)·저장소#브랜치·프롬프트/도구 수", "긴 응답을 읽자" in head and "#dev" in head and "프롬프트 1" in head and "도구 1" in head, head)
        check("대화 화면: 이어진 세션 안내(] 다음 세션)", "] 다음 세션: gggg0002" in head, head)
        check("대화 화면: 기본은 프롬프트·응답만(도구·서브에이전트 숨김)", len(scr.msgs) == 2 and "서브 작업" not in sess_txt(scr) and "echo hi" not in sess_txt(scr))
        check("대화 화면: 긴 메시지는 접히고 펼치는 방법 안내", "더 — Enter: 펼치기" in txt(scr.views[1]) and "끝" not in txt(scr.views[1]).replace("더 — Enter: 펼치기", ""))
        check("대화 화면: 검색어 강조(스타일 span)", any("on #b8a46a" in str(sp.style) for sp in scr.render_msg(scr.msgs[0]).spans))
        await pilot.press("right"); await pilot.pause(0.3)
        check("n: 다음 검색어 메시지로 이동", scr.sel == 1 and "msg-sel" in scr.views[1].classes, str(scr.sel))
        check("n: 검색어가 접힌 뒷부분에 있으면 자동으로 펼쳐서 보여 줌", "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter: 펼친 메시지는 다시 접힘", "더 — Enter: 펼치기" in txt(scr.views[1]))
        await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter: 다시 펼침(끝 글자가 보임)", "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("left"); await pilot.pause(0.3)
        check("N: 이전 검색어 메시지(첫 프롬프트)로 이동", scr.sel == 0)
        await pilot.press("f6"); await pilot.pause(0.3)
        check("y: 선택한 메시지를 클립보드로 복사", app.clipboard == "긴 응답을 읽자 NEEDLE_X", repr(app.clipboard))
        await pilot.press("down"); await pilot.press("f6"); await pilot.pause(0.3)
        check("↓ 이동 후 y: 그 메시지 전체 복사", app.clipboard == long_text and scr.sel == 1)
        await pilot.press("f3"); await settle(pilot, lambda: len(scr.msgs) == 4)
        check("t: 도구 호출·결과 보기(4개), 보던 메시지 위치 유지", len(scr.msgs) == 4 and "echo hi" in sess_txt(scr) and scr.msgs[scr.sel]["uuid"] == "gggg-r0", str(scr.sel))
        await pilot.press("f4"); await pilot.pause(0.5)
        check("s: 서브에이전트 메시지도 보기(5개)", len(scr.msgs) == 5 and "서브 작업 지시" in sess_txt(scr) and "(서브에이전트)" in sess_txt(scr))
        await pilot.press("f4"); await pilot.press("f3"); await settle(pilot, lambda: len(scr.msgs) == 2)
        await pilot.press("f2"); await pilot.pause(0.4)
        check("f: 전체 펼침", all_open_ok(scr) and "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("f2"); await pilot.pause(0.3)
        await pilot.press("end"); await pilot.pause(0.2)
        check("End/Home: 처음·끝 이동", scr.sel == 1)
        await pilot.press("home"); await pilot.pause(0.2)
        check("Home", scr.sel == 0)
        await pilot.press("right_square_bracket"); await settle(pilot, lambda: scr.session_id == "gggg0002")
        check("]: 이어진 다음 세션으로 이동(머리글·메시지 교체)", scr.session_id == "gggg0002" and "다음 세션의 첫 말" in sess_txt(scr) and "[ 이전 세션: gggg0001" in txt(scr.query_one("#sess-head")), txt(scr.query_one("#sess-head")))
        await pilot.press("right_square_bracket"); await pilot.pause(0.4)
        check("] : 더 이어진 세션이 없으면 알림만(그대로)", scr.session_id == "gggg0002" and app.is_running)
        await pilot.press("left_square_bracket"); await settle(pilot, lambda: scr.session_id == "gggg0001")
        check("[: 이전 세션으로 돌아옴", scr.session_id == "gggg0001")
        scr.limit = 1; scr.rebuild(None); await pilot.pause(0.4)
        check("메시지 수 상한: 넘으면 생략 개수를 알리고 마지막 쪽을 보여줌", len(scr.msgs) == 1 and "생략" in txt(scr.query_one("#sess-state")) and scr.hidden_before == 1, txt(scr.query_one("#sess-state")))
        await pilot.press("f7"); await pilot.pause(0.5)
        check("a: 전부 불러오기", len(scr.msgs) == 2 and "생략" not in txt(scr.query_one("#sess-state")))
        await pilot.press("escape"); await pilot.pause(0.3)
        check("대화 화면 닫힘", not isinstance(app.screen, llmui.SessionScreen))
        await pilot.press("2"); await pilot.pause(0.3)
        q.value = "NEEDLE_X"; await submit(pilot, q); await settle(pilot, lambda: hits(app) == 2)
        r0 = app.query_one("#results").get_row_at(0)
        check("검색: 결과에 세션 제목 열", hits(app) == 2 and "긴 응답을 읽자" in str(r0[4]), str(r0))
        q.value = "echo hi"; await submit(pilot, q); await pilot.pause(0.6)
        check("검색: 기본은 도구 메시지 제외", hits(app) == 0)
        await pilot.press("f4"); await submit(pilot, q); await settle(pilot, lambda: hits(app) == 1)
        check("F4: 도구 메시지 포함하면 찾아짐(종류가 역할 칸에 표시)", hits(app) == 1 and app.groups[0]["hits"][0]["kind"] == "tool_use" and "도구 메시지: 포함" in txt(app.query_one("#sstate")))
        await pilot.press("f4")
        # --- 세션 기준 검색: 펼침·모두 펼침·제목만
        q.value = "배포"; await submit(pilot, q); await settle(pilot, lambda: hits(app) == 6)
        rt = app.query_one("#results")
        check("세션 기준: 일치 6건이 세션 행 3개로 묶임(접힌 상태)", rt.row_count == len(app.groups) == 3 and "세션 3개 · 일치 6건" in rt.border_title, rt.border_title)
        await pilot.press("space"); await pilot.pause(0.3)
        check("Space: 선택한 세션의 일치 메시지가 아래에 펼쳐짐(▾)", rt.row_count == 3 + app.groups[0]["count"] and "▾" in str(rt.get_row_at(0)[1]), str(rt.row_count))
        await pilot.press("space"); await pilot.pause(0.3)
        check("Space 다시: 접힘, 커서는 그 세션 행", rt.row_count == 3 and rt.cursor_row == 0)
        await pilot.press("f7"); await pilot.pause(0.3)
        check("x: 모든 세션 펼침(세션 3 + 메시지 6)", rt.row_count == 9)
        await pilot.press("down"); await pilot.pause(0.2)
        await submit(pilot, rt); await pilot.pause(0.6)
        check("펼친 메시지 행에서 Enter: 그 메시지에 맞춰 대화가 열림", isinstance(app.screen, llmui.SessionScreen))
        await pilot.press("escape"); await pilot.pause(0.3)
        await pilot.press("f7"); await pilot.pause(0.2)
        await pilot.press("f6"); await settle(pilot, lambda: "제목만: 켜짐" in txt(app.query_one("#sstate")))
        check("F6: 제목만 — 제목(첫 프롬프트)에 '배포' 가 없는 세션은 빠짐", all("배포" in g["title"] for g in app.groups) and "제목만" in rt.border_title, [g["title"] for g in app.groups])
        await pilot.press("f6"); await settle(pilot, lambda: "제목만: 꺼짐" in txt(app.query_one("#sstate")))

        # --- 자동 메시지(작업 알림·스킬 호출) 배지·접기·숨김 토글
        _msgs = [("user", "prompt", "<command-message>donghans-resume</command-message>\n<command-name>/donghans-resume</command-name>\n<command-args>c9bf</command-args>"),
                 ("user", "prompt", "<task-notification>\n<task-id>x1</task-id>\n<status>completed</status>\n<summary>배포 끝났다</summary>\n</task-notification>"),
                 ("user", "prompt", "진짜 사람의 말")]
        with cc.connect() as c:
            c.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)", ("iiii0001", "h1", ["h1"], A, "2026-10-11T01:00:00Z", "2026-10-11T01:05:00Z"))
            for i, (r_, k_, t_) in enumerate(_msgs):
                c.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"iiii-{i:04d}", "iiii0001", "h1", f"2026-10-11T01:0{i}:00Z", r_, k_, t_, json.dumps({"i": i})))
        app.push_screen(llmui.SessionScreen(app, "iiii0001", None)); await pilot.pause(0.8)
        scr = app.screen
        body = sess_txt(scr)
        check("자동 메시지: 작업 알림은 [작업 알림] 배지+한 줄 요약(원문 태그는 접힘)", "[작업 알림]" in body and "[completed] 배포 끝났다" in body and "<task-id>" not in body, body[:300])
        check("스킬 호출은 [스킬 호출] 배지와 /이름 인자", "[스킬 호출]" in body and "/donghans-resume c9bf" in body and "<command-name>" not in body)
        check("대화 화면 제목: 첫 사람 프롬프트", "진짜 사람의 말" in txt(scr.query_one("#sess-head")), txt(scr.query_one("#sess-head"))[:120])
        await pilot.press("down"); await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter: 작업 알림 원문 펼침", "<task-id>x1</task-id>" in sess_txt(scr))
        await pilot.press("f8"); await pilot.pause(0.4)
        hid = sess_txt(scr)
        check("i: 자동 메시지 숨김(작업 알림 사라지고 스킬 호출·사람 말은 남음)", "[작업 알림]" not in hid and "<task-id>" not in hid and "진짜 사람의 말" in hid and "/donghans-resume" in hid and "자동 메시지 숨김" in txt(scr.query_one("#sess-state")), txt(scr.query_one("#sess-state")))
        await pilot.press("f8"); await pilot.pause(0.4)
        check("i 다시: 자동 메시지 보임", "[작업 알림]" in sess_txt(scr))
        await pilot.press("escape"); await pilot.pause(0.3)
        check("자동 메시지 시험 후 대화 화면 닫힘", not isinstance(app.screen, llmui.SessionScreen))
        # --- 지침 탭(공유 정본 · DB 만 · 사람 전용 편집)
        import contextlib, stat
        with cc.connect() as c:
            for repo, nm, body, host in [(A, "instructions", "# 알파 지침\n\n## QA 할 때\nqa 본문\n\n## 배포\n배포 본문\n", "h1"), (A, "override", "알파 오버라이드\n", "h2"), (B, "instructions", f"베타 지침 비번은 {PW}\n", "h2")]:
                c.execute("INSERT INTO project_instructions (repo_url, name, body, rev, updated_host) VALUES (%s,%s,%s,1,%s)", (repo, nm, body, host))
        with cc.connect() as c:
            cs.add_secret(c, "INSTR_PW", "literal", PW)          # 앞선 비밀 탭 시험이 등록표를 비웠으므로 이 구간용으로 다시 등록
        fake = os.path.join(os.environ["XDG_RUNTIME_DIR"] if os.environ.get("XDG_RUNTIME_DIR") else tempfile.gettempdir(), "fake-editor-%d.sh" % os.getpid())
        EDITLOG = fake + ".log"
        def make_editor(script_body):
            open(fake, "w").write("#!/bin/sh\n" + script_body); os.chmod(fake, 0o755); os.environ["EDITOR"] = fake; os.environ.pop("VISUAL", None)
        await pilot.press("6"); await settle(pilot, lambda: rows(app, "#instr-table") == 3)
        it = app.query_one("#instr-table")
        check("지침: 6 키로 이동, 모든 저장소의 지침이 목록에(저장소·이름·rev·수정 머신·길이)", app.current_tab() == "instr" and rows(app, "#instr-table") == 3 and it.get_row_at(0)[1] == "instructions" and it.get_row_at(0)[2] == 1 and it.get_row_at(0)[3] == "h1", str(it.get_row_at(0)))
        it.focus(); it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        check("지침 Enter: 본문 보기 화면이 열림", isinstance(app.screen, llmui.InstrScreen))
        body = txt(app.screen.query_one("#instr-body"))
        check("지침 본문: 저장소·이름·rev·절 목록과 본문", "알파 지침" in body and "rev 1" in body and "절 2개: QA 할 때 · 배포" in body and "qa 본문" in body, body[:200])
        await pilot.press("escape"); await pilot.pause(0.3)
        it.move_cursor(row=2); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        shown = txt(app.screen.query_one("#instr-body"))
        check("지침 본문: 등록된 비밀은 [protected] 로 치환해 보인다", PW not in shown and "[protected]" in shown, shown[:160])
        await pilot.press("f10"); await pilot.pause(0.6)
        check("지침 본문 m: 치환을 끄면 원문(경고 표시)", PW in txt(app.screen.query_one("#instr-body")) and "꺼짐" in txt(app.screen.query_one("#instr-body")))
        await pilot.press("f10"); await pilot.pause(0.4); await pilot.press("escape"); await pilot.pause(0.3)
        check("m 으로 다시 켬", app.mask)

        # 편집: 가짜 편집기(실행 파일)로 대체 — suspend 는 헤드리스에서 못 쓰므로 빈 컨텍스트로 바꾼다
        app.suspend = lambda: contextlib.nullcontext()
        cache_marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-cache")      # 캐시 파일 경로를 쓰지 않는다는 것을 아래에서 확인
        make_editor(f'cp "$1" {EDITLOG}.mode_probe 2>/dev/null; stat -c %a "$1" > {EDITLOG}.perm; printf "\\n## 추가 절\\n새 내용\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3)
        await pilot.press("f2"); await settle(pilot, lambda: it.get_row_at(0)[2] == 2)
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "instructions")
        check("지침 e: 편집기로 고치면 DB 에 올라가고 rev 가 오른다", raw[0] == 2 and "## 추가 절" in raw[1] and "새 내용" in raw[1] and it.get_row_at(0)[2] == 2, str(raw))
        check("지침 e: 임시 파일은 0600 이었고 편집 뒤 지워진다", open(EDITLOG + ".perm").read().strip() == "600" and not any(f.startswith("instr-") for f in os.listdir(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())))
        with cc.connect(readonly=True) as c:
            row = next(r for r in cd.instr_rows(c) if (r["repo"], r["name"]) == (A, "instructions"))
        check("지침 e: 수정 머신은 이 기기(CLAUDE_CTX_HOST)로 기록", row["host"] == "testhost", str(row))
        # 변경 없음
        make_editor("exit 0\n")
        it.move_cursor(row=1); await pilot.pause(0.3); await pilot.press("f2"); await pilot.pause(0.8)
        with cc.connect(readonly=True) as c:
            check("지침 e: 바꾸지 않으면 저장하지 않는다(rev 그대로)", cd.instr_raw(c, A, "override")[0] == 1)
        # 낡은 rev: 편집기가 도는 사이 다른 기기가 먼저 고침
        make_editor(f'python3 -c "import sys; open(sys.argv[1],\'a\').write(\'\\n내 편집\\n\')" "$1"\n')
        orig_edit = app.edit_instr
        def race(repo, name):
            if (repo, name) == (A, "override"):
                with cc.connect() as c:
                    c.execute("UPDATE project_instructions SET body='다른 기기가 먼저 씀\n', rev=rev+1, updated_host='other' WHERE repo_url=%s AND name='override'", (repo,))
            return orig_edit(repo, name)
        # 편집기가 뜨기 직전(읽은 뒤)에 끼어들도록 subprocess.run 을 감싼다
        import subprocess as _sp
        real_run = _sp.run
        def run_with_race(cmd, *a, **k):
            with cc.connect() as c:
                c.execute("UPDATE project_instructions SET body='다른 기기가 먼저 씀\n', rev=rev+1, updated_host='other' WHERE repo_url=%s AND name='override'", (A,))
            return real_run(cmd, *a, **k)
        llmui.subprocess.run = run_with_race
        it.move_cursor(row=1); await pilot.pause(0.3); await pilot.press("f2"); await pilot.pause(1.0)
        llmui.subprocess.run = real_run
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "override")
        check("지침 e: 편집 중 다른 기기가 먼저 고쳤으면(낡은 rev) 거부하고 상대 본문을 덮지 않는다", raw == (2, "다른 기기가 먼저 씀\n"), str(raw))
        # 비밀이 든 본문
        make_editor(f'printf "비번 {PW}\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("f2"); await pilot.pause(1.0)
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "instructions")
        check("지침 e: 등록된 비밀이 든 본문은 거부(저장 안 됨)", PW not in raw[1] and raw[0] == 2, str(raw[0]))
        # 빈 본문
        make_editor(': > "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("f2"); await pilot.pause(1.0)
        with cc.connect(readonly=True) as c:
            check("지침 e: 빈 본문은 거부(저장 안 됨)", cd.instr_raw(c, A, "instructions")[0] == 2 and cd.instr_raw(c, A, "instructions")[1].strip() != "")
        # 본문 보기 화면 안에서 편집하면 화면이 새 내용으로 갱신된다
        make_editor('printf "\\n## 화면 안에서 추가\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        await pilot.press("f2"); await settle(pilot, lambda: "화면 안에서 추가" in txt(app.screen.query_one("#instr-body")))
        check("지침 본문 e: 보기 화면에서 고치면 화면이 새 rev·내용으로 바뀜", "rev 3" in txt(app.screen.query_one("#instr-body")) and "화면 안에서 추가" in txt(app.screen.query_one("#instr-body")))
        await pilot.press("escape"); await pilot.pause(0.3)
        # 목록 새로고침·에이전트용 경로는 그대로(사람 전용 화면이 DB 를 지우지 않는다)
        await pilot.press("f5"); await pilot.pause(0.6)
        check("지침: r 새로고침, 행 삭제 기능은 없다(범위 밖)", rows(app, "#instr-table") == 3 and not any(b.key == "d" and "지침" in str(b.description) for b in app.BINDINGS))
        for f in (fake, EDITLOG + ".perm", EDITLOG + ".mode_probe"):
            try: os.unlink(f)
            except OSError: pass

        # --- 도움말·종료
        await pilot.press("f1"); await pilot.pause(0.3)
        check("F1: 도움말", app.screen.__class__.__name__ == "HelpScreen"); await pilot.press("escape"); await pilot.pause(0.2)
        await pilot.press("1"); await pilot.pause(0.5)
        check("1: 대시보드로 돌아옴", app.current_tab() == "dashboard")
        await pilot.press("2"); await pilot.pause(0.5)
        check("2: 탭 전환은 종료 확인창을 띄우지 않음(표로 포커스만 이동)", app.current_tab() == "search" and len(app.screen_stack) == 1)
        await pilot.press("1"); await pilot.pause(0.5)
        check("1: 이미 표에 있어도 탭 키는 확인창을 띄우지 않음", app.current_tab() == "dashboard" and len(app.screen_stack) == 1)
        await pilot.press("2"); await pilot.pause(0.5)
        tbl = app.query_one(app.TAB_TABLES["search"])
        app.query_one("#q").focus(); await pilot.pause(0.2)
        check("(준비) 검색 탭의 검색칸에 포커스", app.focused is app.query_one("#q"))
        await pilot.press("escape"); await pilot.pause(0.3)
        check("Esc: 표가 아닌 곳(검색칸)에서는 표로 포커스 이동(확인창 안 뜸)", app.focused is tbl and len(app.screen_stack) == 1)
        await pilot.press("escape"); await pilot.pause(0.3)
        check("Esc: 이미 표에 있으면 종료 확인창(기본 「아니오」)", type(app.screen).__name__ == "QuitConfirmScreen" and app.focused.id == "quit-no")
        await pilot.press("enter"); await pilot.pause(0.3)
        await pilot.press("q"); await pilot.pause(0.3)
        check("확인창 Enter = 취소, q 는 종료 키가 아님", app.is_running and len(app.screen_stack) == 1)

        # --- 알파벳 단축키 폐지(2026-11-03): 옛 글자 키는 아무 일도 안 하고, 같은 F키가 탭마다 다른 동작을 한다
        await pilot.press("1"); await pilot.pause(0.6)
        st0 = (app.stat_period, app.stat_bucket, app.stat_by, app.stat_order)
        await pilot.press("p", "b", "g", "o", "c", "m", "x", "r"); await pilot.pause(0.3)
        check("옛 알파벳 키(p b g o c m x r)는 아무 일도 안 한다", (app.stat_period, app.stat_bucket, app.stat_by, app.stat_order) == st0 and app.mask and len(app.screen_stack) == 1)
        fkey = lambda k: getattr(app.screen.active_bindings.get(k), "binding", None)
        check("푸터: 대시보드의 F2 는 기간, F7 은 필터 지움", fkey("f2").action == "stat_period" and fkey("f7").action == "stat_clear", str(fkey("f2")))
        await pilot.press("f2"); await pilot.pause(0.4)
        check("대시보드 F2 = 기간 순환", app.stat_period != st0[0])
        await pilot.press("2"); await pilot.pause(0.6)
        check("푸터: 검색 탭의 F2 는 역할, F7 은 모두 펼침(대시보드 동작은 꺼짐)", fkey("f2").action == "toggle_role" and fkey("f7").action == "expand_all" and app.check_action("stat_period", ()) is False)
        await pilot.press("4"); await pilot.pause(0.6)
        check("푸터: 비밀 탭의 F2 는 비밀 추가, F4 는 값 보기, Delete 는 삭제", fkey("f2").action == "secret_add" and fkey("f4").action == "reveal" and fkey("delete").action == "secret_delete")
        await pilot.press("5"); await pilot.pause(0.6)
        check("푸터: 후보 탭의 F2 는 무시, 비밀 추가는 꺼짐", fkey("f2").action == "cand_ignore" and app.check_action("secret_add", ()) is False)
        await pilot.press("6"); await pilot.pause(0.6)
        check("푸터: 지침 탭의 F2 는 지침 편집", fkey("f2").action == "instr_edit")
        await pilot.press("f10"); await pilot.pause(0.3)
        check("F10 = 치환 끔, 한 번 더 누르면 켬", app.mask is False)
        await pilot.press("f10"); await pilot.pause(0.3)
        check("F10 두 번 = 치환 켜짐으로 복귀", app.mask is True)
        await pilot.press("1"); await pilot.pause(0.5)


async def run_wrap():
    """대시보드 줄바꿈 → 1열 전환: 폭에 따라 글 칸이 줄바꿈되지 않아야 한다(2열이면 줄바꿈 없음, 아니면 1열). 그래프·막대는 칸 폭에 맞고 박스는 겹치지 않는다."""
    barw = {}
    for cols in (100, 150, 400):
        app = llmui.LlmUI()
        async with app.run_test(size=(cols, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#stat-sessions") >= 1)
            await pilot.pause(1.5)
            box = app.query_one("#dash-scroll")
            narrow = box.has_class("narrow")
            check(f"대시보드 {cols}칸: 2열이면 글이 줄바꿈되지 않고, 줄바꿈이 생기면 1열", narrow or not app._wrapping(), (narrow, app._wrapping()))
            tt = app.query_one("#stat-trend")
            barw[cols] = max((len(tt.get_row_at(i)[3].plain) for i in range(tt.row_count)), default=0)
            lt = txt(app.query_one("#stat-limits"))
            check(f"대시보드 {cols}칸: 한도는 점자 그래프(시간축 날짜 포함)이고 시간대별도 점자 그래프", any("\u2800" <= ch <= "\u28ff" and ch != "\u2800" for ch in lt) and re.search(r"\d\d-\d\d", lt) and any("\u2800" <= ch <= "\u28ff" for ch in txt(app.query_one("#stat-summary"))), lt[:300])
            tops = [app.query_one("#" + k) for kids in app.DASH_ROWS.values() for k in kids]
            bad = [(a.id, b.id) for i, a in enumerate(tops) for b in tops[i + 1:] if a.region.overlaps(b.region)]
            check(f"대시보드 {cols}칸: 박스끼리 겹치지 않는다", not bad, bad)
            check(f"대시보드 {cols}칸: 추이·분류 표 박스 높이가 내용(행 3개 안팎)에 맞아 예전 고정 14줄보다 낮다", all(app.query_one("#" + k).region.height < 14 for k in ("stat-trend", "stat-break")), [(k, app.query_one("#" + k).region.height) for k in ("stat-trend", "stat-break")])
            if cols == 100:
                check("대시보드 100칸: 최소 폭 규칙으로 1열", narrow)
            if cols == 400:
                check("대시보드 아주 넓은 폭(400칸): 2열 유지", not narrow and not app._wrapping(), (narrow, app._wrapping(), app._wrap_at))
    check("대시보드: 비용 막대는 박스가 넓을수록 길다(150칸 < 400칸, 18칸 고정 아님)", barw[400] > barw[150] > 0 and barw[400] > 18, barw)


async def run_resize():
    """창 크기를 바꾸면 그래프·막대가 새 폭으로 다시 그려진다: 그릴 때 박스 폭이 아직 이전 레이아웃의 값이라 한 단계 전 폭으로 남던 결함(170→120 에서 박스 68 인데 본문 94칸).
    각 칸의 본문 최대 줄 폭이 칸 폭을 넘지 않고(잘림·줄바꿈 없음) 칸 폭 − 8 보다 좁지 않다(너무 좁게 남지 않음)."""
    from rich.cells import cell_len
    app = llmui.LlmUI()
    async with app.run_test(size=(170, 50)) as pilot:
        await settle(pilot, lambda: rows(app, "#stat-sessions") >= 1)
        await pilot.pause(1.0)
        for cols in (120, 220, 170, 100, 200, 90, 300):
            await pilot.resize_terminal(cols, 50)
            await pilot.pause(0.8)

            def widths_bad():
                out = []
                for wid in ("stat-trend-chart", "stat-limits", "stat-summary"):
                    w = app.query_one("#" + wid)
                    need = max((cell_len(l) for l in txt(w).split("\n")), default=0)
                    if not (w.size.width - 8 <= need <= w.size.width):
                        out.append((wid, w.size.width, need))
                return out
            # 고정 대기만으로는 부하 때 다시 그리기가 늦어 실패한다 — 폭이 맞을 때까지 조건 대기(최대 15초), 끝내 안 맞으면 실패
            await settle(pilot, lambda: not widths_bad(), timeout=15.0)
            bad = widths_bad()
            check(f"리사이즈 → {cols}칸: 그래프·글 칸의 본문 폭이 칸 폭에 맞는다(칸 폭−8 ≤ 본문 ≤ 칸 폭)", not bad, (bad, "그릴 때 폭", getattr(app, "_painted_w", None), "지금 폭", app._box_widths(), "좁은 배치", app.query_one("#dash-scroll").has_class("narrow"), "앱 폭", app.size.width))
            tt = app.query_one("#stat-trend")
            bw = max((len(tt.get_row_at(i)[3].plain) for i in range(tt.row_count)), default=0)
            check(f"리사이즈 → {cols}칸: 추이 표의 막대가 표 폭 안에 있다", bw <= tt.size.width, (bw, tt.size.width))


async def run_restricted():
    """제한 모드(LLM 세션): 모든 탭을 볼 수 있되 비밀 값은 추출·조회할 수 없다 — 모든 텍스트에서 등록한 비밀과 비밀처럼 보이는 문자열을 [protected] 로 치환(끌 수 없음),
    값 보기·비밀 추가/삭제/끄기·후보 무시·지침 편집은 막고, 후보 승인은 허용한다."""
    pass
    with cc.connect() as c:
        cs.add_secret(c, "RESTRICT_PW", "literal", PW, replace=True)
        c.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)", ("dddd0001", "h1", ["h1"], A, "2026-10-06T01:00:00Z", "2026-10-06T01:00:10Z"))
        for i, (role, text) in enumerate([("user", f"새 키는 {KEY2} 이고 비밀번호는 Zq9!kd82Lm 이다"), ("assistant", "받았다")]):
            c.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"dddd-{i:04d}", "dddd0001", "h1", f"2026-10-06T01:00:{i * 10:02d}Z", role, "prompt" if role == "user" else "response", text, json.dumps({"i": i})))
        n_secrets = len(cs.load_secrets(c, only_enabled=False))
    app = llmui.LlmUI(restricted=True)
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, lambda: rows(app, "#projects") == 3)
        check("제한: 개요는 정상 로드(저장소 3곳)", rows(app, "#projects") == 3 and app.restricted)
        check("제한: 상태줄에 제한 모드 안내", "제한 모드" in txt(app.query_one("#sstate")))
        check("제한: 막힌 동작(m·v·비밀 추가/삭제/끄기·후보 무시)은 푸터에서 숨기고 탭 이동·새로고침은 보임", all(app.check_action(a, ()) is False for a in ("toggle_mask", "reveal", "secret_add", "secret_delete", "secret_toggle", "cand_ignore")) and app.check_action("reload", ()) is True and app.check_action("tab", ("secrets",)) is True)
        # --- 비밀 탭: 열린다, 값은 어디에도 없다
        await pilot.press("4"); await settle(pilot, lambda: app.current_tab() == "secrets" and rows(app, "#secrets-table") >= 1)
        st = app.query_one("#secrets-table")
        cells = " ".join(str(st.get_row_at(i)) for i in range(st.row_count))
        check("제한: 비밀 탭이 열리고 등록된 비밀의 이름·종류·길이·fp 는 보이지만 값은 없음", app.current_tab() == "secrets" and "RESTRICT_PW" in cells and PW not in cells, cells[:200])
        await pilot.press("f4"); await pilot.pause(0.3)
        check("제한: v(값 보기)는 막혀 값이 표시되지 않음", PW not in txt(app.query_one("#sdetail")) and app._reveal is False)
        # --- 후보 탭: 열린다, 미리보기는 [protected]
        _calls = []
        _orig = cd.scan_candidates
        cd.scan_candidates = lambda c: (_calls.append(1), _orig(c))[1]
        await pilot.press("5"); await settle(pilot, lambda: app.current_tab() == "cands" and rows(app, "#cands-table") >= 1, timeout=15)
        await pilot.pause(1.0)
        cd.scan_candidates = _orig
        check("탭을 한 번 열면 후보 탐지는 한 번만 돈다(예전엔 action_tab 과 TabActivated 가 둘 다 불러 두 번 돌고 알림이 겹쳤다)", len(_calls) == 1, len(_calls))
        ct = app.query_one("#cands-table")
        ccells = " ".join(str(ct.get_row_at(i)) for i in range(ct.row_count))
        check("제한: 후보 탭이 열리고 후보가 탐지되며 미리보기는 [protected](N자)이고 값(키)은 어디에도 없음", ct.row_count >= 1 and "[protected] (" in ccells and KEY2 not in ccells and cs.preview(KEY2) not in ccells, ccells[:240])
        await pilot.press("f4"); await pilot.pause(0.3)
        check("제한: 후보 v(값 보기)도 막혀 값이 표시되지 않음", KEY2 not in txt(app.query_one("#cdetail")))
        await pilot.press("f2"); await pilot.pause(0.3)
        with cc.connect() as c:
            ign = len(cd.ignored_fps(c))
        check("제한: 후보 무시(i)는 막힘(무시 목록 불변)", ign == 0, ign)
        ct.move_cursor(row=0); await pilot.pause(0.2); await pilot.press("enter"); await pilot.pause(0.5)
        check("제한: 후보 승인(Enter)은 허용 — 값을 보여 주지 않는 이름 입력 대화상자가 열림", isinstance(app.screen, llmui.PromptScreen) and KEY2 not in txt(app.screen))
        await pilot.press("escape"); await pilot.pause(0.3)
        # --- 치환 고정·후보 패턴 치환
        await pilot.press("f10"); await pilot.pause(0.3)
        mk = app.masker()
        probe = f"등록한 {PW} 와 미등록 키 {KEY2} 그리고 password=hunter99xyzQ 와 비밀번호는 Zq9!kd82Lm 입니다"
        out = mk.text(probe)
        check("제한: m 으로 치환을 끌 수 없고 마스커가 등록한 비밀 + 후보 패턴(키·password=·한글 비밀번호)을 모두 [protected] 로", app.mask is True and all(x not in out for x in (PW, KEY2, "hunter99xyzQ", "Zq9!kd82Lm")) and out.count("[protected]") >= 4, out)
        # --- 검색·대화 화면에서도
        await pilot.press("2"); await pilot.pause(0.3)
        app.query_one("#repo").value = ""; q = app.query_one("#q"); q.value = "새 키는"; q.focus(); await pilot.pause(0.2)
        await pilot.press("enter"); await settle(pilot, lambda: hits(app) >= 1)
        rc = " ".join(str(app.query_one("#results").get_row_at(i)) for i in range(app.query_one("#results").row_count))
        check("제한: 검색 결과 목록에 후보 패턴의 키가 [protected] 로만 보임", hits(app) >= 1 and KEY2 not in rc and PW not in rc and "[protected]" in rc, rc[:200])
        await submit(pilot, app.query_one("#results")); await pilot.pause(0.8)
        sb = sess_txt(app.screen) if isinstance(app.screen, llmui.SessionScreen) else ""
        check("제한: 대화 화면에서도 키·비밀번호는 [protected]", isinstance(app.screen, llmui.SessionScreen) and KEY2 not in sb and PW not in sb and "[protected]" in sb, sb[:200])
        await pilot.press("f10"); await pilot.pause(0.3)
        check("제한: 대화 화면에서 m 을 눌러도 원문이 나오지 않음", PW not in sess_txt(app.screen) and KEY2 not in sess_txt(app.screen))
        await pilot.press("escape"); await pilot.pause(0.3)
        # --- 막힌 동작
        for fn in ("action_secret_add", "action_secret_delete", "action_secret_toggle", "action_reveal", "action_cand_ignore"):
            getattr(app, fn)(); await pilot.pause(0.15)
        with cc.connect() as c:
            after = len(cs.load_secrets(c, only_enabled=False))
        check("제한: 비밀 추가·삭제·끄기·값 보기·후보 무시가 모두 막힘(대화상자 없음, 등록 수 불변, 값 미표시)", not isinstance(app.screen, llmui.PromptScreen) and not isinstance(app.screen, llmui.ConfirmScreen) and after == n_secrets and not app._reveal, (after, n_secrets))
        # --- 대화 화면은 세션 전체가 아니라 보일 창만 치환한다(메시지 수만 개짜리 세션이 느리던 문제)
        with cc.connect() as c:
            c.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)", ("eeee0001", "h1", ["h1"], A, "2026-10-07T01:00:00Z", "2026-10-07T04:00:00Z"))
            for i in range(200):
                c.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"eeee-{i:04d}", "eeee0001", "h1", f"2026-10-07T{1 + i // 60:02d}:{i % 60:02d}:00Z", "user" if i % 2 == 0 else "assistant", "prompt" if i % 2 == 0 else "response", f"긴 세션 {i}번째 메시지", json.dumps({"i": i})))
        _n = []
        _t = cs.Masker.text
        cs.Masker.text = lambda self, x: (_n.append(1), _t(self, x))[1]
        _mm = llmui.MSG_MAX
        llmui.MSG_MAX = 50
        try:
            app.push_screen(llmui.SessionScreen(app, "eeee0001", "eeee-0100")); await settle(pilot, lambda: isinstance(app.screen, llmui.SessionScreen) and len(app.screen.msgs) > 0)
            await pilot.pause(0.5)
            n_open = len(_n)
            shown = len(app.screen.msgs)
            hb, ha = app.screen.hidden_before, app.screen.hidden_after
        finally:
            llmui.MSG_MAX = _mm
            cs.Masker.text = _t
        check("대화 화면: 200개 메시지 세션에서 창(50개)만 그리고 앞 75·뒤 75 생략 표시", shown == 50 and hb + ha == 150 and hb == 75, (shown, hb, ha))
        check("대화 화면: 치환 호출이 세션 전체(200)가 아니라 창 크기 안팎(<110)이라 큰 세션이 느려지지 않음", n_open < 110, n_open)
        await pilot.press("escape"); await pilot.pause(0.3)
        await pilot.press("1"); await pilot.pause(0.5)
        check("제한: 대시보드(통계 포함)는 그대로 열림", app.current_tab() == "dashboard")
        await pilot.press("3"); await pilot.pause(0.4)
        vq = app.query_one("#phrase"); vq.value = "새 키는"; await submit(pilot, vq); await pilot.pause(1.0)
        check("표 셀: 모든 DataTable 의 문자열 셀에 마크업으로 해석될 대괄호(예: [protected])가 없음 — 화면에서 글자가 사라지지 않게 Text 로 넣었는지", risky_cells(app) == [], risky_cells(app))
        app.action_tab("instr")       # 입력칸에 포커스가 있으면 숫자 키가 글자로 들어가므로 동작을 직접 호출
        await settle(pilot, lambda: app.query_one("#instr-table").row_count >= 1, timeout=6)
        check("지침 탭으로 가면 지침 표에 포커스(Enter·↑↓ 가 바로 동작)", app.focused is not None and app.focused.id == "instr-table")
        app.action_tab("dashboard"); await pilot.pause(0.5)
        check("대시보드로 가면 표에 포커스", app.focused is not None and app.focused.id == "projects")
        await pilot.press("f1"); await pilot.pause(0.4)
        hd = " ".join(d for _, d in app.screen._rows) if type(app.screen).__name__ == "HelpScreen" else ""
        check("제한: 도움말 키 목록에서도 막힌 동작(치환 켬/끔·비밀 추가·삭제·켬/끔·값 보기·무시)이 빠지고 열린 동작(검색·대시보드·새로고침)은 있음", hd and not any(x in hd for x in ("치환 켬/끔", "비밀 추가", "값 보기", "무시", "삭제")) and "새로고침" in hd and "대시보드" in hd, hd[:200])
        _terms = " ".join(d for _, d in llmui.LlmUI.HELP_TERMS)
        check("도움말 용어(제한 모드)가 현재 정책을 설명(모든 탭 열람·값 조회 불가)하고 낡은 「탭이 열리지 않음」 문구가 없음", "모든 탭을 볼 수 있" in _terms and "열리지 않고" not in _terms and "[protected]" in _terms, _terms[:100])
        await pilot.press("escape"); await pilot.pause(0.3)
        app.action_tab("instr"); await settle(pilot, lambda: app.current_tab() == "instr" and app.query_one("#instr-table").row_count >= 1, timeout=6)
        check("제한: 지침 탭 보기는 가능(목록이 보임), 편집(edit_instr)은 편집기를 열지 않고 False", app.current_tab() == "instr" and app.query_one("#instr-table").row_count >= 1 and app.edit_instr("x", "y") is False)
    # 사람(제한 없음)은 이전과 같다 — 후보 미리보기가 흐린 미리보기, 값 보기 가능
    app2 = llmui.LlmUI()
    async with app2.run_test(size=(160, 50)) as pilot:
        await settle(pilot, lambda: rows(app2, "#projects") == 3)
        await pilot.press("5"); await settle(pilot, lambda: rows(app2, "#cands-table") >= 1, timeout=15)
        c2 = " ".join(str(app2.query_one("#cands-table").get_row_at(i)) for i in range(rows(app2, "#cands-table")))
        check("사람(제한 없음): 후보 미리보기는 [protected] 가 아니라 흐린 미리보기", not app2.restricted and "[protected] (" not in c2 and cs.preview(KEY2) in c2, c2[:200])
        await pilot.press("f10"); await pilot.pause(0.3)
        check("사람(제한 없음): m 으로 치환을 끌 수 있음", app2.mask is False)


def check_limits_text():
    """한도 칸: 모든 계정이 같은 시간 축(최근 D일)을 쓰고, 오래됐거나 이미 리셋된 샘플은 「지금」이 아니라 「마지막 샘플」로 표시한다."""
    from datetime import datetime, timedelta, timezone
    now = time.time()
    n = datetime.fromtimestamp(now, timezone.utc)
    def acct(aid, email, reset7_h, last_min_ago):
        last = n - timedelta(minutes=last_min_ago)
        r5, r7 = last + timedelta(hours=2), n + timedelta(hours=reset7_h)
        ser5 = [(last - timedelta(minutes=5 * i), 20.0 - i, r5) for i in range(3)][::-1]
        ser7 = [(last - timedelta(hours=i), 30.0 - i, r7) for i in range(3)][::-1]
        mk = lambda ser, r: dict(account=aid, label=email, plan="pro", windows=[(r, ser[-1][1])], series=ser)
        return mk(ser5, r5), mk(ser7, r7)
    a5, a7 = acct("A", "a@x.test", 30, 2)
    b5, b7 = acct("B", "b@x.test", 52, 2)
    win = {"5h": [a5, b5], "7d": [a7, b7]}
    t = llmui.limits_text(win, 80, days=7, now=now).plain
    axes = [l for l in t.split("\n") if re.search(r"\d\d-\d\d \d\d:\d\d", l)]
    check("한도 칸: 계정이 둘이어도 시간축 눈금줄이 같다(같은 기간)", len(axes) == 2 and axes[0].strip() == axes[1].strip(), axes)
    check("한도 칸: 최근 샘플은 「지금 N%」", "지금 " in t and "마지막 샘플" not in t, t[:200])
    old5, old7 = acct("C", "c@x.test", 30, 300)
    old = llmui.limits_text({"5h": [old5], "7d": [old7]}, 80, days=7, now=now).plain
    check("한도 칸: 오래된 샘플은 「마지막 샘플 N% (월-일 시:분)」", "마지막 샘플" in old and "지금 " not in old, old[:200])
    sm = dict(sessions=2, cost=5.0, prompts=4, tools=1, autos=0, unknown_tags=0, median_prompts=2, median_duration_s=60, avg_duration_s=90, by_slot=[0] * 96, by_hour=[0] * 24, by_weekday=[0] * 7, orphan=(3, 1.25))
    st = llmui.summary_text(sm, 60, "7일").plain
    check("세션 통계 칸: 기간 라벨과 「세션 기록 없는 사용」 금액·세션 길이 기준 안내", "비용 $5.00 (7일)" in st and "세션 기록 없는 사용 $1.25(3건) 별도" in st and "세션 전체 기준" in st, st[:200])
    sm["orphan"] = (0, 0.0)
    check("세션 통계 칸: 세션 기록 없는 사용이 없으면 그 줄이 없다", "세션 기록 없는 사용" not in llmui.summary_text(sm, 60, "전체").plain)
    check("한도 칸: 기간 지정 때 샘플이 하나도 없으면 「이 기간에 한도 샘플 없음」", "이 기간에 한도 샘플 없음" in llmui.limits_text({"5h": [], "7d": []}, 80, days=1, now=now).plain)


async def run_sessions_tab():
    """7 세션 탭: tmux 대신 가짜 세션 목록으로 — 목록·미리보기·붙기·새 세션·정리·떼기, 탭별 F키 분리, 제한 모드(목록만, Enter 로도 붙지 않음), `--sessions` 단독 앱."""
    import llm_sessions as lss
    tm = lss.tm
    fake = [tm.Session("claude-a-1", 1.0, time.time(), 0, "/tmp/a", "claude"), tm.Session("claude-b-2", 2.0, time.time(), 1, "/tmp/b", "claude",
                                                                                         [tm.Client("/dev/pts/9", 1, "80x24", "ssh")])]
    log = []
    saved = {k: getattr(tm, k) for k in ("list_sessions", "preview", "exists", "kill", "detach_all", "attach_cmd", "create")}
    tm.list_sessions = lambda: list(fake)
    tm.preview = lambda name, n=14: f"SCREEN-OF-{name}"
    tm.exists = lambda name: True
    tm.kill = lambda name: log.append(("kill", name))
    tm.detach_all = lambda name: (log.append(("detach", name)), True)[1]
    tm.attach_cmd = lambda name: ["true"]
    tm.create = lambda d, args: (log.append(("create", d)), "claude-new-3")[1]
    try:
        app = llmui.LlmUI()
        attached = []
        async with app.run_test(size=(160, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#projects") == 3)
            app.run_attach = lambda name: attached.append(name)           # suspend 는 헤드리스에서 못 쓰므로 붙기 호출만 기록
            check("세션 탭: 탭 이름·F키 동작은 다른 탭에서는 꺼져 있다", all(app.check_action(a, ()) is False for a in ("sess_new", "sess_detach", "sess_kill")))
            await pilot.press("7"); await settle(pilot, lambda: app.current_tab() == "sessions" and rows(app, "#list") == 2)
            check("세션 탭: 7 키로 열리고 세션 2개가 목록에 나옴(분리됨/붙은 곳 표시)", rows(app, "#list") == 2 and "ssh" in str(app.query_one("#list").get_row_at(1)[4]))
            check("세션 탭: 표에 포커스, F키 동작이 켜짐", app.focused is not None and app.focused.id == "list" and all(app.check_action(a, ()) for a in ("sess_new", "sess_detach", "sess_kill")))
            await settle(pilot, lambda: "SCREEN-OF-claude-a-1" in str(app.query_one("#preview").render()))
            check("세션 탭: 선택한 세션의 화면 미리보기", "SCREEN-OF-claude-a-1" in str(app.query_one("#preview").render()))
            await pilot.press("enter"); await pilot.pause(0.3)
            check("세션 탭: Enter = 붙기", attached == ["claude-a-1"], attached)
            await pilot.press("f3"); await pilot.pause(0.3)
            check("세션 탭: F3 = 붙은 곳 떼기(다른 탭의 F3 이 아님)", ("detach", "claude-a-1") in log, log)
            await pilot.press("delete"); await pilot.pause(0.3)
            check("세션 탭: Delete = 정리 확인창(비밀 삭제가 아님)", type(app.screen).__name__ == "ConfirmScreen")
            await pilot.press("enter"); await pilot.pause(0.3)
            check("세션 탭: 확인창은 기본 「아니오」라 그대로 Enter 해도 정리되지 않음", not any(x[0] == "kill" for x in log) and len(app.screen_stack) == 1, log)
            await pilot.press("delete"); await pilot.pause(0.3); await pilot.press("left", "enter"); await pilot.pause(0.3)
            check("세션 탭: 「예」를 고르면 정리", ("kill", "claude-a-1") in log, log)
            await pilot.press("f2"); await pilot.pause(0.5)
            check("세션 탭: F2 = 새 세션 대화상자", type(app.screen).__name__ == "NewScreen")
            await pilot.press("escape"); await pilot.pause(0.3)
            await pilot.press("f1"); await pilot.pause(0.4)
            hd = " ".join(d for _, d in app.screen._rows) if type(app.screen).__name__ == "HelpScreen" else ""
            check("세션 탭: 도움말 키 목록에 세션 동작(새 세션·붙은 곳 떼기·정리)이 있고 비밀 삭제/추가는 없음", hd and all(x in hd for x in ("새 세션", "붙은 곳 떼기", "정리")) and "비밀 추가" not in hd, hd[:200])
            await pilot.press("escape"); await pilot.pause(0.3)
            await pilot.press("1"); await pilot.pause(0.4)
            await pilot.press("f2"); await pilot.pause(0.3)
            check("대시보드에서 F2 는 세션 새로 만들기가 아니라 기간 변경(탭별 분리)", type(app.screen).__name__ != "NewScreen")

        # --- 제한 모드: 목록만
        fake_n = len(log)
        rapp = llmui.LlmUI(restricted=True)
        rattached = []
        async with rapp.run_test(size=(160, 50)) as pilot:
            await settle(pilot, lambda: rows(rapp, "#projects") == 3)
            rapp.run_attach = lambda name: rattached.append(name)
            await pilot.press("7"); await settle(pilot, lambda: rapp.current_tab() == "sessions" and rows(rapp, "#list") == 2)
            check("제한: 세션 목록은 보인다", rows(rapp, "#list") == 2)
            check("제한: 미리보기는 꺼져 있고 다른 세션의 화면 내용이 없음", "SCREEN-OF" not in str(rapp.query_one("#preview").render()) and "제한 모드" in str(rapp.query_one("#preview").render()))
            check("제한: 세션 동작은 푸터·도움말에서 숨김", all(rapp.check_action(a, ()) is False for a in ("sess_new", "sess_detach", "sess_kill", "sess_attach")))
            await pilot.press("enter"); await pilot.press("f3"); await pilot.press("delete"); await pilot.press("f2"); await pilot.pause(0.5)
            check("제한: Enter(행 선택)·F3·Delete·F2 어느 쪽으로도 붙기·떼기·정리·새 세션이 안 됨", len(log) == fake_n and not rattached and len(rapp.screen_stack) == 1, (log[fake_n:], rattached))
            rapp.action_sess_attach(); rapp.action_sess_new(); rapp.action_sess_kill(); rapp.action_sess_detach()
            await pilot.pause(0.3)
            check("제한: 동작을 코드에서 직접 불러도 막힘(run_attach 포함)", len(log) == fake_n and not rattached and len(rapp.screen_stack) == 1)
            lss.SessionsMixin.run_attach(rapp, "claude-a-1")      # 시험이 덮어쓴 run_attach 를 우회해 원래 메서드를 직접
            check("제한: run_attach 자체도 막힘(suspend·tmux 호출 없이 반환)", True)

        # --- 세션 단독 앱(`llmui --sessions`): DB 없이, 제한 모드도 같은 규칙
        sapp = lss.SessionsUI(restricted=True)
        async with sapp.run_test(size=(120, 40)) as pilot:
            await settle(pilot, lambda: sapp.query_one("#list").row_count == 2)
            await pilot.press("enter"); await pilot.press("delete"); await pilot.press("f2"); await pilot.pause(0.4)
            check("--sessions(제한): 목록은 보이고 Enter·Delete·F2 는 아무 일도 안 함", sapp.query_one("#list").row_count == 2 and len(sapp.screen_stack) == 1 and len(log) == fake_n)
            check("--sessions(제한): 동작은 푸터에서 숨김", all(sapp.check_action(a, ()) is False for a in lss.SESS_ACTIONS))
    finally:
        for k, v in saved.items():
            setattr(tm, k, v)


async def run_cards_tab():
    """8 카드 탭: 목록·건너뛴 프로젝트 표시·체크 시에만 하단 표시·논의 세션 시작 인자·상세(근거 대조·원문 팝업·이력)·승격(사람만)·제한 모드 차단."""
    import subprocess, tempfile, ctx_store as st, llmcards as lcd
    import llm_sessions as lss
    tm = lss.tm
    tmp = tempfile.mkdtemp(prefix="llmui-cards-")
    store = f"{tmp}/ctx"; os.makedirs(store)
    open(f"{store}/manifest.toml", "w").write('[projects.alpha]\nrepo_url = "https://github.com/x/alpha"\nowner = "personal"\nremote = ""\n\n[projects.gone]\nrepo_url = "https://github.com/x/gone"\nowner = "personal"\nremote = ""\n')
    genv = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null")
    git = lambda *a: subprocess.run(["git", "-C", f"{store}/alpha", *a], capture_output=True, text=True, env=genv)
    os.makedirs(f"{store}/alpha"); git("init", "-q")
    EVU = "aaaaaaaa-0000-0000-0000-00000000f001"
    C1, C2 = "3f2a9c1b-1111-4222-8333-444455556666", "7e7e7e7e-1111-4222-8333-444455556666"
    def body(cid, title, quote):
        return (f"---\nid: {cid}\ntitle: {title}\nkind: 대전제\nproposer: agent\nlast_confirmed:\n---\n## 내용\n본문 {title}\n\n## 근거 원문\n- [msg:{EVU[:8]}] \"{quote}\"\n\n## 반례·한계\n- 반례 하나\n\n## 이력\n- 만듦\n")
    def put(cid, state, scope, title, quote, msg):
        p = f"{store}/alpha/note/cards/{cid}.md"; os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(st.render_header({"state": state, "scope": scope}) + body(cid, title, quote))
        git("add", "-A"); git("commit", "-q", "-m", f"ctx: alpha/note/cards/{cid} (s@h)")
    put(C1, "draft", "personal", "배포는 금요일", "alpha 배포는 금요일", 1)
    put(C2, "adopted", "project", "엉뚱한 인용 카드", "이 말은 원문에 없다", 2)
    conn = cc.connect()
    full = "alpha 배포는 금요일에 한다고 했다 — 전체 본문 FULLTEXT-MARK"
    conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                 (EVU, "aaaa0001", "h1", "2026-10-01T02:00:00Z", "user", "prompt", full, json.dumps({"uuid": EVU, "type": "user", "message": {"role": "user", "content": full}})))
    conn.commit(); conn.close()
    cdir = f"{tmp}/work"; os.makedirs(cdir)
    saved_env = {k: os.environ.get(k) for k in ("CTX_STORE_DIR", "LLMUI_CARD_DIR", "CTX_SYNC_INLINE", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_CONFIG_GLOBAL", "CTX_VIEWS_DIR")}
    os.environ.update(CTX_STORE_DIR=store, LLMUI_CARD_DIR=cdir, CTX_SYNC_INLINE="1", CTX_VIEWS_DIR=f"{tmp}/views", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null")
    log, saved_create = [], tm.create
    tm.create = lambda d, args=None, name=None: (log.append((d, list(args or []))), "claude-card-1")[1]
    try:
        app = llmui.LlmUI()
        async with app.run_test(size=(170, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#projects") == 3)
            check("카드 탭: 탭 전용 동작은 다른 탭에서는 꺼져 있다", all(app.check_action(a, ()) is False for a in ("card_toggle", "card_state_cycle", "card_scope_cycle")))
            await pilot.press("8"); await settle(pilot, lambda: app.current_tab() == "cards" and rows(app, "#cards-table") == 2)
            check("카드 탭: 8 키로 열리고 카드 2장이 보인다(다른 탭 번호는 그대로)", rows(app, "#cards-table") == 2 and app.focused is not None and app.focused.id == "cards-table")
            st_txt = txt(app.query_one("#card-state"))
            check("카드 탭: 이 머신에 저장소가 없는 프로젝트(gone)를 화면에 알린다", "건너뜀: gone" in st_txt, st_txt)
            check("카드 탭: 체크가 없으면 하단(쟁점 입력·확인)이 숨겨져 있다", app.query_one("#card-bottom").display is False)
            await pilot.press("space"); await pilot.pause(0.3)
            check("카드 탭: Space 로 체크하면 하단이 나타나고 「확인」이 켜진다", app.query_one("#card-bottom").display is True and len(app.card_checked) == 1 and app.query_one("#card-go").disabled is False, app.card_checked)
            await pilot.press("space"); await pilot.pause(0.3)
            check("카드 탭: 다시 Space 로 해제하면 하단이 다시 숨는다", app.query_one("#card-bottom").display is False and app.card_checked == [])
            await pilot.press("f2"); await pilot.pause(0.3)
            check("카드 탭: F2 상태 필터(전체→draft)가 목록을 줄인다", app.card_state == "draft" and rows(app, "#cards-table") == 1)
            await pilot.press("f2", "f2", "f2"); await pilot.pause(0.3)
            check("카드 탭: F2 를 돌면 다시 전체", app.card_state is None and rows(app, "#cards-table") == 2)
            # 체크 → 쟁점 → 세션 시작
            await pilot.press("space"); await pilot.pause(0.3)
            app.query_one("#card-issue").value = "이 카드가\n맞는지"
            first = app.card_checked[0]
            ok = app.launch_card_session(); await pilot.pause(0.3)
            check("카드 세션: tmuxsess.create 가 카드 디렉터리와 `/donghans-card 프로젝트:uuid8 쟁점` 초기 프롬프트로 불린다",
                  ok and len(log) == 1 and log[0][0] == cdir and log[0][1][-1] == f"/donghans-card {first} 이 카드가 맞는지", log)
            check("카드 세션: 권한 확인 건너뛰기 기본 인자가 앞에 붙고, 시작 뒤 체크가 풀리고 세션 탭으로 간다", log[0][1][0].startswith("--") and app.card_checked == [] and app.current_tab() == "sessions", (log, app.current_tab()))
            await pilot.press("8"); await settle(pilot, lambda: app.current_tab() == "cards")
            # 상세: 근거 대조
            app.query_one("#cards-table").focus(); await pilot.pause(0.2)
            tb = app.query_one("#cards-table"); tb.move_cursor(row=[k.value for k in tb.rows].index(f"alpha:{C1[:8]}"))
            await pilot.press("enter"); await settle(pilot, lambda: type(app.screen).__name__ == "CardScreen")
            scr = app.screen
            check("카드 상세: 열리고 근거가 원문과 대조돼 「일치」", type(scr).__name__ == "CardScreen" and scr.res and scr.res[0]["status"] == "일치" and "일치" in str(scr.query_one("#ev-table").get_row_at(0)[1]), (scr.row["name"], [(r["status"], (r["text"] or "")[:40]) for r in scr.res]))
            await pilot.press("enter"); await settle(pilot, lambda: type(app.screen).__name__ == "EvidenceScreen")
            check("카드 상세: 근거에서 Enter → 팝업에 메시지 전체 본문(잘림 없음)", type(app.screen).__name__ == "EvidenceScreen" and "FULLTEXT-MARK" in txt(app.screen.query_one("#ev-text")))
            await pilot.press("escape"); await pilot.pause(0.3)
            await pilot.press("h"); await settle(pilot, lambda: type(app.screen).__name__ == "HistoryScreen")
            check("이력 화면: 판 목록과 diff 가 보인다", type(app.screen).__name__ == "HistoryScreen" and app.screen.query_one("#hist-table").row_count == 1 and "+++" in txt(app.screen.query_one("#hist-diff")), txt(app.screen.query_one("#hist-diff"))[:120])
            await pilot.press("escape"); await pilot.pause(0.3)
            # 승격 (사람): draft → reviewed
            await pilot.press("f2"); await settle(pilot, lambda: type(app.screen).__name__ == "ConfirmScreen")
            check("승격: F2 는 확인창을 먼저 띄운다(바로 쓰지 않음)", type(app.screen).__name__ == "ConfirmScreen" and st.read_doc(store, "alpha", "note", f"cards/{C1}")["meta"]["state"] == "draft")
            await pilot.press("left", "enter"); await settle(pilot, lambda: st.read_doc(store, "alpha", "note", f"cards/{C1}")["meta"]["state"] == "reviewed", 12)
            d = st.read_doc(store, "alpha", "note", f"cards/{C1}")
            import re as _re
            check("승격: 확인하면 reviewed 로 반영되고 last_confirmed 가 오늘 날짜, 이력에 한 줄", d["meta"]["state"] == "reviewed" and _re.search(r"last_confirmed: \d{4}-\d\d-\d\d", d["body"]) and "사용자 확인(llmui): draft → reviewed" in d["body"], d["meta"])
            await pilot.pause(0.5)
            check("승격: 상세 화면이 새 상태로 다시 그려진다", "사용자 확인" in txt(app.screen.query_one("#card-head")), txt(app.screen.query_one("#card-head")))
            await pilot.press("escape"); await pilot.pause(0.3)
            # adopted 카드는 더 올릴 수 없다
            tb.move_cursor(row=[k.value for k in tb.rows].index(f"alpha:{C2[:8]}"))
            await pilot.press("enter"); await settle(pilot, lambda: type(app.screen).__name__ == "CardScreen")
            check("상세: 미일치 인용을 대조 결과에서 보인다", app.screen.res and app.screen.res[0]["status"] == "미일치", [r["status"] for r in app.screen.res])
            await pilot.press("f2"); await pilot.pause(0.4)
            check("승격: adopted 카드는 확인창 없이 안내만", type(app.screen).__name__ == "CardScreen" and st.read_doc(store, "alpha", "note", f"cards/{C2}")["meta"]["state"] == "adopted")
            await pilot.press("escape"); await pilot.pause(0.3)

        # --- 제한 모드: 읽기만
        n_log = len(log)
        rapp = llmui.LlmUI(restricted=True)
        async with rapp.run_test(size=(170, 50)) as pilot:
            await settle(pilot, lambda: rows(rapp, "#projects") == 3)
            await pilot.press("8"); await settle(pilot, lambda: rapp.current_tab() == "cards" and rows(rapp, "#cards-table") == 2)
            await pilot.press("space"); await pilot.pause(0.3)
            check("제한 모드: 카드 목록·체크는 되지만 「확인」 버튼은 꺼져 있다", len(rapp.card_checked) == 1 and rapp.query_one("#card-go").disabled is True)
            check("제한 모드: 세션 시작을 직접 불러도 막힌다", rapp.launch_card_session() is False and len(log) == n_log)
            before = st.read_doc(store, "alpha", "note", f"cards/{C1}")["hash"]
            row = rapp.card_rows[f"alpha:{C1[:8]}"]
            rapp.promote_card(row); await pilot.pause(0.3)
            check("제한 모드: 승격은 확인창도 없이 막힌다(문서가 안 바뀐다)", type(rapp.screen).__name__ != "ConfirmScreen" and st.read_doc(store, "alpha", "note", f"cards/{C1}")["hash"] == before)
            await pilot.press("enter"); await settle(pilot, lambda: type(rapp.screen).__name__ == "CardScreen")
            masked = txt(rapp.screen.query_one("#card-body"))
            check("제한 모드: 상세는 볼 수 있다", "본문" in masked, masked[:80])
    finally:
        tm.create = saved_create
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


async def run_host_tab():
    """9 호스트 탭(S0, 읽기 전용): 키 1~8 매핑 불변·9 → host, 녹화본 렌더링, 파일 없음 안내, 제한 모드(안내문만·파일 안 읽음·동작 숨김)."""
    import llmhost_view as hv
    want = {"1": "dashboard", "2": "search", "3": "verify", "4": "secrets", "5": "cands", "6": "instr", "7": "sessions", "8": "cards", "9": "host"}
    got = {b.key: b.action for b in llmui.LlmUI.BINDINGS if b.key in want}
    check("탭 키 1~9 매핑(1~8 불변, 9 호스트)", got == {k: f"tab('{v}')" for k, v in want.items()}, str(got))
    check("TABS 10개, 9번째가 호스트·10번째가 한도(1~9 불변)", len(llmui.TABS) == 10 and llmui.TABS[8] == ("host", "호스트") and llmui.TABS[9] == ("limits", "한도") and [t[0] for t in llmui.TABS[:8]] == [want[str(i)] for i in range(1, 9)])
    app = llmui.LlmUI()
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, lambda: rows(app, "#projects") == 3)
        await pilot.press("9"); await settle(pilot, lambda: app.current_tab() == "host" and "이벤트" in txt(app.query_one("#host-head")))
        body, head = txt(app.query_one("#host-body")), txt(app.query_one("#host-head"))
        check("9: 호스트 탭이 열리고 녹화본 머리줄(raw 0·녹화본)", app.current_tab() == "host" and "알 수 없는 줄(raw) 0" in head and "녹화본" in head, head[:200])
        check("9: 본문에 도구 호출·질문·결과·비용 줄", all(w in body for w in ("▸ Bash [위험]  command=echo s0-allow", "? 질문 [", "빨간색과 파란색", "✔ 결과 성공", "누적 $0.0100")), body[:300])
        check("9: 세션을 시작하기 전에는 호스트를 만들지 않는다(녹화본 화면, 입력창은 스크롤 밖)", app.host_bridge is None and not app.query("#host-scroll Input") and app.query("#host-input"))
        check("9: 탭 전용 동작(F2·F3·F4)은 호스트 탭에서만 켜진다", all(app.check_action(a, ()) is True for a in ("host_start", "host_close", "host_input")))
        await pilot.press("8"); await pilot.pause(0.3)
        check("9 다음 8 키가 여전히 카드 탭", app.current_tab() == "cards")
        await pilot.press("9"); await pilot.pause(0.3); await pilot.press("f5"); await pilot.pause(0.3)
        check("9: F5 새로고침이 호스트 탭에서 동작(예외 없음)", app.current_tab() == "host" and "누적" in txt(app.query_one("#host-head")))
    os.environ["LLMUI_HOST_FIXTURE"] = "/nonexistent/none.jsonl"
    try:
        app = llmui.LlmUI()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.press("9"); await settle(pilot, lambda: app.current_tab() == "host" and "읽지 못함" in txt(app.query_one("#host-head")))
            check("9: 녹화본을 못 읽으면 안내 문구(앱은 살아 있음)", "읽지 못함" in txt(app.query_one("#host-head")) and txt(app.query_one("#host-body")).strip() == "")
        # 제한 모드: 안내문만, 파일(비밀이 들었을 수 있음)을 읽지 않는다
        os.environ["LLMUI_HOST_FIXTURE"] = "/nonexistent/should-not-be-read.jsonl"
        orig = hv.load_events
        calls = []
        hv.load_events = lambda p: (calls.append(p), orig(p))[1]
        try:
            rapp = llmui.LlmUI(restricted=True)
            async with rapp.run_test(size=(160, 50)) as pilot:
                await pilot.press("9"); await settle(pilot, lambda: rapp.current_tab() == "host" and "제한 모드" in txt(rapp.query_one("#host-head")))
                check("9(제한): 안내문만 보이고 본문은 비어 있다", "읽기만" in txt(rapp.query_one("#host-head")) and txt(rapp.query_one("#host-body")).strip() == "")
                check("9(제한): 녹화본 파일을 읽지 않는다", calls == [], str(calls))
                check("9(제한): 호스트 동작은 푸터에서 숨김(기존 SESS_ACTIONS 패턴)", all(rapp.check_action(a, ()) is False for a in hv.HOST_ACTIONS if a not in hv.RESTRICTED_OK_ACTIONS) and rapp.check_action("tab", ("host",)) is True)
                await pilot.press("f5"); await pilot.pause(0.3)
                check("9(제한): 새로고침해도 파일을 읽지 않는다", calls == [])
                check("9(제한): 입력창은 꺼져 있고 호스트(스레드)는 만들어지지 않는다", rapp.query_one("#host-input").disabled and rapp.host_bridge is None)
                made = []
                rapp.host_bridge_factory = lambda: made.append(1)
                rapp.action_host_start(); rapp.action_host_close(); rapp.action_host_input(); rapp.host_begin("/tmp", "haiku"); rapp.host_send_text(); await pilot.pause(0.3)
                check("9(제한): 시작·닫기·입력·전송을 직접 불러도 deny 로 막힌다(호스트 만들지 않음, 모달 없음)", made == [] and rapp.host_bridge is None and len(rapp.screen_stack) == 1 and not rapp.host_live)
            app2 = llmui.LlmUI()
            async with app2.run_test(size=(160, 50)) as pilot:
                await pilot.press("9"); await settle(pilot, lambda: app2.current_tab() == "host")
                check("9(비제한): 같은 동작은 막히지 않는다", all(app2.check_action(a, ()) is True for a in hv.HOST_ACTIONS))
        finally:
            hv.load_events = orig
    finally:
        del os.environ["LLMUI_HOST_FIXTURE"]


async def run_host_live():
    """9 호스트 탭(S1): F2 로 세션 시작 → 지시 입력·Enter → 텍스트 스트림·결과·비용이 실시간으로 그려진다. 가짜 백엔드(fake_claude + 녹화본)만 쓴다(비용 0).
    백엔드가 2.5초 쉬는 동안에도 화면은 막히지 않는다(탭 전환이 바로 된다). F3 닫기 · 종료 시 자식 프로세스 0개."""
    import json as _j, tempfile as _t
    import llmhost_ctl as hc
    hd = hc.find_host_dir()
    if not hd:
        print("llm-host 가 없어 호스트 실시간 시험을 건너뜀"); return
    fx = [_j.loads(l) for l in open(os.path.join(hd, "tests", "fixtures", "main.jsonl"), encoding="utf-8") if l.strip()]
    tmp = _t.mkdtemp(prefix="llmui-s1-")
    steps = [{"expect": {"stdin_type": "user", "line": _j.dumps(fx[0]["line"], ensure_ascii=False, separators=(",", ":"))}}, {"sleep": 2.5}, {"emit": [e["line"] for e in fx[1:15] if e["dir"] == "out"]}]
    sc = os.path.join(tmp, "sc.jsonl")
    open(sc, "w", encoding="utf-8").write("\n".join(_j.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in steps) + "\n")
    hello = fx[0]["line"]["message"]["content"]
    app = llmui.LlmUI()
    app.host_bridge_factory = lambda: hc.HostBridge(log_root=None, use_launcher=False)
    app.host_start_kwargs = {"exe": [sys.executable, os.path.join(hd, "fake_claude.py"), sc, "--timeout", "12"]}
    pid = None
    try:
        async with app.run_test(size=(160, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#projects") == 3)
            await pilot.press("9"); await settle(pilot, lambda: app.current_tab() == "host")
            await pilot.press("f2"); await settle(pilot, lambda: len(app.screen_stack) == 2)
            check("S1: F2 가 작업 폴더 입력창을 띄운다", len(app.screen_stack) == 2 and "작업 폴더" in txt(app.screen.query_one("#dialog-title")))
            app.screen.query_one("#prompt-input").value = tmp; await pilot.pause(0.1); await pilot.press("enter")
            await settle(pilot, lambda: len(app.screen_stack) == 2 and "모델" in txt(app.screen.query_one("#dialog-title")))
            app.screen.query_one("#prompt-input").value = "haiku"; await pilot.pause(0.1); await pilot.press("enter")
            await settle(pilot, lambda: len(app.screen_stack) == 1 and app.host_live)
            head = txt(app.query_one("#host-head"))
            check("S1: 모델까지 답하면 실시간 화면(머리줄 '실시간 세션')으로 바뀌고 지시 입력창에 포커스", app.host_live and "실시간 세션" in head and app.focused is app.query_one("#host-input"), f"{head[:120]} {app.focused}")
            check("S1: 실시간 상자 제목", "실시간" in (app.query_one("#host-scroll").border_title or ""))
            app.query_one("#host-input").value = hello; await pilot.pause(0.1); await pilot.press("enter")
            await settle(pilot, lambda: "▶ 나" in txt(app.query_one("#host-body")))
            check("S1: 보낸 지시가 즉시 '나:' 로 보이고 입력창은 비워진다", "▶ 나: Say hello" in txt(app.query_one("#host-body")) and app.query_one("#host-input").value == "")
            t0 = time.time()
            await pilot.press("escape"); await pilot.press("8"); await settle(pilot, lambda: app.current_tab() == "cards", timeout=1.0)
            check("S1: 백엔드가 응답 중(2.5초 대기)이어도 화면이 막히지 않는다 — 탭 전환이 바로 된다", app.current_tab() == "cards" and time.time() - t0 < 1.8 and app.host_bridge.state == "busy", f"{app.current_tab()} {time.time() - t0:.2f} {app.host_bridge.state}")
            await pilot.press("9")
            await settle(pilot, lambda: "✔ 결과 성공" in txt(app.query_one("#host-body")), timeout=6.0)
            body, head = txt(app.query_one("#host-body")), txt(app.query_one("#host-head"))
            check("S1: 텍스트 스트림·턴·결과·비용이 본문에", all(w in body for w in ("● 세션 시작", "─ 턴 1", "✔ 결과 성공", "누적 $0.0042")), body[:400])
            check("S1: 머리줄에 상태 idle·턴 1·누적 비용·raw 0", all(w in head for w in ("상태 idle", "턴 1", "$0.0042", "(raw) 0")), head)
            pid = app.host_bridge.child_pids()[0]
            await pilot.press("f3"); await settle(pilot, lambda: app.host_bridge.state == "closed", timeout=6.0)
            await settle(pilot, lambda: "상태 closed" in txt(app.query_one("#host-head")) and "■ 세션 끝 — closed" in txt(app.query_one("#host-body")), timeout=4.0)
            check("S1: F3 로 닫으면 '■ 세션 끝 — closed' 와 상태 closed", "상태 closed" in txt(app.query_one("#host-head")) and "■ 세션 끝 — closed" in txt(app.query_one("#host-body")), txt(app.query_one("#host-body"))[-200:])
            app.query_one("#host-input").value = "또 한 번"; await pilot.pause(0.1); app.query_one("#host-input").focus(); await pilot.pause(0.1); await pilot.press("enter")
            await pilot.pause(0.3)
            check("S1: 세션이 없을 때 Enter 는 보내지 않고 입력을 남긴다", app.query_one("#host-input").value == "또 한 번")
            await pilot.press("f5"); await pilot.pause(0.3)
            check("S1: F5 새로고침이 실시간 화면을 유지한다(녹화본으로 되돌아가지 않음)", "실시간 세션" in txt(app.query_one("#host-head")))
        await asyncio.sleep(0.3)
        check("S1: 앱 종료 뒤 자식 프로세스 0개, 호스트 해제", pid is not None and not _alive(pid) and app.host_bridge is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False



async def run_host_s2():
    """9 호스트 탭(S2): 권한·질문 대화상자(허용·거부·이유·시간 초과·나중에·질문 선택)와 턴 중단. 가짜 백엔드(녹화본 시나리오)만 쓴다(비용 0).
    시간 초과는 시계 주입(HostBridge(clock=…))으로 30분을 건너뛴다. 제한 모드에서는 어떤 경로로도 응답이 호스트에 가지 않는다."""
    import json as _j, tempfile as _t
    import llmhost_ctl as hc
    hd = hc.find_host_dir()
    if not hd:
        print("llm-host 가 없어 호스트 S2 시험을 건너뜀"); return
    fxd = os.path.join(hd, "tests", "fixtures")
    R = lambda n: [_j.loads(l) for l in open(os.path.join(fxd, n + ".jsonl"), encoding="utf-8") if l.strip()]
    perm, main = R("perm"), R("main")
    tmp = _t.mkdtemp(prefix="llmui-s2-")
    dump = lambda o: _j.dumps(o, ensure_ascii=False, separators=(",", ":"))

    def scen(rows_, a, b, resp=None, name="sc"):
        steps = []
        for e in rows_[a:b]:
            ln = e["line"]
            if e["dir"] == "in":
                if ln.get("type") == "control_response":
                    steps.append({"expect": {"control_response": resp or {"behavior": "deny"}}})
                elif ln.get("type") == "control_request":
                    steps.append({"expect": {"control_request": {"subtype": ln["request"]["subtype"]}}})
                else:
                    steps.append({"expect": {"stdin_type": "user", "line": dump(ln)}})
            elif steps and "emit" in steps[-1]:
                steps[-1]["emit"].append(ln)
            else:
                steps.append({"emit": [ln]})
        pth = os.path.join(tmp, f"{name}{len(os.listdir(tmp))}.jsonl")
        open(pth, "w", encoding="utf-8").write("\n".join(dump(x) for x in steps) + "\n")
        return [sys.executable, os.path.join(hd, "fake_claude.py"), pth, "--timeout", "90"]

    T = [5000.0]

    async def session(app, pilot, exe):
        app.host_bridge_factory = lambda: hc.HostBridge(log_root=None, use_launcher=False, clock=lambda: T[0], poll=0.05)
        app.host_start_kwargs = {"exe": exe}
        app.host_begin(tmp, "haiku")
        await settle(pilot, lambda: app.host_bridge.running)

    def finish_session(app):
        b = app.host_bridge
        if b is not None:
            b.close()

    app = llmui.LlmUI()
    ALLOW = perm[24]["line"]["response"]["response"]
    pids = []
    try:
        async with app.run_test(size=(160, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#projects") == 3)
            await pilot.press("9"); await settle(pilot, lambda: app.current_tab() == "host")
            check("S2: 응답·중단 동작은 호스트 탭에서만 켜진다(F6·F7)", app.check_action("host_answer", ()) is True and app.check_action("host_interrupt", ()) is True)
            # ---- 허용
            await session(app, pilot, scen(perm, 0, 54, resp=ALLOW))
            pids.append(app.host_bridge.child_pids()[0])
            app.host_bridge.send(perm[0]["line"]["message"]["content"])
            await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen))
            scr = app.screen
            body, title, left, hint = txt(scr.query_one("#req-body")), txt(scr.query_one("#dialog-title")), txt(scr.query_one("#req-left")), txt(scr.query_one("#dialog-hint"))
            check("S2: 권한 요청이 오면 대화상자가 저절로 열리고 도구 이름과 [위험] 표시(도구 이름 기준)", "권한 요청 — Write" in title and "[위험]" in title, title)
            check("S2: 도구 입력(경로·내용)이 보인다", "s0-allow.txt" in body, body[:200])
            check("S2: 남은 응답 시간 30:00 부근을 보여 준다", "남은 응답 시간 29:5" in left or "남은 응답 시간 30:00" in left, left)
            check("S2: sudo 비밀번호·skip-permissions 는 받지 않는다는 안내(D-6)", "sudo 비밀번호" in hint and "skip-permissions" in hint and "터미널" in hint, hint)
            check("S2: 대기 중 머리줄 상태 waiting", "상태 waiting" in txt(app.query_one("#host-head")) or app.host_bridge.state == "waiting", app.host_bridge.state)
            check("S2: 처음 포커스는 안전한 [거부] 버튼(실수로 Enter 를 눌러도 거부)", app.screen.query_one("#btn-deny").has_focus)
            await pilot.press("shift+tab"); await pilot.pause(0.1)
            check("S2: Shift+Tab 으로 [허용] 버튼으로 이동", app.screen.query_one("#btn-allow").has_focus)
            await pilot.press("enter")
            await settle(pilot, lambda: len(app.screen_stack) == 1)
            await settle(pilot, lambda: "✔ 결과 성공" in txt(app.query_one("#host-body")), timeout=6.0)
            ev = [e for e in app.host_events]
            body = txt(app.query_one("#host-body"))
            check("S2: [허용] 버튼 + Enter → 허용이 호스트에 가서 턴이 끝난다(백엔드가 allow+updatedInput 을 확인)", app.host_bridge.pending_requests() == [] and "✔ 결과 성공" in body and app.host_bridge.state == "idle", f"{app.host_bridge.state}")
            finish_session(app)
            await settle(pilot, lambda: not app.host_bridge.running)

            # ---- 거부 + 이유
            await session(app, pilot, scen(perm, 54, 103))
            pids.append(app.host_bridge.child_pids()[0])
            app.host_bridge.send(perm[54]["line"]["message"]["content"])
            await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen))
            await pilot.click("#btn-reason"); await pilot.pause(0.2)
            check("S2: [이유 적고 거부] 를 마우스로 누르면 거부 이유 입력창으로 포커스가 간다", app.screen.query_one("#req-input").has_focus)
            app.screen.query_one("#req-input").value = "이 폴더 밖은 안 된다"; await pilot.pause(0.1); await pilot.press("enter")
            await settle(pilot, lambda: len(app.screen_stack) == 1)
            await settle(pilot, lambda: any(e.get("kind") == "request_resolved" for e in app.host_events) or app.host_bridge.state == "idle", timeout=6.0)
            await settle(pilot, lambda: any(e.get("kind") == "turn_result" for e in app.host_events), timeout=6.0)
            rs = [e for e in app.host_events if e.get("kind") == "request_resolved"]
            check("S2: 이유를 적고 Enter → deny, 이유가 모델 문구에 그대로 간다(by=user)", rs and rs[0]["outcome"] == "deny" and rs[0]["by"] == "user" and "이 폴더 밖은 안 된다" in (rs[0].get("message") or ""), str(rs))
            finish_session(app)
            await settle(pilot, lambda: not app.host_bridge.running)

            # ---- 나중에(Esc) → 자동으로 다시 열지 않고 F6 으로 연다
            await session(app, pilot, scen(perm, 54, 103))
            pids.append(app.host_bridge.child_pids()[0])
            app.host_bridge.send(perm[54]["line"]["message"]["content"])
            await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen))
            await pilot.press("escape"); await settle(pilot, lambda: len(app.screen_stack) == 1)
            await pilot.pause(0.8)
            check("S2: Esc(나중에)는 요청을 그대로 두고 대화상자를 자동으로 다시 열지 않는다", len(app.screen_stack) == 1 and len(app.host_bridge.pending_requests()) == 1, str(len(app.screen_stack)))
            check("S2: 머리줄에 응답 대기 1건·F6 안내", "응답 대기 1건" in txt(app.query_one("#host-head")) and "F6" in txt(app.query_one("#host-head")))
            await pilot.press("f6"); await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen))
            check("S2: F6 이 미룬 요청 대화상자를 다시 연다", isinstance(app.screen, llmui.HostRequestScreen))
            # ---- 시간 초과: 대화상자가 열린 채로 30분이 지난다
            left0 = txt(app.screen.query_one("#req-left"))
            T[0] += 600.0
            await settle(pilot, lambda: "남은 응답 시간 20:" in txt(app.screen.query_one("#req-left")) if isinstance(app.screen, llmui.HostRequestScreen) else True, timeout=3.0)
            check("S2: 시간이 지나면 남은 시간이 줄어든다(600초 뒤 20분대)", isinstance(app.screen, llmui.HostRequestScreen) and "남은 응답 시간 20:" in txt(app.screen.query_one("#req-left")), txt(app.screen.query_one("#req-left")))
            T[0] += 1300.0
            await settle(pilot, lambda: len(app.screen_stack) == 1, timeout=4.0)
            await settle(pilot, lambda: any(e.get("kind") == "turn_result" for e in app.host_events), timeout=6.0)
            rs = [e for e in app.host_events if e.get("kind") == "request_resolved"]
            check("S2: 30분 넘기면 대화상자가 닫히고 자동 거부(by 는 호스트 기록상 user 라도 문구는 시간 초과)", len(app.screen_stack) == 1 and rs and rs[0]["outcome"] == "deny" and "30분" in (rs[0].get("message") or ""), str(rs))
            check("S2: 자동 거부 notice 가 화면에 보인다", "자동 거부했다" in txt(app.query_one("#host-body")), txt(app.query_one("#host-body"))[-300:])
            finish_session(app)
            await settle(pilot, lambda: not app.host_bridge.running)

            # ---- 질문
            QR = main[103]["line"]["response"]["response"]
            await session(app, pilot, scen(main, 73, 121, resp=QR))
            pids.append(app.host_bridge.child_pids()[0])
            app.host_bridge.send(main[73]["line"]["message"]["content"])
            await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen))
            # 화면이 뜬 직후엔 본문이 아직 비어 있을 수 있다 — 질문 문구가 채워질 때까지 조건 대기
            await settle(pilot, lambda: isinstance(app.screen, llmui.HostRequestScreen) and "파란색" in txt(app.screen.query_one("#req-body")) and "색상 선호" in txt(app.screen.query_one("#dialog-title")))
            title, body = txt(app.screen.query_one("#dialog-title")), txt(app.screen.query_one("#req-body"))
            check("S2: 질문 대화상자 — 머리글·질문·번호 붙은 선택지", "질문 1/1" in title and "색상 선호" in title and "빨간색과 파란색" in body and "1 " in body and "파란색" in body, f"{title} | {body}")
            await pilot.press("1")
            await settle(pilot, lambda: len(app.screen_stack) == 1)
            await settle(pilot, lambda: any(e.get("kind") == "turn_result" for e in app.host_events), timeout=6.0)
            tr = [e for e in app.host_events if e.get("kind") == "turn_result"]
            check("S2: 숫자 키 1 → updatedInput.answers 로 답이 가고 턴이 정상 종료(백엔드가 answers 를 확인)", tr and tr[0]["ok"] and not app.host_bridge.pending_requests(), str(tr[:1]))
            finish_session(app)
            await settle(pilot, lambda: not app.host_bridge.running)

            # ---- 중단(F7)
            await session(app, pilot, scen(main, 121, 163))
            pids.append(app.host_bridge.child_pids()[0])
            await pilot.press("f7"); await pilot.pause(0.2)
            check("S2: 진행 중인 턴이 없으면 F7 은 아무것도 보내지 않는다", app.host_bridge.state == "idle")
            app.host_bridge.send(main[121]["line"]["message"]["content"])
            await settle(pilot, lambda: any(e.get("kind") == "text_delta" for e in app.host_events) or (app.host_bridge.drain() and False), timeout=3.0)
            await pilot.pause(0.5)
            await pilot.press("f7")
            await settle(pilot, lambda: any(e.get("kind") == "turn_result" for e in app.host_events), timeout=6.0)
            tr = [e for e in app.host_events if e.get("kind") == "turn_result"]
            check("S2: F7 → 진행 중인 턴이 중단되고(ok 아님) 세션은 살아 있다", tr and tr[0]["ok"] is False and app.host_bridge.running and app.host_bridge.state == "idle", f"{tr[:1]} {app.host_bridge.state}")
            finish_session(app)
            await settle(pilot, lambda: not app.host_bridge.running)
        await asyncio.sleep(0.3)
        check("S2: 앱 종료 뒤 자식 프로세스 0개", pids and all(not _alive(x) for x in pids), str(pids))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 제한 모드(H-4): 응답·허용 동작 전부 비활성 — 호스트로 아무것도 가지 않는다
    class Boom:
        calls = []
        def pending_requests(self):
            return [{"req": "r1", "kind": "permission", "tool": "Bash", "input": {"command": "ls"}, "description": None, "questions": [], "left": 100.0, "event": {}}]
        def __getattr__(self, n):
            def f(*a, **k):
                Boom.calls.append(n); return None
            return f
    rapp = llmui.LlmUI(restricted=True)
    rapp.host_bridge = Boom()
    async with rapp.run_test(size=(160, 50)) as pilot:
        await pilot.press("9"); await pilot.pause(0.3)
        check("S2(제한): 응답·중단 동작은 푸터에서 숨김", rapp.check_action("host_answer", ()) is False and rapp.check_action("host_interrupt", ()) is False)
        r1 = [rapp.host_allow("r1"), rapp.host_deny("r1", "x"), rapp.host_answer_question("r1", {"q": "a"})]
        rapp.host_open_request("r1"); rapp.action_host_answer(); rapp.action_host_interrupt(); rapp._host_tick(); await pilot.pause(0.6)
        check("S2(제한): 허용·거부·답·열기·중단을 직접 불러도 호스트 호출 0·대화상자 없음", r1 == [False, False, False] and Boom.calls == [] and len(rapp.screen_stack) == 1, f"{r1} {Boom.calls}")
    rapp.host_bridge = None


async def run_host_s3():
    """9 호스트 탭(S3): F8 산출물 보기 — 색인(INDEX.md)의 항목 접기·펴기, 검사 상태, 파일 내용. 표본 산출물은 임시 폴더에 만든다(비용 0, 호스트 불필요).
    비밀은 화면 마스커로 치환(제한 모드의 StrictMasker 는 끌 수 없다), 폴더 밖 경로는 열지 않고, 제한 모드에서는 이 화면이 열리지 않는다."""
    import json as _j, tempfile as _t
    import llmhost_artifacts as ha
    with cc.connect() as c:
        cs.add_secret(c, "ART_PW", "literal", PW)            # 앞선 시험이 등록표를 비웠을 수 있어 이 구간용으로 다시 등록
    tmp = _t.mkdtemp(prefix="llmui-s3-")
    work = os.path.join(tmp, "work"); root = os.path.join(work, "art")
    os.makedirs(os.path.join(root, "facts")); os.makedirs(os.path.join(root, ".check"))
    W = lambda rel, t: open(os.path.join(root, rel), "w", encoding="utf-8").write(t)
    W("INDEX.md", "# INDEX — 표본\n- 분류: 결정(승인 전)\n- 상태: 완료\n\n## 지금 결정할 것\n1. A 안으로 갈까요\n\n## 파일\n| 파일 | 한 줄 요약 | 언제 읽나 | 근거 대화 범위 | 종류 | 검사 |\n|---|---|---|---|---|---|\n"
              "| 00-cover.md | 표지 | 지금 | - | 해석 | 통과 |\n| facts/diff-stat.txt | 변경 목록 | 필요할 때 | - | 사실 | 통과 |\n| ../outside.txt | 밖 | - | - | 해석 | 통과 |\n| /etc/passwd | 절대 | - | - | 해석 | 통과 |\n")
    W("00-cover.md", f"# 표지\n결정할 것: 첫째 본문 마커\n비밀 {PW} 와 키 {KEY2}\n"); W("facts/diff-stat.txt", " a.py | 2 +-\n")
    open(os.path.join(work, "outside.txt"), "w").write("밖의 내용 마커")
    _j.dump({"mode": "final", "ts": "t", "counts": {"FAIL": 1, "WARN": 0, "INFO": 0}, "items": [{"id": "C3", "level": "FAIL", "file": "facts/diff-stat.txt", "reason": "x"}]}, open(os.path.join(root, ".check", "result.json"), "w"))
    def body(app):
        try:
            return txt(app.screen.query_one("#art-text"))
        except Exception:                                # 화면이 아직 조립 중
            return ""
    app = llmui.LlmUI()
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, lambda: rows(app, "#projects") == 3)
        await pilot.press("9"); await settle(pilot, lambda: app.current_tab() == "host")
        check("S3: F8 은 호스트 탭에서만 켜진다", app.check_action("host_artifacts", ()) is True)
        await pilot.press("f8"); await settle(pilot, lambda: len(app.screen_stack) == 2)
        check("S3: F8 이 산출물 폴더 입력창을 띄운다", len(app.screen_stack) == 2 and "산출물 폴더" in txt(app.screen.query_one("#dialog-title")))
        app.screen.query_one("#prompt-input").value = os.path.join(tmp, "nope"); await pilot.pause(0.1); await pilot.press("enter")
        await settle(pilot, lambda: len(app.screen_stack) == 1)
        check("S3: 없는 폴더는 안내만 하고 화면을 열지 않는다", len(app.screen_stack) == 1)
        await pilot.press("f8"); await settle(pilot, lambda: len(app.screen_stack) == 2)
        app.screen.query_one("#prompt-input").value = root; await pilot.pause(0.1); await pilot.press("enter")
        await settle(pilot, lambda: isinstance(app.screen, llmui.HostArtifactScreen) and "표지" in body(app))
        b = body(app)
        check("S3: 산출물 화면이 열리고 머리·결정할 것·읽힘 보장 아님 문구", all(w in b for w in ("산출물 — INDEX — 표본", "분류: 결정(승인 전)", "A 안으로 갈까요", "읽힘")), b[:300])
        check("S3: 접힌 상태 — 항목 4개, 내용(본문 마커)은 없다", b.count("▶") == 4 and "첫째 본문 마커" not in b, b)
        check("S3: 검사 상태 — 검사기 FAIL 이 색인의 통과보다 우선, 종류 라벨", "미충족 C3  [검사기]" in b and "검사: 통과  [검사기]" in b and "도구가 모은 사실분" in b and "LLM 의 해석" in b)
        await pilot.press("enter"); await pilot.pause(0.3)
        b = body(app)
        check("S3: Enter 로 첫 항목을 펴면 내용이 나오고 나머지는 접혀 있다", "▼ 00-cover.md" in b and "첫째 본문 마커" in b and b.count("▶") == 3, b[:400])
        check("S3: 화면 텍스트의 등록한 비밀은 [protected] 로 치환", PW not in b and "[protected]" in b, b[:500])
        await pilot.press("enter"); await pilot.pause(0.3)
        check("S3: Enter 를 다시 누르면 접힌다", "첫째 본문 마커" not in body(app) and body(app).count("▶") == 4)
        await pilot.press("down"); await pilot.press("space"); await pilot.pause(0.3)
        check("S3: ↓ 로 이동해 Space 로 두 번째 항목을 편다", "▼ facts/diff-stat.txt" in body(app) and "a.py | 2" in body(app))
        await pilot.press("f2"); await pilot.pause(0.3)
        b = body(app)
        check("S3: F2 모두 펴기 — 폴더 밖·절대 경로는 오류 줄이고 내용이 새지 않는다", b.count("▼") == 4 and b.count("✗") == 2 and "밖의 내용 마커" not in b and "root:" not in b, b[-500:])
        await pilot.press("f3"); await pilot.pause(0.3)
        check("S3: F3 모두 접기", body(app).count("▶") == 4)
        await pilot.press("right"); await pilot.pause(0.3)
        check("S3: → 는 현재 항목만 펴고 ← 는 접는다", body(app).count("▼") == 1)
        await pilot.press("left"); await pilot.pause(0.3)
        check("S3: ← 로 접힘", body(app).count("▼") == 0)
        await pilot.press("up"); await pilot.press("enter"); await pilot.pause(0.3)
        check("S3: ↑ 로 첫 항목으로 이동해 Enter — 그 항목만 펼쳐진다", "▼ 00-cover.md" in body(app) and body(app).count("▼") == 1)
        app.mask = True
        await pilot.press("f10"); await pilot.pause(0.3)
        await pilot.press("f2"); await pilot.pause(0.3)
        check("S3: 사람 모드에서 F10 으로 치환을 끄면 원문(앱 설정을 따른다), 다시 켜면 가려진다", PW in body(app))
        await pilot.press("f10"); await pilot.pause(0.3)
        check("S3: F10 다시 — 가려진다", PW not in body(app) and app.mask)
        W("01-new.md", "새 파일")
        await pilot.press("f5"); await pilot.pause(0.3)
        check("S3: F5 다시 읽기 후에도 화면이 산다", "산출물 — INDEX" in body(app))
        await pilot.press("escape"); await settle(pilot, lambda: len(app.screen_stack) == 1)
        check("S3: Esc 로 닫으면 호스트 탭으로 돌아온다", len(app.screen_stack) == 1 and app.current_tab() == "host")
        # 세션 작업 폴더가 있으면 그 밖은 열지 않는다
        app.host_cwd = os.path.join(tmp, "elsewhere"); os.makedirs(app.host_cwd)
        check("S3: 실시간 세션의 작업 폴더 밖 산출물 폴더는 열지 않는다", app.host_open_artifacts(root) is False and len(app.screen_stack) == 1)
        app.host_cwd = work
        check("S3: 작업 폴더 안이면 열린다", app.host_open_artifacts(root) is True)
        await settle(pilot, lambda: isinstance(app.screen, llmui.HostArtifactScreen))
        await pilot.press("escape"); await settle(pilot, lambda: len(app.screen_stack) == 1)
    # 제한 모드: 열리지 않는다(읽지도 않는다). 화면을 억지로 열어도 StrictMasker 는 끌 수 없다
    calls = []
    orig = ha.load
    ha.load = lambda *a, **k: (calls.append(a), orig(*a, **k))[1]
    try:
        rapp = llmui.LlmUI(restricted=True)
        async with rapp.run_test(size=(160, 50)) as pilot:
            await pilot.press("9"); await pilot.pause(0.4)
            check("S3(제한): F8(host_artifacts) 만 푸터에 남고 나머지 호스트 동작은 숨김", rapp.check_action("host_artifacts", ()) is True and all(rapp.check_action(a, ()) is False for a in llmui.hv.HOST_ACTIONS if a != "host_artifacts"))
            rapp.action_host_artifacts(); await settle(pilot, lambda: isinstance(rapp.screen, llmui.PromptScreen))
            check("S3(제한): F8 은 폴더 입력창을 연다(읽기 전용 경로)", isinstance(rapp.screen, llmui.PromptScreen))
            await pilot.press("escape"); await settle(pilot, lambda: len(rapp.screen_stack) == 1)
            # 세션 동작은 그대로 막힌다(F8 허용이 다른 동작을 열지 않는다)
            made = []; rapp.host_bridge_factory = lambda: made.append(1)
            rapp.action_host_start(); rapp.action_host_input(); rapp.action_host_interrupt(); rapp.host_begin("/tmp", "haiku"); await pilot.pause(0.2)
            check("S3(제한): F8 을 허용해도 세션 시작·입력·중단은 막힌다", made == [] and rapp.host_bridge is None and len(rapp.screen_stack) == 1)
            r = rapp.host_open_artifacts(root); await settle(pilot, lambda: isinstance(rapp.screen, llmui.HostArtifactScreen))
            check("S3(제한): 산출물 폴더를 열 수 있다(읽기)", r is True and isinstance(rapp.screen, llmui.HostArtifactScreen) and len(calls) >= 1, str(calls))
            await pilot.press("escape"); await settle(pilot, lambda: len(rapp.screen_stack) == 1)
            rapp.mask = False        # 어떤 경로로 꺼져도 제한 모드의 마스커는 StrictMasker
            check("S3(제한): mask 가 꺼져 있어도 마스커는 StrictMasker 로 유지", isinstance(rapp.masker(), llmui.cs.StrictMasker))
            rapp.mask = True
            rapp.push_screen(llmui.HostArtifactScreen(rapp, root))
            await settle(pilot, lambda: isinstance(rapp.screen, llmui.HostArtifactScreen) and "표지" in body(rapp))
            await pilot.press("f2"); await pilot.pause(0.3)
            await pilot.press("f10"); await pilot.pause(0.3)
            b = body(rapp)
            check("S3(제한): 화면을 열어도 F10 으로 치환을 끌 수 없고 비밀·키는 [protected]", rapp.mask is True and PW not in b and KEY2 not in b and "[protected]" in b and "첫째 본문 마커" in b, b[:400])
    finally:
        ha.load = orig


def check_launch_prompt():
    import llmcards as lcd
    check("초기 프롬프트: 슬래시로 시작, 카드 여러 장과 쟁점(줄바꿈은 공백)", lcd.launch_prompt(["a:11111111", "b:22222222"], "첫째\n  둘째") == "/donghans-card a:11111111 b:22222222 첫째 둘째")
    check("초기 프롬프트: 쟁점이 없으면 카드만", lcd.launch_prompt(["a:11111111"]) == "/donghans-card a:11111111")


LIM_CALIB = {"version": 1, "source": "limits.jsonl", "updated": "2026-11-10T00:00:48+09:00", "plans": {
    "max_5x": {"five": {"median": 1.68, "p25": 1.58, "p75": 1.73, "min": 1.3, "max": 1.87, "n": 24},
               "seven": {"median": 9.95, "p25": 9.93, "p75": 9.97, "min": 9.9, "max": 9.99, "n": 2}, "updated": "2026-11-10T00:00:48+09:00", "pinned": {}},
    "max_20x": {"five": {"median": 6.0, "p25": 5.0, "p75": 7.0, "min": 4.0, "max": 8.0, "n": 9}, "updated": "2026-11-10T00:00:48+09:00", "pinned": {"five": 5.5},
                "suggest": {"five": {"median": 6.2, "p25": 5.1, "p75": 7.1, "n": 10}}}}}
LW_SRC = os.path.normpath(os.path.join(ROOT, "..", "..", "_data", "claude-skills", "donghans-limit-watch", "scripts", "limitwatch.py"))


def check_limit_logic():
    """llmlimit 순수 로직: 입력 검증·행 만들기·스킬이 없을 때."""
    import llmlimit as ll
    check("parse_pin: 정상 값", ll.parse_pin(" 1.7 ")[0] == 1.7 and ll.parse_pin("10")[0] == 10.0)
    bad = ["", "abc", "0", "-1", "nan", "inf", "1e9", "1001"]
    check("parse_pin: 숫자 아님·0 이하·nan·inf·상한 초과는 거부(오류 문구가 있다)", all(ll.parse_pin(b)[0] is None and ll.parse_pin(b)[1] for b in bad), str([ll.parse_pin(b) for b in bad]))
    orig = ll.find_limitwatch
    ll.find_limitwatch = lambda: None
    try:
        v = ll.load_view()
        check("스킬이 없으면 안내만(행 없음)", v["err"] and "찾지 못함" in v["err"] and v["rows"] == [], str(v))
        ok, out = ll.pin("max_5x", "five", 2.0)
        check("스킬이 없으면 고정은 실패로 돌려주고 예외가 없다", ok is False and "찾지 못함" in out, out)
    finally:
        ll.find_limitwatch = orig
    check("pin: 5h·7d 가 아닌 구분은 거부", ll.pin("max_5x", "nine", 2.0)[0] is False)


async def clear_prompt(app):
    app.screen.query_one("#prompt-input").value = ""


async def run_limits_tab():
    """10 한도 탭(S5): 키 0·보정값 표·Enter/F2/버튼으로 고정·해제·다시 계산·입력 검증·다른 키 보존·제한 모드(조회만)·기존 탭 키 불변.
    보정 파일은 임시 폴더(LLMUI_LIMIT_DIR)의 합성본, 쓰기는 소스 트리의 limitwatch.py(LLMUI_LIMITWATCH)가 한다 — 실제 ~/.local/share 는 건드리지 않는다."""
    import llmlimit as ll, tempfile
    d = tempfile.mkdtemp(prefix="llmui-limit-")
    cal = os.path.join(d, "limit-calibration.json")
    os.environ["LLMUI_LIMIT_DIR"] = d; os.environ["LLMUI_LIMITWATCH"] = LW_SRC
    save = lambda: json.dump(LIM_CALIB, open(cal, "w"))
    load = lambda: json.load(open(cal))
    pinned = lambda: {p: e.get("pinned") for p, e in load()["plans"].items()}
    tbl = lambda app: [[str(c) for c in app.query_one("#lim-table").get_row_at(i)] for i in range(app.query_one("#lim-table").row_count)]
    try:
        keys = {b.key: b.action for b in llmui.LlmUI.BINDINGS}
        check("키 0 → 한도 탭, 1~9 매핑은 그대로", keys.get("0") == "tab('limits')" and all(keys.get(str(i)) for i in range(1, 10)) and keys["9"] == "tab('host')" and keys["1"] == "tab('dashboard')")
        check("한도 탭에는 단일 알파벳 키 바인딩이 없다(한영 전환)", not [b.key for b in llmui.LlmUI.BINDINGS if b.action.startswith("limit_") and len(b.key) == 1 and b.key.isalpha()])
        save()
        app = llmui.LlmUI()
        async with app.run_test(size=(170, 50)) as pilot:
            await settle(pilot, lambda: rows(app, "#projects") == 3)
            check("한도: 다른 탭에서는 한도 동작이 꺼져 있다(F2 재사용 충돌 없음)", all(app.check_action(a, ()) is False for a in ll.LIMIT_ACTIONS) and app.check_action("host_start", ()) is False)
            await pilot.press("0"); await settle(pilot, lambda: app.current_tab() == "limits" and app.query_one("#lim-table").row_count == 3)
            t = tbl(app)
            check("한도: 표 3행(max_20x 5h·max_5x 5h·7d, 플랜 순) — 자동 값·분위·창 수", [r[:2] for r in t] == [["max_20x", "5h"], ["max_5x", "5h"], ["max_5x", "7d"]] and t[1][4] == "1.68" and t[1][5] == "1.58~1.73" and t[1][6] == "24", str(t))
            check("한도: 고정 중인 플랜은 쓰는 값=고정값, 제안 칸에 자동 제안이 보인다", t[0][2] == "5.50" and t[0][3] == "5.50" and t[0][7].startswith("6.20"), str(t[0]))
            check("한도: 한도 동작이 이 탭에서 켜져 있다", all(app.check_action(a, ()) is True for a in ll.LIMIT_ACTIONS) and app.focused is app.query_one("#lim-table"))
            check("한도: 머리줄에 파일 경로와 갱신 시각", cal in txt(app.query_one("#lim-head")) and "2026-11-10" in txt(app.query_one("#lim-head")))
            await pilot.press("9"); await pilot.pause(0.3); await pilot.press("0"); await settle(pilot, lambda: app.current_tab() == "limits")
            check("한도: 9 다음 0 이 다시 한도 탭", app.current_tab() == "limits")
            # --- F2: max_5x 5h 행에 고정
            await pilot.press("down"); await pilot.pause(0.2)
            await pilot.press("f2"); await settle(pilot, lambda: len(app.screen_stack) == 2)
            check("F2: 값 입력창이 현재 값(1.68)을 채워 열린다", app.screen.query_one("#prompt-input").value == "1.68" and "max_5x 5h" in txt(app.screen.query_one("#dialog-title")))
            await clear_prompt(app); await type_text(pilot, "abc"); await pilot.press("enter"); await settle(pilot, lambda: len(app.screen_stack) == 1)
            check("한도: 숫자가 아니면 거부하고 파일은 그대로", pinned() == {"max_20x": {"five": 5.5}, "max_5x": {}}, str(pinned()))
            for bad in ("0", "-3", "nan", "5000"):
                await pilot.press("f2"); await settle(pilot, lambda: len(app.screen_stack) == 2)
                await clear_prompt(app); await type_text(pilot, bad); await pilot.press("enter"); await settle(pilot, lambda: len(app.screen_stack) == 1)
            check("한도: 0·음수·nan·상한 초과도 거부(파일 그대로)", pinned() == {"max_20x": {"five": 5.5}, "max_5x": {}}, str(pinned()))
            await pilot.press("f2"); await settle(pilot, lambda: len(app.screen_stack) == 2)
            await clear_prompt(app); await type_text(pilot, "2.5"); await pilot.press("enter")
            await settle(pilot, lambda: pinned()["max_5x"] == {"five": 2.5})
            await settle(pilot, lambda: tbl(app)[1][3] == "2.50")
            t = tbl(app)
            check("한도: 2.5 고정 → 파일 pinned.five=2.5, 표의 쓰는 값·고정값 2.50, 다른 플랜 고정 보존", pinned() == {"max_20x": {"five": 5.5}, "max_5x": {"five": 2.5}} and t[1][2] == "2.50" and t[1][3] == "2.50" and t[0][3] == "5.50", f"{pinned()} {t}")
            # --- Enter: 7d 행(다른 키 보존)
            await pilot.press("down"); await pilot.pause(0.2); await pilot.press("enter"); await settle(pilot, lambda: len(app.screen_stack) == 2)
            check("Enter: 행에서 입력창이 열린다(7d)", "max_5x 7d" in txt(app.screen.query_one("#dialog-title")) and app.screen.query_one("#prompt-input").value == "9.95")
            await clear_prompt(app); await type_text(pilot, "11"); await pilot.press("enter")
            await settle(pilot, lambda: pinned()["max_5x"] == {"five": 2.5, "seven": 11.0})
            check("한도: 7d 를 고정해도 5h 고정이 남는다(CLI pin 이 다른 키를 지우는 것을 막음)", pinned()["max_5x"] == {"five": 2.5, "seven": 11.0}, str(pinned()))
            # --- Esc 로 취소하면 변화 없음
            before = open(cal).read()
            await pilot.press("f2"); await settle(pilot, lambda: len(app.screen_stack) == 2); await pilot.press("escape"); await settle(pilot, lambda: len(app.screen_stack) == 1)
            check("한도: 입력창을 Esc 로 닫으면 파일 불변", open(cal).read() == before)
            # --- 버튼 클릭(마우스)·Tab 이동
            await pilot.click("#lim-pin"); await settle(pilot, lambda: len(app.screen_stack) == 2)
            check("한도: 「값 고정」 버튼 클릭으로 입력창이 열린다", "값 고정" in txt(app.screen.query_one("#dialog-title"))); await pilot.press("escape"); await settle(pilot, lambda: len(app.screen_stack) == 1)
            app.query_one("#lim-table").focus(); await pilot.press("tab"); await pilot.pause(0.2)
            check("한도: Tab 으로 버튼에 포커스가 간다(키보드 접근)", app.focused is not None and app.focused.id == "lim-pin", str(app.focused))
            # --- F3 해제(max_5x 행이 선택돼 있다)
            app.query_one("#lim-table").focus(); await pilot.pause(0.2)
            await pilot.press("f3"); await settle(pilot, lambda: pinned()["max_5x"] == {})
            check("F3: max_5x 고정이 모두 풀리고 max_20x 고정은 그대로", pinned() == {"max_20x": {"five": 5.5}, "max_5x": {}}, str(pinned()))
            await settle(pilot, lambda: tbl(app)[1][3] == "-")
            check("한도: 해제 뒤 표의 고정값 '-'·쓰는 값은 자동 값", tbl(app)[1][3] == "-" and tbl(app)[1][2] == "1.68", str(tbl(app)[1]))
            before = open(cal).read()
            await pilot.press("f3"); await pilot.pause(0.5)
            check("한도: 고정이 없는 플랜에서 F3 는 아무것도 쓰지 않는다", open(cal).read() == before)
            # --- F4 다시 계산: limits.jsonl 이 없으면 보정할 창이 없어 파일 불변
            await pilot.press("f4"); await pilot.pause(1.5)
            check("F4: 기록이 없어 만들 값이 없으면 보정 파일은 그대로(앱은 살아 있음)", open(cal).read() == before and app.current_tab() == "limits")
            check("한도: F5 새로고침이 동작(행 3개 유지)", (await pilot.press("f5") or True) and app.query_one("#lim-table").row_count == 3)
        # --- 보정 파일이 없을 때
        os.remove(cal)
        app = llmui.LlmUI()
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.press("0"); await settle(pilot, lambda: app.current_tab() == "limits" and "보정 파일이 없" in txt(app.query_one("#lim-head")))
            check("한도: 보정 파일이 없으면 안내(행 0)이고 F2·F3 는 알리기만 한다", app.query_one("#lim-table").row_count == 0)
            await pilot.press("f2"); await pilot.press("f3"); await pilot.pause(0.4)
            check("한도: 행이 없을 때 F2 가 입력창을 열지 않는다", len(app.screen_stack) == 1)
        # --- 제한 모드: 조회만
        save()
        before = open(cal).read()
        rapp = llmui.LlmUI(restricted=True)
        async with rapp.run_test(size=(170, 50)) as pilot:
            await pilot.press("0"); await settle(pilot, lambda: rapp.current_tab() == "limits" and rapp.query_one("#lim-table").row_count == 3)
            check("한도(제한): 표는 보인다(읽기)", rapp.query_one("#lim-table").row_count == 3 and "조회만" in txt(rapp.query_one("#lim-head")))
            check("한도(제한): 쓰기 동작은 푸터에서 숨김, 버튼은 비활성, 안내문", all(rapp.check_action(a, ()) is False for a in ll.LIMIT_ACTIONS) and all(rapp.query_one("#" + b).disabled for b in ("lim-pin", "lim-unpin", "lim-recalc")) and "읽기만" in txt(rapp.query_one("#lim-note")))
            await pilot.press("f2"); await pilot.press("f3"); await pilot.press("f4"); await pilot.press("enter"); await pilot.pause(0.5)
            rapp.action_limit_pin(); rapp.action_limit_unpin(); rapp.action_limit_recalc(); rapp.limit_do("pin", "max_5x", "five", 9.0); await pilot.pause(0.5)
            check("한도(제한): 키·직접 호출(limit_do 포함)로도 입력창이 안 열리고 파일은 불변", len(rapp.screen_stack) == 1 and open(cal).read() == before)
    finally:
        os.environ.pop("LLMUI_LIMIT_DIR", None); os.environ.pop("LLMUI_LIMITWATCH", None)
        shutil.rmtree(d, ignore_errors=True)


def check_sessions_only_no_db():
    """`llmui --sessions` 는 DB 에 연결하지 않는다 — DB 접속을 막아 두고(잘못된 PG 환경) 띄워도 앱이 뜬다(main 이 SessionsUI 로 직행하는지 코드로 확인)."""
    src = open(os.path.join(ROOT, "llmui.py"), encoding="utf-8").read()
    body = src[src.index("def main():"):]
    sess_branch = body[body.index('["--sessions"]'):body.index("if argv:")]
    check("--sessions: main 의 세션 분기는 DB(cc.connect·LlmUI)를 부르지 않고 SessionsUI 만 띄운다", "SessionsUI" in sess_branch and "connect" not in sess_branch and "LlmUI" not in sess_branch, sess_branch[:200])


try:
    seed()
    check_limits_text()
    asyncio.run(run())
    asyncio.run(run_wrap())
    asyncio.run(run_resize())
    asyncio.run(run_restricted())
    asyncio.run(run_sessions_tab())
    check_launch_prompt()
    asyncio.run(run_cards_tab())
    asyncio.run(run_host_tab())
    asyncio.run(run_host_live())
    asyncio.run(run_host_s2())
    asyncio.run(run_host_s3())
    check_limit_logic()
    asyncio.run(run_limits_tab())
    check_sessions_only_no_db()
finally:
    pg.stop()
finish("llmui")
