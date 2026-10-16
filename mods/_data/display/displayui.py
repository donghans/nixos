#!/usr/bin/env python3
"""displayui — Hyprland 화면 관리 TUI (Textual). 코어는 displayctl.py

왼쪽: 화면 모드(확장/미러/노트북만/외부만)와 프리셋(프리젠테이션 등). Enter 로 바로 적용.
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

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import displayctl as dc  # noqa: E402

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
    Confirm > Vertical { width: 64; height: auto; border: round #33ccff; background: $surface; padding: 1 2; }
    Confirm Horizontal { height: 3; margin-top: 1; align-horizontal: center; }
    Confirm Button { margin: 0 2; }
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
                yield Button("유지 (Enter)", id="keep", variant="success")
                yield Button("되돌리기 (Esc)", id="undo", variant="error")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        self.query_one("#ccount", Static).update(f"{self.left}초 안에 선택하지 않으면 자동으로 되돌립니다")
        if self.left <= 0:
            self.dismiss(False)
        self.left -= 1

    def action_keep(self) -> None:
        self.dismiss(True)

    def action_undo(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(ev.button.id == "keep")


class NameInput(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", "취소")]
    DEFAULT_CSS = """
    NameInput { align: center middle; }
    NameInput > Vertical { width: 56; height: auto; border: round #33ccff; background: $surface; padding: 1 2; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("현재 구성을 프리셋으로 저장 — 이름:")
            yield Input(placeholder="예: 회의실", id="pname")

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class DisplayUI(App):
    TITLE = "화면 관리"
    CSS = """
    #body { height: 1fr; }
    #left { width: 38; border: round #33ccff; }
    #right { width: 1fr; }
    #modes { height: 1fr; background: transparent; }
    #mons { height: 6; border: round #33ccff; }
    #form { border: round #33ccff; padding: 0 1; height: auto; }
    .row { height: 3; }
    .row Label { width: 12; padding-top: 1; }
    .row Select { width: 1fr; }
    #buttons { height: 3; margin-top: 1; }
    #buttons Button { margin-right: 2; }
    #msg { height: auto; min-height: 1; padding: 0 1; color: #ebcb8b; }
    .narrow #body { layout: vertical; }
    .narrow #left { width: 1fr; height: 10; }
    """
    BINDINGS = [
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
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label(" 화면 모드 / 프리셋  (Enter: 적용)")
                yield OptionList(id="modes")
            with VerticalScroll(id="right"):
                yield DataTable(id="mons", cursor_type="row")
                with Vertical(id="form"):
                    yield Label("선택한 모니터 설정")
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

    def on_mount(self) -> None:
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
        for k, label in dc.LAYOUTS.items():
            ol.add_option(Option(("● " if k == cur and not (st and st.get("preset")) else "  ") + label, id=f"layout:{k}"))
        ol.add_option(Option("── 프리셋 ──", disabled=True))
        for k, v in dc.BUILTIN_PRESETS.items():
            ol.add_option(Option(("● " if st and st.get("preset") == k else "  ") + v["label"], id=f"preset:{k}"))
        users = dc.load_presets()
        for k in users:
            ol.add_option(Option(("● " if st and st.get("preset") == k else "  ") + f"★ {k}", id=f"preset:{k}"))
        ol.add_option(Option("── 기타 ──", disabled=True))
        if st and st.get("before"):
            ol.add_option(Option("  ↩ 이전 구성으로 복귀", id="back"))
        ol.add_option(Option("  ⟲ 기본 구성으로 초기화", id="reset"))

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
            self.query_one("#align", Select).value = (spec or {}).get("align", "start")
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
        if oid.startswith("layout:"):
            self.run_layout(dc.op_layout(oid[7:]), confirm=False)
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
        st = dc.op_set(m.name, str(v("res")), float(v("hz")), float(v("scale")), pos)
        if rel == "auto":
            st["pos"].pop(m.name, None)
        self.run_layout(st, confirm=True)

    @work(thread=True, exclusive=True)
    def run_layout(self, st: dict, confirm: bool) -> None:
        self.call_from_thread(self.msg, "적용 중…")
        tx = dc.Transaction()
        issues = tx.apply(st)
        self.call_from_thread(self.after_apply, tx, issues, confirm)

    def after_apply(self, tx: dc.Transaction, issues: list[str], confirm: bool) -> None:
        text = "\n".join(issues) if issues else "적용했습니다."

        def done(keep: bool | None) -> None:
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
