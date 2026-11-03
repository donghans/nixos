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
        for k in ("enter", "question_mark"):
            await pilot.press("f1"); await pilot.pause(0.15)
            await pilot.press(k); await pilot.pause(0.15)
            check(f"{k} 로도 닫힘", type(app.screen).__name__ != "HelpScreen")
        await pilot.press("f1"); await pilot.pause(0.15); await pilot.press("q"); await pilot.pause(0.15)
        check("q 로는 도움말이 닫히지 않음(q 는 종료·닫기 키가 아니다)", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("escape"); await pilot.pause(0.15)
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

# ---- 종료 확인창(QuitConfirmScreen / QuitMixin)
class Q(uikit.QuitMixin, uikit.HelpMixin, App):
    BINDINGS = [Binding("escape", "confirm_quit", "종료"), *uikit.HelpMixin.HELP_BINDINGS]
    def compose(self): yield Static("본문")

async def quit_cases():
    scr = lambda a: type(a.screen).__name__
    async def fresh(quit_confirm=True):
        a = Q(); a.quit_confirm = quit_confirm; return a
    a = await fresh()
    async with a.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2)
        await pilot.press("escape"); await pilot.pause(0.2)
        check("Esc → 종료 확인창이 뜸, 기본 포커스는 「아니오」", scr(a) == "QuitConfirmScreen" and a.focused.id == "quit-no")
        await pilot.press("enter"); await pilot.pause(0.2)
        check("Esc 후 바로 Enter = 취소(앱 유지)", scr(a) != "QuitConfirmScreen" and not a._exit)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("escape"); await pilot.pause(0.2)
        check("확인창에서 Esc = 취소", scr(a) != "QuitConfirmScreen" and not a._exit)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("n"); await pilot.pause(0.2)
        check("확인창에서 n/y 같은 글자 키는 아무 일도 안 함(한영 전환에 영향받는 키는 쓰지 않는다)", scr(a) == "QuitConfirmScreen" and not a._exit)
        await pilot.press("y"); await pilot.pause(0.2); await pilot.press("ㅛ"); await pilot.pause(0.2)
        check("  … y·ㅛ 도 마찬가지", scr(a) == "QuitConfirmScreen" and not a._exit)
        await pilot.press("escape"); await pilot.pause(0.2)
        await pilot.press("escape"); await pilot.pause(0.2); await pilot.press("q"); await pilot.pause(0.2)
        check("확인창 위에서 q 는 아무 일도 안 함", scr(a) == "QuitConfirmScreen" and not a._exit)
        await pilot.press("right"); await pilot.pause(0.2)
        check("→ 로 「예」에 포커스가 감", a.focused.id == "quit-yes")
        await pilot.press("left"); await pilot.pause(0.2)
        check("← 로 다시 「아니오」", a.focused.id == "quit-no")
        await pilot.press("escape"); await pilot.pause(0.2)
        await pilot.press("f1"); await pilot.pause(0.2)
        check("도움말(모달) 위에서는 Esc 가 확인창을 띄우지 않고 도움말만 닫음", scr(a) == "HelpScreen")
        await pilot.press("escape"); await pilot.pause(0.2)
        check("  … 도움말이 닫히고 확인창은 안 뜸", scr(a) not in ("HelpScreen", "QuitConfirmScreen") and len(a.screen_stack) == 1)
        a.action_confirm_quit(); a.action_confirm_quit(); await pilot.pause(0.2)
        check("확인창이 이미 떠 있으면 중복으로 쌓이지 않음", len(a.screen_stack) == 2)
        await pilot.press("escape"); await pilot.pause(0.2)
        check("끝난 뒤 screen_stack 정리됨", len(a.screen_stack) == 1)
    for label, keys in (("Esc → → → Enter", ("escape", "right", "enter")), ("Esc → Tab → Enter", ("escape", "tab", "enter")), ("Esc → ← → Enter", ("escape", "left", "enter"))):
        a = await fresh()
        async with a.run_test(size=(80, 20)) as pilot:
            await pilot.pause(0.2)
            for k in keys:
                await pilot.press(k); await pilot.pause(0.2)
            check(f"{label} = 종료", bool(a._exit))
    a = await fresh()
    async with a.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2); await pilot.press("ctrl+q"); await pilot.pause(0.2)
        check("Ctrl+Q = 확인 없이 즉시 종료", bool(a._exit))
    a = await fresh(False)
    async with a.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2); await pilot.press("escape"); await pilot.pause(0.2)
        check("quit_confirm=False 면 Esc 로 바로 종료(팝업형 모드)", bool(a._exit))
asyncio.run(quit_cases())

# ---- 일반 확인창(ConfirmScreen): 문구·버튼 이름을 받고, 기본 포커스는 취소, y/n 글자 키는 무반응
class CS(App):
    res = "미정"
    def compose(self): yield Static("본문")
    def on_mount(self): self.push_screen(uikit.ConfirmScreen("삭제할까요?", "삭제", "취소"), lambda r: setattr(self, "res", r))

async def confirm_cases():
    a = CS()
    async with a.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2)
        check("ConfirmScreen: 문구·버튼 이름을 쓰고 기본 포커스는 취소쪽", a.focused.id == "quit-no" and str(a.screen.query_one("#quit-yes").label) == "삭제")
        await pilot.press("y", "n", "ㅛ"); await pilot.pause(0.2)
        check("ConfirmScreen: y/n/ㅛ 글자 키는 무반응", type(a.screen).__name__ == "ConfirmScreen" and a.res == "미정")
        await pilot.press("left", "enter"); await pilot.pause(0.2)
        check("ConfirmScreen: ← 로 「삭제」를 골라 Enter 하면 True", a.res is True)
    a = CS()
    async with a.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.2); await pilot.press("enter"); await pilot.pause(0.2)
        check("ConfirmScreen: 바로 Enter = False(오발 방지)", a.res is False)
asyncio.run(confirm_cases())
from rich.cells import cell_len
check("wrap_cells: 칸 폭(한글 2칸) 기준 줄바꿈, 모든 줄이 폭 이하", all(cell_len(x) <= 10 for x in uikit.wrap_cells("한글로 된 긴 문장을 열 칸 폭으로 줄바꿈 합니다", 10)))
tt = uikit.terms_text([("용어", "설명 " * 30), ("English", "x")], 50).plain.splitlines()
cc = lambda l, t: cell_len(l[:l.index(t)])
check("terms_text: 이름 칸이 같고 줄바꿈 줄은 이름 칸만큼 들여씀, 폭 이하", all(cell_len(l) <= 50 for l in tt) and cc(tt[0], "설명") == cc(tt[1], "설명") and cc(tt[-1], "x") == cc(tt[0], "설명"), tt[:3])
check("pad: 한글 칸 폭 기준이고 넘치면 한 칸만 둠", cell_len(uikit.pad("한글", 8)) == 8 and uikit.pad("가나다라마", 4) == "가나다라마 ")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import lint_keys
check("lint_keys: 변환을 마친 앱에 단일 알파벳 Binding 키가 없다(남은 앱: %s)" % sorted(lint_keys.PENDING), not lint_keys.check_apps(), lint_keys.check_apps())
finish("uikit")
