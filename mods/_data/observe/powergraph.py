"""powerui 의 순수 계산/그림 함수(터미널 없이 시험 가능): 시간 구간 평균, 점자(braille) 면적 그래프, 막대, 단위 형식.
점자 한 글자 = 가로 2 × 세로 4 점(btop 과 같은 방식)이라 글자 칸보다 가로 2배·세로 4배 해상도로 그린다."""
from __future__ import annotations

# 점자 점 비트: 왼쪽 열 위→아래 0x01,0x02,0x04,0x40 / 오른쪽 열 0x08,0x10,0x20,0x80
_LEFT = (0x40, 0x04, 0x02, 0x01)       # 아래→위 순서(아래부터 채우므로)
_RIGHT = (0x80, 0x20, 0x10, 0x08)
BLOCKS = " ▏▎▍▌▋▊▉█"


def bucketize(points, t0, t1, n):
    """[(t, v)] 를 [t0, t1) 을 n 등분한 구간 평균으로 줄인다. v 가 None 이면 무시, 값이 없는 구간은 None. 반환: 길이 n 의 리스트."""
    if n <= 0 or t1 <= t0:
        return []
    sums, cnt = [0.0] * n, [0] * n
    w = (t1 - t0) / n
    for t, v in points:
        if v is None or t < t0 or t >= t1:
            continue
        i = min(n - 1, int((t - t0) / w))
        sums[i] += v
        cnt[i] += 1
    return [sums[i] / cnt[i] if cnt[i] else None for i in range(n)]


def bucket_labels(keys_points, t0, t1, n):
    """[(t, 문자열)] 을 n 등분하고 구간마다 가장 많이 나온 값(없으면 None)을 돌려준다(상태 띠용)."""
    if n <= 0 or t1 <= t0:
        return []
    bins = [dict() for _ in range(n)]
    w = (t1 - t0) / n
    for t, k in keys_points:
        if k is None or t < t0 or t >= t1:
            continue
        b = bins[min(n - 1, int((t - t0) / w))]
        b[k] = b.get(k, 0) + 1
    return [max(b, key=b.get) if b else None for b in bins]


def nice_range(values, floor=0.0, pad=0.1):
    """그래프 세로 범위 (lo, hi). 값이 없으면 (0, 1). 위쪽에 pad 만큼 여유."""
    v = [x for x in values if x is not None]
    if not v:
        return (floor, floor + 1.0)
    hi = max(v)
    hi = hi * (1 + pad) if hi > floor else floor + 1.0
    return (floor, hi)


def braille_area(values, height, lo, hi):
    """면적 그래프. values 는 길이 2*width 이하의 리스트(None=빈칸). 반환: height 개 줄(위→아래)의 문자열(각 줄 길이 = ceil(len/2)).
    값이 lo 이하면 그 열은 비우고, hi 이상이면 꼭대기까지 채운다."""
    if height <= 0:
        return []
    cols = list(values)
    if len(cols) % 2:
        cols.append(None)
    levels = []
    for v in cols:
        if v is None or hi <= lo:
            levels.append(0)
        else:
            levels.append(max(0, min(4 * height, round((v - lo) / (hi - lo) * 4 * height))))
    rows = []
    for r in range(height):
        base = 4 * (height - 1 - r)          # 이 줄의 맨 아래 점 높이
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


def hbar(frac, width):
    """가로 막대(1/8 칸 해상도). frac 0..1, 반환 길이는 항상 width."""
    frac = 0.0 if frac != frac else max(0.0, min(1.0, frac))
    eighths = round(frac * width * 8)
    full, part = divmod(eighths, 8)
    s = "█" * full + (BLOCKS[part] if part and full < width else "")
    return s.ljust(width)


def fmt_w(x, p=2):
    return "-" if x is None or x != x else f"{x:.{p}f} W"


def fmt_dur(hours):
    """시간(float) → '9시간 12분' / '45분'. 음수/NaN 은 '-'."""
    if hours is None or hours != hours or hours < 0:
        return "-"
    m = round(hours * 60)
    return f"{m // 60}시간 {m % 60:02d}분" if m >= 60 else f"{m}분"
