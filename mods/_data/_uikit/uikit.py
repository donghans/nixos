"""uikit — 우리 Textual TUI(displayui · clipui · notif_ui · powerui)가 공유하는 겉모습과 공통 동작.

여기에 모은 것(각 앱이 복사해 쓰던 것들):
  - PALETTE / BASE_CSS : 검정 배경, 둥근 회색 테두리(포커스 시 하늘색), 선택 줄 파랑, 하단 키 안내줄(Footer) 색
  - DIALOG_CSS         : 가운데 뜨는 대화상자(#dialog, #stats-box) 모양
  - `.box` 클래스      : btop 처럼 제목이 달린 테두리 칸(border_title). `box(widget, "제목")` 로 붙인다
  - HelpScreen / HelpMixin : `?`(또는 F1)로 그 앱의 키 목록을 보여 주는 도움말(Binding 에서 자동 생성)
  - PauseOnBlurMixin   : 창이 포커스를 잃으면 주기 갱신을 멈춘다(보이지 않는 화면 갱신이 PSR 을 방해하지 않도록)
각 앱은 `CSS = uikit.BASE_CSS + (앱 고유 규칙 문자열)` 로 쓰고 같은 디렉터리(배포 시) 또는 ../_uikit(소스)에서 이 파일을 가져온다.
"""
from __future__ import annotations

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
InfoScreen, StatsScreen, ConfirmScreen, BusyScreen, HelpScreen { align: center middle; }
#dialog { width: 70%; max-width: 90; height: auto; background: #101010; border: round #33ccff; padding: 1 2; }
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
        rows.append((keys, b.description))
    return rows


class HelpScreen(ModalScreen):
    """키 목록 대화상자. 아무 키나 누르면 닫힌다."""
    BINDINGS = [Binding("escape,q,enter,question_mark,f1", "close", "닫기")]

    def __init__(self, title: str, rows):
        super().__init__()
        self._title, self._rows = title, rows

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Static(f"{self._title} — 키", id="dialog-title")
            t = Text()
            for keys, desc in self._rows:
                t.append(f"{keys:<18}", style="#33ccff")
                t.append(desc + "\n")
            yield Static(t)
            yield Static("아무 키나 누르면 닫힘", id="dialog-hint")

    def action_close(self):
        self.dismiss()


class HelpMixin:
    """`?` / F1 로 도움말을 띄운다. App 에 섞어 쓰고 BINDINGS 에 `*HelpMixin.HELP_BINDINGS` 를 넣는다. 입력칸이 포커스일 땐 글자 입력이 우선이라 F1 만 동작."""
    HELP_BINDINGS = [Binding("question_mark,f1", "help", "도움말")]

    def action_help(self):
        rows = binding_rows(list(self.BINDINGS) + [b for sc in [self.screen] for b in getattr(sc, "BINDINGS", [])])
        self.push_screen(HelpScreen(getattr(self, "TITLE", "도움말"), rows))


class PauseOnBlurMixin:
    """포커스를 잃으면 `self._timer`(set_interval 결과)를 멈추고, 돌아오면 재개하며 `refresh_data()` 를 한 번 부른다."""
    _timer = None

    def on_app_blur(self, _ev: events.AppBlur):
        if self._timer:
            self._timer.pause()

    def on_app_focus(self, _ev: events.AppFocus):
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
