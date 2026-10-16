#!/usr/bin/env python3
"""clipui — cliphist 클립보드 이력 관리 TUI (Textual)

검색(퍼지 + 항목 내용 전체), 전문 미리보기와 부분 복사, 체크 후 일괄 삭제, 통계, DB 최적화.
창 크기에 따라 배치가 바뀌는 반응형 레이아웃 (htop 처럼).
(Nix 가 @...@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/clipboard-menu.nix)
"""
from __future__ import annotations

import os
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    ProgressBar,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

CLIPHIST = os.environ.get("CLIPUI_CLIPHIST", "@cliphist@")
CLIPCTL = os.environ.get("CLIPUI_CLIPCTL", "@clipctl@")
COPY_CMD = os.environ.get("CLIPUI_COPY", "@wlcopy@")
DB = os.environ.get("CLIPHIST_DB") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cliphist", "db"
)
PREVIEW_WIDTH = 300
WIDE_COLUMNS = 110  # 이 폭 이상이면 목록/미리보기를 좌우로, 미만이면 위아래로
SHORT_ROWS = 16  # 이 높이 미만이면 미리보기를 숨김
MATCH_STYLE = "bold #cb4b16"  # fuzzel/wofi 시절 일치 글자 색


def human(n: int) -> str:
    size = float(max(n, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"


def cliphist(*args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([CLIPHIST, "-db-path", DB, *args], input=data, capture_output=True)


@dataclass
class Entry:
    id: int
    preview: str
    size: int = -1
    text: str | None = None
    lower: str = ""


def load_entries() -> list[Entry]:
    out = cliphist("-preview-width", str(PREVIEW_WIDTH), "list").stdout.decode("utf-8", "replace")
    entries: list[Entry] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        ident, _, preview = line.partition("\t")
        try:
            entries.append(Entry(int(ident), preview))
        except ValueError:
            continue
    return entries


def fetch_raw(entry_id: int) -> bytes:
    return cliphist("decode", str(entry_id)).stdout


def match(query: str, text: str):
    """(점수, 일치 위치) 또는 None. 대소문자 무시. 연속 일치를 우선하고, 아니면 순서만 맞는 부분수열."""
    if not query:
        return (0.0, [])
    q, t = query.lower(), text.lower()
    i = t.find(q)
    if i >= 0:
        bonus = 3.0 if i == 0 else (2.0 if t[i - 1] in " /-_.:" else 0.0)
        return (100.0 + bonus - i * 0.01, list(range(i, i + len(q))))
    positions: list[int] = []
    j = 0
    score = 50.0
    last = -2
    for ch in q:
        k = t.find(ch, j)
        if k < 0:
            return None
        positions.append(k)
        score += (2.0 if k == last + 1 else 0.0) - (k - j) * 0.01
        last = k
        j = k + 1
    return (score, positions)


def copy_bytes(data: bytes) -> None:
    subprocess.run(shlex.split(COPY_CMD), input=data, check=False)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "예"),
        Binding("enter", "answer(True)", "예", show=False),
        Binding("n", "answer(False)", "아니오"),
        Binding("escape", "answer(False)", "취소", show=False),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message, id="dialog-text")
            yield Label("[y/Enter] 예   [n/Esc] 아니오", id="dialog-hint")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class InfoScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "닫기"),
        Binding("q", "close", "닫기", show=False),
        Binding("enter", "close", "닫기", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            yield Static(self.body, id="dialog-body")
            yield Label("[Esc/Enter] 닫기", id="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class BusyScreen(ModalScreen[None]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message, id="dialog-text")
            yield LoadingIndicator()


class ClipList(OptionList):
    BINDINGS = [
        Binding("space", "app.toggle_mark", "표시", show=False),
        Binding("a", "app.mark_all", "전체 표시", show=False),
        Binding("u", "app.clear_marks", "표시 해제", show=False),
        Binding("d", "app.delete", "삭제", show=False),
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


class ClipUI(App):
    TITLE = "클립보드"
    ENABLE_COMMAND_PALETTE = False  # 푸터의 ^p palette 안내 숨김 (쓰지 않음)

    CSS = """
    Screen { background: #000000; }
    #search { background: #000000; border: round #595959; }
    #search:focus { border: round #33ccff; }
    #main { height: 1fr; layout: horizontal; }
    #main.narrow { layout: vertical; }
    ClipList { width: 1fr; height: 1fr; background: #000000; border: round #595959; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis; }
    ClipList:focus { border: round #33ccff; }
    ClipList > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    ClipList:focus > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    Preview { width: 1fr; height: 1fr; background: #000000; border: round #595959; }
    Preview:focus { border: round #33ccff; }
    #main.narrow ClipList { width: 100%; height: 3fr; }
    #main.narrow Preview { width: 100%; height: 2fr; }
    #main.short Preview { display: none; }
    #main.short ClipList { width: 100%; }
    #main.hide-preview Preview { display: none; }
    #main.hide-preview ClipList { width: 100%; height: 1fr; }
    #status-row { height: 1; }
    #status { width: 1fr; color: #9a9a9a; padding: 0 1; }
    #progress { width: 30; display: none; }
    #progress.active { display: block; }
    ConfirmScreen, InfoScreen, BusyScreen { align: center middle; }
    #dialog { width: 70%; max-width: 90; height: auto; background: #101010; border: round #33ccff; padding: 1 2; }
    #dialog-title { text-style: bold; padding-bottom: 1; }
    #dialog-hint { color: #7a7a7a; padding-top: 1; }
    """

    BINDINGS = [
        Binding("enter", "copy_quit", "복사", priority=True),
        Binding("escape", "escape", "지우기/종료"),
        Binding("down", "move(1)", "아래", show=False),
        Binding("up", "move(-1)", "위", show=False),
        Binding("pagedown", "move(10)", "", show=False),
        Binding("pageup", "move(-10)", "", show=False),
        Binding("f2", "toggle_mark", "표시"),
        Binding("f3", "mark_all", "전체표시"),
        Binding("f4", "clear_marks", "해제"),
        Binding("f5", "reload", "새로고침"),
        Binding("f6", "toggle_sort", "정렬"),
        Binding("f7", "toggle_preview", "미리보기"),
        Binding("f8", "delete", "삭제"),
        Binding("delete", "delete", "삭제", show=False),
        Binding("f9", "stats", "통계"),
        Binding("f10", "compact", "최적화"),
        Binding("ctrl+q", "quit", "종료", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[Entry] = []
        self.by_id: dict[int, Entry] = {}
        self.shown: list[Entry] = []
        self.marked: set[int] = set()
        self.sort_size = False
        self.generation = 0
        self.indexed = 0
        self.indexing = False
        self.current_id: int | None = None

    # ---------- 화면 구성 ----------
    def compose(self) -> ComposeResult:
        yield Input(placeholder="검색 — 내용 전체에서도 찾습니다   (Enter: 복사, ↑↓: 이동)", id="search")
        with Container(id="main"):
            yield ClipList(id="list")
            yield Preview("", read_only=True, soft_wrap=True, show_line_numbers=False, id="preview")
        with Horizontal(id="status-row"):
            yield Static("", id="status")
            yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="progress")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search", Input).focus()
        self.apply_layout(self.size.width, self.size.height)
        self.reload()

    # ---------- 반응형 ----------
    def on_resize(self, event: events.Resize) -> None:
        self.apply_layout(event.size.width, event.size.height)

    def apply_layout(self, width: int, height: int) -> None:
        main = self.query_one("#main")
        main.set_class(width < WIDE_COLUMNS, "narrow")
        main.set_class(height < SHORT_ROWS, "short")

    def action_toggle_preview(self) -> None:
        main = self.query_one("#main")
        main.set_class(not main.has_class("hide-preview"), "hide-preview")

    # ---------- 데이터 ----------
    def reload(self, keep_cache: bool = True) -> None:
        old = self.by_id if keep_cache else {}
        self.entries = load_entries()
        for entry in self.entries:
            cached = old.get(entry.id)
            if cached is not None and cached.preview == entry.preview and cached.text is not None:
                entry.size, entry.text, entry.lower = cached.size, cached.text, cached.lower
        self.by_id = {e.id: e for e in self.entries}
        self.marked &= set(self.by_id)
        self.refresh_list()
        self.index_contents()

    @work(thread=True, exclusive=True, group="index")
    def index_contents(self) -> None:
        """모든 항목의 전문을 병렬로 읽어 크기/내용 검색용 캐시를 만든다 (진행 표시줄 포함)."""
        self.generation += 1
        gen = self.generation
        todo = [e for e in self.entries if e.text is None]
        total = len(self.entries)
        done = total - len(todo)
        self.call_from_thread(self.index_begin, done, total)

        def fetch(entry: Entry) -> None:
            if gen != self.generation:
                return
            raw = fetch_raw(entry.id)
            entry.size = len(raw)
            entry.text = raw.decode("utf-8", "replace")
            entry.lower = entry.text.lower()

        with ThreadPoolExecutor(max_workers=8) as pool:
            for count, _ in enumerate(pool.map(fetch, todo), start=1):
                if gen != self.generation:
                    return
                if count % 25 == 0 or count == len(todo):
                    self.call_from_thread(self.index_progress, done + count, total)
        if gen == self.generation:
            self.call_from_thread(self.index_end)

    def index_begin(self, done: int, total: int) -> None:
        self.indexing = bool(total - done)
        bar = self.query_one("#progress", ProgressBar)
        if self.indexing:
            bar.update(total=total, progress=done)
            bar.add_class("active")
        self.update_status()

    def index_progress(self, done: int, total: int) -> None:
        self.indexed = done
        self.query_one("#progress", ProgressBar).update(total=total, progress=done)
        self.update_status(f"내용 색인 중 {done}/{total}")

    def index_end(self) -> None:
        self.indexing = False
        self.query_one("#progress", ProgressBar).remove_class("active")
        self.refresh_list()  # 내용 검색이 가능해졌으므로 다시 필터링

    # ---------- 목록 ----------
    def row_text(self, entry: Entry, positions: list[int]) -> Text:
        mark = "[x]" if entry.id in self.marked else "[ ]"
        size = human(entry.size) if entry.size >= 0 else "…"
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f"{mark} ", style="bold #33ccff" if entry.id in self.marked else "#595959")
        text.append(f"{size:>7} ", style="#9a9a9a")
        preview = entry.preview.replace("\t", " ")
        start = len(text.plain)
        text.append(preview)
        for pos in positions:
            if pos < len(preview):
                text.stylize(MATCH_STYLE, start + pos, start + pos + 1)
        return text

    def refresh_list(self) -> None:
        query = self.query_one("#search", Input).value.strip()
        tokens = [t.lower() for t in query.split()]
        rows: list[tuple[float, Entry, list[int]]] = []
        for entry in self.entries:
            if not query:
                rows.append((0.0, entry, []))
                continue
            hit = match(query, entry.preview)
            if hit is None and entry.text is not None and tokens and all(t in entry.lower for t in tokens):
                hit = (10.0, [])
            if hit is not None:
                rows.append((hit[0], entry, hit[1]))
        if query:
            rows.sort(key=lambda r: -r[0])
        elif self.sort_size:
            rows.sort(key=lambda r: -r[1].size)
        self.shown = [r[1] for r in rows]

        lst = self.query_one("#list", ClipList)
        keep = self.current_id
        lst.clear_options()
        lst.add_options([Option(self.row_text(e, pos), id=str(e.id)) for _, e, pos in rows])
        if self.shown:
            index = next((i for i, e in enumerate(self.shown) if e.id == keep), 0)
            lst.highlighted = index
        else:
            self.query_one("#preview", Preview).load_text("")
            self.current_id = None
        self.update_status()

    def update_status(self, extra: str = "") -> None:
        bits = [f"{len(self.shown)}/{len(self.entries)}개"]
        if self.marked:
            bits.append(f"표시 {len(self.marked)}개")
        if self.sort_size:
            bits.append("크기순")
        if self.current_id is not None and self.current_id in self.by_id:
            cur = self.by_id[self.current_id]
            if cur.size >= 0:
                bits.append(f"#{cur.id} · {human(cur.size)}")
            else:
                bits.append(f"#{cur.id}")
        if extra:
            bits.append(extra)
        elif self.indexing:
            bits.append("내용 색인 중…")
        self.query_one("#status", Static).update("  ·  ".join(bits))

    def highlighted_entry(self) -> Entry | None:
        lst = self.query_one("#list", ClipList)
        if lst.highlighted is None or not (0 <= lst.highlighted < len(self.shown)):
            return None
        return self.shown[lst.highlighted]

    # ---------- 이벤트 ----------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_list()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id is None:
            return
        entry = self.by_id.get(int(event.option_id))
        if entry is None:
            return
        self.current_id = entry.id
        if entry.text is None:
            raw = fetch_raw(entry.id)
            entry.size = len(raw)
            entry.text = raw.decode("utf-8", "replace")
            entry.lower = entry.text.lower()
        self.query_one("#preview", Preview).load_text(entry.text)
        self.update_status()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()  # 클릭은 선택만 (복사는 Enter)

    # ---------- 동작 ----------
    def action_move(self, delta: int) -> None:
        lst = self.query_one("#list", ClipList)
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
        else:
            self.exit()

    def action_copy_quit(self) -> None:
        # Enter 는 우선순위 바인딩이라 대화상자에서도 여기로 오므로, 대화상자에서는 그 화면의 동작으로 넘긴다
        screen = self.screen
        if isinstance(screen, ConfirmScreen):
            screen.dismiss(True)
            return
        if isinstance(screen, InfoScreen):
            screen.dismiss(None)
            return
        if isinstance(screen, ModalScreen):
            return
        entry = self.highlighted_entry()
        if entry is None:
            return
        copy_bytes(fetch_raw(entry.id))
        self.exit()

    def action_copy_selection(self) -> None:
        preview = self.query_one("#preview", Preview)
        selected = preview.selected_text
        entry = self.by_id.get(self.current_id) if self.current_id is not None else None
        if selected:
            copy_bytes(selected.encode())
            self.notify(f"선택한 {len(selected)}자를 복사했습니다")
        elif entry is not None:
            copy_bytes(fetch_raw(entry.id))
            self.notify("전체를 복사했습니다 (선택 영역이 없음)")

    def action_toggle_mark(self) -> None:
        entry = self.highlighted_entry()
        if entry is None:
            return
        self.marked ^= {entry.id}
        self.refresh_list()
        self.action_move(1)

    def action_mark_all(self) -> None:
        self.marked |= {e.id for e in self.shown}
        self.refresh_list()

    def action_clear_marks(self) -> None:
        self.marked.clear()
        self.refresh_list()

    def action_toggle_sort(self) -> None:
        self.sort_size = not self.sort_size
        self.refresh_list()

    def action_reload(self) -> None:
        self.reload()

    def action_delete(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        targets = list(self.marked) or ([self.current_id] if self.current_id is not None else [])
        targets = [t for t in targets if t in self.by_id]
        if not targets:
            return
        total = sum(max(self.by_id[t].size, 0) for t in targets)
        what = f"표시한 {len(targets)}개" if self.marked else f"#{targets[0]}"
        message = f"{what} 항목({human(total)})을 삭제할까요?\n되돌릴 수 없습니다."

        def done(answer: bool | None) -> None:
            if not answer:
                return
            lines = "".join(f"{t}\t{self.by_id[t].preview}\n" for t in targets).encode()
            cliphist("delete", data=lines)
            self.marked -= set(targets)
            self.notify(f"{len(targets)}개를 삭제했습니다")
            self.reload()

        self.push_screen(ConfirmScreen(message), done)

    def action_stats(self) -> None:
        known = [e for e in self.entries if e.size >= 0]
        total = sum(e.size for e in known)
        try:
            db_size = os.path.getsize(DB)
        except OSError:
            db_size = 0
        lines = [
            f"항목 수        {len(self.entries)}개" + ("" if len(known) == len(self.entries) else f"  (크기 확인 {len(known)}개, 색인 중)"),
            f"내용 총 크기   {human(total)}",
            f"DB 파일 크기   {human(db_size)}",
        ]
        if db_size > total * 3 + 1048576:
            lines.append("→ DB 가 내용보다 훨씬 큽니다. F10 으로 최적화할 수 있습니다.")
        lines += ["", "큰 항목 TOP 5"]
        for e in sorted(known, key=lambda x: -x.size)[:5]:
            lines.append(f"  #{e.id:<5} {human(e.size):>8}  {e.preview[:50]}")
        self.push_screen(InfoScreen("클립보드 통계", "\n".join(lines)))

    def action_compact(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        message = "DB 를 새로 구성합니다.\n백업이 자동으로 만들어지고 이력 번호는 새로 매겨집니다.\n수 초 걸리며 그동안 새 복사는 기록되지 않습니다."

        def done(answer: bool | None) -> None:
            if answer:
                self.push_screen(BusyScreen("DB 를 최적화하는 중…"))
                self.run_compact()

        self.push_screen(ConfirmScreen(message), done)

    @work(thread=True)
    def run_compact(self) -> None:
        env = dict(os.environ, CLIPHIST_DB=DB)
        result = subprocess.run([CLIPCTL, "compact"], capture_output=True, env=env)
        output = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
        self.call_from_thread(self.compact_done, output)

    def compact_done(self, output: str) -> None:
        self.pop_screen()  # BusyScreen
        self.marked.clear()
        self.reload(keep_cache=False)  # 번호가 새로 매겨졌으므로 캐시 폐기
        self.push_screen(InfoScreen("DB 최적화 결과", output or "(출력 없음)"))


def main() -> None:
    ClipUI().run()


if __name__ == "__main__":
    main()
