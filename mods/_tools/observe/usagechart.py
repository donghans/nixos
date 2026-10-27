"""usageui 의 차트 조각(rich Text 만 만든다 — Textual 앱 없이도 시험 가능): 점자 면적 그래프 한 개, 상태·PSR·전원 띠, 시간축."""
from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text

import usagegraph as pg

STATE_STYLE = {"low": "green", "high": "dark_orange", "?": "grey50"}
AXIS_W = 8


def _stats(vals):
    v = [x for x in vals if x is not None]
    return (min(v), sum(v) / len(v), max(v), v[-1]) if v else None


GRADIENT = ["#2ecc71", "#7ddc4c", "#c7e03a", "#f1c40f", "#f39c12", "#e67e22", "#e74c3c"]   # 아래(초록) → 위(빨강), btop 의 세로 그라데이션과 같은 방식


def chart(points, t0, t1, width, height, unit="W", style="dark_orange", lo=0.0, hi=None, fmt="{:.1f}", gradient=False, max_gap_s=120, axis=False):
    """그래프 한 개(박스 안 내용). points=[(t, v)]. 반환 (Text, 통계 또는 None). 통계는 (최소, 평균, 최대, 마지막).
    점자 면적 그래프(가로 2배 해상도). axis=True 면 맨 아래에 시간축 한 줄을 붙인다(그 줄도 height 에 포함)."""
    plot_w = max(8, width - AXIS_W)
    cols = plot_w * 2
    raw = pg.bucketize(points, t0, t1, cols)
    st = _stats(raw)
    vals = pg.fill_gaps(raw, (t1 - t0) / cols, max_gap_s)
    if hi is None:
        lo, hi = pg.nice_range(vals, floor=lo)
    if fmt is None:                                 # 자릿수 자동: 값이 클수록 소수점을 줄인다
        fmt = "{:.0f}" if hi >= 100 else "{:.1f}" if hi >= 10 else "{:.2f}"
    h = max(1, height - (1 if axis else 0))
    rows = pg.braille_area(vals, h, lo, hi)
    mid = h // 2
    t = Text()
    for i, r in enumerate(rows):
        label = fmt.format(hi) if i == 0 else fmt.format(lo) if i == h - 1 else fmt.format((hi + lo) / 2) if h >= 5 and i == mid else ""
        t.append(f"{label:>{AXIS_W - 1}} ", style="grey50")
        t.append(r, style=GRADIENT[round((h - 1 - i) / max(1, h - 1) * (len(GRADIENT) - 1))] if gradient else style)
        if i < h - 1 or axis:
            t.append("\n")
    if axis:
        t.append_text(time_axis(t0, t1, width))
    return t, (st + (fmt,) if st else None)


def stats_str(st, unit="W", fmt="{:.1f}"):
    """통계 (최소, 평균, 최대, 마지막[, 형식]) → 박스 부제 문자열. chart() 가 돌려준 형식이 있으면 그것을 쓴다."""
    if not st:
        return "데이터 없음"
    if len(st) == 5:
        st, fmt = st[:4], st[4]
    return f"지금 {fmt.format(st[3])}{unit} · 평균 {fmt.format(st[1])} · 최소 {fmt.format(st[0])} · 최대 {fmt.format(st[2])}"


def series_points(recs, key):
    return [(r["t"], r[key] if key != "batt_vi" or r["status"] == "Discharging" else None) for r in recs]


def bands_text(recs, t0, t1, width, max_gap_s=120):
    """상태/PSR/전원 띠 3줄 + 시간축 + 범례(마지막에 줄바꿈 없음). 칸 폭이 표본 간격보다 짧아도 끊겨 보이지 않게 직전 값으로 이어 준다."""
    plot_w = max(8, width - AXIS_W)
    bs = (t1 - t0) / plot_w

    def lab(f):
        return pg.hold_labels(pg.bucket_labels([(r["t"], f(r)) for r in recs], t0, t1, plot_w), bs, max_gap_s)
    out = band_text("상태", lab(lambda r: r["state"]), STATE_STYLE, plot_w)
    out.append("\n")
    out.append_text(band_text("PSR", lab(lambda r: "on" if r["psr"] else "off"), {"on": "cyan", "off": "grey35"}, plot_w))
    out.append("\n")
    out.append_text(band_text("전원", lab(lambda r: "ac" if r["ac"] else "bat"), {"ac": "dodger_blue1", "bat": "grey35"}, plot_w))
    out.append("\n")
    out.append_text(time_axis(t0, t1, width))
    out.append("\n 상태: 초록 low=깊은 절전 · 주황 high    PSR: 청록=켬    전원: 파랑=AC    ░=데이터 없음", style="grey50")
    return out


def band_text(title, labels, styles, width):
    """한 줄 상태 띠(구간마다 색 블록). labels=[키|None], styles={키: 색}."""
    t = Text()
    t.append(" " * max(0, AXIS_W - 1 - cell_len(title)) + title + " ", style="grey70")   # 한글은 2칸 폭이라 글자 수가 아니라 칸 수로 맞춘다
    for k in labels:
        t.append("█" if k is not None else "░", style=styles.get(k, "grey50") if k is not None else "grey23")
    return t


def time_axis(t0, t1, width):
    plot_w = max(8, width - AXIS_W)
    fmt = "%H:%M" if t1 - t0 <= 86400 + 1 else "%d일 %H시"
    n = max(2, min(8, plot_w // 14))
    line = [" "] * plot_w
    for i in range(n):
        x = round(i * (plot_w - 1) / (n - 1))
        s = datetime.fromtimestamp(t0 + (t1 - t0) * x / (plot_w - 1)).strftime(fmt)
        x = min(x, plot_w - len(s))
        for j, ch in enumerate(s):
            line[x + j] = ch
    return Text(" " * AXIS_W + "".join(line), style="grey50")
