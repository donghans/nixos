#!/usr/bin/env python3
"""embedctlui — embedctl 의 TUI (Textual + uikit). MSI Summit E16Flip(MS-1592) 한 기종의 EC 상태를 보고 바꾼다.

한 화면에 ① 기종·펌웨어 게이트와 접근 방식 ② 충전 상한(드롭다운) ③ 성능 모드(드롭다운) ④ Cooler Boost(켜짐일 때 경고) ⑤ 팬 RPM·온도(2초 갱신, 창이 포커스를 잃으면 멈춤) ⑥ 스냅샷 저장/복원.
EC 바이트를 읽는 건 root helper 를 부르므로 열 때·동작 뒤·F5 에서만 한다(주기 갱신 대상은 사용자 권한으로 읽히는 팬·온도·전원뿐).
모든 쓰기는 embedctl 과 같은 경로(embedlib.helper_call → embedctl-root@<동작>.service)이고 게이트·되읽기 확인은 helper 가 한다. 설계: ctx `plan/embedctl-구현` §3-5.
"""
from __future__ import annotations

import json
import os
import sys

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, OptionList, Select, Static
from textual.widgets.option_list import Option

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../../_lib/uikit
    sys.path.insert(0, os.path.join(HERE, "..", "..", "_lib", "uikit"))
    import uikit
import embedlib as lib   # noqa: E402

CHARGE_STEPS = (50, 60, 70, 80, 90, 100)
MODE_OPTS = [("sport — 성능", "sport"), ("comfort — 균형", "comfort"), ("eco — 조용(팬 정지)", "eco")]
GATE_TEXT = {"verified": "검증됨", "unverified_fw": "미검증 펌웨어 — 읽기만", "unsupported_board": "지원하지 않는 기종 — 읽기만", "unknown": "펌웨어를 읽지 못함 — 쓰기 거부"}
ACCESS_TEXT = {"direct": "직접(root)", "helper": "helper(polkit)", "unavailable": "사용 불가"}


def charge_options(limit):
    """50~100 (10 단위) + 지금 값이 그 밖이면 지금 값도 보인다(예: 85, 또는 허용 범위 밖이어도 현재 상태는 보여 준다)."""
    vals = list(CHARGE_STEPS)
    if limit is not None and limit not in vals:
        vals = sorted(vals + [limit])
    return [(("100% — 상한 없음" if v == 100 else f"{v}%") + ("" if v in CHARGE_STEPS else " (현재)"), v) for v in vals]


class SnapshotPick(ModalScreen):
    """저장된 스냅샷을 고르는 대화상자(최신순). Enter = 고름, Esc = 취소."""
    BINDINGS = [Binding("escape", "close", "취소")]

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def compose(self):
        with Vertical(id="dialog"):
            yield Static("복원할 스냅샷", id="dialog-title")
            opts = []
            for p in self.paths:
                try:
                    s = json.load(open(p))
                    desc = f"{s.get('time', '?')[:19].replace('T', ' ')}  충전 {((s.get('charge') or {}).get('limit'))}% · {s.get('mode')} · boost {'on' if s.get('boost') else 'off'}"
                except (OSError, ValueError):
                    desc = f"{os.path.basename(p)} (읽을 수 없음)"
                opts.append(Option(desc, id=p))
            yield OptionList(*opts, id="snap-list")
            yield Static("↑↓ 선택 · Enter 복원 계획 보기 · Esc 취소", id="dialog-hint")

    def on_mount(self):
        self.query_one("#snap-list", OptionList).focus()

    def on_option_list_option_selected(self, ev):
        ev.stop()
        self.dismiss(ev.option.id)

    def action_close(self):
        self.dismiss(None)


class EmbedUI(uikit.PauseOnBlurMixin, uikit.QuitMixin, uikit.HelpMixin, App):
    TITLE = "EC 상태"
    ENABLE_COMMAND_PALETTE = False
    HELP_TERMS = [
        ("충전 상한", "충전을 이 % 에서 멈춘다(50~100). 100 이 「상한 없음」과 같다. 값은 EC 에 남아 OS 를 바꿔도 유지된다. TLP 가 같은 설정을 갖고 있으면 TLP 가 덮어쓸 수 있다"),
        ("성능 모드", "sport · comfort · eco. 팬 동작이 달라진다 — 이 기기에서 eco 는 유휴·가벼운 부하에서 팬이 멈추고 comfort/sport 는 약 2,800 RPM 으로 돈다. user 모드는 다루지 않는다"),
        ("Cooler Boost", "F8. 팬을 최대(약 8,000 RPM)로 돌린다. 끄기 전까지 자동으로 꺼지지 않는다 — 켜져 있으면 화면에 경고가 보인다"),
        ("스냅샷", "F6 저장 / F7 복원. 충전 상한·성능 모드·Cooler Boost 를 파일(~/.local/state/embedctl/snapshots)에 남기고 되돌린다. 복원은 먼저 계획을 보여 주고 확인을 받는다. 펌웨어가 다른 스냅샷은 거부"),
        ("접근 방식", "helper(polkit) = 로컬 세션에서 root helper 를 거친다. 「사용 불가」면 EC 항목을 읽거나 바꿀 수 없다(SSH 같은 세션 밖). 쓰기는 기종·EC 펌웨어가 검증된 때만 켜진다"),
    ]
    HELP_NOTES = [
        "종료는 Esc(뒤로 갈 곳이 없을 때 확인창), Ctrl+Q 는 확인 없이 즉시 종료. 모든 동작은 helper 가 쓴 뒤 되읽어 확인하며 어긋나면 실패로 표시한다",
    ]
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    #status { height: 3; padding: 1 1 0 1; color: #cfcfcf; }
    #selects { height: 5; }
    #selects > Select { width: 1fr; }
    #row2 { height: 7; }
    #boost-box { width: 1fr; height: 7; padding: 0 1; }
    #boost-box.on { border: round #b8a46a; }
    #boost-state { height: 3; }
    #snap-box { width: 1fr; height: 7; padding: 0 1; }
    #live { height: 6; padding: 0 1; }
    #msg { height: 3; padding: 0 1; color: #cfcfcf; }
    #msg.err { color: #d75f5f; }
    #msg.ok { color: #87d787; }
    Button { margin: 0 1 0 0; }
    """
    BINDINGS = [
        *uikit.HelpMixin.HELP_BINDINGS,
        Binding("escape", "escape", "뒤로/종료"),
        Binding("f5", "reload", "새로고침"),
        Binding("f6", "snap_save", "스냅샷 저장"),
        Binding("f7", "snap_restore", "스냅샷 복원"),
        Binding("f8", "toggle_boost", "Cooler Boost"),
        Binding("ctrl+q", "quit", "종료", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.st = None
        self._syncing = False
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        with Horizontal(id="selects"):
            yield uikit.select_box(charge_options(100), 100, "sel-charge", "충전 상한")
            yield uikit.select_box(MODE_OPTS, "comfort", "sel-mode", "성능 모드")
        with Horizontal(id="row2"):
            yield uikit.box(Vertical(Static("", id="boost-state"), Button("켜기 / 끄기 (F8)", id="btn-boost"), id="boost-box"), "Cooler Boost")
            yield uikit.box(Vertical(Static("F6 저장 · F7 복원\n저장 위치: " + lib.snapshot_dir(), id="snap-info"),
                                     Horizontal(Button("저장", id="btn-save"), Button("복원…", id="btn-restore"))), "스냅샷")
        yield uikit.box(Static("", id="live"), "팬 · 온도 · 전원")
        yield Static("", id="msg")
        yield Footer()

    def on_mount(self) -> None:
        self._timer = self.set_interval(2.0, self.tick)
        self.tick()
        self.reload()

    # --- 갱신 ----------------------------------------------------------------------------------
    def refresh_data(self) -> None:                # PauseOnBlurMixin: 포커스가 돌아오면 한 번 부른다
        self.tick()

    def tick(self) -> None:
        """사용자 권한으로 읽히는 것(팬·온도·전원)만. EC 바이트는 여기서 읽지 않는다(helper 호출이라 무겁다)."""
        fans, temp = lib.read_fans(), lib.read_temp_pkg()
        ac = lib._read(os.path.join(lib.p_ac(), "online"))
        bat = lib._read(os.path.join(lib.p_bat(), "status"))
        cap = lib._read(os.path.join(lib.p_bat(), "capacity"))
        t = Text()
        t.append("팬  ")
        t.append(" · ".join(f"fan{i + 1} {v}" for i, v in enumerate(fans)) + " RPM" if fans else "읽지 못함")
        t.append("\n온도  " + (f"패키지 {temp:.1f}°C" if temp is not None else "읽지 못함"))
        t.append("\n전원  " + {"1": "AC 연결", "0": "배터리"}.get(ac, "?") + f" · {bat or '?'} {cap or '?'}%")
        self.query_one("#live", Static).update(t)

    @work(thread=True, exclusive=True, group="reload")
    def reload(self) -> None:
        st = lib.collect_status()
        self.call_from_thread(self.apply_state, st)

    def action_reload(self) -> None:
        self.reload()
        self.say("새로고침", None)

    def writable(self) -> bool:
        return bool(self.st) and self.st["access"] != "unavailable" and self.st["gate"]["state"] == "verified"

    def apply_state(self, st) -> None:
        self.st = st
        g = st["gate"]
        line = Text()
        line.append(f"{g['board'] or '?'} · EC 펌웨어 {g['fw'] or '?'} · {GATE_TEXT[g['state']]}  |  EC 접근: {ACCESS_TEXT[st['access']]}")
        if st["warnings"] and st["access"] == "unavailable":
            line.append("\n" + st["warnings"][0][:120], style="#b8a46a")
        self.query_one("#status", Static).update(line)
        can = self.writable()
        self._syncing = True
        try:
            sc, sm = self.query_one("#sel-charge", Select), self.query_one("#sel-mode", Select)
            limit = st["charge"]["limit"]
            if limit is not None:
                opts = charge_options(limit)
                if [o[1] for o in opts] != [o[1] for o in getattr(self, "_charge_opts", [])]:
                    sc.set_options(opts)
                    self._charge_opts = opts
                uikit.sync_select(sc, limit)
            if st["mode"] and st["mode"]["name"] in lib.MODE_BITS:
                uikit.sync_select(sm, st["mode"]["name"])
            sc.disabled = not can or limit is None
            sm.disabled = not can or not (st["mode"] and st["mode"]["name"] in lib.MODE_BITS)
        finally:
            self.call_after_refresh(self._unsync)
        boost = st["boost"]
        bs = self.query_one("#boost-state", Static)
        box = self.query_one("#boost-box")
        if boost is None:
            bs.update("알 수 없음(EC 를 읽지 못함)")
        elif boost:
            bs.update(Text("켜짐 — 팬 최대 · 자동으로 꺼지지 않는다", style="bold #b8a46a"))
        else:
            bs.update("꺼짐")
        box.set_class(bool(boost), "on")
        self.query_one("#btn-boost", Button).disabled = not can
        self.query_one("#btn-restore", Button).disabled = not can
        self.query_one("#btn-save", Button).disabled = False

    def _unsync(self) -> None:
        self._syncing = False

    def say(self, text, ok) -> None:
        m = self.query_one("#msg", Static)
        m.update(text)
        m.set_class(ok is False, "err")
        m.set_class(ok is True, "ok")

    # --- 쓰기 동작 --------------------------------------------------------------------------------
    # 주의: 이름을 run_action 으로 하면 Textual 의 App.run_action(모든 키 바인딩이 부르는 내부 메서드)을 덮어쓴다
    @work(thread=True, exclusive=True, group="act")
    def act_worker(self, kind: str, inst: str) -> None:
        try:
            res = lib.helper_call(inst, timeout=30)
            _, line = lib.action_summary(kind, res)
            self.call_from_thread(self.after_action, True, line)
        except lib.HelperError as e:
            self.call_from_thread(self.after_action, False, f"실패(종료 코드 {e.code}): {e}")

    def after_action(self, ok: bool, text: str) -> None:
        self._busy = False
        self.say(text, ok)
        self.reload()                              # 성공이든 실패든 실제 상태로 화면(드롭다운 포함)을 다시 맞춘다

    def start_action(self, kind: str, inst: str) -> None:
        if self._busy or not self.writable():
            return
        self._busy = True
        self.say(f"{lib.LABEL[kind]}: 적용 중…", None)
        self.act_worker(kind, inst)

    def on_select_changed(self, ev: Select.Changed) -> None:
        if self._syncing or self.st is None:
            return
        v = ev.value
        if ev.select.id == "sel-charge":
            if v == self.st["charge"]["limit"]:    # 현재 상태와 같으면 무시(uikit 규칙: 되돌아온 Changed)
                return
            self.start_action("charge", f"charge-{v}")
        elif ev.select.id == "sel-mode":
            if self.st["mode"] and v == self.st["mode"]["name"]:
                return
            self.start_action("mode", f"mode-{v}")

    def action_toggle_boost(self) -> None:
        if self.st and self.st["boost"] is not None:
            self.start_action("boost", "boost-off" if self.st["boost"] else "boost-on")

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        ev.stop()
        bid = ev.button.id
        if bid == "btn-boost":
            self.action_toggle_boost()
        elif bid == "btn-save":
            self.action_snap_save()
        elif bid == "btn-restore":
            self.action_snap_restore()

    # --- 스냅샷 ----------------------------------------------------------------------------------
    def action_snap_save(self) -> None:
        if len(self.screen_stack) > 1 or self.st is None:
            return
        try:
            path = lib.save_snapshot(self.st)
        except OSError as e:
            self.say(f"스냅샷을 저장하지 못했다: {e}", False)
            return
        warn = "" if self.st["ec"] else "  (주의: EC 값이 없는 스냅샷이라 복원에는 쓸 수 없다)"
        self.say(f"스냅샷을 저장했다: {path}{warn}", True)

    def action_snap_restore(self) -> None:
        if len(self.screen_stack) > 1 or not self.writable():
            return
        paths = lib.list_snapshots()
        if not paths:
            self.say(f"저장된 스냅샷이 없다({lib.snapshot_dir()}) — F6 으로 먼저 저장한다", False)
            return
        self.push_screen(SnapshotPick(paths), self._picked)

    def _picked(self, path) -> None:
        if not path:
            return
        try:
            snap = json.load(open(path))
        except (OSError, ValueError) as e:
            self.say(f"스냅샷을 읽지 못했다: {e}", False)
            return
        try:
            plan, notes = lib.restore_plan(snap, self.st)
        except lib.RestoreError as e:
            self.say(f"복원할 수 없다(종료 코드 {e.code}): {e.msg}", False)
            return
        if not plan:
            self.say("이미 스냅샷과 같은 상태다 — 할 일이 없다", True)
            return
        question = "다음을 적용할까요?\n" + "\n".join("  " + p["text"] for p in plan) + ("\n" + "\n".join("  (참고) " + n for n in notes) if notes else "")
        self.push_screen(uikit.ConfirmScreen(question, "적용", "취소"), lambda yes, plan=plan: self.restore_apply(plan) if yes is True else None)

    @work(thread=True, exclusive=True, group="act")
    def restore_apply(self, plan) -> None:
        done = []
        try:
            for p in plan:
                res = lib.helper_call(p["instance"], timeout=30)
                _, line = lib.action_summary(p["kind"], res)
                done.append(line)
            self.call_from_thread(self.after_action, True, "복원 완료\n" + "\n".join(done))
        except lib.HelperError as e:
            self.call_from_thread(self.after_action, False, f"복원 중 실패(종료 코드 {e.code}): {e} — 이미 적용된 것: {len(done)}개")

    # --- 종료 규칙 ---------------------------------------------------------------------------------
    def action_escape(self) -> None:
        self.action_confirm_quit()


def main() -> int:
    EmbedUI().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
