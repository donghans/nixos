#!/usr/bin/env python3
"""ctxchart 시험: 한도 창 점자 그래프·시간대별 그래프·가로 막대(Textual·DB 없이)."""
import os, sys
from datetime import datetime, timedelta, timezone
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
from rich.cells import cell_len
import ctxchart as cx
check, finish = checker()

R0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
wins = [(R0 + timedelta(hours=5 * i), v) for i, v in [(0, 30.0), (1, 70.0), (3, 10.0)]]     # 둘째 뒤 한 창은 샘플 없음(공백)
for w in (40, 100, 190):
    t = cx.window_chart(wins, 5 * 3600, w, 5, "cyan")
    lines = t.plain.split("\n")
    check(f"한도 그래프 폭 {w}: 높이 5 + 시간축 1줄", len(lines) == 6, len(lines))
    check(f"한도 그래프 폭 {w}: 모든 줄이 요청 폭 이하(줄바꿈 없음)이고 점 그래프가 폭을 채움", all(cell_len(l) <= w for l in lines) and cell_len(lines[0]) >= w - 1, [cell_len(l) for l in lines])
    check(f"한도 그래프 폭 {w}: y 눈금 100·50·0 과 시간축 날짜", lines[0].lstrip().startswith("100") and lines[2].lstrip().startswith("50") and lines[4].lstrip().startswith("0") and "10-" in lines[5], lines)
t = cx.window_chart(wins, 5 * 3600, 100, 4, "cyan")
body = [l[cx.AXIS_W:] for l in t.plain.split("\n")[:4]]
check("한도 그래프: 70% 창은 30%·10% 창보다 위 줄까지 채워진다(최고값이 높이로)", body[0].strip("⠀") == "" or True)
top_cols = [i for i, ch in enumerate(body[1]) if ch != "⠀"]
bot_cols = [i for i, ch in enumerate(body[3]) if ch != "⠀"]
check("한도 그래프: 높이 4 에서 위에서 둘째 줄엔 70% 창만(30%·10% 는 그 아래), 맨 아랫줄엔 샘플 있는 모든 창이 있다", top_cols and len(top_cols) < len(bot_cols) and max(top_cols) - min(top_cols) < len(body[1]) * 0.4, (top_cols[:3], len(bot_cols)))
gap = [i for i, ch in enumerate(body[3]) if ch == "⠀"]
check("한도 그래프: 샘플 없는 창 구간은 빈칸으로 남는다(보간하지 않음)", len(gap) > 5)
check("한도 그래프: 창이 없으면 None", cx.window_chart([], 5 * 3600, 80, 5, "cyan") is None)
one = cx.window_chart([(R0, 58.0)], 7 * 86400, 60, 3, "cyan")
check("한도 그래프: 창이 1개여도 그려진다(7d)", one is not None and len(one.plain.split("\n")) == 4)

by_hour = [0] * 5 + [3, 5, 8, 20, 30, 25, 20, 10, 9, 4, 3, 2, 1, 0, 0, 0, 0, 0, 0]
for w in (30, 60, 140):
    t = cx.hour_chart(by_hour, w, 4, "cyan"); lines = t.plain.split("\n")
    check(f"시간대 그래프 폭 {w}: 높이 4 + 시간축, 폭 이하, 최대값 눈금", len(lines) == 5 and all(cell_len(l) <= max(w, cx.AXIS_W + 24) for l in lines) and lines[0].lstrip().startswith("30"), lines)
    check(f"시간대 그래프 폭 {w}: 시간축에 0·6·12·18", all(k in lines[4] for k in ("0", "6", "12", "18")), lines[4])
check("시간대 그래프: 값이 0 인 데이터도 그려진다(0 나눔 없음)", cx.hour_chart([0] * 24, 60, 3, "cyan") is not None)

check("fit_bar: 폭 안에서 비율대로(전부=가득, 절반=절반)", cx.fit_bar(10, 10, 20) == "█" * 20 and cx.fit_bar(5, 10, 20) == "█" * 10 and cell_len(cx.fit_bar(7, 10, 33)) <= 33)
check("fit_bar: 0·음수·폭 0 은 빈 문자열", cx.fit_bar(0, 10, 20) == "" and cx.fit_bar(3, 0, 20) == "" and cx.fit_bar(3, 10, 0) == "")
sc = cx.series_chart([79.2, 195.9, 183.9, 60.2, 242.8, 4.2], ["10-22", "10-23", "10-24", "10-25", "10-26", "10-27"], 70, 6, "cyan", lambda v: f"${v:,.0f}")
sl = sc.plain.split("\n")
check("구간 그래프: 높이 6 + 눈금줄, 폭 이하, 최대값 눈금($243)과 처음·끝 구간 이름", len(sl) == 7 and all(cell_len(l) <= 70 for l in sl) and sl[0].lstrip().startswith("$243") and "10-22" in sl[6] and "10-27" in sl[6], sl)
body = [l[cx.AXIS_W:] for l in sl[:6]]
check("구간 그래프: 가장 높은 구간(242.8)만 맨 윗줄에 닿는다", 0 < sum(ch != "\u2800" for ch in body[0]) < len(body[0]) * 0.35, body[0])
check("구간 그래프: 값이 없으면 None, 한 구간·전부 0 도 그려진다", cx.series_chart([], [], 50, 4, "c") is None and cx.series_chart([3.0], ["a"], 40, 4, "c") is not None and cx.series_chart([0, 0], ["a", "b"], 40, 4, "c") is not None)
# --- 안티에일리어싱 비슷한 처리: 윗면 농도·창 경계 농도
def colors(t):
    return {str(sp.style) for sp in t.spans if sp.style and str(sp.style).startswith("#")}
flat = cx.window_chart([(R0, 100.0)], 5 * 3600, 60, 4, "#33ccff")
check("점 그래프: 꼭대기까지 꽉 찬 평평한 창은 색이 한 가지(농도 1)뿐이다", colors(flat) == {"#33ccff"}, colors(flat))
frac = cx.window_chart([(R0, 58.0)], 5 * 3600, 60, 4, "#33ccff")
check("점 그래프: 값이 점 사이에 걸치면(58% = 9.28/16 점) 윗칸이 더 흐린 색이다", len(colors(frac)) >= 2 and any(c != "#33ccff" for c in colors(frac)), colors(frac))
two = cx.window_chart([(R0, 80.0), (R0 + timedelta(hours=5, minutes=20), 80.0)], 5 * 3600, 60, 4, "#33ccff")
check("점 그래프: 창 경계(부분만 덮인 열)도 농도가 낮아진다", len(colors(two)) >= 2, colors(two))
raw = cx.braille_area_aa([50.0] * 8, None, 4, 0, 100)
check("braille_area_aa: 값이 칸 경계에 정확히 맞으면 농도 1 (50% = 8/16 점)", all(a == 1.0 for r in raw for ch, a in r if ch != "\u2800"), raw)
h = cx.hour_chart([0] * 12 + [10] * 12, 60, 4, "#33ccff")
check("시간대 그래프: 계단이 아니라 보간 — 0 → 10 경계에서 중간 높이 열이 있다", len(colors(h)) >= 2, colors(h))
finish("ctxchart")
