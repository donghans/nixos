#!/usr/bin/env python3
"""powerui — 전력·배터리 현황 TUI (Textual). observectl 수집기가 남긴 표본을 그래프와 표로 보여준다.

탭: 1 지금(전원·W·상태·PSR·남은 시간 추정) / 2 시계열(점자 그래프 + 상태·PSR·전원 띠) / 3 비교(그룹별 평균: 상태·PSR·AC·덮개…) / 4 Netdata(CPU·네트워크·디스크·메모리·온도).
화면 갱신은 PSR 을 방해하므로(화면이 바뀔 때마다 패널이 깨어남) 기본 10초 주기이고, 터미널 창이 포커스를 잃으면 갱신을 멈춘다(`--interval` 로 조절).
측정 중에는 열어 두지 마세요(보이는 화면이 한가함 기준선을 흔듭니다). 데이터: /var/lib/observe (observectl on 으로 수집을 켜야 함).
"""
from __future__ import annotations

import argparse
import time

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

import powerdata as pd
import powergraph as pg
import powerview as pv


class Panel(Static):
    """크기가 바뀔 때마다 provider(폭, 높이) 로 Text 를 새로 만들어 그리는 칸."""

    def __init__(self, provider, **kw):
        super().__init__(**kw)
        self.provider = provider

    def render(self):
        w, h = self.size.width, self.size.height
        return self.provider(max(20, w), max(6, h)) if w and h else Text("")


class PowerUI(App):
    TITLE = "powerui — 전력 현황"
    CSS = """
    #status { height: 1; padding: 0 1; color: $text-muted; }
    Panel { height: 1fr; }
    #nowtext { height: 12; }
    #nowgraphs { height: 1fr; }
    DataTable { height: 1fr; }
    #cmphead { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('now')", "지금"), Binding("2", "tab('series')", "시계열"), Binding("3", "tab('compare')", "비교"), Binding("4", "tab('netdata')", "Netdata"),
        Binding("r", "cycle_range", "구간"), Binding("g", "cycle_group", "그룹"), Binding("c", "toggle_clean", "깨끗한 표본"),
        Binding("f5", "refresh_now", "새로고침"),
    ]

    def __init__(self, interval=10.0, store=None):
        super().__init__()
        self.interval = interval
        self.store = store or pd.Store()
        self.range_i = 0
        self.group_i = 0
        self.clean = False
        self.last = 0.0
        self._timer = None
        self._nd_cache = {}       # chart -> (t, points)
        self._nd_at = 0.0

    # --- 구성
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status")
        with TabbedContent(initial="now", id="tabs"):
            with TabPane("지금 [1]", id="now"):
                yield Panel(self._now_view, id="nowtext")
                yield Panel(self._now_graphs, id="nowgraphs")
            with TabPane("시계열 [2]", id="series"):
                yield Panel(self._series_view, id="seriestext")
            with TabPane("비교 [3]", id="compare"):
                yield Static("", id="cmphead")
                yield DataTable(id="cmptable", cursor_type="row", zebra_stripes=True)
            with TabPane("Netdata [4]", id="netdata"):
                yield Panel(self._netdata_view, id="netdatatext")
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
        for pid in ("#nowtext", "#nowgraphs", "#seriestext", "#netdatatext"):
            self.query_one(pid, Panel).refresh()
        self._fill_compare()
        n = len(self.store.recs)
        self.query_one("#status", Static).update(
            f"마지막 갱신 {time.strftime('%H:%M:%S', time.localtime(self.last))} · 주기 {self.interval:g}초 · 표본 {n}개 (최근 3일) · 구간 {pv.RANGES[self.range_i][0]}")

    # --- 보기 만들기
    def _est(self):
        return pd.battery_estimate(self.store.recs)

    def _now_view(self, w, h):
        return pv.now_text(self.store.recs, self._est(), w)

    def _now_graphs(self, w, h):
        now = time.time()
        t0, t1 = now - 1800, now
        recs = [r for r in self.store.recs if r["t"] >= t0]
        each = max(2, (h - 2 - 1) // 2)
        out = pv.graph_text("최근 30분 · psys", [(r["t"], r["psys"]) for r in recs], t0, t1, w, each, "W", "cyan")
        out.append("\n")
        out.append_text(pv.graph_text("최근 30분 · 배터리 소비 (방전 중만)", [(r["t"], r["batt"] if r["status"] == "Discharging" else None) for r in recs], t0, t1, w, each, "W", "dark_orange"))
        out.append("\n")
        out.append_text(pv.time_axis(t0, t1, w))
        return out

    def _series_view(self, w, h):
        return pv.timeseries_text(self.store.recs, pv.RANGES[self.range_i][0], time.time(), w, h)

    def _fill_compare(self):
        by = list(pd.GROUPS)[self.group_i]
        label = pv.RANGES[self.range_i][0]
        t0, t1 = pv.range_bounds(label, time.time())
        recs = self.store.since(t0, t1)
        rows = pd.group_table(recs, by, self.clean)
        self.query_one("#cmphead", Static).update(pv.compare_header(pd.GROUPS[by], label, self.clean, len(recs)))
        t = self.query_one("#cmptable", DataTable)
        t.clear()
        f = lambda x, p=2: "-" if x is None else f"{x:.{p}f}"
        for r in rows:
            t.add_row(str(r["group"]), str(r["n"]), pg.fmt_dur(r["hours"]), f(r["coulomb"]), f(r["batt"]), f(r["psys"]), f(r["pkg"]), f(r["pc8"], 0), f(r["pc10"], 0), f(r["wake"], 0), f(r["cpu"], 0))

    def _netdata_view(self, w, h):
        t = Text()
        if not self._nd_cache:
            t.append(" Netdata 데이터를 읽는 중… (이 탭을 열면 읽어 옵니다. Netdata 가 꺼져 있으면 표시되지 않습니다)", style="grey70")
            return t
        label = pv.RANGES[self.range_i][0]
        t0, t1 = pv.range_bounds(label, time.time())
        each = max(2, (h - len(pd.NETDATA_CHARTS) - 3) // len(pd.NETDATA_CHARTS))
        for chart, title, unit, _e, _a in pd.NETDATA_CHARTS:
            _, pts = self._nd_cache.get(chart, (0, None))
            if pts is None:
                t.append(f" {title}   (읽지 못함: Netdata 꺼짐 또는 차트 없음)\n", style="grey50")
                continue
            t.append_text(pv.graph_text(title, pts, t0, t1, w, each, unit, "green"))
            t.append("\n")
        t.append_text(pv.time_axis(t0, t1, w))
        return t

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

    # 창이 포커스를 잃으면 갱신을 멈춘다(보이지 않는 화면 갱신이 PSR 을 방해하지 않도록)
    def on_app_blur(self, _ev: events.AppBlur):
        if self._timer:
            self._timer.pause()

    def on_app_focus(self, _ev: events.AppFocus):
        if self._timer:
            self._timer.resume()
        self.refresh_data()


def main(argv=None):
    p = argparse.ArgumentParser(prog="powerui", description="전력·배터리 현황 TUI")
    p.add_argument("--interval", type=float, default=10.0, help="갱신 주기(초, 기본 10)")
    a = p.parse_args(argv)
    PowerUI(interval=max(2.0, a.interval)).run()


if __name__ == "__main__":
    main()
