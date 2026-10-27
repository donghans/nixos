#!/usr/bin/env python3
"""clipui 시험(헤드리스, cliphist·wl-copy 없이 가짜로): Enter 는 복사하되 창을 닫지 않고, 정렬 드롭다운이 F6 과 같은 상태를 따라간다."""
import asyncio, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
os.environ.setdefault("XDG_STATE_HOME", tempfile.mkdtemp(prefix="clipui-test-")); os.environ.setdefault("XDG_DATA_HOME", os.environ["XDG_STATE_HOME"])
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(DATA), "_lib", "_testkit")); sys.path.insert(0, os.path.join(os.path.dirname(DATA), "_lib", "_uikit"))
from harness import checker
import clipui
from textual.widgets import Input, Select
check, finish = checker()

COPIED = []
clipui.load_entries = lambda: [clipui.Entry(3, "세 번째 항목"), clipui.Entry(2, "두 번째 항목"), clipui.Entry(1, "첫 번째 항목")]
clipui.fetch_raw = lambda i: f"본문 {i}".encode()
clipui.copy_bytes = lambda data: COPIED.append(data)
clipui.clipmeta.load_all = lambda: {}
USES = []
clipui.clipmeta.mark_use = lambda i: USES.append(i)


async def drive():
    app = clipui.ClipUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("enter"); await pilot.pause(0.4)
        check("Enter: 선택 항목을 복사하고 사용 횟수를 기록한다", COPIED == ["본문 3".encode()] and USES == [3], (COPIED, USES))
        check("Enter: 복사해도 창은 닫히지 않는다(빠른 붙여넣기는 Super+V 의 wofi)", app.is_running)
        await pilot.press("enter"); await pilot.pause(0.3)
        check("Enter 를 또 눌러도 계속 복사된다(창 유지)", len(COPIED) == 2 and app.is_running, len(COPIED))
        sel = app.query_one("#sel-sort", Select)
        check("정렬 드롭다운은 현재 정렬(최신순)을 보인다", sel.value == 0 and clipui.SORT_MODES[sel.value] == "최신순", sel.value)
        await pilot.press("f6"); await pilot.pause(0.4)
        check("F6 으로 정렬을 바꾸면 드롭다운이 따라간다", sel.value == app.sort_mode == 1, (sel.value, app.sort_mode))
        sel.value = 4; await pilot.pause(0.5)
        check("드롭다운으로 고르면 정렬이 바뀌고 포커스가 검색창으로 돌아간다", app.sort_mode == 4 and app.focused is app.query_one("#search", Input), (app.sort_mode, app.focused))
        sel.focus(); await pilot.pause(0.2)
        n = len(COPIED)
        await pilot.press("enter"); await pilot.pause(0.4)
        check("드롭다운에 포커스가 있을 때 Enter 는 복사하지 않고 드롭다운을 연다", len(COPIED) == n, (n, len(COPIED)))
        await pilot.press("escape"); await pilot.pause(0.3)
        check("(여전히) 앱이 살아 있다", app.is_running)


asyncio.run(drive())
finish("clipui")
