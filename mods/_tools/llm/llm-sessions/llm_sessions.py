#!/usr/bin/env python3
"""llm-sessions — claude 의 tmux 세션 목록을 보고 이어 붙거나 새로 만든다(ssh 에서도, 다른 kitty 에서도 같은 화면).

  llm-sessions                 목록 UI(Textual)
  llm-sessions ls              목록을 글자로 출력
  llm-sessions attach <이름|접두|번호>
  llm-sessions new [디렉터리] [-- claude 인자…]   새 세션을 만들고 붙는다

UI 키: Enter 붙기 · n 새 세션 · x 정리(세션 종료) · d 붙은 곳 모두 떼기 · r 새로고침 · ? 도움말 · q 종료.
붙은 뒤 분리(F12 또는 Ctrl+] d)하면 이 목록으로 돌아온다. 한 세션에 여러 곳이 동시에 붙으면 화면이 서로 비친다.
세션 이름·tmux 설정·종료 규칙은 tmuxsess.py 와 claude-tmux 머리말 참고. 사람이 터미널에서 직접 쓰는 도구라 UI 는 TTY 가 아니면 실행하지 않는다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib", "uikit"))
    import uikit

import tmuxsess as tm


def fmt_ago(ts: float) -> str:
    d = max(0, time.time() - ts)
    if d < 90:
        return f"{d:.0f}초 전"
    if d < 5400:
        return f"{d / 60:.0f}분 전"
    if d < 86400 * 2:
        return f"{d / 3600:.1f}시간 전"
    return f"{d / 86400:.1f}일 전"


def short_path(p: str) -> str:
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p == home or p.startswith(home + "/") else p


def attached_label(s: tm.Session) -> str:
    if not s.clients:
        return "— (분리됨)"
    return " + ".join(f"{c.origin} {c.size}" for c in s.clients)


class NewScreen(ModalScreen):
    """새 세션: 작업 디렉터리와 claude 인자(선택)."""
    BINDINGS = [Binding("escape", "cancel", "취소")]

    def __init__(self, default_dir: str):
        super().__init__()
        self.default_dir = default_dir

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("새 claude 세션", id="dialog-title")
            yield uikit.box(Input(value=self.default_dir, id="new-dir"), "작업 디렉터리")
            yield uikit.box(Input(placeholder="예: --resume  (비워도 됨)", id="new-args"), "claude 인자")
            yield Static("Enter: 만들고 붙기 · Esc: 취소", id="dialog-hint")

    def on_mount(self):
        self.query_one("#new-dir", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted):
        if ev.input.id == "new-dir":
            self.query_one("#new-args", Input).focus()
            return
        import shlex
        d = os.path.expanduser(self.query_one("#new-dir", Input).value.strip())
        try:
            args = shlex.split(self.query_one("#new-args", Input).value)
        except ValueError as e:
            self.app.notify(f"인자 오류: {e}", severity="error"); return
        self.dismiss((d, args))

    def action_cancel(self):
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    BINDINGS = [Binding("y,enter", "yes", "예"), Binding("n,escape", "no", "아니오")]

    def __init__(self, msg: str):
        super().__init__()
        self.msg = msg

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.msg, id="dialog-title")
            yield Static("y/Enter: 예 · n/Esc: 아니오", id="dialog-hint")

    def action_yes(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


class SessionsUI(uikit.HelpMixin, uikit.PauseOnBlurMixin, App):
    TITLE = "llm-sessions — tmux 세션"
    HELP_TERMS = [   # ? 도움말의 「용어·사용법」 — 별도 용어 탭 대신(uikit 공통 규칙)
        ('세션', 'claude 가 도는 tmux 세션 목록 — ssh 에서도 다른 터미널에서도 같은 화면이다'),
        ('붙기 / 분리', 'Enter 로 붙고, 분리는 F12 또는 Ctrl+] d — 분리하면 이 목록으로 돌아온다'),
        ('여러 곳 붙음', '한 세션에 여러 곳이 동시에 붙으면 화면이 서로 비친다. d 로 붙은 곳을 모두 뗀다'),
        ('정리', 'x = 세션 종료(확인 대화상자)'),
        ('화면 미리보기', '선택한 세션의 지금 화면 일부를 아래에 보인다(그 세션의 내용이므로 어깨너머 노출에 주의)'),
    ]
    HELP_NOTES = [
        '종료는 q. Esc 는 대화상자만 닫는다',
    ]
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    NewScreen, ConfirmScreen { align: center middle; }
    #list { height: 1fr; }
    #preview-box { height: 16; }
    #preview { padding: 0 1; color: #cfcfcf; }
    #hint { height: 1; color: #7a7a7a; padding: 0 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("enter", "attach", "붙기"), Binding("n", "new", "새 세션"),
        Binding("x", "kill", "정리(종료)"), Binding("d", "detach_all", "붙은 곳 떼기"),
        Binding("r,f5", "reload", "새로고침"),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, start_dir: str | None = None):
        super().__init__()
        self.start_dir = start_dir or os.getcwd()
        self.sessions: dict[str, tm.Session] = {}

    def compose(self) -> ComposeResult:
        yield uikit.box(DataTable(id="list", cursor_type="row"), "claude 세션 — Enter: 붙기 · n: 새 세션")
        yield uikit.box(VerticalScroll(Static("", id="preview"), id="preview-box"), "화면 미리보기")
        yield Static("분리: F12 또는 Ctrl+] d  ·  같은 세션에 여러 곳이 붙으면 화면이 서로 비칩니다", id="hint")
        yield Footer()

    def on_mount(self):
        self.query_one("#list", DataTable).add_columns("이름", "작업 디렉터리", "시작", "마지막 활동", "붙은 곳", "실행 중")
        self._timer = self.set_interval(3.0, self.refresh_data)
        self.refresh_data()
        self.query_one("#list", DataTable).focus()

    # --- 목록
    def selected(self) -> str | None:
        t = self.query_one("#list", DataTable)
        try:
            return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            return None

    def refresh_data(self):
        try:
            ss = tm.list_sessions()
        except Exception as e:
            self.notify(f"tmux 조회 실패: {e}", severity="error"); return
        keep = self.selected()
        self.sessions = {s.name: s for s in ss}
        t = self.query_one("#list", DataTable)
        t.clear()
        for s in ss:
            t.add_row(s.name, short_path(s.path), time.strftime("%m-%d %H:%M", time.localtime(s.created)), fmt_ago(s.activity), attached_label(s),
                      s.command, key=s.name)
        if keep in self.sessions:
            t.move_cursor(row=list(self.sessions).index(keep))
        self.query_one("#list").border_title = f"claude 세션 {len(ss)}개 — Enter: 붙기 · n: 새 세션" if ss else "claude 세션 없음 — n: 새 세션"
        self.show_preview()

    def on_data_table_row_highlighted(self, _ev):
        self.show_preview()

    def on_data_table_row_selected(self, _ev):      # DataTable 이 Enter 를 먼저 받으므로 행 선택을 「붙기」로 처리
        self.action_attach()

    def show_preview(self):
        name = self.selected()
        box = self.query_one("#preview-box")
        if not name:
            self.query_one("#preview", Static).update(Text("선택한 세션이 없습니다", style="#7a7a7a"))
            box.border_title = "화면 미리보기"
            return
        self.query_one("#preview", Static).update(Text(tm.preview(name, 14) or "(비어 있음)"))
        box.border_title = f"화면 미리보기 — {name}"

    # --- 동작
    def run_attach(self, name: str):
        """UI 를 잠시 멈추고 tmux 에 붙는다. 분리하거나 claude 가 끝나면 목록으로 돌아온다."""
        with self.suspend():
            subprocess.run(tm.attach_cmd(name))
        self.refresh_data()

    def action_attach(self):
        name = self.selected()
        if not name:
            return
        if not tm.exists(name):
            self.notify("그 세션은 이미 끝났습니다", severity="warning"); self.refresh_data(); return
        self.run_attach(name)

    def action_new(self):
        def done(r):
            if not r:
                return
            d, args = r
            try:
                name = tm.create(d, args)
            except RuntimeError as e:
                self.notify(str(e), severity="error"); return
            self.run_attach(name)
        self.push_screen(NewScreen(self.start_dir), done)

    def action_kill(self):
        name = self.selected()
        if not name:
            return
        n = self.sessions[name].attached if name in self.sessions else 0

        def done(yes):
            if yes:
                tm.kill(name)
                self.notify(f"정리했습니다: {name}")
                self.refresh_data()
        self.push_screen(ConfirmScreen(f"'{name}' 세션을 끝낼까요?" + (f" (지금 {n}곳이 붙어 있음 — 그 화면도 닫힙니다)" if n else "") + " 안의 claude 도 종료됩니다."), done)

    def action_detach_all(self):
        name = self.selected()
        if name and tm.detach_all(name):
            self.notify(f"붙은 곳을 모두 뗐습니다: {name}")
            self.refresh_data()

    def action_reload(self):
        self.refresh_data()


# ---------------------------------------------------------------- CLI
def cmd_ls() -> int:
    ss = tm.list_sessions()
    if not ss:
        print("claude 세션 없음"); return 0
    for i, s in enumerate(ss, 1):
        print(f"{i:>2}  {s.name:<42} {short_path(s.path):<40} {fmt_ago(s.activity):>10}  {attached_label(s)}")
    return 0


def cmd_attach(spec: str) -> int:
    name = tm.resolve(spec)
    if not name:
        print(f"세션을 찾지 못했거나 모호합니다: {spec}", file=sys.stderr); return 1
    return subprocess.run(tm.attach_cmd(name)).returncode


def cmd_new(argv: list[str]) -> int:
    directory, args = (argv[0] if argv and argv[0] != "--" else os.getcwd()), []
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        directory = argv[0] if argv[0] != "--" else os.getcwd()
    try:
        name = tm.create(os.path.expanduser(directory), args)
    except RuntimeError as e:
        print(e, file=sys.stderr); return 1
    return subprocess.run(tm.attach_cmd(name)).returncode


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__); return 0
    if argv[:1] == ["ls"]:
        return cmd_ls()
    if argv[:1] == ["attach"] and len(argv) == 2:
        return cmd_attach(argv[1])
    if argv[:1] == ["new"]:
        return cmd_new(argv[1:])
    if argv:
        print(__doc__, file=sys.stderr); return 2
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("llm-sessions 는 터미널에서 실행하세요(목록만 보려면 `llm-sessions ls`)", file=sys.stderr); return 1
    SessionsUI().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
