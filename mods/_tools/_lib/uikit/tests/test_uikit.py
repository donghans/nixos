#!/usr/bin/env python3
"""uikit 시험(textual 필요): CSS 가 실제로 파싱되는지, 도움말 키 목록 생성, box 제목, 도움말 화면 열고 닫기, 포커스 일시정지."""
import asyncio, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "testkit"))
from harness import checker
check, finish = checker()
try:
    import textual  # noqa
except ImportError:
    print("  (textual 없음: 시험을 건너뜀 — PYTHON=<textual 이 있는 python> 으로 실행)"); print("\nuikit 0 통과 / 0 실패"); sys.exit(0)
import uikit
from textual.app import App
from textual.binding import Binding
from textual.widgets import Static, Footer

rows = uikit.binding_rows([Binding("q", "quit", "종료"), Binding("question_mark,f1", "help", "도움말"), Binding("x", "x", ""), ("a", "a", "A"), Binding("q", "quit", "종료")])
check("binding_rows: 설명 없는 줄·중복 제외, 키 표기", rows == [("q", "종료"), ("? / f1", "도움말"), ("a", "A")], str(rows))

class A(uikit.HelpMixin, uikit.PauseOnBlurMixin, App):
    TITLE = "시험앱"
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + "#x { height: 3; }"
    BINDINGS = [Binding("q", "quit", "종료"), *uikit.HelpMixin.HELP_BINDINGS]
    HELP_TERMS = [("용어하나", "아주 긴 설명 문장입니다 " * 12), ("English term", "짧은 설명")]
    HELP_NOTES = ["종료는 q 입니다"]
    refreshed = 0
    def compose(self):
        yield uikit.box(Static("본문", id="x"), "제목", "부제")
        yield Footer()
    def refresh_data(self):
        self.refreshed += 1

class T:
    def pause(self): self.p = True
    def resume(self): self.p = False

async def drive():
    app = A()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2)
        x = app.query_one("#x")
        check("box: 클래스·제목·부제", x.has_class("box") and x.border_title == "제목" and x.border_subtitle == "부제")
        await pilot.press("question_mark"); await pilot.pause(0.2)
        check("? 로 도움말 화면", type(app.screen).__name__ == "HelpScreen")
        body = " ".join(str(app.screen.query_one(i, __import__("textual.widgets", fromlist=["Static"]).Static).render()) for i in ("#help-keys", "#help-terms", "#help-common"))
        check("도움말 한 화면에 키 목록·앱 메모·용어·공통 안내가 모두 있음", all(k in body for k in ("종료", "종료는 q 입니다", "용어하나", "English term", "Ctrl+Q", "Ctrl+C")), body[:200])
        await pilot.press("x"); await pilot.pause(0.2)
        check("정해진 닫기 키가 아닌 키(x)로는 닫히지 않음(안내 문구가 거짓이 아님)", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("down"); await pilot.press("pagedown"); await pilot.pause(0.2)
        check("스크롤 키는 도움말을 닫지 않음", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("escape"); await pilot.pause(0.2)
        check("Esc 로 닫힘", type(app.screen).__name__ != "HelpScreen")
        for k in ("q", "enter", "question_mark"):
            await pilot.press("f1"); await pilot.pause(0.15)
            await pilot.press(k); await pilot.pause(0.15)
            check(f"{k} 로도 닫힘", type(app.screen).__name__ != "HelpScreen")
        from textual.screen import ModalScreen as _MS
        from textual.containers import Vertical as _V
        class WhateverScreen(_MS):          # DIALOG_CSS 예전 이름 목록에 없던 이름
            def compose(self):
                with _V(id="dialog"):
                    yield Static("아무 대화상자")
        app.push_screen(WhateverScreen()); await pilot.pause(0.3)
        d = app.screen.query_one("#dialog")
        check("DIALOG_CSS: 이름과 상관없이 모든 대화상자가 화면 가운데(좌우·상하 ±1칸)", abs(d.region.x + d.region.width / 2 - app.size.width / 2) <= 1 and abs(d.region.y + d.region.height / 2 - app.size.height / 2) <= 1.5, (d.region, app.size))
        await pilot.press("escape"); app.pop_screen(); await pilot.pause(0.2)
        await pilot.press("f1"); await pilot.pause(0.2)
        check("F1 로도 도움말", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("f1"); await pilot.pause(0.2)
        app._timer = T()
        app.on_app_blur(None)
        check("포커스 잃으면 타이머 정지", app._timer.p is True)
        n = app.refreshed; app.on_app_focus(None)
        check("포커스 돌아오면 재개 + 한 번 갱신", app._timer.p is False and app.refreshed == n + 1)
asyncio.run(drive())
from rich.cells import cell_len
check("wrap_cells: 칸 폭(한글 2칸) 기준 줄바꿈, 모든 줄이 폭 이하", all(cell_len(x) <= 10 for x in uikit.wrap_cells("한글로 된 긴 문장을 열 칸 폭으로 줄바꿈 합니다", 10)))
tt = uikit.terms_text([("용어", "설명 " * 30), ("English", "x")], 50).plain.splitlines()
cc = lambda l, t: cell_len(l[:l.index(t)])
check("terms_text: 이름 칸이 같고 줄바꿈 줄은 이름 칸만큼 들여씀, 폭 이하", all(cell_len(l) <= 50 for l in tt) and cc(tt[0], "설명") == cc(tt[1], "설명") and cc(tt[-1], "x") == cc(tt[0], "설명"), tt[:3])
check("pad: 한글 칸 폭 기준이고 넘치면 한 칸만 둠", cell_len(uikit.pad("한글", 8)) == 8 and uikit.pad("가나다라마", 4) == "가나다라마 ")
finish("uikit")
