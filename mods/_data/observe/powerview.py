"""powerui 의 화면 조각(rich Text 만 만든다 — Textual 앱 없이도 시험 가능)."""
from __future__ import annotations

import glob
import os
import time
from datetime import datetime

from rich.cells import cell_len
from rich.text import Text

import powergraph as pg

STATE_STYLE = {"low": "green", "high": "dark_orange", "?": "grey50"}
RANGES = [("1시간", 3600), ("6시간", 6 * 3600), ("오늘", None), ("3일", 3 * 86400)]
AXIS_W = 8


def range_bounds(label, now):
    secs = dict(RANGES)[label]
    if secs is None:
        mid = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return mid, max(now, mid + 1800)
    return now - secs, now


def _stats(vals):
    v = [x for x in vals if x is not None]
    return (min(v), sum(v) / len(v), max(v), v[-1]) if v else None


def graph_text(title, points, t0, t1, width, height, unit="W", style="dark_orange", lo=0.0, hi=None, fmt="{:.1f}"):
    """제목 줄 + 점자 면적 그래프(왼쪽 눈금). points=[(t, v)]. 반환 Text(줄 수 = 1 + height)."""
    plot_w = max(8, width - AXIS_W)
    vals = pg.bucketize(points, t0, t1, plot_w * 2)
    st = _stats(vals)
    if hi is None:
        lo, hi = pg.nice_range(vals, floor=lo)
    t = Text()
    t.append(f" {title}", style="bold")
    if st:
        t.append(f"   지금 {fmt.format(st[3])}{unit} · 평균 {fmt.format(st[1])} · 최소 {fmt.format(st[0])} · 최대 {fmt.format(st[2])}", style="grey70")
    else:
        t.append("   (데이터 없음)", style="grey50")
    t.append("\n")
    rows = pg.braille_area(vals, height, lo, hi)
    for i, r in enumerate(rows):
        label = fmt.format(hi) if i == 0 else (fmt.format(lo) if i == len(rows) - 1 else "")
        t.append(f"{label:>{AXIS_W - 1}} ", style="grey50")
        t.append(r, style=style)
        if i < len(rows) - 1:
            t.append("\n")
    return t


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


def timeseries_text(recs, rng, now, width, height):
    """시계열 탭 전체. 세로 공간을 그래프 4개에 나누고, 아래에 상태/PSR/전원 띠와 시간축."""
    t0, t1 = range_bounds(rng, now)
    sel = [r for r in recs if t0 <= r["t"] <= t1]
    bars = 5                                      # 띠 3줄 + 시간축 + 범례
    each = max(2, (height - bars - 4 - 1) // 4)   # 그래프 4개의 제목 줄(4) 제외
    spec = [("배터리 소비 (V×I)", "batt", "W", "dark_orange", 0.0, None, "{:.1f}"),
            ("psys (플랫폼 합계)", "psys", "W", "cyan", 0.0, None, "{:.1f}"),
            ("패키지 (CPU+GPU)", "pkg", "W", "magenta", 0.0, None, "{:.1f}"),
            ("배터리 잔량", "pct", "%", "green", 0.0, 100.0, "{:.0f}")]
    out = Text(f" 구간 {rng} · 표본 {len(sel)}개 · {datetime.fromtimestamp(t0):%m-%d %H:%M} ~ {datetime.fromtimestamp(t1):%H:%M}\n", style="grey70")
    for title, key, unit, style, lo, hi, fmt in spec:
        pts = [(r["t"], r[key] if key != "batt" or r["status"] == "Discharging" else None) for r in sel]
        out.append_text(graph_text(title, pts, t0, t1, width, each, unit, style, lo, hi, fmt))
        out.append("\n")
    plot_w = max(8, width - AXIS_W)
    out.append_text(band_text("상태", pg.bucket_labels([(r["t"], r["state"]) for r in sel], t0, t1, plot_w), STATE_STYLE, plot_w))
    out.append("\n")
    out.append_text(band_text("PSR", pg.bucket_labels([(r["t"], "on" if r["psr"] else "off") for r in sel], t0, t1, plot_w), {"on": "cyan", "off": "grey35"}, plot_w))
    out.append("\n")
    out.append_text(band_text("전원", pg.bucket_labels([(r["t"], "ac" if r["ac"] else "bat") for r in sel], t0, t1, plot_w), {"ac": "dodger_blue1", "bat": "grey35"}, plot_w))
    out.append("\n")
    out.append_text(time_axis(t0, t1, width))
    out.append("\n 상태: 초록 low · 주황 high    PSR: 청록 켬    전원: 파랑 AC    (빈 칸 ░ = 그 시간 데이터 없음)", style="grey50")
    return out


def _max_brightness():
    for f in glob.glob("/sys/class/backlight/*/max_brightness"):
        try:
            return float(open(f).read())
        except (OSError, ValueError):
            pass
    return None


def now_text(recs, est, width, now=None):
    now = now if now is not None else time.time()
    t = Text()
    if not recs:
        t.append("표본이 없습니다. `observectl on` 으로 수집을 켜세요.", style="yellow")
        return t
    r = recs[-1]
    age = now - r["t"]
    if age > 120:
        t.append(f"⚠ 마지막 표본이 {age / 60:.0f}분 전입니다(수집이 꺼져 있을 수 있음: observectl status)\n", style="yellow")
    pct = f"{r['pct']:.0f}%" if r["pct"] is not None else "?"
    status = {"Discharging": "방전 중", "Charging": "충전 중", "Full": "완충", "Not charging": "충전 안 함"}.get(r["status"], r["status"] or "?")
    t.append(" 전원  ", style="bold")
    t.append(f"{status}", style="dodger_blue1" if r["status"] != "Discharging" else "green")
    t.append(f" · {pct}")
    if est and est.get("remain_wh"):
        t.append(f"  ({est['remain_wh']:.1f}" + (f" / {est['full_wh']:.1f}" if est.get("full_wh") else "") + " Wh)", style="grey70")
    t.append("\n")
    t.append(" 지금  ", style="bold")
    t.append(f"psys {pg.fmt_w(r['psys'])} · 배터리 {pg.fmt_w(r['batt']) if r['status'] == 'Discharging' else '(충전 중)'} · 패키지 {pg.fmt_w(r['pkg'])}\n")
    t.append("       상태 ")
    t.append(r["state"], style=STATE_STYLE.get(r["state"], "grey50") + " bold")
    t.append(f" · 패키지 pc8 {r['pc8'] or 0:.0f}% pc10 {r['pc10'] or 0:.0f}% · 깨움 {r['wake']:.0f}/s · CPU {r['cpu'] or 0:.0f}%\n", style="grey70")
    t.append(" PSR   ", style="bold")
    on = r["psr"]
    t.append(r["psr_mode"] or "정보 없음(수집기 갱신 필요)", style="cyan" if on else "grey50")
    if r["psr_sink"]:
        t.append(f" · 싱크 {r['psr_sink']}", style="grey70")
    t.append("\n")
    mb = _max_brightness()
    bl = f"{r['bl'] / mb * 100:.0f}%" if r["bl"] is not None and mb else "?"
    t.append(" 장치  ", style="bold")
    t.append(f"밝기 {bl} · 덮개 {r['lid'] or '?'} · 화면 {r['vt'] or '?'} · Wi-Fi 절전 {r['wifi_ps'] or '?'} · {'AC 연결' if r['ac'] else 'AC 없음'}\n", style="grey70")
    t.append("\n")
    if est and r["status"] == "Discharging":
        t.append(" 남은 시간 추정 (잔량 ÷ 전력, 0%까지 쓴다고 가정 — 실제로는 5~10% 남기고 끄므로 그만큼 빼서 보세요)\n", style="bold")
        for key, label in (("recent", "최근 30분 평균"), ("typical", "최근 6시간 평균(깨끗한 표본)"), ("now", "지금 순간")):
            w, h = est.get(key + "_w"), est.get(key + "_h")
            t.append(f"   {label:<26}{pg.fmt_w(w):>9}  →  {pg.fmt_dur(h)}\n")
    elif est and est.get("charging"):
        t.append(" 충전 중이라 남은 시간 추정은 생략합니다. (뽑으면 방전 기준으로 계산)\n", style="grey70")
        if est.get("full_wh"):
            fw = est["full_wh"]
            for key, label in (("typical", "만충에서 쓰면(평소 평균)"),):
                w = est.get(key + "_w")
                t.append(f"   {label:<26}{pg.fmt_w(w):>9}  →  {pg.fmt_dur(fw / w if w and w > 0.5 else None)}\n")
    return t


def compare_header(by_label, rng, clean, n):
    return Text(f" 그룹 기준: {by_label} · 구간 {rng} · {'깨끗한 표본만(내 활동·빌드 제외)' if clean else '모든 표본'} · 표본 {n}개   [g] 기준 바꾸기  [c] 깨끗한 표본  [r] 구간")
