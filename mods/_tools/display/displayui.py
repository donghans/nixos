#!/usr/bin/env python3
"""displayui — Hyprland 화면 관리 TUI (Textual). 코어는 displayctl.py

왼쪽: 화면 모드(확장/미러/내장만/외부만)와 프리셋(프리젠테이션 등). Enter 로 바로 적용.
오른쪽: 모니터 목록과, 선택한 모니터의 해상도·주사율·배율·상대 위치. 적용하면 10초 안에 확인하지 않으면 되돌린다
(되지 않는 모드로 화면이 안 나와도 스스로 복구되게).

  displayui --focus mode        화면 모드 목록에서 시작 (단축키용)
  displayui --focus refresh     주사율에서 시작 (앱 런처용). resolution / scale / position / monitors 도 가능
  displayui --quick             모드를 고르면 적용하고 바로 종료
"""
from __future__ import annotations

import argparse
import os
import sys

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import displayctl as dc  # noqa: E402
import os
import sys

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../_uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib", "_uikit"))
    import uikit
from dispctl.observelog import events as observe_events  # noqa: E402

FOCUS_IDS = {
    "mode": "modes", "monitors": "mons", "resolution": "res", "refresh": "hz", "scale": "scale", "position": "rel",
}
CONFIRM_SECONDS = int(os.environ.get("DISPLAYUI_CONFIRM", "10"))
NARROW = 100  # 이 폭 미만이면 모드 목록과 설정을 위아래로


def hz_key(hz: float) -> str:
    return ("%.2f" % hz).rstrip("0").rstrip(".")


class Confirm(ModalScreen[bool]):
    """적용 결과를 확인하는 창. 시간 안에 '유지'하지 않으면 False(되돌림)"""

    BINDINGS = [
        Binding("enter,y", "keep", "유지"),
        Binding("escape,n", "undo", "되돌리기"),
    ]
    DEFAULT_CSS = """
    Confirm { align: center middle; }
    Confirm > Vertical { width: 64; height: auto; border: round #33ccff; background: #101010; padding: 1 2; }
    Confirm Horizontal { height: 1; margin-top: 1; align-horizontal: center; }
    Confirm Button { margin: 0 2; border: none; height: 1; min-width: 0; padding: 0 2; background: #141414; color: #cfcfcf; text-style: none; }
    Confirm Button:hover, Confirm Button:focus { background: #268bd2; color: #ffffff; text-style: none; }
    Confirm #ccount { color: #7a7a7a; padding-top: 1; }
    """

    def __init__(self, message: str, seconds: int) -> None:
        super().__init__()
        self.message = message
        self.left = seconds

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.message, id="cmsg")
            yield Static("", id="ccount")
            with Horizontal():
                yield Button("유지 (Enter)", id="keep", variant="primary")
                yield Button("되돌리기 (Esc)", id="undo")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        self.query_one("#ccount", Static).update(f"{self.left}초 안에 선택하지 않으면 자동으로 되돌립니다")
        if self.left <= 0:
            self.app.ev.warn("confirm", choice="undo", via="timeout")
            self.dismiss(False)
        self.left -= 1

    def action_keep(self) -> None:
        self.app.ev.info("confirm", choice="keep", via="key", left=self.left)
        self.dismiss(True)

    def action_undo(self) -> None:
        self.app.ev.info("confirm", choice="undo", via="key", left=self.left)
        self.dismiss(False)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.app.ev.info("confirm", choice="keep" if ev.button.id == "keep" else "undo", via="button", left=self.left)
        self.dismiss(ev.button.id == "keep")


class NameInput(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", "취소")]
    DEFAULT_CSS = """
    NameInput { align: center middle; }
    NameInput > Vertical { width: 56; height: auto; border: round #33ccff; background: #101010; padding: 1 2; }
    NameInput Input { border: none; height: 1; background: #141414; padding: 0 1; margin-top: 1; }
    NameInput Input:focus { border: none; background: #1b2a38; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("현재 구성을 프리셋으로 저장 — 이름:")
            yield Input(placeholder="예: 회의실", id="pname")

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class DisplayUI(uikit.HelpMixin, App):
    TITLE = "화면 관리"
    HELP_TERMS = [   # ? 도움말의 「용어·사용법」 — 별도 용어 탭 대신(uikit 공통 규칙)
        ('화면 모드', '확장 / 미러 / 내장만 / 외부만 — Enter 로 바로 적용. m 으로 목록에 포커스'),
        ('프리셋', '프리젠테이션 등 해상도 조합 — Enter 적용, S 저장, d 삭제'),
        ('확인 시간', '적용하면 정해진 시간(기본 10초) 안에 확인하지 않으면 이전 구성으로 되돌린다 — 되지 않는 모드로 화면이 안 나와도 스스로 복구된다'),
        ('모니터별 설정', 's 해상도 · r 주사율 · c 배율 · p 위치 · a 적용. 위치는 기준 모니터에 대한 상대 위치와 정렬'),
    ]
    HELP_NOTES = [
        'q·Esc 로 종료. r 은 새로고침이 아니라 주사율이다(새로고침은 F5)',
    ]
    ENABLE_COMMAND_PALETTE = False  # 푸터의 ^p palette 안내 숨김 (clipui 와 같음, 쓰지 않음)
    # 색은 lazygit(mods/sys/utils/lazygit.nix) / clipui 와 같음: 비활성 테두리 #595959, 포커스 #33ccff, 선택 줄 #268bd2, 배경 검정.
    CSS = uikit.BASE_CSS + """
    #body { height: 1fr; }
    #left, #mons, #form { background: #000000; border: round #595959; border-title-color: #9a9a9a; border-subtitle-color: #7a7a7a; }
    #left:focus-within, #mons:focus-within, #form:focus-within { border: round #33ccff; border-title-color: #33ccff; border-title-style: bold; }
    #left { width: 38; }
    #right { width: 1fr; background: #000000; }
    #modes { height: 1fr; background: #000000; border: none; padding: 0 1; }
    #modes > .option-list--option-highlighted { background: #1b2a38; color: #cfcfcf; text-style: none; }
    #modes:focus > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    #modes > .option-list--option-disabled { color: #7a7a7a; }
    #mons { height: 6; padding: 0 1; }
    #mons > .datatable--header { background: #000000; color: #9a9a9a; text-style: none; }
    #mons > .datatable--cursor { background: #1b2a38; color: #cfcfcf; text-style: none; }
    #mons:focus > .datatable--cursor { background: #268bd2; color: #ffffff; text-style: none; }
    #form { height: auto; padding: 0 1; }
    .row { height: 1; margin-bottom: 1; }
    .row Label { width: 12; color: #9a9a9a; }
    .row Select { width: 1fr; height: 1; }
    Select > SelectCurrent { border: none; height: 1; padding: 0 1; background: #141414; }
    Select:focus > SelectCurrent { border: none; background: #1b2a38; }
    SelectOverlay { border: round #33ccff; background: #000000; }
    SelectOverlay > .option-list--option-highlighted { background: #268bd2; color: #ffffff; text-style: none; }
    #buttons { height: 1; margin-top: 1; }
    Button { border: none; height: 1; min-width: 0; padding: 0 2; margin-right: 2; background: #141414; color: #cfcfcf; text-style: none; }
    Button:hover, Button:focus { background: #268bd2; color: #ffffff; text-style: none; }
    Button.-primary { background: #1b4f7a; color: #ffffff; }
    Button.-primary:hover, Button.-primary:focus { background: #268bd2; }
    #msg { height: auto; min-height: 1; padding: 0 1; color: #b8a46a; }
    .narrow #body { layout: vertical; }
    .narrow #left { width: 1fr; height: 10; }
    """
    BINDINGS = [
        *uikit.HelpMixin.HELP_BINDINGS,
        Binding("m", "focus_to('modes')", "모드"),
        Binding("s", "focus_to('res')", "해상도"),
        Binding("r", "focus_to('hz')", "주사율"),
        Binding("c", "focus_to('scale')", "배율"),
        Binding("p", "focus_to('rel')", "위치"),
        Binding("a", "apply", "적용"),
        Binding("S", "save_preset", "프리셋 저장"),
        Binding("d", "delete_preset", "프리셋 삭제"),
        Binding("f5", "reload", "새로고침"),
        Binding("q,escape", "quit", "종료"),
    ]

    def __init__(self, focus: str = "mode", quick: bool = False) -> None:
        super().__init__()
        self.focus_target = FOCUS_IDS.get(focus, "modes")
        self.quick = quick
        self.sel: str | None = None
        self._updating = False
        self.mons: list[dc.Mon] = []

    # ───── 화면 구성 ─────
    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield OptionList(id="modes")
            with VerticalScroll(id="right"):
                yield DataTable(id="mons", cursor_type="row")
                with Vertical(id="form"):
                    with Horizontal(classes="row"):
                        yield Label("해상도 (s)")
                        yield Select([("-", "-")], id="res", allow_blank=False)
                    with Horizontal(classes="row"):
                        yield Label("주사율 (r)")
                        yield Select([("-", "-")], id="hz", allow_blank=False)
                    with Horizontal(classes="row"):
                        yield Label("배율 (c)")
                        yield Select([("-", "-")], id="scale", allow_blank=False)
                    with Horizontal(classes="row"):
                        yield Label("위치 (p)")
                        yield Select([("-", "-")], id="rel", allow_blank=False)
                    with Horizontal(classes="row"):
                        yield Label("기준 모니터")
                        yield Select([("-", "-")], id="of", allow_blank=False)
                    with Horizontal(classes="row"):
                        yield Label("정렬")
                        yield Select([("-", "-")], id="align", allow_blank=False)
                    with Horizontal(id="buttons"):
                        yield Button("적용 (a)", id="apply", variant="primary")
                        yield Button("기본 구성으로 초기화", id="reset")
                yield Static("", id="msg")
        yield Footer()

    ev = observe_events("displayui")

    async def on_event(self, event) -> None:
        # 위젯이 처리하기 전에 키를 기록(어느 위젯에 포커스가 있었는지 포함). 입력창에서는 글자 내용을 기록하지 않음
        if isinstance(event, events.Key):
            f = self.focused
            typing = isinstance(f, Input)
            self.ev.debug("key", key="(입력)" if typing and event.is_printable else event.key, focus=getattr(f, "id", None) or type(f).__name__,
                          screen=type(self.screen).__name__)
        await super().on_event(event)

    def on_descendant_focus(self, event) -> None:
        w = event.widget
        pane = next((a.id for a in [w, *w.ancestors] if a.id in ("left", "mons", "form")), None)
        self.ev.debug("focus", widget=w.id or type(w).__name__, pane=pane)
        for wid, title in self._pane_titles.items():
            try:
                self.query_one(wid).border_title = ("▶ " if wid == "#" + str(pane) else "") + title
            except Exception:
                pass

    def on_mount(self) -> None:
        # lazygit 처럼 제목을 테두리 안에 둠 ("[키]-이름"). 포커스가 있는 칸은 제목 앞에 ▶ 를 붙여 Enter 가 어디로 가는지 분명히 함
        self._pane_titles = {}
        for wid, title, sub in (("#left", "\\[m] 화면 모드 / 프리셋", "Enter 적용"), ("#mons", "모니터", ""), ("#form", "선택한 모니터 설정", "")):
            box = self.query_one(wid)
            box.border_title = title
            box.border_subtitle = sub
            self._pane_titles[wid] = title
        self.ev.info("mount", focus=self.focus_target, quick=self.quick, size=f"{self.size.width}x{self.size.height}",
                     monitors=[(m.name, m.mode, m.disabled) for m in dc.get_monitors()])
        t = self.query_one("#mons", DataTable)
        t.add_columns("모니터", "설명", "모드", "배율", "위치", "상태")
        self.reload_all()
        self.query_one("#" + self.focus_target).focus()
        self.on_resize()

    def on_resize(self, *_a) -> None:
        self.set_class(self.size.width < NARROW, "narrow")

    # ───── 데이터 갱신 ─────
    def msg(self, text: str) -> None:
        self.query_one("#msg", Static).update(text)

    def action_focus_to(self, wid: str) -> None:
        self.query_one("#" + wid).focus()

    def action_reload(self) -> None:
        self.reload_all()

    def reload_all(self) -> None:
        self.mons = dc.get_monitors()
        if self.sel not in [m.name for m in self.mons]:
            ext = next((m for m in self.mons if not m.internal), None)
            self.sel = (ext or self.mons[0]).name if self.mons else None
        self.fill_modes()
        self.fill_table()
        self.fill_form()

    def fill_modes(self) -> None:
        ol = self.query_one("#modes", OptionList)
        ol.clear_options()
        st = dc.load_state()
        cur = st["layout"] if st else "extend"
        arr = dc.current_arrange(st, self.mons)
        laptop = dc.has_internal(self.mons)     # 내장 패널이 있으면 노트북 용어/선택지, 없으면 PC(메인/보조)
        layouts, arranges = (dc.LAYOUTS, dc.ARRANGES) if laptop else (dc.LAYOUTS_PC, dc.ARRANGES_PC)
        for k, label in layouts.items():
            ol.add_option(Option(("● " if k == cur and not (st and st.get("preset")) else "  ") + label, id=f"layout:{k}"))
        # 확장 배치(위아래/좌우, 모두 가운데 정렬). 위쪽 4줄의 순서는 그대로 둬서 ↓ Enter 같은 기존 동작이 바뀌지 않게 별도 구역으로 둠
        ol.add_option(Option("── 확장 배치 ──", disabled=True))
        in_extend = cur == "extend" and not (st and st.get("preset"))
        for ak, alabel in arranges.items():
            ol.add_option(Option(("● " if in_extend and arr == ak else "  ") + alabel, id=f"arrange:{ak}"))
        if in_extend and arr == "custom":
            ol.add_option(Option("● 사용자 지정 배치 (아래 위치 설정)", disabled=True))
        ol.add_option(Option("── 프리셋 ──", disabled=True))
        for k, v in dc.BUILTIN_PRESETS.items():
            if not laptop and v["layout"] == "internal":
                continue                      # 내장 화면 전용 프리셋
            ol.add_option(Option(("● " if st and st.get("preset") == k else "  ") + v["label"], id=f"preset:{k}"))
        users = dc.load_presets()
        for k in users:
            ol.add_option(Option(("● " if st and st.get("preset") == k else "  ") + f"★ {k}", id=f"preset:{k}"))
        ol.add_option(Option("── 기타 ──", disabled=True))
        if st and st.get("before"):
            ol.add_option(Option("  ↩ 이전 구성으로 복귀", id="back"))
        ol.add_option(Option("  ⟲ 기본 구성으로 초기화", id="reset"))
        # 선택 줄(커서)을 지금 적용된 모드에 둠 — 없으면 Enter 가 아무것도 안 하고 방향키를 한 번 눌러야 했음
        cur_id = f"preset:{st['preset']}" if st and st.get("preset") else f"layout:{cur}"
        ids = [ol.get_option_at_index(i).id for i in range(ol.option_count)]
        ol.highlighted = ids.index(cur_id) if cur_id in ids else 0

    def fill_table(self) -> None:
        t = self.query_one("#mons", DataTable)
        t.clear()
        for m in self.mons:
            stat = "꺼짐" if m.disabled else f"미러({m.mirror_of})" if m.mirror_of else "켜짐"
            t.add_row(m.name, m.desc[:26], m.mode, f"x{m.scale:g}", f"{m.x},{m.y}", stat, key=m.name)
        idx = next((i for i, m in enumerate(self.mons) if m.name == self.sel), 0)
        t.move_cursor(row=idx)

    def mon(self) -> dc.Mon | None:
        return next((m for m in self.mons if m.name == self.sel), None)

    def intent(self, m: dc.Mon) -> tuple[str, float]:
        st = dc.load_state()
        s = (st or {}).get("monitors", {}).get(m.name, {})
        return s.get("mode") or m.mode, float(s.get("scale") or m.scale)

    def res_options(self, m: dc.Mon, current: str) -> list[tuple[str, str]]:
        groups = dc.mode_groups(m)
        order = sorted(groups, key=lambda k: -int(k.split("x")[0]) * int(k.split("x")[1]))
        opts = [(f"{r}   ★ 모니터 지원", r) for r in order]
        for r in dc.COMMON_RES:
            if r not in groups:
                opts.append((f"{r}   (사용자 지정 — 되는지는 적용 후 확인)", r))
        if current not in [v for _, v in opts]:
            opts.append((current, current))
        return opts

    def hz_options(self, m: dc.Mon, res: str, current: str) -> list[tuple[str, str]]:
        native = dc.mode_groups(m).get(res, [])
        opts = [(f"{hz_key(h)} Hz   ★ 모니터 지원", hz_key(h)) for h in native]
        have = {v for _, v in opts}
        for h in dc.COMMON_HZ:
            if not any(abs(h - n) < 0.5 for n in native) and hz_key(h) not in have:
                opts.append((f"{hz_key(h)} Hz   (사용자 지정)", hz_key(h)))
                have.add(hz_key(h))
        if current not in have:
            opts.append((f"{current} Hz", current))
        return opts

    def fill_form(self) -> None:
        m = self.mon()
        if m is None:
            return
        self._updating = True
        try:
            mode, scale = self.intent(m)
            pm = dc.parse_mode(mode) or (m.width, m.height, m.hz)
            res, hz = f"{pm[0]}x{pm[1]}", hz_key(pm[2])
            self.query_one("#res", Select).set_options(self.res_options(m, res))
            self.query_one("#res", Select).value = res
            self.query_one("#hz", Select).set_options(self.hz_options(m, res, hz))
            self.query_one("#hz", Select).value = hz
            sc = [(f"x{s:g}", f"{s:g}") for s in dc.SCALES]
            if f"{scale:g}" not in [v for _, v in sc]:
                sc.append((f"x{scale:g}", f"{scale:g}"))
            self.query_one("#scale", Select).set_options(sc)
            self.query_one("#scale", Select).value = f"{scale:g}"
            others = [x.name for x in self.mons if x.name != m.name]
            rel_opts = [("자동 배치(레이아웃 기본)", "auto")] + [(f"{v} 쪽", k) for k, v in dc.RELS.items()]
            st = dc.load_state() or {}
            spec = (st.get("pos") or {}).get(m.name)
            self.query_one("#rel", Select).set_options(rel_opts)
            self.query_one("#rel", Select).value = spec["rel"] if spec and spec.get("of") in others else "auto"
            self.query_one("#of", Select).set_options([(n, n) for n in others] or [("-", "-")])
            self.query_one("#of", Select).value = spec["of"] if spec and spec.get("of") in others else (others[0] if others else "-")
            self.query_one("#align", Select).set_options([(v, k) for k, v in dc.ALIGNS.items()])
            self.query_one("#align", Select).value = (spec or {}).get("align", "center")
        finally:
            self._updating = False
        self.msg(f"{m.name} 선택됨 — 값을 고르고 a 로 적용 (10초 안에 확인하지 않으면 되돌립니다)")

    # ───── 이벤트 ─────
    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted) -> None:
        # (표를 다시 채울 때 첫 행 하이라이트 이벤트가 뒤늦게 도착하므로, 현재 커서와 다른 오래된 이벤트는 무시)
        if ev.cursor_row != self.query_one("#mons", DataTable).cursor_row:
            return
        name = ev.row_key.value if ev.row_key else None
        if name and name != self.sel:
            self.sel = name
            self.fill_form()

    def on_select_changed(self, ev: Select.Changed) -> None:
        if self._updating or ev.select.id != "res":
            return
        # (값을 채우는 동안 발생한 이벤트가 뒤늦게 도착하면 오래된 값 기준으로 주사율 목록을 다시 만들어 버리므로,
        #  현재 값과 다른 이벤트는 무시)
        if ev.value != ev.select.value:
            return
        m = self.mon()
        if m is None:
            return
        hz = self.query_one("#hz", Select)
        want = hz.value if hz.value is not Select.BLANK else "60"
        self._updating = True
        try:
            opts = self.hz_options(m, str(ev.value), str(want))
            hz.set_options(opts)
            vals = [v for _, v in opts]
            hz.value = want if want in vals else min(vals, key=lambda v: abs(float(v) - float(want)))
        finally:
            self._updating = False

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        oid = ev.option.id or ""
        self.ev.info("option.selected", option=oid)
        if oid.startswith("layout:"):
            self.run_layout(dc.op_layout(oid[7:]), confirm=False)
        elif oid.startswith("arrange:"):
            self.run_layout(dc.op_layout("extend", oid[8:]), confirm=False)
        elif oid.startswith("preset:"):
            st = dc.resolve_preset(oid[7:], dc.get_monitors())
            if st is not None:
                self.run_layout(st, confirm=True)
        elif oid == "back":
            st = dc.op_back()
            if st is not None:
                self.run_layout(st, confirm=False)
        elif oid == "reset":
            self.do_reset()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.ev.info("button", id=ev.button.id)
        if ev.button.id == "apply":
            self.action_apply()
        elif ev.button.id == "reset":
            self.do_reset()

    # ───── 적용 ─────
    def action_apply(self) -> None:
        m = self.mon()
        if m is None:
            return
        v = lambda i: self.query_one("#" + i, Select).value  # noqa: E731
        rel = v("rel")
        pos = None
        if rel != "auto" and v("of") not in ("-", Select.BLANK):
            pos = {"rel": rel, "of": v("of"), "align": v("align")}
        self.ev.info("action.apply", mon=m.name, res=str(v("res")), hz=str(v("hz")), scale=str(v("scale")), rel=rel)
        st = dc.op_set(m.name, str(v("res")), float(v("hz")), float(v("scale")), pos)
        if rel == "auto":
            st["pos"].pop(m.name, None)
        self.run_layout(st, confirm=True)

    @work(thread=True, exclusive=True)
    def run_layout(self, st: dict, confirm: bool) -> None:
        self.call_from_thread(self.msg, "적용 중…")
        self.ev.info("run_layout.begin", layout=st.get("layout"), confirm=confirm)
        tx = dc.Transaction()
        try:
            issues = tx.apply(st)
        except Exception as e:
            self.ev.error("run_layout.fail", exc=f"{type(e).__name__}: {e}")
            raise
        self.ev.info("run_layout.applied", issues=issues)
        if confirm:
            # 이 TUI(또는 터미널)가 죽어도 되돌려지도록 별도 프로세스(systemd 타이머)에도 되돌리기를 예약.
            # 보통은 아래 확인 창의 타이머가 먼저 끝나므로 여유를 둠
            tx.arm(CONFIRM_SECONDS + 5)
        self.call_from_thread(self.after_apply, tx, issues, confirm)

    def after_apply(self, tx: dc.Transaction, issues: list[str], confirm: bool) -> None:
        text = "\n".join(issues) if issues else "적용했습니다."

        def done(keep: bool | None) -> None:
            self.ev.info("after_apply.done", keep=bool(keep), confirm=confirm)
            if keep or not confirm:
                tx.commit()
                self.msg(("⚠ " + text.replace("\n", "\n⚠ ")) if issues else "적용했습니다.")
            else:
                tx.revert()
                self.msg("되돌렸습니다.")
            self.reload_all()
            if self.quick and (keep or not confirm):
                self.exit()

        if confirm:
            self.push_screen(Confirm(("화면이 정상으로 보이면 '유지'를 누르세요.\n\n" + (("⚠ " + text.replace("\n", "\n⚠ ")) if issues else "")).strip(), CONFIRM_SECONDS), done)
        else:
            done(True)

    def do_reset(self) -> None:
        dc.save_state(None)
        dc.hyprctl("reload")
        self.msg("기본 구성으로 초기화했습니다.")
        self.reload_all()
        if self.quick:
            self.exit()

    # ───── 프리셋 저장/삭제 ─────
    def action_save_preset(self) -> None:
        def got(name: str | None) -> None:
            if name:
                ps = dc.load_presets()
                st = dc.mutated_state()
                ps[name] = {k: st[k] for k in ("layout", "monitors", "pos")}
                dc.save_presets(ps)
                self.msg(f"프리셋 '{name}' 저장")
                self.fill_modes()
        self.push_screen(NameInput(), got)

    def action_delete_preset(self) -> None:
        ol = self.query_one("#modes", OptionList)
        if ol.highlighted is None:
            return
        oid = ol.get_option_at_index(ol.highlighted).id or ""
        name = oid[7:] if oid.startswith("preset:") else ""
        ps = dc.load_presets()
        if name in ps:
            ps.pop(name)
            dc.save_presets(ps)
            self.msg(f"프리셋 '{name}' 삭제")
            self.fill_modes()
        else:
            self.msg("사용자 프리셋(★)에서만 삭제할 수 있습니다")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", default="mode", choices=list(FOCUS_IDS))
    ap.add_argument("--quick", action="store_true", help="모드를 고르면 적용하고 바로 종료")
    a = ap.parse_args()
    DisplayUI(a.focus, a.quick).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
