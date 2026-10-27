"""notif ui — 알림 센터(Textual). clipui/displayui 와 같은 외형·조작 규약(검은 배경, 둥근 테두리: 포커스는 하늘색·제목은 테두리 안,
항상 입력 가능한 검색창, ↑↓ 이동, F키, Enter 로 복사하고 종료)을 따르되, 알림 센터답게 **왼쪽 그룹 패널**(전체 / 시스템 문제 / 앱별 건수)을
고르면 오른쪽에 그 그룹의 알림이 나오고 아래에 미리보기가 나온다. 본체 로직(읽기·검색어 해석·통계·장애 점검)은 notif.py — 여기는 화면만.

  왼쪽 그룹: 전체 · ‼ 시스템 문제 · 앱 이름(건수, 긴급이 있으면 ‼N) — ↑↓ 로 고르면 바로 오른쪽 목록이 바뀐다
  검색창: 글자(앱·제목·본문에 모두 포함)   app:이름   is:problem   is:urgent   since:3h|2d|1w   (그룹 건수도 검색에 맞춰 바뀜)
  Enter 현재 알림 복사 후 종료(그룹에서는 목록으로 이동)  Esc 검색 지우기 → 그룹을 '전체'로 → 종료  Tab 영역 이동  ←/→ 그룹↔목록
  F5 새로고침  F6 그룹 패널  F7 미리보기  F9 통계(지금 그룹/검색 기준)  F10 서비스 점검      목록에서: c 본문만 복사, g 그룹, / 검색, q 종료
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
import os
import sys

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib", "uikit"))
    import uikit

WIDE_COLUMNS = 80    # 이 폭 미만이면 그룹 패널을 숨김(F6 으로 다시 보임)
SHORT_ROWS = 16      # 이 높이 미만이면 미리보기를 숨김
META_COLUMNS = 50    # 목록 폭이 이 이상일 때만 시각/앱 열을 보여줌
GROUP_WIDTH = 30
URGENCY = {0: "낮음", 1: "보통", 2: "긴급", None: "알 수 없음"}
ALL, PROBLEMS = "all", "problems"


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

    def __init__(self, title: str, renderable) -> None:
        super().__init__()
        self.title_text, self.renderable = title, renderable

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Label(self.title_text, id="dialog-title")
            with VerticalScroll(id="stats-scroll"):
                yield Static(self.renderable, id="stats-body")
            yield Label("[Esc/Enter] 닫기", id="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class GroupList(OptionList):
    BINDINGS = [
        Binding("right", "app.focus_list", "목록", show=False),
        Binding("slash", "app.focus_search", "검색", show=False),
        Binding("q", "app.quit", "종료", show=False),
    ]


class NotifList(OptionList):
    BINDINGS = [
        Binding("left", "app.focus_groups", "그룹", show=False),
        Binding("g", "app.focus_groups", "그룹", show=False),
        Binding("c", "app.copy_body", "본문 복사", show=False),
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


class NotifUI(uikit.HelpMixin, App):
    HELP_TERMS = [   # ? 도움말의 「용어·사용법」 — 별도 용어 탭 대신(uikit 공통 규칙)
        ('그룹', '왼쪽: 전체 · ‼ 시스템 문제 · 앱 이름(건수, 긴급이 있으면 ‼N). ↑↓ 로 고르면 오른쪽 목록이 바로 바뀐다'),
        ('검색 문법', '글자(앱·제목·본문에 모두 포함) · app:이름 · is:problem · is:urgent · since:3h|2d|1w — 그룹 건수도 검색에 맞춰 바뀐다'),
        ('Enter / Esc', 'Enter = 현재 알림 복사 후 종료(그룹에서는 목록으로). Esc = 검색 지우기 → 그룹을 「전체」로 → 종료'),
        ('영역 이동', 'Tab, ←/→ 로 그룹 ↔ 목록. 목록에서 c 본문만 복사 · g 그룹 · / 검색'),
        ('F 키', 'F5 새로고침 · F6 그룹 패널 · F7 미리보기 · F9 통계(지금 그룹/검색 기준) · F10 서비스 점검'),
    ]
    HELP_NOTES = [
        '검색창이 기본 포커스라 q 는 글자로 들어간다 — 종료는 Esc(여러 번) 또는 목록에서 q',
    ]
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    #search { background: #000000; border: round #595959; }
    #search:focus { border: round #33ccff; }
    #main { height: 1fr; layout: horizontal; }
    GroupList { width: 30; height: 1fr; background: #000000; border: round #595959; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis; }
    GroupList:focus { border: round #33ccff; }
    #main.narrow GroupList, #main.hide-groups GroupList { display: none; }
    #right { width: 1fr; height: 1fr; layout: vertical; }
    NotifList { width: 100%; height: 3fr; background: #000000; border: round #595959; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis; }
    NotifList:focus { border: round #33ccff; }
    #preview-box { width: 100%; height: 2fr; layout: vertical; }
    #meta-header { height: auto; max-height: 4; padding: 0 1; color: #9a9a9a; background: #000000; }
    Preview { width: 100%; height: 1fr; background: #000000; border: round #595959; }
    Preview:focus { border: round #33ccff; }
    #main.short #preview-box, #main.hide-preview #preview-box { display: none; }
    #main.short NotifList, #main.hide-preview NotifList { height: 1fr; }
    """

    BINDINGS = [
        *uikit.HelpMixin.HELP_BINDINGS,
        Binding("enter", "copy_quit", "복사", priority=True),
        Binding("escape", "escape", "지우기/종료"),
        Binding("down", "move(1)", "아래", show=False),
        Binding("up", "move(-1)", "위", show=False),
        Binding("pagedown", "move(10)", "", show=False),
        Binding("pageup", "move(-10)", "", show=False),
        Binding("f5", "reload", "새로고침"),
        Binding("f6", "toggle_groups", "그룹패널"),
        Binding("f7", "toggle_preview", "미리보기"),
        Binding("f9", "stats", "통계"),
        Binding("f10", "check_services", "서비스점검"),
        Binding("ctrl+q", "quit", "종료", show=False),
    ]

    def __init__(self, group: str = ALL) -> None:
        super().__init__()
        self.group = group              # ALL / PROBLEMS / "app:이름"
        self.entries: list = []
        self.shown: list = []           # 오른쪽 목록에 보이는 알림
        self.group_keys: list = []      # 그룹 패널 행의 키(행 순서와 같음)
        self.failed: list = []
        self.building = False           # 그룹 패널을 다시 채우는 동안은 선택 이벤트를 무시
        self.list_width = 80

    # ---------- 화면 구성 ----------
    def compose(self) -> ComposeResult:
        yield Input(placeholder="검색 — 앱·제목·본문   필터: app:이름  is:problem  is:urgent  since:3h   (Enter: 복사)", id="search")
        with Container(id="main"):
            yield GroupList(id="groups")
            with Vertical(id="right"):
                yield NotifList(id="list")
                with Vertical(id="preview-box"):
                    yield Static("", id="meta-header")
                    yield Preview("", read_only=True, soft_wrap=True, show_line_numbers=False, id="preview")
        with Horizontal(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(GroupList).border_title = "그룹"
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
        groups = width >= WIDE_COLUMNS and not main.has_class("hide-groups")
        new = width - (GROUP_WIDTH if groups else 0) - 4
        changed = (new >= META_COLUMNS) != (self.list_width >= META_COLUMNS)
        self.list_width = new
        if changed and self.entries:
            self.refresh_list()

    def action_toggle_groups(self) -> None:
        main = self.query_one("#main")
        main.set_class(not main.has_class("hide-groups"), "hide-groups")
        self.apply_layout(self.size.width, self.size.height)

    def action_toggle_preview(self) -> None:
        main = self.query_one("#main")
        main.set_class(not main.has_class("hide-preview"), "hide-preview")
        self.apply_layout(self.size.width, self.size.height)

    # ---------- 데이터 ----------
    def reload(self) -> None:
        self.entries = notif.read_entries()
        self.failed = notif.failed_units()
        self.refresh_all()

    def action_reload(self) -> None:
        self.reload()
        self.notify("새로고침했습니다")

    def search(self) -> dict:
        return notif.parse_query(self.query_one("#search", Input).value, datetime.datetime.now())

    def select(self, q: dict, group=None) -> list:
        """검색창 조건 + 그룹 조건으로 거른 알림(가장 나중에 기록된 것이 앞)."""
        group = self.group if group is None else group
        return notif.select(self.entries, app=group[4:] if group.startswith("app:") else None, since=q["since"], urgent=q["urgent"],
                            problems=q["problems"] or group == PROBLEMS, app_like=q["app_like"], words=q["words"])

    def refresh_all(self) -> None:
        """검색이 바뀌면 그룹 건수도 바뀐다 → 그룹 패널과 목록을 모두 다시 그림."""
        q = self.search()
        base = notif.select(self.entries, since=q["since"], urgent=q["urgent"], problems=q["problems"], app_like=q["app_like"], words=q["words"])
        apps = notif.group_by_app(list(reversed(base)))
        problems = sum(1 for e in base if notif.is_problem(e))
        warn = Text("‼ ", style="bold #ff5555")
        rows = [(ALL, Text(pad("전체", GROUP_WIDTH - 13) + f"{len(base):>6}")),
                (PROBLEMS, warn + Text(pad("시스템 문제", GROUP_WIDTH - 14) + f"{problems:>6}"))]
        for app, n, k, _ in apps:
            t = Text(pad(app, GROUP_WIDTH - 13) + f"{n:>6}")      # 패널 안쪽 폭 26칸 = 이름 17 + 건수 6 + 「 ‼N」 3 — 이전엔 1칸 넘쳐 긴급 건수가 …로 잘렸다
            if k:
                t.append(f" ‼{k}", style="bold #ff5555")
            rows.append(("app:" + app, t))
        if not any(k == self.group for k, _ in rows):
            self.group = ALL
        self.group_keys = [k for k, _ in rows]
        groups = self.query_one(GroupList)
        self.building = True
        groups.clear_options()
        groups.add_options([Option(t) for _, t in rows])
        groups.highlighted = self.group_keys.index(self.group)
        self.building = False
        self.refresh_list()

    def row_text(self, e: dict) -> Text:
        flag = Text("‼ ", style="bold #ff5555") if notif.is_problem(e) else Text("  ")
        body = e["body"].replace("\n", " ⏎ ")
        show_app = not self.group.startswith("app:")        # 앱 그룹 안에서는 앱 열이 필요 없음
        if self.list_width >= META_COLUMNS:
            t = Text(f"{e['ts']:%m-%d %H:%M}  ", style="#9a9a9a")
            if show_app:
                t.append(pad(e["app"], 14) + " ", style="#7aa2c7")
            t.append_text(flag)
            t.append(e["summary"])
            t.append((" — " + body) if body else "", style="#7a7a7a")
            return t
        t = Text()
        t.append_text(flag)
        t.append(e["summary"])
        return t

    def refresh_list(self) -> None:
        self.shown = self.select(self.search())
        lst = self.query_one(NotifList)
        lst.clear_options()
        lst.add_options([Option(self.row_text(e)) for e in self.shown])
        if self.shown:
            lst.highlighted = 0
        else:
            self.query_one(Preview).load_text("")
            self.query_one("#meta-header", Static).update("")
        title = {ALL: "전체", PROBLEMS: "시스템 문제"}.get(self.group, self.group[4:])
        lst.border_title = f"알림 · {title}"
        self.update_status()

    def update_status(self, extra: str = "") -> None:
        bits = [f"{len(self.shown)}/{len(self.entries)}개"]
        if self.group != ALL:
            bits.append("그룹: " + {PROBLEMS: "시스템 문제"}.get(self.group, self.group[4:]))
        if self.failed:
            bits.append(f"⚠ 실패한 서비스 {len(self.failed)}개 (F10)")
        if extra:
            bits.append(extra)
        self.query_one("#status", Static).update("  ·  ".join(bits))

    # ---------- 선택/미리보기 ----------
    def highlighted_entry(self):
        lst = self.query_one(NotifList)
        if lst.highlighted is None or not (0 <= lst.highlighted < len(self.shown)):
            return None
        return self.shown[lst.highlighted]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_all()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "groups":
            idx = event.option_index
            if self.building or idx is None or not (0 <= idx < len(self.group_keys)):
                return
            if self.group_keys[idx] != self.group:
                self.group = self.group_keys[idx]
                self.refresh_list()
            return
        e = self.highlighted_entry()
        if e is None:
            return
        same_app = sum(1 for x in self.entries if x["app"] == e["app"])
        same_title = sum(1 for x in self.entries if x["app"] == e["app"] and x["summary"] == e["summary"])
        first = Text(f"{e['ts']:%Y-%m-%d %H:%M:%S} · [{e['app']}] · 긴급도 {URGENCY.get(e['urgency'], '?')}"
                     + (" · 시스템 문제" if notif.is_problem(e) else ""), style="bold #9a9a9a")
        second = Text(f"같은 앱 {same_app}건 · 같은 제목 {same_title}건", style="#7aa2c7")
        self.query_one("#meta-header", Static).update(Text("\n").join([first, second]))
        self.query_one(Preview).load_text(e["summary"] + ("\n\n" + e["body"] if e["body"] else ""))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()                                        # 클릭은 선택만(복사는 Enter). 그룹을 클릭하면 오른쪽 목록으로 포커스
        if event.option_list.id == "groups":
            self.action_focus_list()

    # ---------- 동작 ----------
    def action_move(self, delta: int) -> None:
        """↑↓: 그룹 패널에 포커스가 있으면 그룹을, 그 외(검색창 포함)에는 알림 목록을 움직인다."""
        groups = self.query_one(GroupList)
        target = groups if self.focused is groups else self.query_one(NotifList)
        n = len(self.group_keys) if target is groups else len(self.shown)
        if not n:
            return
        cur = target.highlighted if target.highlighted is not None else 0
        target.highlighted = max(0, min(n - 1, cur + delta))

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_focus_groups(self) -> None:
        main = self.query_one("#main")
        if not (main.has_class("narrow") or main.has_class("hide-groups")):
            self.query_one(GroupList).focus()

    def action_focus_list(self) -> None:
        self.query_one(NotifList).focus()

    def action_escape(self) -> None:
        search = self.query_one("#search", Input)
        if search.value:
            search.value = ""
        elif self.group != ALL:
            self.group = ALL
            self.refresh_all()
        else:
            self.exit()

    def action_copy_quit(self) -> None:
        screen = self.screen                                # Enter 는 우선순위 바인딩이라 대화상자에서도 여기로 옴
        if isinstance(screen, ModalScreen):
            screen.dismiss(None)
            return
        if self.focused is self.query_one(GroupList):       # 그룹에서 Enter: 그 그룹의 알림 목록으로
            self.action_focus_list()
            return
        e = self.highlighted_entry()
        if e is None:
            return
        if notif.copy_text(notif.entry_text(e)):
            self.exit()
        else:
            self.notify("복사 실패(wl-copy 없음)", severity="error")

    def action_copy_body(self) -> None:
        e = self.highlighted_entry()
        if e:
            ok = notif.copy_text(notif.entry_text(e, True))
            self.notify("본문을 복사했습니다" if ok else "복사 실패(wl-copy 없음)", severity="information" if ok else "error")

    def action_copy_selection(self) -> None:
        sel = self.query_one(Preview).selected_text
        e = self.highlighted_entry()
        if sel:
            ok = notif.copy_text(sel)
            self.notify(f"선택한 {len(sel)}자를 복사했습니다" if ok else "복사 실패", severity="information" if ok else "error")
        elif e:
            ok = notif.copy_text(notif.entry_text(e))
            self.notify("전체를 복사했습니다 (선택 영역이 없음)" if ok else "복사 실패", severity="information" if ok else "error")

    def action_stats(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        title = "알림 통계 — " + {ALL: "전체", PROBLEMS: "시스템 문제"}.get(self.group, self.group[4:])
        body = Text()
        for i, line in enumerate(notif.render_stats(notif.stats(self.select(self.search()))).splitlines()):
            body.append(line + "\n", style="bold #33ccff" if line and not line.startswith(" ") and i else "")
        self.push_screen(StatsScreen(title, body))

    def action_check_services(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        r = notif.health()                                   # 새 실패는 알림으로 알리고 waybar 도 갱신
        self.failed = r["failed"]
        self.update_status()
        lines = [f"✗ {u} ({s})" for s, u in r["failed"]] or ["실패한 서비스가 없습니다."]
        self.push_screen(InfoScreen("서비스 점검 (시스템 + 사용자)", "\n".join(lines)))


def run(tab: str = "all") -> int:
    app = NotifUI(PROBLEMS if tab == "problems" else ALL)
    if tab == "stats":
        app.call_later(app.action_stats)
    elif tab == "apps":
        app.call_later(app.action_focus_groups)
    app.run()
    return 0
