#!/usr/bin/env python3
"""ctxchart 시험: 한도 시계열·시간당 비용·시간대별 점자 그래프와 가로 막대(Textual·DB 없이)."""
import os, sys
from datetime import datetime, timedelta, timezone
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
from rich.cells import cell_len
import ctxchart as cx
check, finish = checker()
BLANK = "⠀"
R0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
H = lambda h: R0 + timedelta(hours=h)


def body(t, rows):
    return [l[cx.AXIS_W:] for l in t.plain.split("\n")[:rows]]


# --- 한도: 창 안에서 0 에서 올라가는 모양, 창 사이 리셋에서 떨어짐
def saw(reset_h, peak, start_h, n=10):
    """리셋(reset_h 시) 창에서 start_h 부터 n 개 샘플이 0→peak 로 올라간다."""
    return [(H(reset_h - 5 + start_h + 4 * i / n), peak * (i + 1) / n, H(reset_h)) for i in range(n)]


ser = saw(5, 40.0, 0) + saw(10, 80.0, 0) + saw(15, 20.0, 0)
for w in (40, 100, 190):
    t = cx.limit_chart(ser, 5 * 3600, w, 5, "cyan", now=H(15).timestamp() + 1)
    lines = t.plain.split("\n")
    check(f"한도 그래프 폭 {w}: 높이 5 + 시간축 1줄, 모든 줄이 폭 이하(줄바꿈 없음)", len(lines) == 6 and all(cell_len(l) <= w for l in lines), [cell_len(l) for l in lines])
    check(f"한도 그래프 폭 {w}: y 눈금 100·50·0 과 시간축 날짜", lines[0].lstrip().startswith("100") and lines[2].lstrip().startswith("50") and lines[4].lstrip().startswith("0") and "10-" in lines[5], lines)
t = cx.limit_chart(ser, 5 * 3600, 100, 4, "cyan", now=H(15).timestamp() + 1)
b = body(t, 4)
filled = lambda row: [i for i, ch in enumerate(row) if ch != BLANK]
cols_by_row = [filled(r) for r in b]
check("한도 그래프: 80% 창의 맨 윗줄(둘째 줄)에는 가운데 창만 닿고, 맨 아랫줄은 세 창 모두 있다", cols_by_row[1] and len(cols_by_row[1]) < len(cols_by_row[3]) and min(cols_by_row[1]) > len(b[1]) * 0.25, (cols_by_row[1][:2], len(cols_by_row[3])))
# 올라가는 모양: 80% 창 안에서 왼쪽 열(초반)의 높이 < 오른쪽 열(후반)의 높이
def col_height(c):
    return sum(1 for r in b if r[c] != BLANK)
w2 = [c for c in range(len(b[3])) if col_height(c) >= 1]
mid_start, mid_end = int(len(b[3]) * 0.36), int(len(b[3]) * 0.62)
hs = [col_height(c) for c in range(mid_start, mid_end)]
check("한도 그래프: 한 창 안에서 왼쪽(초반)보다 오른쪽(후반)이 높다 — 올라가는 톱니", hs and max(hs[len(hs) // 2:]) > max(hs[:3]) , hs)
bnd = int(len(b[3]) * 2 / 3)
check("한도 그래프: 창 사이 리셋에서는 사용률이 떨어진다(80% 창 끝 → 다음 창 시작은 비거나 낮다)", col_height(bnd - 2) >= 3 and col_height(bnd + 2) < col_height(bnd - 2), (col_height(bnd - 2), col_height(bnd + 2)))
# 지금(now) 이후와 첫 샘플 이전은 비운다
half = cx.limit_chart(ser, 5 * 3600, 100, 4, "cyan", now=H(7).timestamp())
hb = body(half, 4)
check("한도 그래프: 지금(now) 이후는 비운다(앞 창들만 그려진다)", all(ch == BLANK for r in hb for ch in r[int(len(r) * 0.6):]), [r[-20:] for r in hb])
check("한도 그래프: 샘플이 없으면 None", cx.limit_chart([], 5 * 3600, 80, 5, "cyan") is None)
one = cx.limit_chart([(H(0), 58.0, R0 + timedelta(days=7))], 7 * 86400, 60, 3, "cyan", now=R0.timestamp() + 7 * 86400)
check("한도 그래프: 창이 1개·샘플 1개여도 그려진다(7d)", one is not None and len(one.plain.split("\n")) == 4)
check("한도 그래프: 색을 섞지 않는다(스타일은 한 가지 + 눈금 회색)", {str(sp.style) for sp in t.spans} <= {"cyan", "grey50"}, {str(sp.style) for sp in t.spans})

# --- 시간당 비용
pts = [(H(i), c) for i, c in enumerate([1.0, 1.0, 5.0, 0.0, 0.0, 2.0])]
for w in (40, 100):
    t, top = cx.rate_chart(pts, H(0).timestamp(), H(6).timestamp(), 3600, w, 6, "cyan", lambda v: f"${v:,.0f}")
    lines = t.plain.split("\n")
    check(f"비용 그래프 폭 {w}: 높이 6 + 시간축, 폭 이하, 최대 $5", len(lines) == 7 and all(cell_len(l) <= w for l in lines) and lines[0].lstrip().startswith("$5") and abs(top - 5.0) < 1e-6, (lines[0][:12], top))
t, top = cx.rate_chart(pts, H(0).timestamp(), H(6).timestamp(), 3600, 100, 6, "cyan")
bb = body(t, 6)
check("비용 그래프: 가장 비싼 시간(5$)이 맨 윗줄에 닿고 비어 있던 시간(0$)은 바닥이 비어 있다", any(ch != BLANK for ch in bb[0]) and any(bb[5][i] == BLANK for i in range(len(bb[5]))), bb[0][:30])
wide, topw = cx.rate_chart([(H(i), 1.0) for i in range(48)], H(0).timestamp(), H(48).timestamp(), 3600, 60, 4, "cyan")
check("비용 그래프: 구간(48시간)이 열 수보다 많아도 시간당 비율이 보존된다(전부 1$ → 최대 1$)", abs(topw - 1.0) < 1e-6, topw)
check("비용 그래프: 값이 없으면 (None, 0)", cx.rate_chart([], 0, 1, 3600, 40, 4, "c") == (None, 0.0))

# --- 시간대별(15분 96칸)
bins = [0] * 36 + [3, 5, 8, 20, 30, 25, 20, 10, 9, 4, 3, 2] * 4 + [0] * 12
for w in (30, 60, 140):
    t = cx.slot_chart(bins, w, 4, "cyan"); lines = t.plain.split("\n")
    check(f"시간대 그래프 폭 {w}: 높이 4 + 시간축, 폭 이하, 최대값 눈금", len(lines) == 5 and all(cell_len(l) <= max(w, cx.AXIS_W + 24) for l in lines) and lines[0].lstrip().startswith("30"), lines)
    check(f"시간대 그래프 폭 {w}: 시간축에 0·6·12·18", all(k in lines[4] for k in ("0", "6", "12", "18")), lines[4])
check("시간대 그래프: 값이 0 인 데이터도 그려진다(0 나눔 없음)", cx.slot_chart([0] * 96, 60, 3, "cyan") is not None)
t = cx.slot_chart([0] * 48 + [10] * 48, 60, 4, "cyan"); b2 = body(t, 4)
check("시간대 그래프: 0~12시는 비고 12~24시는 채워진다(칸 경계가 열 경계와 맞음)", all(ch == BLANK for r in b2 for ch in r[:int(len(r) * 0.45)]) and all(r[-1] != BLANK for r in b2[-1:]), b2[-1])
check("시간대 그래프: 24칸(시 단위)도 그려진다", cx.slot_chart([1] * 24, 60, 4, "cyan") is not None)

check("fit_bar: 폭 안에서 비율대로(전부=가득, 절반=절반)", cx.fit_bar(10, 10, 20) == "█" * 20 and cx.fit_bar(5, 10, 20) == "█" * 10 and cell_len(cx.fit_bar(7, 10, 33)) <= 33)
check("fit_bar: 0·음수·폭 0 은 빈 문자열", cx.fit_bar(0, 10, 20) == "" and cx.fit_bar(3, 0, 20) == "" and cx.fit_bar(3, 10, 0) == "")
# --- 5h·7d 겹침 그래프
R7 = R0 + timedelta(days=7)
s7 = [(R0 + timedelta(hours=h), 10 + 60 * h / 168, R7) for h in range(0, 168, 2)]                      # 7d: 7일에 걸쳐 10 → 70%
s5 = []
for k in range(0, 28):                                                                                    # 5h: 약 6시간 간격의 창 28개, 창마다 0 → 40%
    reset = R0 + timedelta(hours=6 * k + 5)
    s5 += [(reset - timedelta(hours=5 - i * 0.5), 4 * (i + 1), reset) for i in range(10)]
for w in (50, 100, 190):
    t = cx.limit_chart_both(s5, s7, w, 6, "#33ccff", now=R7.timestamp() + 1)
    lines = t.plain.split("\n")
    check(f"겹침 그래프 폭 {w}: 높이 6 + 시간축 1줄, 폭 이하, y 눈금 100·50·0", len(lines) == 7 and all(cell_len(l) <= w for l in lines) and lines[0].lstrip().startswith("100") and lines[3].lstrip().startswith("50") and lines[5].lstrip().startswith("0"), (len(lines), [cell_len(l) for l in lines]))
t = cx.limit_chart_both(s5, s7, 100, 6, "#33ccff", now=R7.timestamp() + 1)
styles = {str(sp.style) for sp in t.spans}
check("겹침 그래프: 5h 색(#33ccff)과 7d 선의 밝은 색(tint)이 모두 쓰인다", "#33ccff" in styles and cx.tint("#33ccff") in styles and styles <= {"#33ccff", cx.tint("#33ccff"), "grey50"}, styles)
# 7d 선은 오른쪽으로 갈수록 올라간다: 선 색이 칠해진 칸의 가장 높은 줄이 오른쪽에서 더 위
line_c = cx.tint("#33ccff")
cells = []                                    # (줄, 칸 번호) 중 7d 선 색
spans = sorted(t.spans, key=lambda sp: sp.start)
for sp in spans:
    if str(sp.style) == line_c:
        r = t.plain[:sp.start].count("\n")
        c = sp.start - (t.plain.rfind("\n", 0, sp.start) + 1) - cx.AXIS_W
        for k in range(sp.end - sp.start):
            cells.append((r, c + k))
left = [r for r, c in cells if c < 15]; right = [r for r, c in cells if c > 70]
check("겹침 그래프: 7d 선이 왼쪽(10%)보다 오른쪽(70%)에서 더 위 줄에 있다", left and right and min(right) < min(left), (min(left) if left else None, min(right) if right else None))
check("겹침 그래프: 7d 가 없으면 5h 만(limit_chart), 5h 가 없으면 7d 만, 둘 다 없으면 None", cx.limit_chart_both(s5, [], 80, 5, "cyan", now=R7.timestamp()).plain.count("\n") == 5 and cx.limit_chart_both([], s7, 80, 3, "cyan", now=R7.timestamp()) is not None and cx.limit_chart_both([], [], 80, 5, "cyan") is None)
check("tint: 흰색 쪽으로 밝아진다", cx.tint("#000000", 0.5) == "#808080" and cx.tint("#ffffff") == "#ffffff")
finish("ctxchart")
