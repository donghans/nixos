"""notif ui — 알림 센터(Textual). clipui/displayui 와 같은 사용 경험: 검은 배경 + 둥근 테두리(포커스는 하늘색, 제목은 테두리 안),
위쪽 검색창(항상 입력 가능, ↑↓ 로 목록 이동), 좌우 목록/미리보기(좁으면 위아래, 낮으면 숨김), F키 기능, Enter 로 복사하고 종료.
본체 로직(읽기·검색어 해석·통계·장애 점검)은 notif.py 를 그대로 쓴다 — 여기는 화면만.

  검색창: 글자(앱·제목·본문에 모두 포함)   app:이름   is:problem   is:urgent   since:3h|2d|1w
  Enter 복사 후 종료(체크한 게 있으면 모두)  Esc 검색 지우기 → 체크 해제 → 종료  ↑↓ PgUp/PgDn 이동
  F2 체크  F3 전체체크  F4 체크해제  F5 새로고침  F6 보기(전체/앱별/문제)  F7 미리보기  F8 같은 앱만  F9 통계  F10 서비스 점검
  목록에서: 스페이스 체크, a 전체체크, u 체크해제, / 검색, q 종료.  미리보기에서: c/y 선택(없으면 전체) 복사
"""
import datetime

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

import notif

WIDE_COLUMNS = 110   # 이 폭 이상이면 목록/미리보기를 좌우로, 미만이면 위아래로
SHORT_ROWS = 16      # 이 높이 미만이면 미리보기를 숨김
META_COLUMNS = 60    # 목록 폭이 이 이상일 때만 시각/앱 열을 보여줌
VIEWS = ["전체", "앱별", "문제"]
URGENCY = {0: "낮음", 1: "보통", 2: "긴급", None: "알 수 없음"}


def pad(text: str, width: int) -> str:
    """셀 폭(한글은 2칸) 기준으로 자르고 채운다."""
    while cell_len(text) > width:
        text = text[:-1]
    return text + " " * (width - cell_len(text))


class InfoScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "닫기"), Binding("q", "close", "닫기", show=False), Binding("enter", "close", "닫기", show=False)]

    def __init__(self, title: str, body) -> None:
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            yield Static(self.body, id="dialog-body")
            yield Label("[Esc/Enter] 닫기", id="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class StatsScreen(ModalScreen[None]):
    """화면을 넓게 쓰는 통계 화면(스크롤 가능)."""
    BINDINGS = InfoScreen.BINDINGS

    def __init__(self, renderable) -> None:
        super().__init__()
        self.renderable = renderable

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Label("알림 통계", id="dialog-title")
            with VerticalScroll(id="stats-scroll"):
                yield Static(self.renderable, id="stats-body")
            yield Label("[Esc/Enter] 닫기", id="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class NotifList(OptionList):
    BINDINGS = [
        Binding("space", "app.toggle_mark", "체크", show=False),
        Binding("a", "app.mark_all", "전체체크", show=False),
        Binding("u", "app.clear_marks", "체크해제", show=False),
        Binding("slash", "app.focus_search", "검색", show=False),
        Binding("q", "app.quit", "종료", show=False),
    ]


class Preview(TextArea):
    BINDINGS = [
        Binding("c", "app.copy_selection", "선택 복사", show=False),
        Binding("y", "app.copy_selection", "선택 복사", show=False),
        Binding("slash", "app.focus_search", "검색", show=False),
        Binding("q", "app.quit", "종료", show=False),
    ]


class NotifUI(App):
    CSS = """
    Screen { background: #000000; }
    #search { background: #000000; border: round #595959; }
    #search:focus { border: round #33ccff; }
    #main { height: 1fr; layout: horizontal; }
    #main.narrow { layout: vertical; }
    NotifList { width: 1fr; height: 1fr; background: #000000; border: round #595959; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis; }
    NotifList:focus { border: round #33ccff; }
    NotifList > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    NotifList:focus > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    #preview-box { width: 1fr; height: 1fr; layout: vertical; }
    #meta-header { height: auto; max-height: 4; padding: 0 1; color: #9a9a9a; background: #000000; }
    Preview { width: 100%; height: 1fr; background: #000000; border: round #595959; }
    Preview:focus { border: round #33ccff; }
    #main.narrow NotifList { width: 100%; height: 3fr; }
    #main.narrow #preview-box { width: 100%; height: 2fr; }
    #main.short #preview-box { display: none; }
    #main.short NotifList { width: 100%; }
    #main.hide-preview #preview-box { display: none; }
    #main.hide-preview NotifList { width: 100%; height: 1fr; }
    #status-row { height: 1; }
    #status { width: 1fr; color: #9a9a9a; padding: 0 1; }
    InfoScreen, StatsScreen { align: center middle; }
    #dialog { width: 70%; max-width: 90; height: auto; background: #101010; border: round #33ccff; padding: 1 2; }
    #stats-box { width: 90%; max-width: 120; height: 90%; background: #101010; border: round #33ccff; padding: 1 2; }
    #stats-scroll { height: 1fr; }
    #dialog-title { text-style: bold; padding-bottom: 1; }
    #dialog-hint { color: #7a7a7a; padding-top: 1; }
    Footer { background: #000000; color: #9a9a9a; }
    Footer FooterKey { background: #000000; }
    Footer .footer-key--key { background: #000000; color: #33ccff; text-style: none; }
    Footer .footer-key--description { background: #000000; color: #9a9a9a; }
    """

    BINDINGS = [
        Binding("enter", "copy_quit", "복사", priority=True),
        Binding("escape", "escape", "지우기/종료"),
        Binding("down", "move(1)", "아래", show=False),
        Binding("up", "move(-1)", "위", show=False),
        Binding("pagedown", "move(10)", "", show=False),
        Binding("pageup", "move(-10)", "", show=False),
        Binding("f2", "toggle_mark", "체크"),
        Binding("f3", "mark_all", "전체체크"),
        Binding("f4", "clear_marks", "체크해제"),
        Binding("f5", "reload", "새로고침"),
        Binding("f6", "cycle_view", "보기"),
        Binding("f7", "toggle_preview", "미리보기"),
        Binding("f8", "same_app", "같은앱만"),
        Binding("f9", "stats", "통계"),
        Binding("f10", "check_services", "서비스점검"),
        Binding("ctrl+q", "quit", "종료", show=False),
    ]

    def __init__(self, view: str = "전체") -> None:
        super().__init__()
        self.view = view if view in VIEWS else "전체"
        self.app_filter = None          # 같은 앱만(F8) / 앱별 보기에서 Enter
        self.entries: list = []
        self.shown: list = []           # 목록에 보이는 항목: 알림 dict 또는 (앱, 건수, 긴급, 마지막) 튜플(앱별 보기)
        self.marked: set = set()        # 체크한 알림의 entries 인덱스
        self.failed: list = []
        self.list_width = 80

    # ---------- 화면 구성 ----------
    def compose(self) -> ComposeResult:
        yield Input(placeholder="검색 — 앱·제목·본문   필터: app:이름  is:problem  is:urgent  since:3h   (Enter: 복사)", id="search")
        with Container(id="main"):
            yield NotifList(id="list")
            with Vertical(id="preview-box"):
                yield Static("", id="meta-header")
                yield Preview("", read_only=True, soft_wrap=True, show_line_numbers=False, id="preview")
        with Horizontal(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(NotifList).border_title = "알림"
        self.query_one(Preview).border_title = "미리보기"
        self.query_one("#search", Input).focus()
        self.apply_layout(self.size.width, self.size.height)
        self.reload()

    def on_resize(self, event: events.Resize) -> None:
        self.apply_layout(event.size.width, event.size.height)

    def apply_layout(self, width: int, height: int) -> None:
        main = self.query_one("#main")
        main.set_class(width < WIDE_COLUMNS, "narrow")
        main.set_class(height < SHORT_ROWS, "short")
        side = width >= WIDE_COLUMNS and height >= SHORT_ROWS and not main.has_class("hide-preview")
        new = (width // 2 if side else width) - 4
        changed = (new >= META_COLUMNS) != (self.list_width >= META_COLUMNS)
        self.list_width = new
        if changed and self.entries:
            self.refresh_list()

    def action_toggle_preview(self) -> None:
        main = self.query_one("#main")
        main.set_class(not main.has_class("hide-preview"), "hide-preview")
        self.apply_layout(self.size.width, self.size.height)

    # ---------- 데이터 ----------
    def reload(self) -> None:
        self.entries = notif.read_entries()
        self.failed = notif.failed_units()
        self.marked = set()
        self.refresh_list()

    def action_reload(self) -> None:
        self.reload()
        self.notify("새로고침했습니다")

    def query(self) -> dict:
        q = notif.parse_query(self.query_one("#search", Input).value, datetime.datetime.now())
        if self.view == "문제":
            q["problems"] = True
        return q

    def row_text(self, item) -> Text:
        if isinstance(item, tuple):                         # 앱별 보기
            app, n, k, last = item
            t = Text(pad(app, 28) + f"{n:>6}건  ")
            t.append(f"긴급 {k}" if k else "", style="bold #ff5555")
            t.append(f"   마지막 {last:%m-%d %H:%M}", style="#7a7a7a")
            return t
        idx = self.idx_of.get(id(item))
        mark = "● " if idx in self.marked else "  "
        flag = Text("‼ ", style="bold #ff5555") if notif.is_problem(item) else Text("  ")
        body = item["body"].replace("\n", " ⏎ ")
        if self.list_width >= META_COLUMNS:
            t = Text(mark + f"{item['ts']:%m-%d %H:%M}  ", style="#9a9a9a")
            t.append(pad(item["app"], 14) + " ", style="#7aa2c7")
            t.append_text(flag)
            t.append(item["summary"])
            t.append((" — " + body) if body else "", style="#7a7a7a")
            return t
        t = Text(mark)
        t.append_text(flag)
        t.append(item["summary"])
        return t

    def refresh_list(self, reset: bool = False) -> None:
        """reset=True: 보기/필터가 바뀐 것이므로 선택 위치를 맨 위로(글자 입력 중에는 위치 유지)."""
        q = self.query()
        sel = notif.select(self.entries, app=self.app_filter, since=q["since"], urgent=q["urgent"], problems=q["problems"],
                           app_like=q["app_like"], words=q["words"])
        self.idx_of = {id(e): i for i, e in enumerate(self.entries)}
        self.shown = notif.group_by_app(list(reversed(sel))) if self.view == "앱별" and not self.app_filter else sel
        lst = self.query_one(NotifList)
        keep = 0 if reset else lst.highlighted
        lst.clear_options()
        lst.add_options([Option(self.row_text(x)) for x in self.shown])
        if self.shown:
            lst.highlighted = min(keep or 0, len(self.shown) - 1)
        else:
            self.query_one(Preview).load_text("")
            self.query_one("#meta-header", Static).update("")
        self.query_one(NotifList).border_title = "알림" if self.view != "앱별" or self.app_filter else "앱별 묶음"
        self.update_status()

    def update_status(self, extra: str = "") -> None:
        bits = [f"{len(self.shown)}/{len(self.entries)}개"]
        if self.view != "전체":
            bits.append(f"보기: {self.view}")
        if self.app_filter:
            bits.append(f"앱: {self.app_filter}")
        if self.marked:
            bits.append(f"체크 {len(self.marked)}개")
        if self.failed:
            bits.append(f"⚠ 실패한 서비스 {len(self.failed)}개 (F10)")
        if extra:
            bits.append(extra)
        self.query_one("#status", Static).update("  ·  ".join(bits))

    # ---------- 선택/미리보기 ----------
    def highlighted_item(self):
        lst = self.query_one(NotifList)
        if lst.highlighted is None or not (0 <= lst.highlighted < len(self.shown)):
            return None
        return self.shown[lst.highlighted]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_list()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        item = self.highlighted_item()
        preview, header = self.query_one(Preview), self.query_one("#meta-header", Static)
        if item is None:
            return
        if isinstance(item, tuple):
            app, n, k, last = item
            recent = notif.select(self.entries, app=app)[:8]
            header.update(Text(f"{app} · {n}건" + (f" · 긴급 {k}건" if k else "") + f" · 마지막 {last:%m-%d %H:%M}", style="bold #9a9a9a"))
            preview.load_text("최근 알림\n" + "\n".join(f"  {notif.one_line(e, 100)}" for e in recent) + "\n\nEnter: 이 앱의 알림만 보기")
            return
        same_app = sum(1 for e in self.entries if e["app"] == item["app"])
        same_title = sum(1 for e in self.entries if e["app"] == item["app"] and e["summary"] == item["summary"])
        first = Text(f"{item['ts']:%Y-%m-%d %H:%M:%S} · [{item['app']}] · 긴급도 {URGENCY.get(item['urgency'], '?')}"
                     + (" · 시스템 문제" if notif.is_problem(item) else ""), style="bold #9a9a9a")
        second = Text(f"같은 앱 {same_app}건 · 같은 제목 {same_title}건", style="#7aa2c7")
        header.update(Text("\n").join([first, second]))
        preview.load_text(item["summary"] + ("\n\n" + item["body"] if item["body"] else ""))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()                                        # 클릭은 선택만(복사는 Enter)
        item = self.highlighted_item()
        if isinstance(item, tuple):                         # 앱별 보기: 클릭으로 그 앱 안으로
            self.drill(item)

    # ---------- 동작 ----------
    def action_move(self, delta: int) -> None:
        lst = self.query_one(NotifList)
        if not self.shown:
            return
        cur = lst.highlighted if lst.highlighted is not None else 0
        lst.highlighted = max(0, min(len(self.shown) - 1, cur + delta))

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_escape(self) -> None:
        search = self.query_one("#search", Input)
        if search.value:
            search.value = ""
        elif self.marked:
            self.action_clear_marks()
        elif self.app_filter:
            self.app_filter = None
            self.refresh_list(reset=True)
        else:
            self.exit()

    def modal_open(self) -> bool:
        return isinstance(self.screen, ModalScreen)

    def action_copy_quit(self) -> None:
        screen = self.screen                                # Enter 는 우선순위 바인딩이라 대화상자에서도 여기로 옴
        if isinstance(screen, (InfoScreen, StatsScreen)):
            screen.dismiss(None)
            return
        item = self.highlighted_item()
        if isinstance(item, tuple):
            self.drill(item)
            return
        picked = [self.entries[i] for i in sorted(self.marked)] or ([item] if item else [])
        if not picked:
            return
        text = "\n\n".join(notif.entry_text(e) for e in picked)
        if notif.copy_text(text):
            self.exit()
        else:
            self.notify("복사 실패(wl-copy 없음)", severity="error")

    def drill(self, item) -> None:
        self.app_filter, self.view = item[0], "전체"
        self.refresh_list(reset=True)

    def action_copy_selection(self) -> None:
        sel = self.query_one(Preview).selected_text
        item = self.highlighted_item()
        if sel:
            ok = notif.copy_text(sel)
            self.notify(f"선택한 {len(sel)}자를 복사했습니다" if ok else "복사 실패", severity="information" if ok else "error")
        elif item and not isinstance(item, tuple):
            ok = notif.copy_text(notif.entry_text(item))
            self.notify("전체를 복사했습니다 (선택 영역이 없음)" if ok else "복사 실패", severity="information" if ok else "error")

    def toggle(self, i: int) -> None:
        self.marked.symmetric_difference_update({i})

    def action_toggle_mark(self) -> None:
        item = self.highlighted_item()
        if item is None or isinstance(item, tuple):
            return
        self.toggle(self.idx_of[id(item)])
        cur = self.query_one(NotifList).highlighted
        self.refresh_list()
        self.query_one(NotifList).highlighted = min((cur or 0) + 1, len(self.shown) - 1)

    def action_mark_all(self) -> None:
        if self.shown and not isinstance(self.shown[0], tuple):
            self.marked = {self.idx_of[id(e)] for e in self.shown}
            self.refresh_list()

    def action_clear_marks(self) -> None:
        self.marked = set()
        self.refresh_list()

    def action_cycle_view(self) -> None:
        self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
        self.app_filter = None
        self.refresh_list(reset=True)

    def action_same_app(self) -> None:
        item = self.highlighted_item()
        if self.app_filter:
            self.app_filter = None
        elif item is not None:
            self.app_filter = item[0] if isinstance(item, tuple) else item["app"]
            self.view = "전체" if self.view == "앱별" else self.view
        self.refresh_list(reset=True)

    def action_stats(self) -> None:
        if self.modal_open():
            return
        q = self.query()
        sel = notif.select(self.entries, app=self.app_filter, since=q["since"], urgent=q["urgent"], problems=q["problems"],
                           app_like=q["app_like"], words=q["words"])
        body = Text()
        for i, line in enumerate(notif.render_stats(notif.stats(sel)).splitlines()):
            body.append(line + "\n", style="bold #33ccff" if line and not line.startswith(" ") and i else "")
        self.push_screen(StatsScreen(body))

    def action_check_services(self) -> None:
        if self.modal_open():
            return
        r = notif.health()                                   # 새 실패는 알림으로 알리고 waybar 도 갱신
        self.failed = r["failed"]
        self.update_status()
        lines = [f"✗ {u} ({s})" for s, u in r["failed"]] or ["실패한 서비스가 없습니다."]
        self.push_screen(InfoScreen("서비스 점검 (시스템 + 사용자)", "\n".join(lines)))


def run(tab: str = "all") -> int:
    view = {"all": "전체", "apps": "앱별", "problems": "문제"}.get(tab, "전체")
    app = NotifUI(view)
    if tab == "stats":
        app.call_later(app.action_stats)
    app.run()
    return 0
