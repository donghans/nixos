"""ctxui 의 차트 조각(rich Text 만 만든다 — Textual 앱 없이도 시험 가능): 한도 사용률 시계열, 시간당 비용, 시간대별 프롬프트의 점자 면적 그래프와 폭에 맞춘 가로 막대.
점자 한 글자 = 가로 2 × 세로 4 점이라 글자 칸보다 가로 2배·세로 4배 해상도다(usageui 의 그래프와 같은 방식, 배포 단위가 달라 작은 함수만 따로 둔다).
색을 흐리게 해서 계단을 감추지 않는다 — 계단은 데이터가 거칠 때 생기므로, 실제 샘플·시간당·15분 단위처럼 **데이터를 곱게 재서** 줄인다."""
from __future__ import annotations

import time
from datetime import datetime

from rich.text import Text

AXIS_W = 6                      # y 눈금 글자 폭(마지막 칸은 구분 공백)
_LEFT = (0x40, 0x04, 0x02, 0x01)       # 왼쪽 열, 아래 → 위
_RIGHT = (0x80, 0x20, 0x10, 0x08)      # 오른쪽 열, 아래 → 위


def braille_area(values, height, lo, hi):
    """면적 그래프. values 는 열(가로 점) 값 리스트(None=빈칸). height 개 줄(위→아래)의 문자열을 돌려준다(각 줄 길이 = ceil(len/2))."""
    cols = list(values)
    if len(cols) % 2:
        cols.append(None)
    levels = [0 if v is None or hi <= lo else max(0, min(4 * height, round((v - lo) / (hi - lo) * 4 * height))) for v in cols]
    rows = []
    for r in range(height):
        base = 4 * (height - 1 - r)
        line = []
        for i in range(0, len(levels), 2):
            bits = 0
            for k in range(max(0, min(4, levels[i] - base))):
                bits |= _LEFT[k]
            for k in range(max(0, min(4, levels[i + 1] - base))):
                bits |= _RIGHT[k]
            line.append(chr(0x2800 + bits))
        rows.append("".join(line))
    return rows


def _plot(values, width, height, lo, hi, style, labels, axis_line=None):
    """값 열(plot 폭 × 2 개)을 y 눈금(labels: 줄 번호 → 글자)과 함께 Text 로. axis_line 이 있으면 맨 아래에 붙인다."""
    t = Text()
    rows = braille_area(values, height, lo, hi)
    for i, r in enumerate(rows):
        t.append(f"{labels.get(i, ''):>{AXIS_W - 1}} ", style="grey50")
        t.append(r, style=style)
        if i < len(rows) - 1 or axis_line:
            t.append("\n")
    if axis_line:
        t.append(" " * AXIS_W + axis_line, style="grey50")
    return t


def _axis(plot_w, marks):
    """marks: [(0~1 위치, 글자)] → plot_w 칸 눈금줄. 겹치거나 넘치는 글자는 건너뛴다."""
    line = [" "] * plot_w
    last = -2
    for frac, s in marks:
        x = min(max(0, round(frac * (plot_w - 1)) - (len(s) if frac >= 0.999 else len(s) // 2 if 0 < frac < 0.999 else 0)), plot_w - len(s))
        if x <= last or x + len(s) > plot_w:
            continue
        line[x:x + len(s)] = s
        last = x + len(s)
    return "".join(line)


def _epoch(t):
    return t.timestamp() if hasattr(t, "timestamp") else float(t)


def _time_axis(plot_w, t0, t1, fmt="%m-%d %H:%M"):
    f = lambda s: datetime.fromtimestamp(s).strftime(fmt)
    return _axis(plot_w, [(0.0, f(t0)), (0.5, f((t0 + t1) / 2)), (1.0, f(t1))] if plot_w >= 44 else [(0.0, f(t0)), (1.0, f(t1))])


def limit_chart(series, span_s, width, height, style, now=None):
    """한도 사용률 시계열 그래프 한 개. series=[(시각, %, 리셋 시각)…](시각 순). 창(리셋 직전 span_s 초)마다 사용률이 0 에서 올라가다 리셋에서 떨어지는 모양이 그대로 나온다.
    창 안에서 사용률은 줄지 않으므로 샘플이 없는 구간은 앞 값을 이어 주되, 지금(now)을 넘기거나 창이 끝난 뒤, 창의 첫 샘플 이전은 비운다.
    y 는 0~100 % 고정, x 는 시간(첫 창 시작 ~ 마지막 창 리셋). 반환 Text(높이 = height 줄 + 시간축 1줄), 샘플이 없으면 None."""
    if not series:
        return None
    now = time.time() if now is None else now
    pts = sorted((_epoch(t), float(v), _epoch(r)) for t, v, r in series)
    resets = sorted({r for _, _, r in pts})
    t0, t1 = resets[0] - span_s, resets[-1]
    plot_w = max(10, width - AXIS_W)
    n = plot_w * 2
    dt = (t1 - t0) / n
    vals = [None] * n
    for r in resets:
        ws = [(t, v) for t, v, rr in pts if rr == r]
        i, cur = 0, None
        for c in range(n):
            ca, cb = t0 + c * dt, t0 + (c + 1) * dt
            if cb <= r - span_s or ca >= r:
                continue
            while i < len(ws) and ws[i][0] <= cb:
                cur = ws[i][1]; i += 1
            if cur is not None and ca < now:
                vals[c] = cur
    labels = {0: "100", height // 2: "50", height - 1: "0"} if height >= 3 else {0: "100", height - 1: "0"}
    return _plot(vals, width, height, 0, 100, style, labels, _time_axis(plot_w, t0, t1))


def rate_chart(points, t0, t1, unit_s, width, height, style, fmt=lambda v: f"{v:,.0f}"):
    """구간별 합계(예: 시간별 비용 $)를 「단위 시간당」 비율의 면적 그래프로. points=[(구간 시작, 값)…], 각 구간 길이는 unit_s. 구간이 없는 시간은 0.
    열이 구간보다 굵으면 열 안의 구간들의 시간 가중 평균, 가늘면 같은 값을 이어 그린다. y 는 0~최대. 반환 (Text, 최대 비율), 값이 없으면 (None, 0)."""
    if not points or t1 <= t0:
        return None, 0.0
    pts = sorted((_epoch(t), float(v)) for t, v in points)
    plot_w = max(10, width - AXIS_W)
    n = plot_w * 2
    dt = (t1 - t0) / n
    vals, j = [], 0
    for c in range(n):
        ca, cb = t0 + c * dt, t0 + (c + 1) * dt
        while j < len(pts) and pts[j][0] + unit_s <= ca:
            j += 1
        tot, k = 0.0, j
        while k < len(pts) and pts[k][0] < cb:
            tot += pts[k][1] * max(0.0, min(cb, pts[k][0] + unit_s) - max(ca, pts[k][0])) / dt
            k += 1
        vals.append(tot)
    top = max(vals) or 1.0
    labels = {0: fmt(top), height // 2: fmt(top / 2), height - 1: "0"} if height >= 4 else {0: fmt(top), height - 1: "0"}
    return _plot(vals, width, height, 0, top, style, labels, _time_axis(plot_w, t0, t1, "%m-%d %H:00" if unit_s < 86400 else "%m-%d")), max(vals)


def slot_chart(bins, width, height, style):
    """하루(0~24시)를 같은 길이로 나눈 칸(예: 15분 96칸)별 개수 그래프. 칸이 열보다 많으면 열 안의 칸들의 평균, 적으면 같은 값을 이어 그린다.
    y 는 0~최대 칸 값, x 눈금 0·6·12·18·24. 반환 Text(높이 = height 줄 + 시간축 1줄)."""
    plot_w = max(24, width - AXIS_W)
    n, m = plot_w * 2, len(bins)
    vals = []
    for c in range(n):
        a, b = c * m / n, (c + 1) * m / n
        tot = sum(bins[i] * max(0.0, min(b, i + 1) - max(a, i)) for i in range(int(a), min(m, int(b) + 1)))
        vals.append(tot / (b - a))
    top = max(bins) if bins and max(bins) > 0 else 1
    labels = {0: f"{top:,}", height - 1: "0"}
    return _plot(vals, width, height, 0, top, style, labels, _axis(plot_w, [(h / 24, str(h)) for h in (0, 6, 12, 18)] + [(1.0, "24")]))


def fit_bar(v, vmax, width):
    """가로 막대(1/8 칸 해상도) — width 칸 안에서 v/vmax 만큼. v·vmax 가 0 이하이거나 width<1 이면 빈 문자열."""
    if not vmax or v <= 0 or width < 1:
        return ""
    eighths = max(1, round(width * 8 * v / vmax))
    return "█" * (eighths // 8) + (" ▏▎▍▌▋▊▉"[eighths % 8] if eighths % 8 else "")

