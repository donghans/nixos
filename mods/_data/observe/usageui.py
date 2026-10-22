#!/usr/bin/env python3
"""usageui — 전력·자원 사용 습관 TUI (Textual). observectl 이 쌓은 표본을 '시간 범위' 기준으로 조회해 보여 준다.

원칙: ① 조회는 범위 기준(기본 = 지금까지 최근 7일) ② **갱신은 수동만**(타이머 없음 — r/F5) ③ 값마다 '측정/추정' 표시
④ 프로세스 *관리*(종료·nice)는 btop(b 키), 프로세스 *지표*(누가 얼마나 쓰나)는 여기.
탭: 1 대시보드(전력·배터리·습관·앱) / 2 앱·프로세스 / 3 원인 / 4 시스템·기기(Netdata·수집 상태) / 5 용어
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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Collapsible, DataTable, Footer, Input, Static, TabbedContent, TabPane

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


class SpikesScreen(ModalScreen):
    """튀었던 순간 전체 순위. Enter 로 그 시각(앞뒤 30분)으로 범위를 옮긴다, Esc 닫기."""
    BINDINGS = [Binding("escape", "cancel", "닫기")]

    def __init__(self, view):
        super().__init__()
        self.view = view

    def compose(self):
        with Vertical(id="dialog", classes="wide"):
            yield Static(f"튀었던 순간 순위 — 5분 평균 {uv.spike_basis(self.view)} 전력, 평소(중앙값)보다 더 쓴 에너지 순", id="dialog-title")
            yield DataTable(id="spk", cursor_type="row", zebra_stripes=True)
            yield Static("Enter 그 시각으로 이동(앞뒤 30분) · Esc 닫기 · 상관일 뿐 원인 아님", id="dialog-hint")

    def on_mount(self):
        t = self.query_one("#spk", DataTable)
        t.add_columns("순위", "시각", "길이", "평균 W", "평소 대비", "초과 Wh", "앞 W", "뒤 W", "다른 날 W", "CPU", "그때 앱·포커스")
        for r in uv.spike_rows(self.view):
            t.add_row(*r, key=r[0])
        t.focus()

    def on_data_table_row_selected(self, ev):
        rank = int(str(ev.row_key.value))
        s = next(x for x in self.view["spikes"] if x["rank"] == rank)
        self.dismiss(ud.Range(s["t0"] - 1800, s["t1"] + 1800, "직접", False))

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
    #dashscroll { height: 1fr; }
    #dash { height: 1fr; min-height: 46; }
    #dleft { width: 3fr; height: 1fr; }
    #dright { width: 2fr; min-width: 52; height: 1fr; }
    #dright > #dnow { height: 9; }
    #dright > #dcpu { height: 8; }
    #dash.desk #dright > #dapps { min-height: 8; }
    #dright > #dsum { height: 9; }
    #dright > #dctx { height: 8; }
    #dash.narrow { layout: vertical; height: auto; }
    #dash.narrow #dleft, #dash.narrow #dright { width: 100%; height: auto; }
    #dash.narrow .box { height: 12; }
    #dpower { height: 1fr; min-height: 20; }
    #dleft > #dspk { height: 13; }
    #dbatt { height: 12; }
    #dbatt Horizontal { height: 1fr; }
    #dbatt #pwr3 { width: 3fr; }
    #dbatt #dhealth { width: 2fr; }
    #dsum { height: 11; }
    #dhab { height: 9; }
    #dapps { height: 1fr; min-height: 14; }
    #dbands { height: 8; }
    #causehead { height: auto; min-height: 5; }
    #causechg { height: auto; min-height: 5; }
    Collapsible { background: #000000; border: round #595959; padding: 0 1; }
    Collapsible > Contents { height: auto; padding: 0; }
    DataTable { height: 1fr; background: #000000; }
    #range-err { height: auto; }
    #dialog.wide { width: 96%; max-width: 220; }
    #dialog.wide DataTable { height: auto; max-height: 14; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('dashboard')", "대시보드"), Binding("2", "tab('apps')", "앱"), Binding("3", "tab('cause')", "원인"),
        Binding("4", "tab('system')", "시스템"), Binding("5", "tab('help')", "용어"),
        Binding("t", "set_range", "범위"), Binding("s", "spikes", "튄 순간"), Binding("v", "cycle_baseline", "비교 기준"),
        Binding("r,f5", "reload", "새로고침"), Binding("b", "btop", "btop"), Binding("e", "export", "저장"),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, rng=None, baseline="prev", tab=None, expand=False):
        super().__init__()
        # 센서 유무로 화면을 가른다: 배터리가 있으면 노트북형(전력·배터리 중심), 없으면 데스크톱형(프로세스·CPU 중심). 기준은 usagedata.host_profile.
        self.prof = ud.host_profile()
        self.desktop = not self.prof["battery"]
        if tab is None:
            tab = "dashboard"        # 노트북·데스크톱 모두 대시보드가 첫 화면(데스크톱 대시보드에 '지금 어떤가'·깨움 상위·앱 요약을 모음)
        self.expand = expand
        self.rng = rng or ud.preset("7일", time.time())
        self.baseline = baseline
        self.start_tab = tab
        self.view = None
        self.cause = None            # ex.build 결과 | False(표본 없음) | None(아직)
        self.sysdata = None          # {"snap", "series"}
        self._busy = False

    # --- 구성: 표·그래프마다 박스(btop 처럼 박스 안 박스). 대시보드는 2열(좁으면 1열)
    def compose(self) -> ComposeResult:
        with TabbedContent(initial=self.start_tab, id="tabs"):
            with TabPane("대시보드 [1]", id="dashboard"):
                with VerticalScroll(id="dashscroll"):
                    with Horizontal(id="dash"):
                        if self.desktop:
                            yield from self._compose_dash_desktop()
                        else:
                            yield from self._compose_dash_laptop()
            with TabPane("앱·프로세스 [2]", id="apps"):
                with VerticalScroll():
                    yield self._table_box("tapps", "앱(전체 프로세스를 앱으로 묶은 합) — CPU 는 코어 1개=100%", ("앱", "CPU %", "CPU 점유", "전환/s", "메모리 MB", "프로세스", "CPU+GPU 전력량 추정 Wh*" if not self.prof["psys"] else "전력량 추정 Wh*"), "xl")
                    yield self._table_box("tfocus", "가장 오래 본 앱 — 창 포커스 시간(창 제목은 기록하지 않음)", ("앱", "시간", "비율"), "mid")
                    yield self._table_box("tproc", "프로세스 이름별 — 저장된 상위 16행(긴 꼬리는 앱 표가 대신함)", ("이름", "CPU %", "전환/s"), "mid")
                    yield self._table_box("tebpf", "정밀(eBPF) — 켜 둔 동안의 프로세스별 정확한 값", ("이름", "PID", "CPU %", "자발 전환/s", "비자발 전환/s", "깨움/s"), "mid")
                    yield self._table_box("tspans", "기록된 작업 구간 — nixup·덮개 정책 등" + ("(전력량은 psys 적분)" if self.prof["psys"] else ""), ("작업", "길이", "전력량") if self.prof["psys"] else ("작업", "길이"), "mid")
            with TabPane("원인 [3]", id="cause"):
                with VerticalScroll(id="causescroll"):
                    # 데스크톱형은 전력 비교가 불가능하니 전체 CPU·문맥 전환·앱별 CPU 변화로 비교한다(전력 상세 접이식은 없음)
                    yield uikit.box(Static("", id="causehead"), "이 구간 vs 기준 구간 — CPU·문맥 전환·패키지 전력" if self.desktop else "결론 — 이 구간 vs 기준 구간")
                    yield uikit.box(Static("", id="causechg"), "앱별 CPU 변화 — 무엇이 달라졌나" if self.desktop else "무엇이 같이 달라졌나 — 상관일 뿐 인과가 아님")
                    for i, title in enumerate(ex.SECTION_TITLES):
                        if i in (0, 5) or self.desktop:
                            continue
                        with Collapsible(title=f"{title} (펼치기)", collapsed=not self.expand, id=f"excol{i}"):
                            yield Static("", id=f"ex{i}")
            with TabPane("시스템·기기 [4]", id="system"):
                with VerticalScroll():
                    b = uikit.box(Panel(lambda w, h: self._v(uv.device_text), id="hwdev"), "기기 상태(마지막 표본)")
                    b.add_class("mid")
                    yield b
                    b = uikit.box(Panel(lambda w, h: uv.collector_text(ud.collector_status()), id="hwcol"), "수집 상태")
                    b.add_class("short")
                    yield b
                    yield self._table_box("tnd", "Netdata 신호 — 이 범위 평균(꺼져 있던 시간은 '관측 공백')", ("신호", "값", "단위"), "tall")
                    for i, (key, title, unit, _s) in enumerate(uv.nd_charts(self.prof)):
                        b = uikit.box(Panel(lambda w, h, key=key: self._ndchart(key, w, h), id=f"nd{i}"), title)
                        b.add_class("mid")
                        yield b
            with TabPane("용어 [5]", id="help"):
                with VerticalScroll():
                    yield uikit.box(Static(self._help_text(), id="helptext"), "용어 — 값이 무엇을 뜻하나")
        with Vertical(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def _compose_dash_laptop(self):
        with Vertical(id="dleft"):
            with Vertical(id="dpower", classes="box") as pw:
                pw.border_title = "전력 (측정)"
                yield uikit.box(Panel(lambda w, h: self._chart(0, w, h), id="pwr0"), "psys · 플랫폼 전체(약 1 W 적게 보임)")
                yield uikit.box(Panel(lambda w, h: self._chart(1, w, h), id="pwr1"), "패키지 · CPU+GPU")
                yield uikit.box(Panel(lambda w, h: self._chart(2, w, h), id="pwr2"), "배터리에서 나가는 전력 · 순간 V×I, 방전 중만(노이즈 큼)")
                yield uikit.box(Panel(lambda w, h: self._bands(w), id="dbands"), "상태 · PSR · 전원")
            with Vertical(id="dbatt", classes="box") as bt:
                bt.border_title = "배터리"
                with Horizontal():
                    yield uikit.box(Panel(lambda w, h: self._chart(3, w, h), id="pwr3"), "잔량 %")
                    yield uikit.box(Panel(lambda w, h: self._health(), id="dhealth"), "건강 · 예상 사용 시간(추정)")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.spikes_text(v, 3, w)), id="dspk"), "튀었던 순간 TOP 3 — 평소·이웃과 비교")
        with Vertical(id="dright"):
            yield uikit.box(Panel(lambda w, h: self._v(self._sumtext), id="dsum"), "구간 · 전력 요약")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.summary_habit(v, w)), id="dhab"), "시간 배분 — 어떻게 썼나")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.summary_apps(v, w)), id="dapps"), "앱 — CPU 점유(전력 점유율 아님) · 오래 본 앱")

    def _compose_dash_desktop(self):
        """데스크톱형 대시보드: 배터리·psys·덮개·PSR 박스 없이 패키지 전력·전체 CPU·문맥 전환 추이와 앱 요약."""
        with Vertical(id="dleft"):
            with Vertical(id="dpower", classes="box") as pw:
                pw.border_title = "전력·부하 (측정)"
                yield uikit.box(Panel(lambda w, h: self._chart(1, w, h), id="pwr1"), "패키지 · CPU+GPU(전체 소비 전력이 아님)")
                yield uikit.box(Panel(lambda w, h: self._chart(4, w, h), id="pwr4"), "전체 CPU · 전체 대비 %")
                yield uikit.box(Panel(lambda w, h: self._chart(5, w, h), id="pwr5"), "시스템 전체 문맥 전환/s")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.spikes_text(v, 3, w)), id="dspk"), "튀었던 순간 TOP 3 — 평소·이웃과 비교")
        with Vertical(id="dright"):
            yield uikit.box(Panel(lambda w, h: self._v(uv.desktop_headline), id="dnow"), "지금 어떤가 — 기준 구간 대비")
            yield uikit.box(Panel(lambda w, h: self._v(self._sumtext), id="dsum"), "구간 · 요약")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.desktop_cpu_top(v, w)), id="dcpu"), "CPU 상위 앱 — 연산 부하")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.desktop_ctxsw(v, w)), id="dctx"), "깨움(문맥 전환) 상위 앱")
            yield uikit.box(Panel(lambda w, h: self._v(lambda v: uv.summary_apps(v, w)), id="dapps"), "앱 — CPU 점유 · 오래 본 앱")

    def _sumtext(self, v):
        t = uv.summary_range(v)
        t.append("\n")
        t.append_text(uv.summary_power(v))
        return t

    def _health(self):
        return uv.summary_battery(self.view, ud.battery_health()) if self.view else Text(" 불러오는 중…", style="grey50")

    NARROW_COLS = 125                  # 이보다 좁으면 대시보드를 1열로(오른쪽 칸 글이 줄바꿈되기 때문)

    def _fit(self):
        try:
            self.query_one("#dash").set_class(self.size.width < self.NARROW_COLS, "narrow")
        except Exception:
            pass

    def on_resize(self, ev):
        self._fit()

    def on_mount(self):
        self.query_one("#dash").set_class(self.desktop, "desk")
        self._fit()
        self.reload()

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
        t.append("\n 키: 1~5 탭 · t 범위 · s 튄 순간 순위 · v 비교 기준 · r/F5 새로고침 · b btop · e 내보내기 · ? 키 목록 · q 종료", style="grey50")
        return t

    # --- 데이터: 수동 갱신만(타이머 없음)
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
        if tab == "cause" and self.cause is None and self.desktop:
            self.cause = True                      # 데스크톱형은 ex.build(전력 설명)를 쓰지 않고 화면 쪽에서 view 로 비교한다
            self.call_from_thread(self.redraw)
        elif tab == "cause" and self.cause is None:
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
        basis = "psys" if v["profile"]["psys"] else "패키지(CPU+GPU, 전체 소비 전력이 아님)"
        self._box("tapps").border_subtitle = f"*전력량 추정 = 이 범위 {basis} 전력량 × CPU 점유율 — 유휴 전력도 비례 배분한 참고값(앱이 전력을 쓴 몫이 아님)"
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
        if self.desktop:
            if view and res is not None:
                self.query_one("#causehead", Static).update(uv.desktop_cause_head(view))
                self.query_one("#causechg", Static).update(uv.desktop_cause_changes(view))
                base = view["baseline"]
                if base:
                    self.query_one("#causehead").parent.border_subtitle = "비교 기준 " + time.strftime("%H:%M", time.localtime(base[0])) + "~" + time.strftime("%H:%M", time.localtime(base[1])) + " (v 로 바꿈)"
            return
        self.query_one("#causehead", Static).update(uv.cause_headline(res))
        self.query_one("#causechg", Static).update(uv.cause_changes(res) if res else Text(""))
        secs = ex.sections(res, core.hms) if res else None
        for i, title in enumerate(ex.SECTION_TITLES):
            if i in (0, 5):
                continue
            w = self.query_one(f"#ex{i}", Static)
            w.update(Text("\n".join(secs[i][1])) if secs else Text(""))
        base = view["baseline"] if view else None
        if base:
            self.query_one("#causehead").parent.border_subtitle = "비교 기준 " + time.strftime("%H:%M", time.localtime(base[0])) + "~" + time.strftime("%H:%M", time.localtime(base[1])) + " (v 로 바꿈)"

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

    def action_spikes(self):
        if not self.view:
            return
        def done(rng):
            if rng is not None:
                self.rng = rng
                self.reload()
        self.push_screen(SpikesScreen(self.view), done)

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
    p.add_argument("--range", default=None, help="처음 범위(기본: 7일): 1시간·6시간·오늘·어제·3일·7일 · -30m · 10:00..11:30")
    p.add_argument("--tab", default=None, help="처음 탭(기본: 배터리 있으면 dashboard, 없으면 apps)", choices=["dashboard", "apps", "cause", "system", "help"])
    p.add_argument("--expand", action="store_true", help="원인 탭의 상세 표를 처음부터 펼침")
    p.add_argument("--baseline", default="prev", choices=[k for k, _ in BASELINES])
    a = p.parse_args(argv)
    try:
        rng = ud.parse_range(a.range or "7일")
    except ValueError as e:
        sys.exit(str(e))
    UsageUI(rng, a.baseline, a.tab, a.expand).run()


if __name__ == "__main__":
    main()
