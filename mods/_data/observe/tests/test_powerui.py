#!/usr/bin/env python3
"""powergraph/powerdata/powerview 순수 시험 + powerui 화면 시험(textual 이 있을 때만)."""
import asyncio, json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="powerui-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state"); os.environ["POWERUI_NETDATA"] = "http://127.0.0.1:1"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import powergraph as pg, powerdata as pd
from harness import checker
check, finish = checker()

# --- 그래프 계산
check("bucketize 평균·빈 구간 None", pg.bucketize([(1, 2), (2, 4), (9, 6)], 0, 10, 4) == [3.0, None, None, 6.0], str(pg.bucketize([(1, 2), (2, 4), (9, 6)], 0, 10, 4)))
check("bucketize 범위 밖·None 무시", pg.bucketize([(-1, 5), (10, 5), (3, None)], 0, 10, 2) == [None, None])
check("bucket_labels 최빈값", pg.bucket_labels([(1, "a"), (2, "a"), (3, "b"), (7, "b")], 0, 10, 2) == ["a", "b"])
rows = pg.braille_area([0, 8, 8, 0], 2, 0, 8)
check("braille_area 높이·너비", len(rows) == 2 and all(len(r) == 2 for r in rows), str(rows))
check("braille_area 꽉 찬 열은 반쪽 ⢸(오른쪽 열)/⡇(왼쪽 열)", rows[1][0] == "⢸" and rows[1][1] == "⡇", str(rows))
check("braille_area None/하한 이하는 빈칸", pg.braille_area([None, 0], 1, 0, 8) == ["⠀"])
check("braille_area 상한 이상은 꼭대기까지", pg.braille_area([99, 99], 1, 0, 8) == ["⣿"])
check("fill_gaps 선형 보간", pg.fill_gaps([0, None, None, 3], 30, 120) == [0, 1.0, 2.0, 3], str(pg.fill_gaps([0, None, None, 3], 30, 120)))
check("fill_gaps 큰 틈(수집 끊김)은 비워 둔다", pg.fill_gaps([0, None, None, None, 4], 60, 120) == [0, None, None, None, 4])
check("fill_gaps 가장자리 None 유지", pg.fill_gaps([None, 1, None], 30, 120) == [None, 1, None])
check("hbar 길이 고정", all(len(pg.hbar(f, 10)) == 10 for f in (0, 0.33, 1, 5, float("nan"))))
check("fmt_dur", pg.fmt_dur(9.2) == "9시간 12분" and pg.fmt_dur(0.75) == "45분" and pg.fmt_dur(None) == "-" and pg.fmt_dur(-1) == "-")
check("nice_range 값 없으면 (0,1)", pg.nice_range([None]) == (0.0, 1.0))

# --- 데이터: 합성 표본으로 증분 읽기/집계/추정
now = time.time()
def raw(t, psys=4.0, batt=5.0, q=3000000, status="Discharging", ac=0, psr=True, state="low", proc=None, pct="50"):
    return {"t": t, "pw": {"psys_w": psys, "batt_w": batt, "pkg_w": 1.5, "q_uah": q, "v_uv": 15000000, "full_uah": 3600000, "status": status, "ac": ac, "batt_pct": pct},
            "cs": {"pc8": 10.0, "pc10": 20.0}, "state": state, "proc": proc or [], "irq": {"cpu_busy_pct": 2.0},
            "dev": {"vt": "tty1", "lid": "open", "bl": "9600", "boot": "abc", "wifi": {"ps": "off"}, "psr": {"mode": "PSR1 enabled" if psr else "disabled", "sink": "active"}}}
d = os.path.join(TMP, "samples"); os.makedirs(d)
fn = os.path.join(d, time.strftime("samples-%Y%m%d.jsonl"))
with open(fn, "w") as f:
    for i in range(80):                                   # 40분, 30초 간격, 방전: 1 mAh/30초 단위가 아니라 큼직하게 감소
        f.write(json.dumps(raw(now - 2400 + i * 30, q=3000000 - i * 1000, psr=i >= 40, state="low" if i % 2 else "high",
                               proc=[{"comm": "nix-daemon", "cpu": 5, "wake": 1}] if i == 5 else [])) + "\n")
    f.write(json.dumps(raw(now + 4 * 3600)) + "\n")       # 가짜 미래(RTC 글리치) → 버려져야 함
    f.write("깨진 줄\n")
st = pd.Store(d)
n = st.refresh(now)
check("Store: 읽은 수 80(미래·깨진 줄 제외)", n == 80 and len(st.recs) == 80, str(n))
check("Store: 증분 — 두 번째 읽기는 0", st.refresh(now) == 0)
with open(fn, "a") as f:
    f.write(json.dumps(raw(now - 1, q=3000000 - 80 * 1000)) + "\n")
    f.write('{"t": 1')                                    # 쓰는 중인 마지막 줄(개행 없음)
check("Store: 새 줄만 읽고 미완성 줄은 보류", st.refresh(now) == 1 and len(st.recs) == 81)
with open(fn, "a") as f:
    f.write(', "pw": {}}\n')
check("Store: 보류했던 줄은 완성되면 읽는다(시각 범위 밖이면 버림)", st.refresh(now) == 0)
rc = [r for r in st.recs if r["psr"]]
check("compact: PSR 켬/끔 구분", 0 < len(rc) < len(st.recs) and st.recs[0]["psr"] is False)
check("compact: nix 가 보인 표본은 clean=False", sum(1 for r in st.recs if not r["clean"]) == 1)
w, hrs = pd.coulomb(st.recs)
# 1000 µAh/30초 × 15 V = 15 mWh/30초 = 1.8 W
check("coulomb: 누적 계량 평균 전력(1.8 W)", w is not None and abs(w - 1.8) < 0.05 and abs(hrs - 80 * 30 / 3600) < 0.02, f"{w} {hrs}")
est = pd.battery_estimate(st.recs)
check("battery_estimate: 잔량 Wh·만충 Wh", abs(est["remain_wh"] - (3000000 - 80000) * 15 / 1e6) < 0.1 and abs(est["full_wh"] - 54.0) < 0.1, str(est))
check("battery_estimate: 최근 30분 기준 남은 시간 = 잔량/전력", est["recent_h"] is None or abs(est["recent_h"] - est["remain_wh"] / est["recent_w"]) < 1e-6)
tbl = {r["group"]: r for r in pd.group_table(st.recs, "psr")}
check("group_table: PSR 켬/끔 두 그룹, 표본 합 81", set(tbl) == {"PSR 켬", "PSR 끔"} and sum(r["n"] for r in tbl.values()) == 81, str(tbl.keys()))
check("group_table(clean): nix 표본 제외", sum(r["n"] for r in pd.group_table(st.recs, "psr", clean=True)) == 80)
ch = pd.battery_estimate([dict(st.recs[-1], status="Charging", ac=True)])
check("충전 중이면 charging=True", ch["charging"] is True)
check("Netdata 읽기 실패는 None(예외 아님)", pd.netdata_series("system.cpu", 60, 10, timeout=0.5) is None)

# --- 화면 조각(rich)
try:
    import powerview as pv
    from rich.console import Console
    have_rich = True
except ImportError:
    have_rich = False
if have_rich:
    now_t = pv.now_text(st.recs, est, 100, now)
    s = now_t.plain
    check("now_text: 전원·PSR·남은 시간 줄", "방전 중" in s and "PSR1 enabled" in s and "남은 시간 추정" in s and "최근 30분 평균" in s, s)
    check("now_text: 빈 데이터 안내", "observectl on" in pv.now_text([], None, 100).plain)
    t0, t1 = pv.range_bounds("1시간", now)
    recs1 = [r for r in st.recs if t0 <= r["t"] <= t1]
    text, stt = pv.chart(pv.series_points(recs1, "psys"), t0, t1, 100, 8, "W", "cyan", axis=True)
    lines = text.plain.split("\n")
    check("chart: 줄 수 = 높이(시간축 포함)·통계 있음", len(lines) == 8 and stt is not None and stt[2] >= stt[0], str(len(lines)))
    check("chart: 줄 너비가 요청 폭 이내", all(len(l) <= 100 for l in lines), str(max(len(l) for l in lines)))
    text, _ = pv.chart(pv.series_points(recs1, "psys"), t0, t1, 60, 6, "W", "cyan")
    check("chart: 점자 면적 그래프(블록 문자 없음)", any("\u2800" < ch <= "\u28ff" for ch in text.plain) and not any(ch in text.plain for ch in "▁▂▃▄▅▆▇█"))
    check("chart: 높이 5 이상이면 가운데 눈금", len([l for l in text.plain.split("\n") if l.strip(" ")[:1].isdigit()]) == 3, text.plain)
    check("chart: fmt=None 은 값 크기에 맞춰 자릿수 자동", "26416" in pv.chart([(1, 26415.6)], 0, 10, 40, 4, "KiB/s", lo=0.0, hi=26415.6, fmt=None)[0].plain and "6.90" in pv.chart([(1, 6.9)], 0, 10, 40, 4, "x", lo=0.0, hi=6.9, fmt=None)[0].plain)
    check("stats_str", "지금" in pv.stats_str((1.0, 2.0, 3.0, 2.5)) and pv.stats_str(None) == "데이터 없음")
    from rich.cells import cell_len
    bt = pv.bands_text(st.recs, t0, t1, 100)
    check("bands_text: 한글 라벨 줄도 칸 폭이 너비 이내", all(cell_len(l) <= 100 for l in bt.plain.split("\n")), str(max(cell_len(l) for l in bt.plain.split("\n"))))
    check("bands_text: 상태·PSR·전원·범례", "PSR" in bt.plain and "전원" in bt.plain and "초록 low" in bt.plain)
    check("SERIES: 그래프 4개(배터리·psys·패키지·잔량)", [x[1] for x in pv.SERIES] == ["batt", "psys", "pkg", "pct"])
    check("chart: 작은 높이·빈 데이터에서도 예외 없음", len(pv.chart([], t0, t1, 30, 3)[0].plain) > 0)

# --- Textual 화면
try:
    import textual  # noqa
    have_textual = have_rich
except ImportError:
    have_textual = False
if not have_textual:
    print("  (textual 없음: 화면 시험은 건너뜀 — PYTHON=<textual 이 있는 python> 으로 실행)")
else:
    import powerui

    async def drive():
        app = powerui.PowerUI(interval=2.0, store=pd.Store(d))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            status = str(app.query_one("#status").render())
            check("화면: 상태줄에 표본 수", "표본" in status and "마지막 갱신" in status, status)
            check("화면: 지금 탭은 박스 3개(현황 + 그래프 2)", len(app.query("#now .box")) == 3, str(len(app.query("#now .box"))))
            check("화면: 지금 탭이 기본", app.query_one("#tabs").active == "now")
            for key, tab in (("2", "series"), ("3", "compare"), ("4", "netdata"), ("1", "now")):
                await pilot.press(key); await pilot.pause(0.2)
                check(f"화면: {key} 키 → {tab} 탭", app.query_one("#tabs").active == tab)
            await pilot.press("3"); await pilot.pause(0.3)
            tb = app.query_one("#cmptable")
            check("화면: 비교 표도 박스 하나(제목에 그룹 기준)", "그룹별 평균" in app.query_one("#cmpbox").border_title)
            check("화면: 비교 표에 행(state 기준)", tb.row_count >= 1, str(tb.row_count))
            await pilot.press("g"); await pilot.pause(0.2)
            check("화면: g 로 그룹 기준 PSR 로 전환(행 2개)", tb.row_count == 2, str(tb.row_count))
            await pilot.press("c"); await pilot.pause(0.2)
            check("화면: c 로 깨끗한 표본 토글", app.clean is True)
            await pilot.press("r"); await pilot.pause(0.3)
            check("화면: r 로 구간 전환", app.range_i == 1)
            await pilot.press("2"); await pilot.pause(0.3)
            check("화면: 시계열은 그래프마다 박스(4개 + 띠 박스)", len(app.query("#series .box")) == 5 and app.query_one("#ser0").border_title == "배터리 소비 (V×I, 방전 중)", str(len(app.query("#series .box"))))
            check("화면: 박스 아래 테두리에 통계", "평균" in (app.query_one("#ser1").border_subtitle or ""), str(app.query_one("#ser1").border_subtitle))
            await pilot.press("question_mark"); await pilot.pause(0.3)
            check("화면: ? 로 도움말(키 목록)", type(app.screen).__name__ == "HelpScreen")
            await pilot.press("escape"); await pilot.pause(0.2)
            await pilot.press("4"); await pilot.pause(0.8)
            check("화면: Netdata 꺼져도 안내만(예외 없음)", app.query_one("#tabs").active == "netdata")
            await pilot.press("q")
    asyncio.run(drive())
    async def small():
        app = powerui.PowerUI(interval=5.0, store=pd.Store(d))
        async with app.run_test(size=(50, 14)) as pilot:
            await pilot.pause(0.4)
            for key in ("2", "3", "4", "1"):
                await pilot.press(key); await pilot.pause(0.15)
            check("화면: 작은 터미널(50×14)에서도 예외 없음", True)
    asyncio.run(small())
finish("powerui")
