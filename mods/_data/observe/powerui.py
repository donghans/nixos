#!/usr/bin/env python3
"""powerui — 전력·배터리 현황 TUI (Textual). observectl 수집기가 남긴 표본을 그래프와 표로 보여준다.

탭: 1 지금(전원·W·상태·PSR·남은 시간 추정) / 2 시계열(점자 그래프 + 상태·PSR·전원 띠) / 3 비교(그룹별 평균: 상태·PSR·AC·덮개…) / 4 Netdata(CPU·네트워크·디스크·메모리·온도).
화면 갱신은 PSR 을 방해하므로(화면이 바뀔 때마다 패널이 깨어남) 기본 10초 주기이고, 터미널 창이 포커스를 잃으면 갱신을 멈춘다(`--interval` 로 조절).
측정 중에는 열어 두지 마세요(보이는 화면이 한가함 기준선을 흔듭니다). 데이터: /var/lib/observe (observectl on 으로 수집을 켜야 함).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Static, TabbedContent, TabPane

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../_uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_uikit"))
    import uikit
import powerdata as pd
import powergraph as pg
import powerview as pv


class Panel(Static):
    """크기가 바뀔 때마다 provider(폭, 높이) 로 내용을 새로 만들어 그리는 칸. provider 는 Text 또는 (Text, 부제 문자열)을 돌려준다(부제는 박스 아래 테두리에 표시)."""

    def __init__(self, provider, **kw):
        super().__init__(**kw)
        self.provider = provider

    def render(self):
        w, h = self.size.width, self.size.height
        if not (w and h):
            return Text("")
        out = self.provider(max(20, w), max(3, h))
        text, sub = out if isinstance(out, tuple) else (out, "")
        if (self.border_subtitle or "") != sub:      # 같을 때는 건드리지 않는다(바꾸면 다시 그려져 무한 반복)
            self.border_subtitle = sub
        return text


class PowerUI(uikit.HelpMixin, uikit.PauseOnBlurMixin, App):
    TITLE = "powerui"
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    Panel { height: 1fr; }
    #nowtext { height: 13; }
    #serbands { height: 8; }
    #cmpbox { height: 1fr; }
    DataTable { height: 1fr; background: #000000; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('now')", "지금"), Binding("2", "tab('series')", "시계열"), Binding("3", "tab('compare')", "비교"), Binding("4", "tab('netdata')", "Netdata"),
        Binding("r", "cycle_range", "구간"), Binding("g", "cycle_group", "그룹"), Binding("c", "toggle_clean", "깨끗한 표본"),
        Binding("f5", "refresh_now", "새로고침"),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, interval=10.0, store=None, tab="now", range_i=0):
        super().__init__()
        self.start_tab = tab
        self.interval = interval
        self.store = store or pd.Store()
        self.range_i = range_i
        self.group_i = 0
        self.clean = False
        self.last = 0.0
        self._timer = None
        self._nd_cache = {}       # chart -> (t, points)
        self._nd_at = 0.0

    # --- 구성: 그래프·표 하나마다 박스 하나(btop 처럼 제목이 달린 테두리)
    def compose(self) -> ComposeResult:
        with TabbedContent(initial=self.start_tab, id="tabs"):
            with TabPane("지금 [1]", id="now"):
                yield uikit.box(Panel(self._now_view, id="nowtext"), "현황")
                yield uikit.box(Panel(lambda w, h: self._now_chart("psys", "psys", "cyan", w, h), id="nowg0"), "최근 30분 · psys (플랫폼 합계)")
                yield uikit.box(Panel(lambda w, h: self._now_chart("batt", "배터리", "dark_orange", w, h, axis=True), id="nowg1"), "최근 30분 · 배터리 소비 (방전 중)")
            with TabPane("시계열 [2]", id="series"):
                for i, spec in enumerate(pv.SERIES):
                    yield uikit.box(Panel(lambda w, h, i=i: self._series_chart(i, w, h), id=f"ser{i}"), spec[0])
                yield uikit.box(Panel(self._series_bands, id="serbands"), "상태 · PSR · 전원")
            with TabPane("비교 [3]", id="compare"):
                with Vertical(id="cmpbox", classes="box"):
                    yield DataTable(id="cmptable", cursor_type="row", zebra_stripes=True)
            with TabPane("Netdata [4]", id="netdata"):
                for i, nd in enumerate(pd.NETDATA_CHARTS):
                    yield uikit.box(Panel(lambda w, h, i=i: self._netdata_chart(i, w, h), id=f"nd{i}"), nd[1])
        with Vertical(id="status-row"):
            yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        t = self.query_one("#cmptable", DataTable)
        t.add_columns("그룹", "표본", "시간", "계량 W", "V×I W", "psys W", "패키지 W", "pc8 %", "pc10 %", "깨움/s", "CPU %")
        self.refresh_data()
        self._timer = self.set_interval(self.interval, self.refresh_data)

    # --- 데이터 갱신(스레드) → 화면
    @work(thread=True, exclusive=True, group="data")
    def refresh_data(self):
        self.store.refresh()
        if self.query_one("#tabs", TabbedContent).active == "netdata":
            self._fetch_netdata()
        self.last = time.time()
        self.call_from_thread(self.redraw)

    def _fetch_netdata(self):
        label = pv.RANGES[self.range_i][0]
        t0, t1 = pv.range_bounds(label, time.time())
        secs = max(300, t1 - t0)
        for chart, _title, _unit, excl, absv in pd.NETDATA_CHARTS:
            self._nd_cache[chart] = (time.time(), pd.netdata_series(chart, secs, 240, excl, absv))
        self._nd_at = time.time()

    def redraw(self):
        for panel in self.query(Panel):
            panel.refresh()
        self._fill_compare()
        label = pv.RANGES[self.range_i][0]
        n = len(self.store.recs)
        self.query_one("#status", Static).update(
            f"마지막 갱신 {time.strftime('%H:%M:%S', time.localtime(self.last))} · 주기 {self.interval:g}초 · 표본 {n}개 (최근 3일) · 구간 {label}")

    # --- 보기 만들기
    def _est(self):
        return pd.battery_estimate(self.store.recs)

    def _now_view(self, w, h):
        return pv.now_text(self.store.recs, self._est(), w)

    def _now_chart(self, key, _name, style, w, h, axis=False):
        now = time.time()
        t0, t1 = now - 1800, now
        recs = [r for r in self.store.recs if r["t"] >= t0]
        text, st = pv.chart(pv.series_points(recs, key), t0, t1, w, h, "W", style, gradient=True, axis=axis)
        return text, pv.stats_str(st)

    def _series_chart(self, i, w, h):
        _title, key, unit, style, lo, hi, fmt = pv.SERIES[i]
        t0, t1 = pv.range_bounds(pv.RANGES[self.range_i][0], time.time())
        recs = [r for r in self.store.recs if t0 <= r["t"] <= t1]
        text, st = pv.chart(pv.series_points(recs, key), t0, t1, w, h, unit, style, lo, hi, fmt, gradient=unit == "W")
        return text, pv.stats_str(st, unit, fmt)

    def _series_bands(self, w, h):
        t0, t1 = pv.range_bounds(pv.RANGES[self.range_i][0], time.time())
        recs = [r for r in self.store.recs if t0 <= r["t"] <= t1]
        return pv.bands_text(recs, t0, t1, w), f"구간 {pv.RANGES[self.range_i][0]} · 표본 {len(recs)}개"

    def _netdata_chart(self, i, w, h):
        chart, title, unit, _e, _a = pd.NETDATA_CHARTS[i]
        if not self._nd_cache:
            return Text(" Netdata 데이터를 읽는 중… (이 탭을 열면 읽어 옵니다. Netdata 가 꺼져 있으면 표시되지 않습니다)", style="grey70"), ""
        _, pts = self._nd_cache.get(chart, (0, None))
        if pts is None:
            return Text(" 읽지 못함: Netdata 꺼짐 또는 차트 없음", style="grey50"), ""
        t0, t1 = pv.range_bounds(pv.RANGES[self.range_i][0], time.time())
        text, st = pv.chart(pts, t0, t1, w, h, unit, "green", fmt=None, axis=i == len(pd.NETDATA_CHARTS) - 1)
        return text, pv.stats_str(st, unit)

    def _fill_compare(self):
        by = list(pd.GROUPS)[self.group_i]
        label = pv.RANGES[self.range_i][0]
        t0, t1 = pv.range_bounds(label, time.time())
        recs = self.store.since(t0, t1)
        rows = pd.group_table(recs, by, self.clean)
        box = self.query_one("#cmpbox")
        box.border_title = f"그룹별 평균 · {pd.GROUPS[by]}"
        box.border_subtitle = f"구간 {label} · {'깨끗한 표본만' if self.clean else '모든 표본'} · 표본 {len(recs)}개"
        t = self.query_one("#cmptable", DataTable)
        t.clear()
        f = lambda x, p=2: "-" if x is None else f"{x:.{p}f}"
        for r in rows:
            t.add_row(str(r["group"]), str(r["n"]), pg.fmt_dur(r["hours"]), f(r["coulomb"]), f(r["batt"]), f(r["psys"]), f(r["pkg"]), f(r["pc8"], 0), f(r["pc10"], 0), f(r["wake"], 0), f(r["cpu"], 0))

    # --- 동작
    def action_tab(self, name):
        self.query_one("#tabs", TabbedContent).active = name
        if name == "netdata":
            self.refresh_data()

    def on_tabbed_content_tab_activated(self, ev):
        if ev.pane.id == "netdata":
            self.refresh_data()

    def action_cycle_range(self):
        self.range_i = (self.range_i + 1) % len(pv.RANGES)
        self.refresh_data()

    def action_cycle_group(self):
        self.group_i = (self.group_i + 1) % len(pd.GROUPS)
        self.redraw()

    def action_toggle_clean(self):
        self.clean = not self.clean
        self.redraw()

    def action_refresh_now(self):
        self.refresh_data()


def main(argv=None):
    p = argparse.ArgumentParser(prog="powerui", description="전력·배터리 현황 TUI")
    p.add_argument("--interval", type=float, default=10.0, help="갱신 주기(초, 기본 10)")
    p.add_argument("--tab", default="now", choices=["now", "series", "compare", "netdata"], help="처음 열 탭")
    p.add_argument("--range", default="1시간", choices=[r[0] for r in pv.RANGES], help="처음 구간")
    a = p.parse_args(argv)
    PowerUI(interval=max(2.0, a.interval), tab=a.tab, range_i=[r[0] for r in pv.RANGES].index(a.range)).run()


if __name__ == "__main__":
    main()
