#!/usr/bin/env python3
"""uikit 시험(textual 필요): CSS 가 실제로 파싱되는지, 도움말 키 목록 생성, box 제목, 도움말 화면 열고 닫기, 포커스 일시정지."""
import asyncio, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
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
        await pilot.press("escape"); await pilot.pause(0.2)
        check("아무 키로 닫힘", type(app.screen).__name__ != "HelpScreen")
        await pilot.press("f1"); await pilot.pause(0.2)
        check("F1 로도 도움말", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("f1"); await pilot.pause(0.2)
        app._timer = T()
        app.on_app_blur(None)
        check("포커스 잃으면 타이머 정지", app._timer.p is True)
        n = app.refreshed; app.on_app_focus(None)
        check("포커스 돌아오면 재개 + 한 번 갱신", app._timer.p is False and app.refreshed == n + 1)
asyncio.run(drive())
finish("uikit")
