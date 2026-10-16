#!/usr/bin/env python3
"""clipui — cliphist 클립보드 이력 관리 TUI (Textual)

검색(퍼지 + 항목 내용 전체 + 필터), 전문 미리보기와 부분 복사, 체크 후 일괄 삭제, 통계, DB 최적화.
저장 시점의 시각·출처 앱·복사/사용 횟수(clipmeta 사이드카)를 함께 보여준다.
창 크기에 따라 배치가 바뀌는 반응형 레이아웃 (htop 처럼).
(Nix 가 @...@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/clipboard-menu.nix)
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from rich.cells import cell_len
from rich.console import Group
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
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

import clipmeta

CLIPCTL = os.environ.get("CLIPUI_CLIPCTL", "@clipctl@")
COPY_CMD = os.environ.get("CLIPUI_COPY", "@wlcopy@")
CLIPHIST = clipmeta.CLIPHIST
DB = clipmeta.DB
PREVIEW_WIDTH = 300
WIDE_COLUMNS = 110  # 이 폭 이상이면 목록/미리보기를 좌우로, 미만이면 위아래로
SHORT_ROWS = 16  # 이 높이 미만이면 미리보기를 숨김
META_COLUMNS = 60  # 목록 폭이 이 이상일 때만 시각/앱 열을 보여줌
MATCH_STYLE = "bold #cb4b16"  # fuzzel/wofi 시절 일치 글자 색
SORT_MODES = ["최신순", "크기순", "많이 쓴 순", "많이 복사된 순", "오래된 순"]

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(password|passwd|비밀번호|secret|token|api[_-]?key|authorization)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
]


def looks_sensitive(text: str) -> bool:
    return any(p.search(text) for p in SENSITIVE_PATTERNS)


def human(n: int) -> str:
    size = float(max(n, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"


def rel_time(ts: int | None, now: float | None = None) -> str:
    if not ts:
        return "—"
    delta = int((now or time.time()) - ts)
    if delta < 60:
        return "방금"
    if delta < 3600:
        return f"{delta // 60}분 전"
    if delta < 86400:
        return f"{delta // 3600}시간 전"
    if delta < 172800:
        return "어제"
    if delta < 86400 * 30:
        return f"{delta // 86400}일 전"
    return datetime.fromtimestamp(ts).strftime("%m-%d")


def abs_time(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "—"


def pad(text: str, width: int, right: bool = False) -> str:
    """셀 폭(한글은 2칸) 기준으로 자르고 채운다."""
    while cell_len(text) > width:
        text = text[:-1]
    gap = " " * (width - cell_len(text))
    return gap + text if right else text + gap


def bar(value: int, maximum: int, width: int = 24) -> str:
    if maximum <= 0 or value <= 0:
        return ""
    return "█" * max(1, round(value / maximum * width))


def cliphist(*args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    return clipmeta.cliphist(*args, data=data)


@dataclass
class Entry:
    id: int
    preview: str
    size: int = -1
    text: str | None = None
    lower: str = ""
    digest: str = ""


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


SIZE_TOKEN = re.compile(r"^([<>])(\d+(?:\.\d+)?)([kKmM]?)[bB]?$")


def parse_query(raw: str) -> tuple[list[tuple], str]:
    """검색어에서 필터(app:이름, >10k, <1k, is:sensitive, is:multi, is:dup)를 분리하고 나머지는 글자 검색어로."""
    filters: list[tuple] = []
    words: list[str] = []
    for token in raw.split():
        low = token.lower()
        m = SIZE_TOKEN.match(token)
        if low.startswith("app:") and len(token) > 4:
            filters.append(("app", low[4:]))
        elif m:
            mult = {"": 1, "k": 1024, "m": 1024 * 1024}[m.group(3).lower()]
            filters.append(("size", m.group(1), int(float(m.group(2)) * mult)))
        elif low in ("is:sensitive", "is:민감"):
            filters.append(("sensitive",))
        elif low in ("is:multi", "is:여러줄"):
            filters.append(("multi",))
        elif low in ("is:dup", "is:중복"):
            filters.append(("dup",))
        else:
            words.append(token)
    return filters, " ".join(words)


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


class StatsScreen(ModalScreen[None]):
    """화면을 넓게 쓰는 통계 화면 (스크롤 가능)."""

    BINDINGS = [
        Binding("escape", "close", "닫기"),
        Binding("q", "close", "닫기", show=False),
        Binding("enter", "close", "닫기", show=False),
    ]

    def __init__(self, renderable) -> None:
        super().__init__()
        self.renderable = renderable

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Label("클립보드 통계", id="dialog-title")
            with VerticalScroll(id="stats-scroll"):
                yield Static(self.renderable, id="stats-body")
            yield Label("[↑↓/PgUp/PgDn] 스크롤   [Esc/Enter] 닫기", id="dialog-hint")

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
        Binding("space", "app.toggle_mark", "체크", show=False),
        Binding("a", "app.mark_all", "전체체크", show=False),
        Binding("u", "app.clear_marks", "체크해제", show=False),
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
    #preview-box { width: 1fr; height: 1fr; layout: vertical; }
    #meta-header { height: auto; max-height: 4; padding: 0 1; color: #9a9a9a; background: #000000; }
    Preview { width: 100%; height: 1fr; background: #000000; border: round #595959; }
    Preview:focus { border: round #33ccff; }
    #main.narrow ClipList { width: 100%; height: 3fr; }
    #main.narrow #preview-box { width: 100%; height: 2fr; }
    #main.short #preview-box { display: none; }
    #main.short ClipList { width: 100%; }
    #main.hide-preview #preview-box { display: none; }
    #main.hide-preview ClipList { width: 100%; height: 1fr; }
    #status-row { height: 1; }
    #status { width: 1fr; color: #9a9a9a; padding: 0 1; }
    #progress { width: 30; display: none; }
    #progress.active { display: block; }
    ConfirmScreen, InfoScreen, BusyScreen, StatsScreen { align: center middle; }
    #dialog { width: 70%; max-width: 90; height: auto; background: #101010; border: round #33ccff; padding: 1 2; }
    #stats-box { width: 90%; max-width: 120; height: 90%; background: #101010; border: round #33ccff; padding: 1 2; }
    #stats-scroll { height: 1fr; }
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
        Binding("f2", "toggle_mark", "체크"),
        Binding("f3", "mark_all", "전체체크"),
        Binding("f4", "clear_marks", "체크해제"),
        Binding("f5", "reload", "새로고침"),
        Binding("f6", "cycle_sort", "정렬"),
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
        self.meta: dict[int, clipmeta.Meta] = {}
        self.shown: list[Entry] = []
        self.marked: set[int] = set()
        self.sort_mode = 0
        self.generation = 0
        self.indexing = False
        self.current_id: int | None = None
        self.list_width = 80

    # ---------- 화면 구성 ----------
    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="검색 — 내용 전체에서도 찾습니다   필터: app:이름  >10k  is:sensitive  is:dup   (Enter: 복사)",
            id="search",
        )
        with Container(id="main"):
            yield ClipList(id="list")
            with Vertical(id="preview-box"):
                yield Static("", id="meta-header")
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
        # 목록 폭 추정: 좌우 배치면 절반, 위아래/숨김이면 전체
        side_by_side = width >= WIDE_COLUMNS and height >= SHORT_ROWS and not main.has_class("hide-preview")
        new_width = (width // 2 if side_by_side else width) - 4
        changed = abs(new_width - self.list_width) > 3 and (new_width >= META_COLUMNS) != (self.list_width >= META_COLUMNS)
        self.list_width = new_width
        if changed and self.entries:
            self.refresh_list()  # 시각/앱 열을 보여줄지 여부가 바뀜

    def action_toggle_preview(self) -> None:
        main = self.query_one("#main")
        main.set_class(not main.has_class("hide-preview"), "hide-preview")
        self.apply_layout(self.size.width, self.size.height)

    # ---------- 데이터 ----------
    def reload(self, keep_cache: bool = True) -> None:
        old = self.by_id if keep_cache else {}
        self.entries = load_entries()
        for entry in self.entries:
            cached = old.get(entry.id)
            if cached is not None and cached.preview == entry.preview and cached.text is not None:
                entry.size, entry.text, entry.lower, entry.digest = cached.size, cached.text, cached.lower, cached.digest
        self.by_id = {e.id: e for e in self.entries}
        self.meta = clipmeta.load_all()
        self.marked &= set(self.by_id)
        self.refresh_list()
        self.index_contents()

    def fill_text(self, entry: Entry, raw: bytes) -> None:
        entry.size = len(raw)
        entry.text = raw.decode("utf-8", "replace")
        entry.lower = entry.text.lower()
        entry.digest = hashlib.sha1(raw).hexdigest()

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
            self.fill_text(entry, fetch_raw(entry.id))

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
        bar_widget = self.query_one("#progress", ProgressBar)
        if self.indexing:
            bar_widget.update(total=total, progress=done)
            bar_widget.add_class("active")
        self.update_status()

    def index_progress(self, done: int, total: int) -> None:
        self.query_one("#progress", ProgressBar).update(total=total, progress=done)
        self.update_status(f"내용 색인 중 {done}/{total}")

    def index_end(self) -> None:
        self.indexing = False
        self.query_one("#progress", ProgressBar).remove_class("active")
        self.refresh_list()  # 내용 검색·민감/중복 필터가 가능해졌으므로 다시 필터링

    # ---------- 목록 ----------
    def row_text(self, entry: Entry, positions: list[int]) -> Text:
        info = self.meta.get(entry.id)
        marked = entry.id in self.marked
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("[x] " if marked else "[ ] ", style="bold #33ccff" if marked else "#595959")
        if self.list_width >= META_COLUMNS:
            when = rel_time(info.created if info and info.created else (info.last_used if info else None))
            text.append(pad(when, 8, right=True) + " ", style="#9a9a9a")
            text.append(pad((info.app if info and info.app else "—"), 11) + " ", style="#7aa2c7")
        size = human(entry.size) if entry.size >= 0 else "…"
        text.append(pad(size, 7, right=True) + " ", style="#9a9a9a")
        preview = entry.preview.replace("\t", " ")
        start = len(text.plain)
        text.append(preview)
        for pos in positions:
            if pos < len(preview):
                text.stylize(MATCH_STYLE, start + pos, start + pos + 1)
        return text

    def passes_filters(self, entry: Entry, filters: list[tuple], dup_hashes: set[str]) -> bool:
        info = self.meta.get(entry.id)
        for flt in filters:
            kind = flt[0]
            if kind == "app":
                if not (info and info.app and flt[1] in info.app.lower()):
                    return False
            elif kind == "size":
                if entry.size < 0:
                    return False
                if flt[1] == ">" and not entry.size >= flt[2]:
                    return False
                if flt[1] == "<" and not entry.size < flt[2]:
                    return False
            elif kind == "sensitive":
                if entry.text is None or not looks_sensitive(entry.text):
                    return False
            elif kind == "multi":
                if entry.text is None or "\n" not in entry.text.strip("\n"):
                    return False
            elif kind == "dup":
                if entry.digest not in dup_hashes:
                    return False
        return True

    def refresh_list(self) -> None:
        raw = self.query_one("#search", Input).value.strip()
        filters, query = parse_query(raw)
        tokens = [t.lower() for t in query.split()]
        dup_hashes: set[str] = set()
        if any(f[0] == "dup" for f in filters):
            counts = Counter(e.digest for e in self.entries if e.digest)
            dup_hashes = {h for h, n in counts.items() if n > 1}

        rows: list[tuple[float, Entry, list[int]]] = []
        for entry in self.entries:
            if not self.passes_filters(entry, filters, dup_hashes):
                continue
            if not query:
                rows.append((0.0, entry, []))
                continue
            hit = match(query, entry.preview)
            if hit is None and entry.text is not None and tokens and all(t in entry.lower for t in tokens):
                hit = (10.0, [])
            if hit is not None:
                rows.append((hit[0], entry, hit[1]))

        mode = SORT_MODES[self.sort_mode]
        if query:
            rows.sort(key=lambda r: -r[0])
        elif mode == "크기순":
            rows.sort(key=lambda r: -r[1].size)
        elif mode == "많이 쓴 순":
            rows.sort(key=lambda r: -(self.meta[r[1].id].uses if r[1].id in self.meta else 0))
        elif mode == "많이 복사된 순":
            rows.sort(key=lambda r: -(self.meta[r[1].id].copies if r[1].id in self.meta else 0))
        elif mode == "오래된 순":
            rows.reverse()
        self.shown = [r[1] for r in rows]

        lst = self.query_one("#list", ClipList)
        keep = self.current_id
        lst.clear_options()
        lst.add_options([Option(self.row_text(e, pos), id=str(e.id)) for _, e, pos in rows])
        if self.shown:
            lst.highlighted = next((i for i, e in enumerate(self.shown) if e.id == keep), 0)
        else:
            self.query_one("#preview", Preview).load_text("")
            self.query_one("#meta-header", Static).update("")
            self.current_id = None
        self.update_status()

    def update_status(self, extra: str = "") -> None:
        bits = [f"{len(self.shown)}/{len(self.entries)}개"]
        if self.marked:
            bits.append(f"체크 {len(self.marked)}개")
        if SORT_MODES[self.sort_mode] != "최신순":
            bits.append(SORT_MODES[self.sort_mode])
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

    def meta_header(self, entry: Entry) -> Text:
        info = self.meta.get(entry.id)
        lines = entry.text.count("\n") + 1 if entry.text else 0
        first = Text(f"#{entry.id} · {human(entry.size)}" + (f" · {lines}줄" if lines > 1 else ""), style="bold #9a9a9a")
        if info is None:
            first.append("   (부가 정보 없음 — 기록 시작 전에 복사된 항목)", style="#595959")
            return first
        second = Text(
            f"복사 {info.copies}회 · 사용 {info.uses}회 · 처음 {abs_time(info.first_seen)} · 최근 {abs_time(info.created)}"
            f" · {info.app or '—'}" + (f" — {info.title}" if info.title else ""),
            style="#7aa2c7",
        )
        return Text("\n").join([first, second])

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
            self.fill_text(entry, fetch_raw(entry.id))
        self.query_one("#preview", Preview).load_text(entry.text)
        self.query_one("#meta-header", Static).update(self.meta_header(entry))
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
        if isinstance(screen, (InfoScreen, StatsScreen)):
            screen.dismiss(None)
            return
        if isinstance(screen, ModalScreen):
            return
        entry = self.highlighted_entry()
        if entry is None:
            return
        try:
            clipmeta.mark_use(entry.id)  # 사용 횟수 기록 + 곧 올 저장 이벤트를 '직접 복사'와 구분
        except Exception:  # noqa: BLE001 — 부가 정보 때문에 복사가 막히면 안 됨
            pass
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

    def action_cycle_sort(self) -> None:
        self.sort_mode = (self.sort_mode + 1) % len(SORT_MODES)
        self.refresh_list()
        self.notify(f"정렬: {SORT_MODES[self.sort_mode]}")

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
        what = f"체크한 {len(targets)}개" if self.marked else f"#{targets[0]}"
        message = f"{what} 항목({human(total)})을 삭제할까요?\n되돌릴 수 없습니다."

        def done(answer: bool | None) -> None:
            if not answer:
                return
            lines = "".join(f"{t}\t{self.by_id[t].preview}\n" for t in targets).encode()
            cliphist("delete", data=lines)
            try:
                clipmeta.prune()
            except Exception:  # noqa: BLE001
                pass
            self.marked -= set(targets)
            self.notify(f"{len(targets)}개를 삭제했습니다")
            self.reload()

        self.push_screen(ConfirmScreen(message), done)

    # ---------- 통계 ----------
    def build_stats(self):
        now = time.time()
        known = [e for e in self.entries if e.size >= 0]
        total = sum(e.size for e in known)
        try:
            db_size = os.path.getsize(DB)
        except OSError:
            db_size = 0
        try:
            meta_size = os.path.getsize(clipmeta.META_DB)
        except OSError:
            meta_size = 0
        sizes = sorted(e.size for e in known)
        median = sizes[len(sizes) // 2] if sizes else 0
        sections: list[Text] = []

        def head(title: str) -> Text:
            return Text(f"\n{title}", style="bold #33ccff")

        # --- 요약
        s = Text()
        s.append(f"  항목 수          {len(self.entries)}개")
        if len(known) != len(self.entries):
            s.append(f"   (크기 확인 {len(known)}개 — 내용 색인 중)", style="#9a9a9a")
        s.append(f"\n  내용 총 크기     {human(total)}   (평균 {human(total // len(known)) if known else '0B'} · 중앙값 {human(median)})")
        s.append(f"\n  DB 파일 크기     {human(db_size)}   부가 정보 DB {human(meta_size)}")
        if db_size > total * 3 + 1048576:
            s.append("\n  → DB 파일이 내용보다 훨씬 큽니다. F10 으로 최적화해 줄일 수 있습니다.", style="bold #cb4b16")
        sections += [head("요약"), s]

        # --- 크기 분포
        buckets = [("100B 미만", 0, 100), ("1KB 미만", 100, 1024), ("10KB 미만", 1024, 10240), ("100KB 미만", 10240, 102400), ("100KB 이상", 102400, 1 << 60)]
        counts = [sum(1 for e in known if lo <= e.size < hi) for _, lo, hi in buckets]
        t = Text()
        for (label, _, _), n in zip(buckets, counts):
            t.append(f"  {pad(label, 12)} {pad(str(n), 5, right=True)}  ")
            t.append(bar(n, max(counts)) + "\n", style="#268bd2")
        sections += [head("크기 분포"), t]

        # --- 종류
        kinds: Counter = Counter()
        for e in known:
            body = (e.text or "").strip()
            if re.match(r"^(https?|ftp)://\S+$", body) or body.startswith("magnet:"):
                kinds["링크"] += 1
            elif re.match(r"^(/|~/|\./)[^\s]*(\s+(/|~/|\./)[^\s]*)*$", body) and "\n" not in body[:-1]:
                kinds["파일 경로"] += 1
            elif "\n" in body:
                kinds["여러 줄(코드·로그·글)"] += 1
            elif len(body) <= 40:
                kinds["짧은 글·단어"] += 1
            else:
                kinds["한 줄 긴 글·명령"] += 1
        t = Text()
        for label, n in kinds.most_common():
            t.append(f"  {pad(label, 22)} {pad(str(n), 5, right=True)}  ")
            t.append(bar(n, max(kinds.values())) + "\n", style="#268bd2")
        sections += [head("종류"), t]

        # --- 부가 정보 기반
        with_meta = [m for m in self.meta.values() if m.created and m.id in self.by_id]
        sections.append(head(f"사용 패턴   (부가 정보가 기록된 항목 {len(with_meta)}/{len(self.entries)}개 — 기록을 시작한 뒤 복사한 것부터)"))
        if with_meta:
            apps = Counter(m.app or "—" for m in with_meta)
            t = Text("  앱별 항목 수\n", style="bold")
            for label, n in apps.most_common(8):
                t.append(f"    {pad(label, 20)} {pad(str(n), 5, right=True)}  ")
                t.append(bar(n, max(apps.values())) + "\n", style="#7aa2c7")
            sections.append(t)
            hours = Counter(datetime.fromtimestamp(m.created).hour for m in with_meta)
            t = Text("  시간대별 복사 (0~23시)\n", style="bold")
            for h in range(24):
                if hours[h]:
                    t.append(f"    {h:02d}시 {pad(str(hours[h]), 4, right=True)}  ")
                    t.append(bar(hours[h], max(hours.values())) + "\n", style="#7aa2c7")
            sections.append(t)
            t = Text("  자주 복사된 항목 TOP 5\n", style="bold")
            frequent = [m for m in sorted(with_meta, key=lambda x: -x.copies)[:5] if m.copies > 1]
            for m in frequent:
                t.append(f"    {m.copies:>3}회  {self.by_id[m.id].preview[:60]}\n")
            if not frequent:
                t.append("    (같은 내용을 여러 번 복사한 항목이 아직 없습니다)\n", style="#7a7a7a")
            sections.append(t)
            t = Text("  메뉴에서 많이 꺼내 쓴 항목 TOP 5\n", style="bold")
            used = [m for m in sorted(with_meta, key=lambda x: -x.uses)[:5] if m.uses > 0]
            for m in used:
                t.append(f"    {m.uses:>3}회  {self.by_id[m.id].preview[:60]}\n")
            if not used:
                t.append("    (Enter 로 꺼내 쓴 기록이 아직 없습니다)\n", style="#7a7a7a")
            sections.append(t)
            oldest = min(m.first_seen or m.created for m in with_meta)
            days = int((now - oldest) // 86400)
            sections.append(Text(f"  기록된 가장 오래된 복사: {abs_time(oldest)} ({days}일 전)" if days >= 1 else f"  기록된 가장 오래된 복사: {abs_time(oldest)} ({rel_time(oldest, now)})"))
        else:
            sections.append(Text("  아직 기록이 없습니다. 이제부터 복사하는 항목에 시각·앱·횟수가 쌓입니다.", style="#9a9a9a"))

        # --- 정리 후보
        sections.append(head("정리 후보"))
        counts_by_hash = Counter(e.digest for e in known if e.digest)
        dup_groups = {h: n for h, n in counts_by_hash.items() if n > 1}
        wasted = sum(e.size for e in known if e.digest in dup_groups) - sum(
            next(e.size for e in known if e.digest == h) for h in dup_groups
        )
        sensitive = [e for e in known if e.text and looks_sensitive(e.text)]
        t = Text()
        t.append(f"  내용이 같은 중복 항목   {sum(dup_groups.values()) - len(dup_groups)}개 (낭비 {human(max(wasted, 0))})   → 검색창에 is:dup\n")
        t.append(f"  민감해 보이는 항목      {len(sensitive)}개 (비밀번호·토큰·키 패턴)   → 검색창에 is:sensitive\n")
        big = [e for e in known if e.size >= 10240]
        t.append(f"  10KB 이상의 큰 항목     {len(big)}개 ({human(sum(e.size for e in big))})   → 검색창에 >10k\n")
        sections.append(t)
        top = Text("\n  큰 항목 TOP 5\n", style="bold")
        for e in sorted(known, key=lambda x: -x.size)[:5]:
            top.append(f"    #{e.id:<5} {pad(human(e.size), 8, right=True)}  {e.preview[:60]}\n")
        sections.append(top)
        return Group(*sections)

    def action_stats(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.push_screen(StatsScreen(self.build_stats()))

    # ---------- DB 최적화 ----------
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
