"""notif ui — 알림 센터(Textual). 본체 로직은 notif.py 를 그대로 쓴다(여기는 화면만).

  a 전체 / g 앱별 묶음 / p 문제 / s 통계   / 검색창에 글자 입력(앱·제목·본문)   r 새로고침
  Enter: 선택한 알림을 복사(제목+본문), c: 본문만 복사, 앱별 화면에서 Enter: 그 앱의 알림만 보기, q 종료
"""
import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Input, Static

import notif

TITLES = {"all": "전체 알림", "apps": "앱별 묶음", "problems": "시스템 문제", "stats": "통계"}


class NotifApp(App):
    CSS = """
    #q { height: 3; }
    #info { height: auto; padding: 0 1; color: $text-muted; }
    #stats { padding: 1 2; }
    DataTable { height: 1fr; }
    """
    BINDINGS = [
        Binding("a", "tab('all')", "전체"), Binding("g", "tab('apps')", "앱별"),
        Binding("p", "tab('problems')", "문제"), Binding("s", "tab('stats')", "통계"),
        Binding("c", "copy_body", "본문 복사"), Binding("r", "reload", "새로고침"), Binding("q", "quit", "종료"),
    ]

    def __init__(self, tab: str = "all"):
        super().__init__()
        self.tab = tab
        self.app_filter = None
        self.rows: list = []      # 현재 표에 보이는 알림(표의 행과 같은 순서)

    def compose(self) -> ComposeResult:
        yield Input(placeholder="검색(앱·제목·본문)", id="q")
        yield Static("", id="info")
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static("", id="stats")
        yield Footer()

    def on_mount(self) -> None:
        self.entries = notif.read_entries()
        self.refresh_view()

    def action_reload(self) -> None:
        self.entries = notif.read_entries()
        self.refresh_view()

    def action_tab(self, tab: str) -> None:
        self.tab, self.app_filter = tab, None
        self.refresh_view()

    def on_input_changed(self, _) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        q = self.query_one("#q", Input).value.strip() or None
        table, stats, info = self.query_one(DataTable), self.query_one("#stats", Static), self.query_one("#info", Static)
        table.clear(columns=True)
        self.rows = []
        now = datetime.datetime.now()
        since = now - datetime.timedelta(days=30)
        sel = notif.select(self.entries, app=self.app_filter, since=since, grep=q, problems=self.tab == "problems")
        table.display, stats.display = self.tab != "stats", self.tab == "stats"
        head = TITLES[self.tab] + (f" · 앱: {self.app_filter}" if self.app_filter else "") + f" · 최근 30일 {len(sel)}건"
        lines = [head]
        if self.tab == "stats":
            stats.update(notif.render_stats(notif.stats(sel)))
        elif self.tab == "apps" and not self.app_filter:
            table.add_columns("앱", "건수", "긴급", "마지막")
            for app, n, k, last in notif.group_by_app(sel):
                table.add_row(app, str(n), str(k) if k else "", f"{last:%m-%d %H:%M}", key=app)
        else:
            if self.tab == "problems":
                cur = notif.failed_units()
                lines.append("지금 실패한 서비스: " + (", ".join(f"{u}({s})" for s, u in cur) if cur else "없음"))
            table.add_columns("시각", "앱", "제목", "본문")
            self.rows = sel[:2000]
            for e in self.rows:
                table.add_row(f"{e['ts']:%m-%d %H:%M}", e["app"], ("‼ " if notif.is_problem(e) else "") + e["summary"], e["body"].replace("\n", " ⏎ ")[:200])
        info.update("\n".join(lines))
        if self.tab != "stats":
            table.focus()

    def on_data_table_row_selected(self, ev: DataTable.RowSelected) -> None:
        if self.tab == "apps" and not self.app_filter:
            self.app_filter = str(ev.row_key.value)
            self.refresh_view()
        elif self.rows:
            self.copy(False)

    def current(self):
        i = self.query_one(DataTable).cursor_row
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def copy(self, body_only: bool) -> None:
        e = self.current()
        if not e:
            return
        ok = notif.copy_text(notif.entry_text(e, body_only))
        self.notify("클립보드에 복사했습니다" if ok else "복사 실패(wl-copy 없음)", severity="information" if ok else "error")

    def action_copy_body(self) -> None:
        self.copy(True)


def run(tab: str = "all") -> int:
    NotifApp(tab).run()
    return 0
