"""uikit — 우리 Textual TUI(displayui · clipui · notif_ui · usageui)가 공유하는 겉모습과 공통 동작.

여기에 모은 것(각 앱이 복사해 쓰던 것들):
  - PALETTE / BASE_CSS : 검정 배경, 둥근 회색 테두리(포커스 시 하늘색), 선택 줄 파랑, 하단 키 안내줄(Footer) 색
  - DIALOG_CSS         : 가운데 뜨는 대화상자(#dialog, #stats-box) 모양
  - `.box` 클래스      : btop 처럼 제목이 달린 테두리 칸(border_title). `box(widget, "제목")` 로 붙인다
  - HelpScreen / HelpMixin : `?`(또는 F1)로 **키 목록(Binding 에서 자동 생성) + 앱별 용어·사용법(HELP_TERMS) + 공통 종료 안내**를 한 화면에 보여 주는 도움말.
                             앱마다 따로 두던 「용어」 탭은 여기로 합친다(모든 uikit 앱 공통 규칙)
  - pad / wrap_cells / terms_text : 한글(2칸 폭) 기준 칸 맞춤·줄바꿈(f-string 의 :<n 은 글자 수라 한글 표가 어긋남)
  - PauseOnBlurMixin   : 창이 포커스를 잃으면 주기 갱신을 멈춘다(보이지 않는 화면 갱신이 PSR 을 방해하지 않도록). 앱이 pause_on_blur() 로 조건을 바꿀 수 있다
각 앱은 `CSS = uikit.BASE_CSS + (앱 고유 규칙 문자열)` 로 쓰고 같은 디렉터리(배포 시) 또는 ../_uikit(소스)에서 이 파일을 가져온다.
"""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

PALETTE = {
    "bg": "#000000", "border": "#595959", "focus": "#33ccff", "select": "#268bd2", "select_dim": "#1b2a38",
    "dim": "#9a9a9a", "faint": "#7a7a7a", "panel": "#101010", "text": "#cfcfcf", "warn": "#b8a46a",
}

BASE_CSS = """
Screen { background: #000000; }
Footer { background: #000000; color: #9a9a9a; }
Footer FooterKey { background: #000000; }
Footer .footer-key--key { background: #000000; color: #33ccff; text-style: none; }
Footer .footer-key--description { background: #000000; color: #9a9a9a; }
.box { background: #000000; border: round #595959; border-title-color: #9a9a9a; border-subtitle-color: #7a7a7a; }
.box:focus, .box:focus-within { border: round #33ccff; border-title-color: #33ccff; border-title-style: bold; }
OptionList > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
OptionList:focus > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
DataTable > .datatable--header { background: #000000; color: #9a9a9a; text-style: none; }
DataTable > .datatable--cursor { background: #1b2a38; color: #cfcfcf; text-style: none; }
DataTable:focus > .datatable--cursor { background: #268bd2; color: #ffffff; text-style: none; }
#status-row { height: 1; }
#status { width: 1fr; color: #9a9a9a; padding: 0 1; }
"""

DIALOG_CSS = """
ModalScreen { align: center middle; }   /* 이름 목록이 아니라 모든 대화상자 화면 — 목록에 없는 RangeScreen·SpikeScreen·OverrideScreen 이 왼쪽 위 구석에 뜨던 것을 고침 */
#dialog { width: 70%; max-width: 90; height: auto; background: #101010; border: round #33ccff; padding: 1 2; }
#dialog.help { width: 92%; max-width: 124; max-height: 94%; }
#stats-box { width: 90%; max-width: 120; height: 90%; background: #101010; border: round #33ccff; padding: 1 2; }
#stats-scroll { height: 1fr; }
#dialog-title { text-style: bold; padding-bottom: 1; }
#dialog-hint { color: #7a7a7a; padding-top: 1; }
"""


def box(widget, title: str = "", subtitle: str = ""):
    """위젯에 `.box` 클래스와 제목/부제를 붙여 돌려준다(compose 안에서 `yield uikit.box(Panel(...), "현황")`)."""
    widget.add_class("box")
    if title:
        widget.border_title = title
    if subtitle:
        widget.border_subtitle = subtitle
    return widget


BUILTIN_DESC = {"Focus Next": "다음 칸으로 포커스", "Focus Previous": "이전 칸으로 포커스", "Copy selected text": "선택한 글자 복사(종료 아님)",
                "Quit the app": "종료", "Command palette": "명령 팔레트"}    # Textual 기본 바인딩 설명을 한글로


def binding_rows(bindings):
    """BINDINGS(리스트, Binding/튜플 혼합) → [(키 표시, 설명)] — 설명이 비었거나 중복된 줄은 건너뛴다."""
    rows, seen = [], set()
    for b in bindings:
        if isinstance(b, tuple):
            b = Binding(*b)
        if not b.description:
            continue
        keys = " / ".join(k.strip() for k in b.key.split(",")).replace("question_mark", "?").replace("slash", "/")
        if (keys, b.description) in seen:
            continue
        seen.add((keys, b.description))
        rows.append((keys, BUILTIN_DESC.get(b.description, b.description)))
    return rows


def pad(s, n):
    """칸 폭(한글 2칸) 기준으로 n 칸까지 공백을 채운다 — 이미 넘치면 뒤에 한 칸만 둔다(다음 열에 붙지 않게)."""
    s = str(s)
    return s + " " * max(1, n - cell_len(s))


def wrap_cells(text, width):
    """칸 폭 기준 줄바꿈 — 공백 단위로 끊고 width 칸을 넘기지 않는다(한 단어가 더 길면 그대로 둠)."""
    lines, cur = [], ""
    for word in str(text).split(" "):
        cand = f"{cur} {word}" if cur else word
        if not cur or cell_len(cand) <= width:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def terms_text(terms, width, key_style="#33ccff"):
    """[(용어, 설명)] → 이름 칸을 칸 폭으로 맞추고 설명은 이름 칸만큼 들여써 줄바꿈한 Text. width = 쓸 수 있는 칸 수."""
    if not terms:
        return Text()
    kw = min(max(cell_len(k) for k, _ in terms) + 2, 26)
    dw = max(20, width - kw - 2)
    t = Text()
    for k, d in terms:
        for i, line in enumerate(wrap_cells(d, dw)):
            t.append(" " + (pad(k, kw) if i == 0 else " " * kw), style=key_style)
            t.append(line + "\n")
    return t


COMMON_HELP = ("Ctrl+Q 어디서나 종료 · Ctrl+C 는 복사일 뿐 종료가 아님(누르면 안내만 뜸) · Ctrl+P 명령 팔레트 · "
               "도움말 닫기: Esc · q · ? · F1 · Enter, 긴 도움말은 ↑↓ PgUp/PgDn 으로 스크롤")


class HelpScreen(ModalScreen):
    """도움말 대화상자: 키 목록 + (있으면) 앱별 메모·용어·사용법 + 공통 안내. Esc·q·?·F1·Enter 로 닫고 ↑↓ PgUp/PgDn 으로 스크롤한다(다른 키는 닫지 않는다)."""
    BINDINGS = [Binding("escape,q,enter,question_mark,f1", "close", "닫기")]

    def __init__(self, title: str, rows, terms=None, notes=None):
        super().__init__()
        self._title, self._rows, self._terms, self._notes = title, rows, terms or [], notes or []

    def compose(self):
        with VerticalScroll(id="dialog", classes="help"):
            yield Static(f"{self._title} — 도움말", id="dialog-title")
            yield Static("", id="help-keys")
            yield Static("", id="help-terms")
            yield Static("", id="help-common")
            yield Static("Esc · q · ? · F1 · Enter 로 닫기  ·  ↑↓ PgUp/PgDn 스크롤", id="dialog-hint")

    def on_mount(self):
        width = max(50, min(114, int(self.app.size.width * 0.9) - 8))
        kw = min(max([cell_len(k) for k, _ in self._rows] + [8]) + 2, 24)
        t = Text(" 키\n", style="bold")
        for keys, desc in self._rows:
            t.append(" " + pad(keys, kw), style="#33ccff")
            t.append(desc + "\n")
        for n in self._notes:
            for line in wrap_cells(n, width - 2):
                t.append(" " + line + "\n", style="grey62")
        self.query_one("#help-keys", Static).update(t)
        if self._terms:
            tt = Text("\n 용어 · 사용법\n", style="bold")
            tt.append_text(terms_text(self._terms, width))
            self.query_one("#help-terms", Static).update(tt)
        c = Text("\n 공통\n", style="bold")
        for line in wrap_cells(COMMON_HELP, width - 2):
            c.append(" " + line + "\n", style="grey62")
        self.query_one("#help-common", Static).update(c)
        self.query_one("#dialog").focus()               # 스크롤 키가 바로 먹도록

    def action_close(self):
        self.dismiss()


class HelpMixin:
    """`?` / F1 로 도움말을 띄운다. App 에 섞어 쓰고 BINDINGS 에 `*HelpMixin.HELP_BINDINGS` 를 넣는다. 입력칸이 포커스일 땐 글자 입력이 우선이라 F1 만 동작.
    앱은 `HELP_TERMS = [(용어, 설명), …]`(용어 탭 대신 — 값의 뜻·검색 문법·개념)와 `HELP_NOTES = ["종료·Esc 규칙 같은 한두 줄", …]` 를 둘 수 있고, 함수 `help_terms()` 로 동적으로 줄 수도 있다."""
    HELP_BINDINGS = [Binding("question_mark,f1", "help", "도움말")]
    HELP_TERMS: list = []
    HELP_NOTES: list = []

    def _binding_enabled(self, b):
        """앱의 check_action 이 False 라고 한 동작(예: ctxui 제한 모드에서 막힌 키)은 도움말 키 목록에서도 뺀다."""
        if isinstance(b, tuple):
            return True
        try:
            from textual.actions import parse
            ns, name, args = parse(b.action)
        except Exception:
            return True
        return not (not ns and self.check_action(name, args) is False)

    def action_help(self):
        bindings = list(self.BINDINGS) + [b for sc in [self.screen] for b in getattr(sc, "BINDINGS", [])]
        bindings = [b for b in bindings if self._binding_enabled(b)]
        rows = binding_rows(bindings)
        terms = self.help_terms() if hasattr(self, "help_terms") else self.HELP_TERMS
        self.push_screen(HelpScreen(getattr(self, "TITLE", "도움말"), rows, terms, self.HELP_NOTES))


class PauseOnBlurMixin:
    """포커스를 잃으면 `self._timer`(set_interval 결과)를 멈추고, 돌아오면 재개하며 `refresh_data()` 를 한 번 부른다.
    앱이 `pause_on_blur()` 를 덮어 쓰면 멈출지 정할 수 있다(예: usageui — 배터리 방전 중일 때만 멈춤). `self._blurred` 로 지금 포커스가 없는지 알 수 있다."""
    _timer = None
    _blurred = False

    def pause_on_blur(self) -> bool:
        return True

    def on_app_blur(self, _ev: events.AppBlur):
        self._blurred = True
        if self._timer and self.pause_on_blur():
            self._timer.pause()

    def on_app_focus(self, _ev: events.AppFocus):
        self._blurred = False
        if self._timer:
            self._timer.resume()
        fn = getattr(self, "refresh_data", None)
        if fn:
            fn()


class Panel(Static):
    """provider(폭, 높이) 로 내용을 만들어 그리는 칸. provider 는 Text 또는 (Text, 부제 문자열)을 돌려준다(부제는 박스 아래 테두리에 표시).
    내용은 build() 에서 미리 만들어 캐시한다 — 부제(테두리)를 그리는 도중에 바꾸면 테두리가 이전 값으로 남기 때문이다.
    build() 는 데이터가 갱신될 때와 크기가 바뀔 때 부른다."""

    def __init__(self, provider, **kw):
        super().__init__(**kw)
        self.provider = provider
        self._text = Text("")

    def build(self):
        w, h = self.size.width, self.size.height
        if not (w and h):
            return
        out = self.provider(max(20, w), max(3, h))
        self._text, sub = out if isinstance(out, tuple) else (out, "")
        if (self.border_subtitle or "") != sub:
            self.border_subtitle = sub

    def on_resize(self, _ev):
        self.build()
        self.refresh()

    def render(self):
        return self._text
