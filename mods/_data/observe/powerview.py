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
STATE_GLOSS = {"low": "low(깊은 절전 진입)", "high": "high(깊은 절전 못 함)"}   # low/high 는 전력 높낮이가 아니라 패키지 pc10 ≥ 5% 여부
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


SERIES = [  # (제목, 필드, 단위, 색, 하한, 상한, 형식)
    ("배터리 소비 (순간 V×I, 방전 중)", "batt_vi", "W", "dark_orange", 0.0, None, "{:.1f}"),
    ("psys (RAPL 플랫폼 — 총 소비보다 약 1 W 적게 보임)", "psys", "W", "cyan", 0.0, None, "{:.1f}"),
    ("패키지 (CPU+GPU)", "pkg", "W", "magenta", 0.0, None, "{:.1f}"),
    ("배터리 잔량", "pct", "%", "green", 0.0, 100.0, "{:.0f}"),
]


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
    t.append(f"psys {pg.fmt_w(r['psys'])} · 배터리 V×I {pg.fmt_w(r['batt_vi']) if r['status'] == 'Discharging' else '(충전 중)'} · 패키지 {pg.fmt_w(r['pkg'])}\n")
    t.append("       상태 ")
    t.append(STATE_GLOSS.get(r["state"], r["state"]), style=STATE_STYLE.get(r["state"], "grey50") + " bold")
    ctxall = f"{r['ctxsw_all']:.0f}" if r["ctxsw_all"] is not None else "-"
    t.append(f" · 패키지 pc8 {r['pc8'] or 0:.0f}% pc10 {r['pc10'] or 0:.0f}%\n", style="grey70")
    t.append(f"       전환 시스템 전체 {ctxall}/s · 상위 프로세스 {r['ctxsw_top']:.0f}/s(합계 아님) · CPU 전체 대비 {r['cpu_all'] or 0:.0f}%\n", style="grey70")
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
