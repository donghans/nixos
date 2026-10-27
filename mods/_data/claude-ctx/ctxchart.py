"""ctxui 의 차트 조각(rich Text 만 만든다 — Textual 앱 없이도 시험 가능): 한도 창 점자 면적 그래프, 시간대별 프롬프트 그래프, 폭에 맞춘 가로 막대.
점자 한 글자 = 가로 2 × 세로 4 점이라 글자 칸보다 가로 2배·세로 4배 해상도다(usageui 의 그래프와 같은 방식, 배포 단위가 달라 작은 함수만 따로 둔다)."""
from __future__ import annotations

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


def window_chart(windows, span_s, width, height, style, now=None):
    """한도 창 그래프 한 개: 창(리셋 시각 직전 span_s 초)마다 그 창에서 찍은 최고 %를 창 길이만큼 가로로 채운다. y 는 0~100 % 고정, x 는 시간(샘플 없는 창 사이는 빈칸).
    windows=[(리셋 datetime, 최고 %)…오래된 것부터]. 반환 Text(높이 = height 줄 + 시간축 1줄), 창이 없으면 None."""
    if not windows:
        return None
    ts = [(r.timestamp(), v) for r, v in windows]
    t1 = ts[-1][0]
    t0 = ts[0][0] - span_s
    plot_w = max(10, width - AXIS_W)
    n = plot_w * 2
    vals = []
    for c in range(n):
        tc = t0 + (c + 0.5) * (t1 - t0) / n
        vals.append(next((v for r, v in ts if r - span_s < tc <= r), None))
    fmt = lambda s: datetime.fromtimestamp(s).strftime("%m-%d %H:%M")
    labels = {0: "100", height // 2: "50", height - 1: "0"} if height >= 3 else {0: "100", height - 1: "0"}
    axis = _axis(plot_w, [(0.0, fmt(t0)), (0.5, fmt((t0 + t1) / 2)), (1.0, fmt(t1))] if plot_w >= 44 else [(0.0, fmt(t0)), (1.0, fmt(t1))])
    return _plot(vals, width, height, 0, 100, style, labels, axis)


def hour_chart(by_hour, width, height, style):
    """시간대별(0~23시) 그래프: 한 시간 = 가로 width/24 만큼의 막대. y 는 0~최대. 반환 Text(높이 = height 줄 + 시간축 1줄)."""
    plot_w = max(24, width - AXIS_W)
    n = plot_w * 2
    vals = [by_hour[min(23, c * 24 // n)] for c in range(n)]
    top = max(by_hour) if by_hour and max(by_hour) > 0 else 1
    labels = {0: f"{top:,}", height - 1: "0"}
    axis = _axis(plot_w, [(h / 24, str(h)) for h in (0, 6, 12, 18)] + [(1.0, "24")])
    return _plot(vals, width, height, 0, top, style, labels, axis)


def series_chart(values, labels, width, height, style, fmt=lambda v: f"{v:,.0f}"):
    """구간별 값(예: 일별 비용) 막대 그래프 한 개. values·labels 는 같은 길이(오래된 것부터). 구간 하나 = 가로 plot 폭/구간 수 칸(넓으면 구간 사이에 한 칸 틈).
    y 는 0~최대, x 눈금은 처음·가운데·끝 구간 이름. 반환 Text(높이 = height 줄 + 눈금 1줄), 값이 없으면 None."""
    if not values:
        return None
    plot_w = max(10, width - AXIS_W)
    cols = plot_w * 2
    n = len(values)
    top = max(values) or 1
    vals = []
    for c in range(cols):
        i = min(n - 1, c * n // cols)
        edge = cols / n >= 3 and min(n - 1, (c + 1) * n // cols) != i      # 구간의 마지막 열은 비워 막대를 구분한다(맨 끝 구간은 제외)
        vals.append(None if edge else values[i])
    labels_y = {0: fmt(top), height // 2: fmt(top / 2), height - 1: "0"} if height >= 4 else {0: fmt(top), height - 1: "0"}
    marks = [(0.0, labels[0])] + ([(0.5, labels[n // 2])] if n >= 3 and plot_w >= 40 else []) + ([(1.0, labels[-1])] if n >= 2 else [])
    return _plot(vals, width, height, 0, top, style, labels_y, _axis(plot_w, marks))


def fit_bar(v, vmax, width):
    """가로 막대(1/8 칸 해상도) — width 칸 안에서 v/vmax 만큼. v·vmax 가 0 이하이거나 width<1 이면 빈 문자열."""
    if not vmax or v <= 0 or width < 1:
        return ""
    eighths = max(1, round(width * 8 * v / vmax))
    return "█" * (eighths // 8) + (" ▏▎▍▌▋▊▉"[eighths % 8] if eighths % 8 else "")
