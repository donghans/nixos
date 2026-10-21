#!/usr/bin/env python3
"""usageui — 전력·자원 사용 습관 TUI (Textual). observectl 이 쌓은 표본을 '시간 범위' 기준으로 조회해 보여 준다.

원칙: ① 조회는 범위 기준(기본 = 지금까지 최근 1시간) ② **갱신은 수동만**(타이머 없음 — r/F5) ③ 값마다 '측정/추정' 표시
④ 프로세스 *관리*(종료·nice)는 btop(b 키), 프로세스 *지표*(누가 얼마나 쓰나)는 여기.
탭: 1 요약 / 2 전력 / 3 앱·프로세스 / 4 원인 / 5 시스템(Netdata) / 6 하드웨어·배터리 / 7 도움말·용어
측정 중에는 열어 두지 마세요(화면 갱신은 없지만 조회 순간 CPU 를 씁니다)."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TabbedContent, TabPane

try:
    import uikit
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_uikit"))
    import uikit
import observe_core as core
import observe_explain as ex
import observe_netdata as ndmod
import usagedata as ud
import usageview as uv

Panel = uikit.Panel
BASELINES = [("prev", "바로 앞의 같은 길이"), ("yday", "어제 같은 시간대"), ("none", "비교 안 함")]


class RangeScreen(ModalScreen):
    """범위 입력 대화상자: 프리셋 이름·-30m·10:00..11:30 을 받는다. Enter 확정, Esc 취소."""
    BINDINGS = [Binding("escape", "cancel", "취소")]

    def __init__(self, current):
        super().__init__()
        self.current = current

    def compose(self):
        with Vertical(id="dialog"):
            yield Static("조회 범위", id="dialog-title")
            yield Static(f"지금 범위: {self.current.text()} ({self.current.label})\n프리셋: " + " · ".join(ud.PRESETS)
                         + "\n직접 입력 예: -30m (지금까지 30분) · 10:00..11:30 · 2026-10-20 09:00..2026-10-20 12:00")
            yield Input(placeholder="1시간", id="range-input")
            yield Static("", id="range-err")
            yield Static("Enter 확정 · Esc 취소", id="dialog-hint")

    def on_mount(self):
        self.query_one("#range-input", Input).focus()

    def on_input_submitted(self, ev):
        try:
            self.dismiss(ud.parse_range(ev.value or "1시간"))
        except ValueError as e:
            self.query_one("#range-err", Static).update(Text(str(e), style="dark_orange"))

    def action_cancel(self):
        self.dismiss(None)


class UsageUI(uikit.HelpMixin, App):
    TITLE = "usageui"
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    Panel { height: 1fr; }
    VerticalScroll > .box { height: auto; }
    VerticalScroll > .xl { height: 24; }
    VerticalScroll > .tall { height: 14; }
    VerticalScroll > .mid { height: 11; }
    VerticalScroll > .short { height: 7; }
    #sumtop { height: 6; }
    #sumpow { height: 8; }
    #sumhab { height: 9; }
    #sumapps { height: 17; }
    #sumest { height: 8; }
    #pwr0, #pwr1, #pwr2, #pwr3 { height: 1fr; }
    #pwrbands { height: 9; }
    DataTable { height: 1fr; background: #000000; }
    #exscroll Static { height: auto; }
    #range-err { height: auto; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('summary')", "요약"), Binding("2", "tab('power')", "전력"), Binding("3", "tab('apps')", "앱"), Binding("4", "tab('cause')", "원인"),
        Binding("5", "tab('system')", "시스템"), Binding("6", "tab('hardware')", "하드웨어"), Binding("7", "tab('help')", "용어"),
        Binding("t", "set_range", "범위"), Binding("v", "cycle_baseline", "비교 기준"),
        Binding("r,f5", "reload", "새로고침"), Binding("b", "btop", "btop"), Binding("e", "export", "저장"),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, rng=None, baseline="prev", tab="summary"):
        super().__init__()
        self.rng = rng or ud.preset("1시간", time.time())
        self.baseline = baseline
        self.start_tab = tab
        self.view = None
        self.cause = None            # (키, ex 결과)  — 원인 탭에서 지연 계산
        self.sysdata = None          # {"key", "snap", "series"}
        self._busy = False

    # --- 구성: 표 하나·그래프 하나마다 박스 하나
    def compose(self) -> ComposeResult:
        with TabbedContent(initial=self.start_tab, id="tabs"):
            with TabPane("요약 [1]", id="summary"):
                with VerticalScroll():
                    yield uikit.box(Panel(lambda w, h: self._v(uv.summary_range), id="sumtop"), "구간")
                    yield uikit.box(Panel(lambda w, h: self._v(uv.summary_power), id="sumpow"), "전력·배터리")
                    yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.summary_habit(v, w)), id="sumhab"), "시간 배분 — 이 범위에서 어떻게 썼나")
                    yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.summary_apps(v, w)), id="sumapps"), "앱 — 누가 CPU 를 쓰고 무엇을 오래 봤나")
                    yield uikit.box(Panel(lambda w, h: self._v(uv.summary_estimate), id="sumest"), "예상 사용 시간 (추정)")
            with TabPane("전력 [2]", id="power"):
                for i, spec in enumerate(uv.POWER_SERIES):
                    yield uikit.box(Panel(lambda w, h, i=i: self._chart(i, w, h), id=f"pwr{i}"), spec[0])
                yield uikit.box(Panel(lambda w, h: self._bands(w), id="pwrbands"), "상태 · PSR · 전원")
            with TabPane("앱·프로세스 [3]", id="apps"):
                with VerticalScroll():
                    yield self._table_box("tapps", "앱(전체 프로세스를 앱으로 묶은 합) — CPU 는 코어 1개=100%", ("앱", "CPU %", "CPU 점유", "전환/s", "메모리 MB", "프로세스", "전력량 추정 Wh*"), "xl")
                    yield self._table_box("tfocus", "가장 오래 본 앱 — 창 포커스 시간(창 제목은 기록하지 않음)", ("앱", "시간", "비율"), "mid")
                    yield self._table_box("tproc", "프로세스 이름별 — 저장된 상위 16행(긴 꼬리는 앱 표가 대신함)", ("이름", "CPU %", "전환/s"), "mid")
                    yield self._table_box("tebpf", "정밀(eBPF) — 켜 둔 동안의 프로세스별 정확한 값", ("이름", "PID", "CPU %", "자발 전환/s", "비자발 전환/s", "깨움/s"), "mid")
                    yield self._table_box("tspans", "기록된 작업 구간 — nixup·덮개 정책 등(전력량은 psys 적분)", ("작업", "길이", "전력량"), "mid")
            with TabPane("원인 [4]", id="cause"):
                with VerticalScroll(id="exscroll"):
                    for i, title in enumerate(ex.SECTION_TITLES):
                        yield uikit.box(Static("이 탭을 열면 계산합니다(Netdata 조회가 있어 몇 초 걸릴 수 있음)" if i == 0 else "", id=f"ex{i}"), title)
            with TabPane("시스템 [5]", id="system"):
                with VerticalScroll():
                    yield self._table_box("tnd", "Netdata 신호 — 이 범위 평균(꺼져 있던 시간은 '관측 공백')", ("신호", "값", "단위"), "tall")
                    for i, (key, title, unit, _s) in enumerate(uv.ND_CHARTS):
                        b = uikit.box(Panel(lambda w, h, key=key: self._ndchart(key, w, h), id=f"nd{i}"), title)
                        b.add_class("mid")
                        yield b
            with TabPane("하드웨어·배터리 [6]", id="hardware"):
                with VerticalScroll():
                    b = uikit.box(Panel(lambda w, h: uv.battery_text(ud.battery_health()), id="hwbat"), "배터리 건강")
                    b.add_class("short")
                    yield b
                    b = uikit.box(Panel(lambda w, h: self._v(uv.device_text), id="hwdev"), "기기 상태(마지막 표본)")
                    b.add_class("mid")
                    yield b
                    b = uikit.box(Panel(lambda w, h: uv.collector_text(ud.collector_status()), id="hwcol"), "수집 상태")
                    b.add_class("short")
                    yield b
                    b = uikit.box(Panel(lambda w, h: self._chart(3, w, h), id="hwcurve"), "방전 곡선 — 배터리 잔량(하루 이상 범위로 보면 사용 시간 추정을 검증할 수 있음)")
                    b.add_class("tall")
                    yield b
            with TabPane("도움말·용어 [7]", id="help"):
                with VerticalScroll():
                    yield uikit.box(Static(self._help_text(), id="helptext"), "용어 — 값이 무엇을 뜻하나")
        with Vertical(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def _table_box(self, tid, title, cols, cls):
        return TableBox(tid, title, cols, cls)

    def _v(self, fn):
        return fn(self.view) if self.view else Text(" 불러오는 중…", style="grey50")

    def _chart(self, i, w, h):
        if not self.view:
            return Text(" 불러오는 중…", style="grey50")
        return uv.power_chart(self.view, i, w, h)

    def _bands(self, w):
        return uv.power_bands(self.view, w) if self.view else Text(" 불러오는 중…", style="grey50")

    def _ndchart(self, key, w, h):
        if self.sysdata is None:
            return Text(" 이 탭을 열면 Netdata 에서 읽어 옵니다(꺼져 있으면 '관측 공백')", style="grey50"), ""
        return uv.nd_chart(self.sysdata, key, self.view["range"], w, h)

    def _help_text(self):
        t = Text()
        for k, d in uv.GLOSSARY:
            t.append(f" {k:<14}", style="#33ccff")
            t.append(d + "\n")
        t.append("\n 키: 1~7 탭 · t 범위 · v 비교 기준 · r/F5 새로고침 · b btop · e 내보내기 · ? 키 목록 · q 종료", style="grey50")
        return t

    # --- 데이터: 수동 갱신만(타이머 없음)
    def on_mount(self):
        self.reload()

    def action_reload(self):
        self.reload()

    @work(thread=True, exclusive=True, group="load")
    def reload(self):
        self._busy = True
        self.call_from_thread(self._status, "불러오는 중…")
        view = ud.load(self.rng, self.baseline)
        self.view = view
        self.cause = None
        self.sysdata = None
        self.call_from_thread(self.redraw)
        self._lazy(self.query_one("#tabs", TabbedContent).active)
        self._busy = False

    def _lazy(self, tab):
        """네트워크가 필요한 탭(원인·시스템)은 열 때 계산한다."""
        view = self.view
        if view is None:
            return
        if tab == "cause" and self.cause is None:
            base = view["baseline"]
            res = ex.build(view["all_rows"], view["spans"], view["range"].t0, view["range"].t1, base, lambda a, b: ndmod.snapshot(a, b)) if view["rows"] else False
            self.cause = res
            self.call_from_thread(self.redraw)
        if tab == "system" and self.sysdata is None:
            rng = view["range"]
            step = max(30, rng.secs / 500)
            try:
                snap = ndmod.snapshot(rng.t0, rng.t1, 0)
                series = ndmod.sample_series(rng.t0, rng.t1, step) if snap else {}
            except ndmod.NetdataError:
                snap, series = None, {}
            self.sysdata = {"snap": snap, "series": series}
            self.call_from_thread(self.redraw)

    def redraw(self):
        v = self.view
        for panel in self.query(Panel):
            panel.build()
            panel.refresh()
        if v:
            self._fill_tables(v)
            self._fill_cause()
            self._status(uv.freshness(v))

    def _status(self, msg):
        v = self.view
        extra = ""
        if v:
            kind = dict(BASELINES)[v["baseline_kind"]]
            extra = f" · 범위 {v['summary']['range']}({v['range'].label}) · 비교 기준: {kind}"
        self.query_one("#status", Static).update(msg + extra)

    def _fill_tables(self, v):
        def fill(tid, rows, empty):
            t = self.query_one(f"#{tid}", DataTable)
            t.clear()
            for r in rows:
                t.add_row(*r)
            if not rows:
                t.add_row(empty, *[""] * (len(t.columns) - 1))
        fill("tapps", uv.apps_rows(v), "앱 단위 표본(v4)이 없습니다")
        self._box("tapps").border_subtitle = "*전력량 추정 = 이 범위 psys 전력량 × CPU 점유율 — 유휴 전력도 비례 배분한 참고값(앱이 전력을 쓴 몫이 아님)"
        fill("tfocus", uv.focus_rows(v), "포커스 기록이 없습니다")
        fill("tproc", uv.proc_rows(v), "프로세스 표본이 없습니다")
        got = uv.ebpf_rows(v)
        fill("tebpf", got[0] if got else [], "정밀 모드가 꺼져 있었음 — observectl ebpf on sample --for 10m")
        fill("tspans", uv.span_rows(v), "이 범위에 기록된 작업 구간이 없습니다")
        sysd = self.sysdata
        fill("tnd", uv.nd_signal_rows(sysd, v), "이 탭을 열면 읽어 옵니다 / Netdata 응답 없음")
        if sysd is not None and sysd.get("snap"):
            self._box("tnd").border_subtitle = f"Netdata 데이터 {sysd['snap']['coverage'] * 100:.0f}% 있음"

    def _box(self, tid):
        return self.query_one(f"#{tid}", DataTable).parent

    def _fill_cause(self):
        res = self.cause
        view = self.view
        secs = ex.sections(res, core.hms) if res else None
        base = view["baseline"] if view else None
        for i, title in enumerate(ex.SECTION_TITLES):
            w = self.query_one(f"#ex{i}", Static)
            if secs:
                w.update(Text("\n".join(secs[i][1])))
            elif res is False:
                w.update(Text("이 범위에는 표본이 없습니다" if i == 0 else ""))
            else:
                w.update(Text("이 탭을 열면 계산합니다(Netdata 조회가 있어 몇 초 걸릴 수 있음)" if i == 0 else ""))
            w.border_title = title
            if i == 0 and base:
                w.border_subtitle = "비교 기준 " + time.strftime("%H:%M", time.localtime(base[0])) + "~" + time.strftime("%H:%M", time.localtime(base[1]))

    # --- 동작
    def action_tab(self, name):
        self.query_one("#tabs", TabbedContent).active = name

    def on_tabbed_content_tab_activated(self, ev):
        if self.view and ev.pane.id in ("cause", "system"):
            self._lazy_worker(ev.pane.id)

    @work(thread=True, exclusive=True, group="lazy")
    def _lazy_worker(self, tab):
        self._lazy(tab)

    def action_set_range(self):
        def done(rng):
            if rng is not None:
                self.rng = rng
                self.reload()
        self.push_screen(RangeScreen(self.rng), done)

    def action_cycle_baseline(self):
        kinds = [k for k, _ in BASELINES]
        self.baseline = kinds[(kinds.index(self.baseline) + 1) % len(kinds)]
        self.reload()

    def action_btop(self):
        exe = shutil.which("btop")
        if not exe:
            self.notify("btop 이 없습니다", severity="warning")
            return
        with self.suspend():
            subprocess.run([exe])

    def action_export(self):
        """지금 탭의 내용을 텍스트 파일로 저장(홈 디렉터리)."""
        tab = self.query_one("#tabs", TabbedContent).active
        pane = self.query_one(f"#{tab}")
        lines = []
        for w in pane.query("Panel, Static, DataTable"):
            title = getattr(w, "border_title", None) or getattr(getattr(w, "parent", None), "border_title", None)
            if isinstance(w, DataTable):
                lines.append(f"## {title or ''}")
                lines.append(" | ".join(str(c.label) for c in w.columns.values()))
                for key in w.rows:
                    lines.append(" | ".join(str(x) for x in w.get_row(key)))
            elif isinstance(w, Panel):
                lines.append(f"## {title or ''}\n{w._text.plain}")
            elif w.id and w.id != "status":
                lines.append(f"## {title or ''}\n{str(w.render())}")
        path = os.path.expanduser(time.strftime(f"~/usageui-{tab}-%Y%m%d-%H%M%S.txt"))
        with open(path, "w") as f:
            f.write(f"usageui {tab} — {self.view['summary']['range'] if self.view else ''}\n\n" + "\n\n".join(lines) + "\n")
        self.notify(f"저장했습니다: {path}")


class TableBox(Vertical):
    """표 박스: 제목이 달린 테두리 안에 DataTable 하나."""

    def __init__(self, tid, title, cols, cls):
        super().__init__(classes=f"box {cls}")
        self.border_title = title
        self._tid, self._cols = tid, cols

    def compose(self):
        t = DataTable(id=self._tid, cursor_type="row", zebra_stripes=True)
        t.add_columns(*self._cols)
        yield t


def main(argv=None):
    p = argparse.ArgumentParser(prog="usageui", description="전력·자원 사용 습관 TUI")
    p.add_argument("--range", default="1시간", help="처음 범위: 1시간·6시간·오늘·어제·3일 · -30m · 10:00..11:30")
    p.add_argument("--tab", default="summary", choices=["summary", "power", "apps", "cause", "system", "hardware", "help"])
    p.add_argument("--baseline", default="prev", choices=[k for k, _ in BASELINES])
    a = p.parse_args(argv)
    try:
        rng = ud.parse_range(a.range)
    except ValueError as e:
        sys.exit(str(e))
    UsageUI(rng, a.baseline, a.tab).run()


if __name__ == "__main__":
    main()
