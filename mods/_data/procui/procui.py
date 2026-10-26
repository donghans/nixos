#!/usr/bin/env python3
"""procui — 프로세스 관리 TUI(Textual). 그룹(뷰)으로 묶어 보고, 필터하고, 골라서 안전하게 종료하고, 세부 사용량을 본다.

usageui 는 읽기 전용 모니터이고 procui 는 **조치 도구**다(둘을 섞지 않는다). 되돌릴 수 없는 동작이므로 무확인·자동화 모드는 없다.
- 뷰(g): 소유(시스템/내 작업/내 환경/컨테이너·VM) · 앱 · 서비스 · 세션 — `~/.config/procui/groups.toml` 로 규칙·뷰·보호 이름을 더할 수 있다(procgroups.py 머리말).
- 선택(Space/A/c) → 종료(k): 미리보기 → 확인(y) → SIGTERM 후 3초 기다림 → 살아남으면 다시 물은 뒤 SIGKILL. 보호된 항목은 자물쇠, 일괄 선택에서 제외.
- 기록: `~/.local/state/procui/actions.jsonl`(시각·그룹·이름·PID·신호·결과만 — 명령 인자 없음).
갱신은 기본 수동(r). a 로 2초 자동 갱신(선택 중 줄이 움직이는 것을 피하려고 기본은 꺼 둠).
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "observe"), os.path.join(HERE, "..", "_uikit"),
           os.path.join(HERE, "..", "claude-skills", "donghans-host-resources", "scripts")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)       # 설치본은 모든 모듈이 이 디렉터리에 같이 복사되므로 위 경로는 소스에서 직접 실행할 때만 쓰인다
import procactions as pa
import procgroups as pg
import procscan as ps
import uikit

try:
    import observe_apps
except ImportError:
    observe_apps = None
try:
    import hostmetrics as hm
except ImportError:
    hm = None

CONFIG_PATH = os.environ.get("PROCUI_CONFIG") or os.path.expanduser("~/.config/procui/groups.toml")
STATE_DIR = os.environ.get("PROCUI_STATE_DIR") or os.path.expanduser("~/.local/state/procui")
LOG_PATH = os.path.join(STATE_DIR, "actions.jsonl")
TERM_WAIT = 3.0
SORT_NAMES = {"cpu": "CPU", "mem": "메모리", "n": "개수", "name": "이름"}
SORT_ORDER = ["cpu", "mem", "n", "name"]
SHORT = {"pid1": "init", "self": "내 터미널", "kernel": "커널", "other-uid": "타 사용자", "llm-session": "LLM 세션", "desktop": "데스크톱",
         "vm-container": "VM·컨테이너", "nix": "nix", "infra": "인프라", "user": "사용자 규칙"}


def gib(x):
    return f"{x / ps.GIB:.1f} GiB" if x >= ps.GIB else f"{x / ps.MIB:.0f} MiB"


def table_rows(groups, expanded, sel, pc):
    """화면 표 행 [(key, 셀 리스트)] — 그룹 행(`g|이름`) 다음에 펼친 그룹의 프로세스 행(`p|pid|start`). 순수 함수(시험 가능)."""
    rows = []
    for g in groups:
        locked = [p for p in g["procs"] if pa.protect_reasons(p, pc)]
        free = [p for p in g["procs"] if p not in locked]
        chosen = sum(1 for p in free if pa.key(p) in sel)
        mark = "[x]" if free and chosen == len(free) else "[-]" if chosen else "[ ]"
        st = "bold" if chosen else "default"
        arrow = "▾" if g["name"] in expanded else "▸"
        rows.append((f"g|{g['name']}", [Text(mark, style=st), Text(f"{arrow} {g['name']} ({g['n']})", style="bold"), "", "",
                                          f"{g['cpu']:.1f}", f"{g['rss'] / ps.MIB:.0f}", Text(f"잠금 {len(locked)}" if locked else "", style="grey62")]))
        if g["name"] in expanded:
            for p in g["procs"]:
                r = pa.protect_reasons(p, pc)
                picked = pa.key(p) in sel
                rows.append((f"p|{p['pid']}|{p['start']}", [Text("[x]" if picked else "[ ]", style="bold" if picked else "default"), Text("   " + p["comm"]), p["app"],
                                                         str(p["pid"]), f"{p['cpu']:.1f}", f"{p['rss'] / ps.MIB:.0f}",
                                                         Text("잠금: " + ", ".join(SHORT.get(c, c) for c, _ in r), style="yellow" if not pa.is_hard(r) else "red") if r else ""]))
    return rows


def preview_text(plan, view_name, ctx, view):
    t = Text()
    n = len(plan["targets"])
    t.append(f"SIGTERM 을 보낼 프로세스 {n}개\n", style="bold")
    by = {}
    for p in plan["targets"]:
        g = pg.classify(view, p, ctx)
        by.setdefault(g, []).append(p)
    for g, ps_ in sorted(by.items(), key=lambda kv: -len(kv[1])):
        t.append(f"  {g}: {len(ps_)}개 — " + ", ".join(sorted({p['comm'] for p in ps_}))[:70] + "\n")
    mem = plan["pss_kib"] * 1024 if plan["pss_kib"] else plan["rss"]
    t.append(f"\n예상 확보 메모리 약 {gib(mem)}" + (" (PSS 합" + (f", {plan['pss_unknown']}개는 못 쟀음" if plan["pss_unknown"] else "") + ")" if plan["pss_kib"] else " (RSS 합, 공유 포함이라 과대)") + "\n")
    if plan["children_separate"]:
        t.append(f"선택하지 않은 자식 프로세스 {plan['children_separate']}개가 있다 — 부모만 죽으면 자식은 남는다(필요하면 자식도 선택)\n", style="yellow")
    if plan["excluded"]:
        t.append(f"\n보호로 제외 {len(plan['excluded'])}개:\n", style="yellow")
        for p, r in plan["excluded"][:8]:
            t.append(f"  {p['comm']}({p['pid']}) — " + ", ".join(x for _, x in r) + "\n", style="grey62")
        if len(plan["excluded"]) > 8:
            t.append(f"  … 외 {len(plan['excluded']) - 8}개\n", style="grey62")
    return t


class ConfirmScreen(ModalScreen):
    """미리보기 후 확인(y/Enter) 또는 취소(Esc/n). 결과는 dismiss(True|False)."""
    BINDINGS = [Binding("y,enter", "yes", "실행"), Binding("n,escape", "no", "취소")]

    def __init__(self, title, body, hint):
        super().__init__()
        self._title, self._body, self._hint = title, body, hint

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Static(self._body)
            yield Static(self._hint, id="dialog-hint")

    def action_yes(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


class OverrideScreen(ModalScreen):
    """소프트 보호를 개별로 풀려면 프로세스 이름을 그대로 다시 입력해야 한다."""
    BINDINGS = [Binding("escape", "no", "취소")]

    def __init__(self, p, reasons):
        super().__init__()
        self.p, self.reasons = p, reasons

    def compose(self):
        with Vertical(id="dialog"):
            yield Static(f"보호된 프로세스 — {self.p['comm']} (pid {self.p['pid']})", id="dialog-title")
            yield Static("보호 사유: " + ", ".join(x for _, x in self.reasons) + "\n\n그래도 종료 대상에 넣으려면 프로세스 이름을 정확히 입력하고 Enter:")
            yield Input(placeholder=self.p["comm"], id="override-name")
            yield Static("Esc 취소", id="dialog-hint")

    def on_mount(self):
        self.query_one("#override-name", Input).focus()

    def on_input_submitted(self, ev):
        self.dismiss(ev.value == self.p["comm"])

    def action_no(self):
        self.dismiss(False)


class InfoScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,enter,d", "close", "닫기")]

    def __init__(self, title, body):
        super().__init__()
        self._title, self._body = title, body

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Static(self._body)
            yield Static("아무 키나 누르면 닫힘", id="dialog-hint")

    def action_close(self):
        self.dismiss()


class ProcUI(uikit.HelpMixin, uikit.PauseOnBlurMixin, App):
    TITLE = "procui"
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    #head { height: 3; padding: 0 1; }
    #filter { height: 3; }
    #tbl { height: 1fr; background: #000000; }
    #dialog { width: 90%; max-width: 110; max-height: 90%; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("g", "cycle_view", "뷰"), Binding("slash", "focus_filter", "필터"), Binding("s", "cycle_sort", "정렬"),
        Binding("space", "toggle_select", "선택"), Binding("A", "select_all", "전체 선택"), Binding("c", "clear_select", "선택 해제"),
        Binding("k", "kill", "종료(미리보기)"), Binding("d", "detail", "상세"), Binding("r,f5", "refresh_now", "새로고침"), Binding("a", "toggle_auto", "자동 갱신"),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, view=None, filter_text="", config_path=None, log_path=None):
        super().__init__()
        extra, self.protect_extra, self.warns = pg.load_config(CONFIG_PATH if config_path is None else config_path)
        self.views = pg.merge_views(pg.BUILTIN_VIEWS, extra)
        names = [v["name"] for v in self.views]
        self.view_i = names.index(view) if view in names else 0
        self.filter_text = filter_text
        self.sort = "cpu"
        self.expanded, self.sel, self.override = set(), set(), set()
        self.procs, self.ctx, self.groups = [], None, []
        self.resolver = observe_apps.AppResolver() if observe_apps else None
        self.cpu_prev, self._t = {}, None
        self.log_path = log_path or LOG_PATH
        self._timer = None
        self._sess_cache = (0.0, {})
        self._rowkeys = []

    # --- 구성
    def compose(self) -> ComposeResult:
        yield Static("", id="head")
        yield uikit.box(Input(value=self.filter_text, placeholder="필터: 이름·app:이름·group:이름·user:me|root·cpu>50·mem>500M·pid:123 (공백=AND)", id="filter"), "필터 ( / 키 )")
        t = DataTable(id="tbl", cursor_type="row", zebra_stripes=True)
        t.add_columns("", "이름 / 그룹", "앱", "PID", "CPU %", "RSS MiB", "보호")
        yield uikit.box(t, "프로세스")
        with Vertical(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        if self.warns:
            self.status("설정 경고: " + " / ".join(self.warns[:2]))
        elif not pa.supported():
            self.status("이 환경은 pidfd 를 지원하지 않아 종료 기능이 꺼져 있습니다(보기만 가능)")
        self.query_one("#tbl", DataTable).focus()
        self.rescan()

    def status(self, msg):
        self.query_one("#status", Static).update(" " + msg)

    @property
    def view(self):
        return self.views[self.view_i]

    # --- 데이터
    def session_names(self):
        """세션 뷰일 때만 {pid: 세션 이름} — transcript 를 읽으므로 10초 캐시, ctx 저장소는 부르지 않는다."""
        if self.view["default"] != "@session" or hm is None:
            return {}
        if time.monotonic() - self._sess_cache[0] > 10:
            try:
                self._sess_cache = (time.monotonic(), {pid: m["name"] for pid, m in hm.session_meta(False).items()})
            except Exception:
                self._sess_cache = (time.monotonic(), {})
        return self._sess_cache[1]

    def rescan(self):
        now = time.monotonic()
        procs = ps.annotate(ps.scan(), self.resolver)
        self.cpu_prev = ps.with_cpu(procs, self.cpu_prev, (now - self._t) if self._t else 0)
        self._t = now
        self.procs = procs
        live = {pa.key(p) for p in procs}
        self.sel &= live
        self.override &= live
        self.redraw()

    def pctx(self):
        return pa.PCtx(self.procs, self.protect_extra)

    def redraw(self):
        self.ctx = pg.Ctx(self.procs, session_names=self.session_names())
        pred, fw = pg.parse_filter(self.filter_text)
        self.groups = pg.build_groups(self.procs, self.view, self.ctx, pred, self.sort)
        if self.filter_text and self.groups and len(self.groups) <= 3:
            self.expanded |= {g["name"] for g in self.groups}        # 필터 결과가 적으면 바로 펼쳐 보인다
        t = self.query_one("#tbl", DataTable)
        cur = self._cur_key()
        rows = table_rows(self.groups, self.expanded, self.sel, self.pctx())
        t.clear()
        for k, cells in rows:
            t.add_row(*cells, key=k)
        self._rowkeys = [k for k, _ in rows]
        if cur in self._rowkeys:
            t.move_cursor(row=self._rowkeys.index(cur))
        n = sum(g["n"] for g in self.groups)
        head = Text()
        head.append(f"뷰 {self.view['name']} ", style="bold #33ccff")
        head.append(f"({self.view_i + 1}/{len(self.views)}, g 로 바꿈) · 정렬 {SORT_NAMES[self.sort]} · 그룹 {len(self.groups)}개 · 프로세스 {n}/{len(self.procs)}개 · 선택 {len(self.sel)}개"
                    f" · 자동 갱신 {'켜짐' if self._timer else '꺼짐'}\n", style="default")
        head.append("Space 선택 · A 전체 선택 · c 해제 · k 종료 미리보기 · Enter 펼침/상세 · d 상세 · / 필터 · s 정렬 · r 새로고침 · ? 도움말", style="grey50")
        self.query_one("#head", Static).update(head)
        if fw:
            self.status("필터 경고: " + " / ".join(fw))

    def _cur_key(self):
        t = self.query_one("#tbl", DataTable)
        try:
            return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            return None

    def _cur(self):
        """현재 줄 → ('g', 그룹 dict) | ('p', 프로세스 dict) | None"""
        k = self._cur_key()
        if not k:
            return None
        if k.startswith("g|"):
            return "g", next((g for g in self.groups if g["name"] == k[2:]), None)
        _, pid, start = k.split("|")
        return "p", next((p for p in self.procs if p["pid"] == int(pid) and p["start"] == int(start)), None)

    # --- 보기·선택
    def action_cycle_view(self):
        self.view_i = (self.view_i + 1) % len(self.views)
        self.expanded = set()
        self.redraw()

    def action_cycle_sort(self):
        self.sort = SORT_ORDER[(SORT_ORDER.index(self.sort) + 1) % len(SORT_ORDER)]
        self.redraw()

    def action_focus_filter(self):
        self.query_one("#filter", Input).focus()

    def on_input_changed(self, ev):
        if ev.input.id == "filter":
            self.filter_text = ev.value
            self.redraw()

    def on_input_submitted(self, ev):
        if ev.input.id == "filter":
            self.query_one("#tbl", DataTable).focus()

    def action_refresh_now(self):
        self.rescan()

    def action_toggle_auto(self):
        if self._timer:
            self._timer.stop()
            self._timer = None
        else:
            self._timer = self.set_interval(2.0, self._auto)
        self.redraw()

    def _auto(self):
        if len(self.screen_stack) == 1:       # 대화상자가 떠 있는 동안은 줄이 바뀌지 않게 갱신하지 않는다
            self.rescan()

    def refresh_data(self):
        if self._timer is not None and len(self.screen_stack) == 1:
            self.rescan()

    def on_data_table_row_selected(self, ev):
        cur = self._cur()
        if not cur or not cur[1]:
            return
        if cur[0] == "g":
            self.expanded ^= {cur[1]["name"]}
            self.redraw()
        else:
            self.action_detail()

    def action_toggle_select(self):
        cur = self._cur()
        if not cur or not cur[1]:
            return
        pc = self.pctx()
        if cur[0] == "g":
            free = [p for p in cur[1]["procs"] if not pa.protect_reasons(p, pc)]
            if not free:
                self.status("이 그룹은 전부 보호 대상이라 선택할 수 없습니다")
                return
            keys = {pa.key(p) for p in free}
            if keys <= self.sel:
                self.sel -= keys
            else:
                self.sel |= keys
            skipped = len(cur[1]["procs"]) - len(free)
            self.status(f"그룹 '{cur[1]['name']}': {len(free)}개 선택 대상" + (f" · 보호 {skipped}개는 제외" if skipped else ""))
            self.redraw()
            return
        p = cur[1]
        r = pa.protect_reasons(p, pc)
        k = pa.key(p)
        if k in self.sel:
            self.sel.discard(k)
            self.override.discard(k)
        elif not r:
            self.sel.add(k)
        elif pa.is_hard(r):
            self.status("선택할 수 없음(하드 보호): " + ", ".join(x for _, x in r))
        else:
            def done(ok):
                if ok:
                    self.sel.add(k)
                    self.override.add(k)
                    self.status(f"{p['comm']}({p['pid']}) 보호를 풀고 선택했습니다")
                else:
                    self.status("보호 해제 취소")
                self.redraw()
            self.push_screen(OverrideScreen(p, r), done)
            return
        self.redraw()

    def action_select_all(self):
        pc = self.pctx()
        n = 0
        for g in self.groups:
            for p in g["procs"]:
                if not pa.protect_reasons(p, pc):
                    self.sel.add(pa.key(p))
                    n += 1
        self.status(f"보이는 프로세스 중 보호되지 않은 {n}개를 선택했습니다")
        self.redraw()

    def action_clear_select(self):
        self.sel, self.override = set(), set()
        self.redraw()

    # --- 상세
    def action_detail(self):
        cur = self._cur()
        if not cur or not cur[1]:
            return
        if cur[0] == "g":
            g = cur[1]
            body = Text(f"프로세스 {g['n']}개 · CPU 합 {g['cpu']:.1f}% · RSS 합 {gib(g['rss'])}(공유 포함)\n\n상위 12:\n")
            for p in g["procs"][:12]:
                body.append(f"  {p['comm'][:24]:<24} pid {p['pid']:<8} CPU {p['cpu']:5.1f}%  RSS {p['rss'] / ps.MIB:6.0f} MiB\n")
            self.push_screen(InfoScreen(f"그룹 — {g['name']}", body))
            return
        p = cur[1]
        labels = {v["name"]: pg.classify(v, p, self.ctx) for v in self.views}
        lines = ps.detail(p, self.procs, labels)
        r = pa.protect_reasons(p, self.pctx())
        lines.append("보호  " + (", ".join(x for _, x in r) if r else "없음"))
        self.push_screen(InfoScreen(f"프로세스 — {p['comm']}", "\n".join(lines)))

    # --- 종료
    def action_kill(self):
        if not pa.supported():
            self.status("이 환경은 pidfd 를 지원하지 않아 종료할 수 없습니다")
            return
        if not self.sel:
            self.status("선택된 프로세스가 없습니다 (Space/A 로 선택)")
            return
        self.rescan()                                                # 미리보기는 항상 새 스냅샷 기준
        plan = pa.build_plan(self.procs, self.sel, self.override, self.pctx())
        if not plan["targets"]:
            self.status("종료 대상이 없습니다(선택이 모두 사라졌거나 보호로 제외됨)")
            return
        body = preview_text(plan, self.view["name"], self.ctx, self.view)

        def go(ok):
            if ok:
                self.run_kill(plan["targets"], sorted(self.override))
            else:
                self.status("종료 취소")
        self.push_screen(ConfirmScreen("종료 미리보기", body, "y/Enter 실행(SIGTERM) · Esc/n 취소 — 되돌릴 수 없습니다"), go)

    @work(thread=True, exclusive=True, group="kill")
    def run_kill(self, targets, override):
        self.call_from_thread(self.status, f"SIGTERM 전송 중… ({len(targets)}개, 최대 {TERM_WAIT:.0f}초 대기)")
        ov = set(override)
        res, alive = pa.send(targets, signal.SIGTERM, ov, self.protect_extra, TERM_WAIT)
        pa.log(self.log_path, res, self.view["name"])
        self.call_from_thread(self.after_term, res, alive, ov)

    def after_term(self, res, alive, ov):
        ok = sum(1 for r in res if r["status"] == "sent")
        bad = [r for r in res if r["status"] not in ("sent", "gone")]
        self.rescan()
        msg = f"SIGTERM {ok}개 전송"
        if bad:
            msg += f" · 거부·실패 {len(bad)}개(" + "; ".join(f"{r['comm']}: {r['detail']}" for r in bad[:2]) + ")"
        if not alive:
            self.status(msg + " · 모두 종료됨")
            return
        body = Text(f"{TERM_WAIT:.0f}초 안에 끝나지 않은 프로세스 {len(alive)}개:\n\n")
        for p in alive[:12]:
            body.append(f"  {p['comm']} (pid {p['pid']})\n")

        def go(ok_):
            if ok_:
                self.run_kill9(alive, ov)
            else:
                self.status(msg + f" · 살아남은 {len(alive)}개는 그대로 둠")
        self.push_screen(ConfirmScreen("SIGTERM 에 응답하지 않음", body, "y/Enter 로 SIGKILL(강제 종료) · Esc/n 그대로 둠"), go)

    @work(thread=True, exclusive=True, group="kill")
    def run_kill9(self, alive, ov):
        res, left = pa.send(alive, signal.SIGKILL, ov, self.protect_extra, 2.0)
        pa.log(self.log_path, res, self.view["name"])
        self.call_from_thread(self.after_kill9, res, left)

    def after_kill9(self, res, left):
        self.rescan()
        self.status(f"SIGKILL {sum(1 for r in res if r['status'] == 'sent')}개 전송 · 남은 것 {len(left)}개")


def main(argv=None):
    p = argparse.ArgumentParser(prog="procui", description="프로세스 관리 TUI — 그룹·필터·안전한 일괄 종료")
    p.add_argument("--view", default=None, help="처음 뷰(소유·앱·서비스·세션 또는 groups.toml 의 이름)")
    p.add_argument("--filter", default="", help="처음 필터 식")
    a = p.parse_args(argv)
    ProcUI(a.view, a.filter).run()


if __name__ == "__main__":
    main()
