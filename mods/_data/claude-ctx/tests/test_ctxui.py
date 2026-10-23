#!/usr/bin/env python3
"""ctxui 시험(Textual Pilot + 임시 Postgres): 5개 탭 · 검색/필터 · 대화 보기 · 치환 켬/끔 · 대조 · 비밀 추가/끄기/삭제/값 보기 · 후보 승인/무시.
필요: psycopg + textual 이 있는 python 과 postgres 17 바이너리. 없으면 건너뛴다."""
import asyncio, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
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
import ctx_secrets as cs, ctxdata as cd, claude_ctx as cc, ctxui

A, B = "https://github.com/x/alpha", "https://github.com/x/beta"
PW, KEY = "hunter2-pass", "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"


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
    for rid, sid, host, ts, model, cost in [("u1", "aaaa0001", "h1", "2026-10-01T01:00:00Z", "claude-sonnet-5-5", 1.0), ("u2", "aaaa0001", "h1", "2026-10-02T01:00:00Z", "claude-haiku-5-5", 0.5),
                                            ("u3", "bbbb0001", "h2", "2026-10-03T01:00:00Z", "claude-sonnet-5-5", 2.0)]:
        conn.execute("INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens) VALUES (%s,%s,%s,%s,%s,%s,100,10,1000,50)",
                     (rid, host, ts, sid, model, cost))
    conn.commit(); conn.close()


def txt(w):
    r = w.render()
    return getattr(r, "plain", None) or str(r)


def all_open_ok(scr):
    return scr.all_open


def sess_txt(scr):
    """대화 화면의 머리글 + 모든 메시지 + 상태줄 글자."""
    return "\n".join([txt(scr.query_one("#sess-head"))] + [txt(v) for v in scr.query(ctxui.MsgView)] + [txt(scr.query_one("#sess-state"))])


async def settle(pilot, cond, timeout=8.0):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        await pilot.pause(0.15)
    return cond()


def rows(app, sel):
    return app.query_one(sel).row_count


async def submit(pilot, widget):
    """위젯에 포커스를 주고 반영될 때까지 기다린 뒤 Enter(포커스 직후 바로 누르면 이전 위젯이 받는다)."""
    widget.focus(); await pilot.pause(0.25); await pilot.press("enter")


async def type_text(pilot, s):
    for ch in s:
        await pilot.press(ch)


async def run():
    app = ctxui.CtxUI()
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
        check("개요 Enter: 그 저장소 메시지만 검색(최대 4건)", 1 <= rows(app, "#results") <= 4, str(rows(app, "#results")))

        # --- 검색
        await pilot.press("2"); await pilot.pause(0.3)
        app.query_one("#repo").value = ""
        q = app.query_one("#q"); q.value = "배포"; q.focus(); await pilot.pause(0.2)
        await pilot.press("enter"); await settle(pilot, lambda: rows(app, "#results") == 6)
        check("검색: '배포' 6건(프롬프트·응답)", rows(app, "#results") == 6, str(rows(app, "#results")))
        await pilot.press("f2"); await pilot.pause(0.2)
        await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") == 4)
        check("F2: 사용자 발언만 4건", rows(app, "#results") == 4 and "사용자만" in txt(app.query_one("#sstate")), str(rows(app, "#results")))
        await pilot.press("f2"); await pilot.pause(0.1)
        q.value = "금요일|월요일"; await pilot.press("f3"); await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") == 4)
        check("F3: 정규식 검색", rows(app, "#results") == 4 and "정규식: 켜짐" in txt(app.query_one("#sstate")), str(rows(app, "#results")))
        q.value = "([a-"; await submit(pilot, q); await pilot.pause(0.5)
        check("잘못된 정규식은 앱이 죽지 않고 이전 결과 유지, 대화 화면이 열리지 않음", app.is_running and rows(app, "#results") == 4 and not isinstance(app.screen, ctxui.SessionScreen))
        await pilot.press("f3"); q.value = "금요일"; await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") >= 1)
        # 일수 필터
        app.query_one("#days").value = "1"; await submit(pilot, q); await pilot.pause(0.6)
        check("기간(일) 필터: 오래된 데이터는 제외", rows(app, "#results") == 0, str(rows(app, "#results")))
        app.query_one("#days").value = ""
        # 대화 보기
        q.value = "금요일"; await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") >= 1)
        await submit(pilot, app.query_one("#results")); await pilot.pause(0.8)
        check("Enter: 앞뒤 대화 화면이 열림", isinstance(app.screen, ctxui.SessionScreen))
        body = sess_txt(app.screen)
        check("대화 화면: 세션 정보와 메시지", "@h" in body and "금요일" in body, body[:200])
        await pilot.press("escape"); await pilot.pause(0.3)
        check("Esc: 대화 화면이 닫힘", not isinstance(app.screen, ctxui.SessionScreen))

        # --- 치환
        with cc.connect() as c:
            cs.add_secret(c, "NAS_PW", "literal", PW)
        q.value = "설정"; await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") >= 1)
        first = app.query_one("#results").get_row_at(0)
        check("치환 켜짐: 결과에 비밀이 [protected]", PW not in str(first[-1]) and "[protected]" in str(first[-1]), str(first))
        await submit(pilot, app.query_one("#results")); await pilot.pause(0.8)
        check("치환 켜짐: 대화 화면에도 [protected]", PW not in sess_txt(app.screen) and "[protected]" in sess_txt(app.screen))
        await pilot.press("m"); await pilot.pause(0.6)
        check("대화 화면 m: 치환 끄면 원문이 보임(경고 표시)", PW in sess_txt(app.screen) and "꺼짐" in sess_txt(app.screen))
        await pilot.press("m"); await pilot.pause(0.3); await pilot.press("escape"); await pilot.pause(0.3)
        check("m 으로 다시 켬", app.mask)

        # --- 대조
        await pilot.press("3"); await pilot.pause(0.3)
        ph = app.query_one("#phrase"); ph.value = "배포"; await submit(pilot, ph); await settle(pilot, lambda: rows(app, "#vrepos") == 3)
        check("대조: 사용자 발언을 저장소 3곳으로 묶음(4건)", rows(app, "#vrepos") == 3 and "4건" in app.query_one("#vrepos").border_title, app.query_one("#vrepos").border_title)
        check("대조: 첫 저장소(가장 많은 beta)의 발언 2건이 오른쪽에", rows(app, "#vhits") == 2, str(rows(app, "#vhits")))
        await pilot.press("down"); await pilot.pause(0.4)
        check("대조: 저장소를 옮기면 발언 목록이 바뀜", rows(app, "#vhits") == 1)
        await submit(pilot, app.query_one("#vhits")); await pilot.pause(0.8)
        check("대조: 발언 Enter → 대화 보기", isinstance(app.screen, ctxui.SessionScreen)); await pilot.press("escape"); await pilot.pause(0.3)

        # --- 비밀
        await pilot.press("4"); await settle(pilot, lambda: rows(app, "#secrets-table") == 1)
        check("비밀: 등록된 1개가 표에 있고 값은 표에 없음", rows(app, "#secrets-table") == 1 and PW not in str(app.query_one("#secrets-table").get_row_at(0)), str(app.query_one("#secrets-table").get_row_at(0)))
        check("비밀: 원문에 들어 있는 메시지 수(2)", app.query_one("#secrets-table").get_row_at(0)[-1] == 2, str(app.query_one("#secrets-table").get_row_at(0)))
        app.query_one("#secrets-table").focus(); await pilot.press("v"); await pilot.pause(0.3)
        check("v: 선택한 비밀 값이 아래에 표시", PW in txt(app.query_one("#sdetail")))
        await pilot.press("v"); await pilot.pause(0.2)
        check("v 다시: 숨김", txt(app.query_one("#sdetail")).strip() == "")
        await pilot.press("e"); await settle(pilot, lambda: app.query_one("#secrets-table").get_row_at(0)[2] == "꺼짐")
        check("e: 끄기", app.query_one("#secrets-table").get_row_at(0)[2] == "꺼짐")
        with cc.connect(readonly=True) as c:
            check("e: 끄면 치환 대상에서 빠짐", cs.load_secrets(c) == [])
        await pilot.press("e"); await settle(pilot, lambda: app.query_one("#secrets-table").get_row_at(0)[2] == "켜짐")
        # 추가
        await pilot.press("a"); await pilot.pause(0.4)
        check("a: 이름 입력 대화상자", isinstance(app.screen, ctxui.PromptScreen))
        await type_text(pilot, "newpw"); await pilot.press("enter"); await pilot.pause(0.4)
        check("a: 값 입력 대화상자는 가려서 표시(password)", isinstance(app.screen, ctxui.PromptScreen) and app.screen.query_one("#prompt-input").password)
        await type_text(pilot, "secretvalue99"); await pilot.press("enter"); await settle(pilot, lambda: rows(app, "#secrets-table") == 2)
        check("a: 새 비밀이 등록됨", rows(app, "#secrets-table") == 2)
        with cc.connect(readonly=True) as c:
            check("a: DB 에 평문으로 저장(설계 결정)", any(s["label"] == "newpw" and s["value"] == "secretvalue99" for s in cs.load_secrets(c)))
        # 삭제(확인)
        app.query_one("#secrets-table").focus(); await pilot.press("d"); await pilot.pause(0.4)
        check("d: 확인 대화상자", isinstance(app.screen, ctxui.ConfirmScreen))
        await pilot.press("n"); await pilot.pause(0.3)
        check("d → n: 취소하면 그대로", rows(app, "#secrets-table") == 2)
        await pilot.press("d"); await pilot.pause(0.3); await pilot.press("y"); await settle(pilot, lambda: rows(app, "#secrets-table") == 1)
        check("d → y: 삭제됨", rows(app, "#secrets-table") == 1)

        # --- 후보
        await pilot.press("5"); await settle(pilot, lambda: rows(app, "#cands-table") >= 1)
        ct = app.query_one("#cands-table")
        check("후보: 탐지됨(키 + 이미 등록된 비밀번호는 제외)", rows(app, "#cands-table") >= 1 and all(PW not in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))))
        check("후보: 값은 흐린 미리보기만", all(KEY not in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))) and any("자)" in str(ct.get_row_at(i)) for i in range(rows(app, "#cands-table"))))
        fp_key = cs.fingerprint(KEY)
        idx = next(i for i in range(rows(app, "#cands-table")) if ct.get_row_at(i)[0] == fp_key)
        ct.focus(); ct.move_cursor(row=idx); await pilot.pause(0.3)
        await pilot.press("v"); await pilot.pause(0.3)
        check("후보 v: 값 보기(승인 판단용)", KEY in txt(app.query_one("#cdetail")))
        await pilot.press("enter"); await pilot.pause(0.4)
        check("후보 Enter: 이름 입력", isinstance(app.screen, ctxui.PromptScreen))
        await type_text(pilot, "anthkey"); await pilot.press("enter")
        await settle(pilot, lambda: all(ct.get_row_at(i)[0] != fp_key for i in range(rows(app, "#cands-table"))) )
        check("후보 승인: 목록에서 사라지고 등록됨", all(ct.get_row_at(i)[0] != fp_key for i in range(rows(app, "#cands-table"))))
        with cc.connect(readonly=True) as c:
            check("후보 승인: 등록표에 들어감", any(s["label"] == "anthkey" and s["value"] == KEY for s in cs.load_secrets(c)))
        n_before = rows(app, "#cands-table")
        if n_before:
            ct.focus(); ct.move_cursor(row=0); await pilot.pause(0.3)
            fp0 = ct.get_row_at(0)[0]
            await pilot.press("i"); await settle(pilot, lambda: rows(app, "#cands-table") < n_before)
            check("후보 i: 무시하면 사라짐", rows(app, "#cands-table") == n_before - 1)
            with cc.connect(readonly=True) as c:
                check("후보 i: 무시 목록에 기록", fp0 in cd.ignored_fps(c))
        # --- 통계
        await pilot.press("6"); await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        check("통계: 6 키로 이동", app.current_tab() == "stats")
        st = txt(app.query_one("#stat-state"))
        check("통계: 상태줄에 기간·단위·분류·정렬과 비용 수집 시작일", all(k in st for k in ("기간: 30일", "단위: 일", "분류: 모델", "정렬: 비용", "10-01 이후")), st)
        check("통계: 기본 30일 필터(합성 데이터는 2026-10 초라 오늘 기준으로는 이미 밖일 수 있음)", "기간: 30일" in st)
        await pilot.press("p")      # 기간 순환: 30일 → 전체
        await settle(pilot, lambda: rows(app, "#stat-trend") == 3)
        check("통계 p: 기간 순환(30일 → 전체)", "기간: 전체" in txt(app.query_one("#stat-state")) and rows(app, "#stat-trend") == 3, txt(app.query_one("#stat-state")))
        tt = app.query_one("#stat-trend")
        check("통계: 추이 표(일 단위 3행, 최근이 위·합계 제목)", rows(app, "#stat-trend") == 3 and "10-03" in str(tt.get_row_at(0)[0]) and "$3.50" in app.query_one("#stat-trend").border_title, app.query_one("#stat-trend").border_title)
        check("통계: 비용 막대 그려짐", any("█" in str(tt.get_row_at(i)[3]) for i in range(3)))
        check("통계: 분류별(모델) 비용순", app.query_one("#stat-break").get_row_at(0)[0] == "claude-sonnet-5-5" and "$3.00" in str(app.query_one("#stat-break").get_row_at(0)))
        sm = txt(app.query_one("#stat-summary"))
        check("통계: 세션 요약(세션·프롬프트·비용·시간대·요일)", all(k in sm for k in ("세션 3개", "프롬프트 5", "시간대별", "요일별")) , sm)
        await pilot.press("g"); await settle(pilot, lambda: "분류: 저장소" in txt(app.query_one("#stat-state")))
        check("통계 g: 분류 순환(모델 → 저장소)", app.query_one("#stat-break").border_title.startswith("저장소별") and rows(app, "#stat-break") == 2)
        await pilot.press("b"); await settle(pilot, lambda: "단위: 주" in txt(app.query_one("#stat-state")))
        check("통계 b: 단위 순환(일 → 주)", "단위: 주" in txt(app.query_one("#stat-state")) and rows(app, "#stat-trend") == 1)
        await pilot.press("o"); await settle(pilot, lambda: "정렬: 최근" in txt(app.query_one("#stat-state")))
        check("통계 o: 세션 정렬 순환(비용 → 최근)", "정렬: 최근" in txt(app.query_one("#stat-state")))
        fr = app.query_one("#f-repo")
        fr.value = "alpha"; await submit(pilot, fr)
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 1)
        check("통계 필터(저장소 alpha): 세션·추이·분류가 함께 줄어듦", rows(app, "#stat-sessions") == 1 and "$1.50" in app.query_one("#stat-trend").border_title, app.query_one("#stat-trend").border_title)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("c")
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        check("통계 c: 필터 지움", app.query_one("#f-repo").value == "" and rows(app, "#stat-sessions") == 3)
        fm = app.query_one("#f-model")
        fm.value = "haiku"; await submit(pilot, fm)
        await settle(pilot, lambda: rows(app, "#stat-sessions") == 1)
        check("통계 필터(모델 haiku): 그 모델을 쓴 세션만", rows(app, "#stat-sessions") == 1 and "$0.50" in app.query_one("#stat-trend").border_title)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("c"); await settle(pilot, lambda: rows(app, "#stat-sessions") == 3)
        sess_t = app.query_one("#stat-sessions")
        sess_t.focus(); sess_t.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        check("통계 세션 Enter: 그 세션 대화 열림", app.screen.__class__.__name__ == "SessionScreen")
        await pilot.press("escape"); await pilot.pause(0.3)
        check("통계: 대화 닫으면 통계 탭으로 복귀", app.current_tab() == "stats" and app.screen.__class__.__name__ != "SessionScreen")
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
        scr = ctxui.SessionScreen(app, "gggg0001", None, "NEEDLE_X", False)
        await app.push_screen(scr); await settle(pilot, lambda: len(list(scr.query(ctxui.MsgView))) == 2)
        head = txt(scr.query_one("#sess-head"))
        check("대화 화면: 머리글에 제목(첫 프롬프트)·저장소#브랜치·프롬프트/도구 수", "긴 응답을 읽자" in head and "#dev" in head and "프롬프트 1" in head and "도구 1" in head, head)
        check("대화 화면: 이어진 세션 안내(] 다음 세션)", "] 다음 세션: gggg0002" in head, head)
        check("대화 화면: 기본은 프롬프트·응답만(도구·서브에이전트 숨김)", len(scr.msgs) == 2 and "서브 작업" not in sess_txt(scr) and "echo hi" not in sess_txt(scr))
        check("대화 화면: 긴 메시지는 접히고 펼치는 방법 안내", "더 — Enter: 펼치기" in txt(scr.views[1]) and "끝" not in txt(scr.views[1]).replace("더 — Enter: 펼치기", ""))
        check("대화 화면: 검색어 강조(스타일 span)", any("on #b8a46a" in str(sp.style) for sp in scr.render_msg(scr.msgs[0]).spans))
        await pilot.press("n"); await pilot.pause(0.3)
        check("n: 다음 검색어 메시지로 이동", scr.sel == 1 and "msg-sel" in scr.views[1].classes, str(scr.sel))
        check("n: 검색어가 접힌 뒷부분에 있으면 자동으로 펼쳐서 보여 줌", "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter: 펼친 메시지는 다시 접힘", "더 — Enter: 펼치기" in txt(scr.views[1]))
        await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter: 다시 펼침(끝 글자가 보임)", "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("N"); await pilot.pause(0.3)
        check("N: 이전 검색어 메시지(첫 프롬프트)로 이동", scr.sel == 0)
        await pilot.press("y"); await pilot.pause(0.3)
        check("y: 선택한 메시지를 클립보드로 복사", app.clipboard == "긴 응답을 읽자 NEEDLE_X", repr(app.clipboard))
        await pilot.press("down"); await pilot.press("y"); await pilot.pause(0.3)
        check("↓ 이동 후 y: 그 메시지 전체 복사", app.clipboard == long_text and scr.sel == 1)
        await pilot.press("t"); await settle(pilot, lambda: len(scr.msgs) == 4)
        check("t: 도구 호출·결과 보기(4개), 보던 메시지 위치 유지", len(scr.msgs) == 4 and "echo hi" in sess_txt(scr) and scr.msgs[scr.sel]["uuid"] == "gggg-r0", str(scr.sel))
        await pilot.press("s"); await pilot.pause(0.5)
        check("s: 서브에이전트 메시지도 보기(5개)", len(scr.msgs) == 5 and "서브 작업 지시" in sess_txt(scr) and "(서브에이전트)" in sess_txt(scr))
        await pilot.press("s"); await pilot.press("t"); await settle(pilot, lambda: len(scr.msgs) == 2)
        await pilot.press("f"); await pilot.pause(0.4)
        check("f: 전체 펼침", all_open_ok(scr) and "마지막NEEDLE_X끝" in txt(scr.views[1]))
        await pilot.press("f"); await pilot.pause(0.3)
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
        await pilot.press("a"); await pilot.pause(0.5)
        check("a: 전부 불러오기", len(scr.msgs) == 2 and "생략" not in txt(scr.query_one("#sess-state")))
        await pilot.press("escape"); await pilot.pause(0.3)
        check("대화 화면 닫힘", not isinstance(app.screen, ctxui.SessionScreen))
        await pilot.press("2"); await pilot.pause(0.3)
        q.value = "NEEDLE_X"; await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") == 2)
        r0 = app.query_one("#results").get_row_at(0)
        check("검색: 결과에 세션 제목 열", rows(app, "#results") == 2 and "긴 응답을 읽자" in str(r0[4]), str(r0))
        q.value = "echo hi"; await submit(pilot, q); await pilot.pause(0.6)
        check("검색: 기본은 도구 메시지 제외", rows(app, "#results") == 0)
        await pilot.press("f4"); await submit(pilot, q); await settle(pilot, lambda: rows(app, "#results") == 1)
        check("F4: 도구 메시지 포함하면 찾아짐(종류가 역할 칸에 표시)", rows(app, "#results") == 1 and app.query_one("#results").get_row_at(0)[1] == "tool_use" and "도구 메시지: 포함" in txt(app.query_one("#sstate")))
        await pilot.press("f4")

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
        await pilot.press("7"); await settle(pilot, lambda: rows(app, "#instr-table") == 3)
        it = app.query_one("#instr-table")
        check("지침: 7 키로 이동, 모든 저장소의 지침이 목록에(저장소·이름·rev·수정 머신·길이)", app.current_tab() == "instr" and rows(app, "#instr-table") == 3 and it.get_row_at(0)[1] == "instructions" and it.get_row_at(0)[2] == 1 and it.get_row_at(0)[3] == "h1", str(it.get_row_at(0)))
        it.focus(); it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        check("지침 Enter: 본문 보기 화면이 열림", isinstance(app.screen, ctxui.InstrScreen))
        body = txt(app.screen.query_one("#instr-body"))
        check("지침 본문: 저장소·이름·rev·절 목록과 본문", "알파 지침" in body and "rev 1" in body and "절 2개: QA 할 때 · 배포" in body and "qa 본문" in body, body[:200])
        await pilot.press("escape"); await pilot.pause(0.3)
        it.move_cursor(row=2); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        shown = txt(app.screen.query_one("#instr-body"))
        check("지침 본문: 등록된 비밀은 [protected] 로 치환해 보인다", PW not in shown and "[protected]" in shown, shown[:160])
        await pilot.press("m"); await pilot.pause(0.6)
        check("지침 본문 m: 치환을 끄면 원문(경고 표시)", PW in txt(app.screen.query_one("#instr-body")) and "꺼짐" in txt(app.screen.query_one("#instr-body")))
        await pilot.press("m"); await pilot.pause(0.4); await pilot.press("escape"); await pilot.pause(0.3)
        check("m 으로 다시 켬", app.mask)

        # 편집: 가짜 편집기(실행 파일)로 대체 — suspend 는 헤드리스에서 못 쓰므로 빈 컨텍스트로 바꾼다
        app.suspend = lambda: contextlib.nullcontext()
        cache_marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-cache")      # 캐시 파일 경로를 쓰지 않는다는 것을 아래에서 확인
        make_editor(f'cp "$1" {EDITLOG}.mode_probe 2>/dev/null; stat -c %a "$1" > {EDITLOG}.perm; printf "\\n## 추가 절\\n새 내용\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3)
        await pilot.press("e"); await settle(pilot, lambda: it.get_row_at(0)[2] == 2)
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "instructions")
        check("지침 e: 편집기로 고치면 DB 에 올라가고 rev 가 오른다", raw[0] == 2 and "## 추가 절" in raw[1] and "새 내용" in raw[1] and it.get_row_at(0)[2] == 2, str(raw))
        check("지침 e: 임시 파일은 0600 이었고 편집 뒤 지워진다", open(EDITLOG + ".perm").read().strip() == "600" and not any(f.startswith("instr-") for f in os.listdir(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())))
        with cc.connect(readonly=True) as c:
            row = next(r for r in cd.instr_rows(c) if (r["repo"], r["name"]) == (A, "instructions"))
        check("지침 e: 수정 머신은 이 기기(CLAUDE_CTX_HOST)로 기록", row["host"] == "testhost", str(row))
        # 변경 없음
        make_editor("exit 0\n")
        it.move_cursor(row=1); await pilot.pause(0.3); await pilot.press("e"); await pilot.pause(0.8)
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
        ctxui.subprocess.run = run_with_race
        it.move_cursor(row=1); await pilot.pause(0.3); await pilot.press("e"); await pilot.pause(1.0)
        ctxui.subprocess.run = real_run
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "override")
        check("지침 e: 편집 중 다른 기기가 먼저 고쳤으면(낡은 rev) 거부하고 상대 본문을 덮지 않는다", raw == (2, "다른 기기가 먼저 씀\n"), str(raw))
        # 비밀이 든 본문
        make_editor(f'printf "비번 {PW}\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("e"); await pilot.pause(1.0)
        with cc.connect(readonly=True) as c:
            raw = cd.instr_raw(c, A, "instructions")
        check("지침 e: 등록된 비밀이 든 본문은 거부(저장 안 됨)", PW not in raw[1] and raw[0] == 2, str(raw[0]))
        # 빈 본문
        make_editor(': > "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("e"); await pilot.pause(1.0)
        with cc.connect(readonly=True) as c:
            check("지침 e: 빈 본문은 거부(저장 안 됨)", cd.instr_raw(c, A, "instructions")[0] == 2 and cd.instr_raw(c, A, "instructions")[1].strip() != "")
        # 본문 보기 화면 안에서 편집하면 화면이 새 내용으로 갱신된다
        make_editor('printf "\\n## 화면 안에서 추가\\n" >> "$1"\n')
        it.move_cursor(row=0); await pilot.pause(0.3); await pilot.press("enter"); await pilot.pause(0.8)
        await pilot.press("e"); await settle(pilot, lambda: "화면 안에서 추가" in txt(app.screen.query_one("#instr-body")))
        check("지침 본문 e: 보기 화면에서 고치면 화면이 새 rev·내용으로 바뀜", "rev 3" in txt(app.screen.query_one("#instr-body")) and "화면 안에서 추가" in txt(app.screen.query_one("#instr-body")))
        await pilot.press("escape"); await pilot.pause(0.3)
        # 목록 새로고침·에이전트용 경로는 그대로(사람 전용 화면이 DB 를 지우지 않는다)
        await pilot.press("r"); await pilot.pause(0.6)
        check("지침: r 새로고침, 행 삭제 기능은 없다(범위 밖)", rows(app, "#instr-table") == 3 and not any(b.key == "d" and "지침" in str(b.description) for b in app.BINDINGS))
        for f in (fake, EDITLOG + ".perm", EDITLOG + ".mode_probe"):
            try: os.unlink(f)
            except OSError: pass

        # --- 도움말·종료
        await pilot.press("f1"); await pilot.pause(0.3)
        check("F1: 도움말", app.screen.__class__.__name__ == "HelpScreen"); await pilot.press("escape"); await pilot.pause(0.2)
        await pilot.press("1"); await pilot.pause(0.5)
        check("1: 개요로 돌아옴", app.current_tab() == "overview")


try:
    seed()
    asyncio.run(run())
finally:
    pg.stop()
finish("ctxui")
