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
    conn.commit(); conn.close()


def txt(w):
    r = w.render()
    return getattr(r, "plain", None) or str(r)


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
        body = txt(app.screen.query_one("#session-body"))
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
        check("치환 켜짐: 대화 화면에도 [protected]", PW not in txt(app.screen.query_one("#session-body")) and "[protected]" in txt(app.screen.query_one("#session-body")))
        await pilot.press("m"); await pilot.pause(0.6)
        check("대화 화면 m: 치환 끄면 원문이 보임(경고 표시)", PW in txt(app.screen.query_one("#session-body")) and "꺼짐" in txt(app.screen.query_one("#session-body")))
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
