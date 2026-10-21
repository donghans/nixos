#!/usr/bin/env python3
"""usagegraph(그래프 계산)·usagedata(표본 압축·배터리 추정)·usagechart(차트 조각) 순수 시험."""
import json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="usagegraph-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state");
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import usagegraph as pg, usagedata as pd, observe_core as core
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
check("hold_labels: 표본 없는 칸을 직전 값으로", pg.hold_labels(["a", None, "b", None, None, "b"], 25, 120) == ["a", "a", "b", "b", "b", "b"])
check("hold_labels: 큰 틈(수집 끊김)·가장자리는 비움", pg.hold_labels(["a", None, None, None, "b", None], 60, 120) == ["a", None, None, None, "b", None])
check("fill_gaps 선형 보간", pg.fill_gaps([0, None, None, 3], 30, 120) == [0, 1.0, 2.0, 3], str(pg.fill_gaps([0, None, None, 3], 30, 120)))
check("fill_gaps 큰 틈(수집 끊김)은 비워 둔다", pg.fill_gaps([0, None, None, None, 4], 60, 120) == [0, None, None, None, 4])
check("fill_gaps 가장자리 None 유지", pg.fill_gaps([None, 1, None], 30, 120) == [None, 1, None])
check("hbar 길이 고정", all(len(pg.hbar(f, 10)) == 10 for f in (0, 0.33, 1, 5, float("nan"))))
check("fmt_dur", pg.fmt_dur(9.2) == "9시간 12분" and pg.fmt_dur(0.75) == "45분" and pg.fmt_dur(None) == "-" and pg.fmt_dur(-1) == "-")
check("nice_range 값 없으면 (0,1)", pg.nice_range([None]) == (0.0, 1.0))

# --- 데이터: 합성 표본으로 증분 읽기/집계/추정
now = time.time()
def raw(t, psys=4.0, batt=5.0, q=3000000, status="Discharging", ac=0, psr=True, state="low", proc=None, pct="50"):
    return {"v": 3, "t": t, "pw": {"psys_w": psys, "batt_vi_w": batt, "pkg_w": 1.5, "q_uah": q, "v_uv": 15000000, "full_uah": 3600000, "status": status, "ac": ac, "batt_pct": pct},
            "cs": {"pc8": 10.0, "pc10": 20.0}, "state": state, "proc": proc or [], "irq": {"cpu_all_pct": 2.0, "ctxt_s": 2400},
            "dev": {"vt": "tty1", "lid": "open", "bl": "9600", "boot": "abc", "wifi": {"ps": "off"}, "psr": {"mode": "PSR1 enabled" if psr else "disabled", "sink": "active"}}}
LEGACY = {"t": now - 3000, "dt": 30, "pw": {"psys_w": 6.0, "batt_w": 7.0, "pkg_w": 2.0, "q_uah": 3100000, "v_uv": 15000000, "status": "Discharging", "ac": 0, "batt_pct": "60"},
          "cs": {"pc8": 5.0, "pc10": 0.0}, "state": "high", "irq": {"cpu_busy_pct": 9.0, "ctxt_s": 3000}, "proc": [{"comm": "x", "exe": "x", "n": 1, "cpu": 4.0, "wake": 50.0}], "dev": {}}
recs_raw = [LEGACY]
for i in range(80):                                   # 40분, 30초 간격, 방전
    recs_raw.append(raw(now - 2400 + i * 30, q=3000000 - i * 1000, psr=i >= 40, state="low" if i % 2 else "high",
                        proc=[{"comm": "nix-daemon", "cpu_core_pct": 5, "ctxsw_vol_s": 1}] if i == 5 else []))
class _St:
    pass
st = _St()
st.recs = sorted((pd.compact(core.normalize_sample(r)) for r in recs_raw), key=lambda r: r["t"])
rc = [r for r in st.recs if r["psr"]]
leg = [r for r in st.recs if r["legacy"]]
check("옛 형식 표본: 새 이름으로 읽혀 값 유지(batt_vi 7.0, cpu_all 9.0, ctxsw_all 3000), 프로세스 전환 합(ctxsw_top)은 메인 스레드만이라 None·legacy 표시", len(leg) == 1 and leg[0]["batt_vi"] == 7.0 and leg[0]["cpu_all"] == 9.0 and leg[0]["ctxsw_top"] is None and leg[0]["ctxsw_all"] == 3000, str(leg))
check("새 형식 표본은 legacy 아님", sum(1 for r in st.recs if not r["legacy"]) == 80)
check("compact: PSR 켬/끔 구분", 0 < len(rc) < len(st.recs) and st.recs[0]["psr"] is False)
check("compact: nix 가 보인 표본은 clean=False", sum(1 for r in st.recs if not r["clean"]) == 1)
w, hrs = pd.coulomb(st.recs)
# 1000 µAh/30초 × 15 V = 15 mWh/30초 = 1.8 W
check("coulomb: 누적 계량 평균 전력(1.8 W)", w is not None and abs(w - 1.8) < 0.05 and abs(hrs - 79 * 30 / 3600) < 0.05, f"{w} {hrs}")
est = pd.battery_estimate(st.recs)
check("battery_estimate: 잔량 Wh·만충 Wh", abs(est["remain_wh"] - (3000000 - 79000) * 15 / 1e6) < 0.1 and abs(est["full_wh"] - 54.0) < 0.1, str(est))
check("battery_estimate: 최근 30분 기준 남은 시간 = 잔량/전력", est["recent_h"] is None or abs(est["recent_h"] - est["remain_wh"] / est["recent_w"]) < 1e-6)
ch = pd.battery_estimate([dict(st.recs[-1], status="Charging", ac=True)])
check("충전 중이면 charging=True", ch["charging"] is True)
# --- 화면 조각(rich)
try:
    import usagechart as pv
    from rich.console import Console
    have_rich = True
except ImportError:
    have_rich = False
if have_rich:
    t0, t1 = now - 3600, now
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
    # 칸 폭(25초)이 표본 간격(30초)보다 짧은 넓은 화면에서도 띠가 끊기지 않아야 한다(회귀: 일정 간격으로 빈 칸이 생겼음)
    t0n, t1n = now - 3600, now
    dense = [dict(st.recs[0], t=t0n + i * 30, state="low", ac=False, psr=True) for i in range(120)]
    bt2 = pv.bands_text(dense, t0n, t1n, 150)
    first_band = bt2.plain.split("\n")[0]
    raw_lab = pg.bucket_labels([(r["t"], "x") for r in dense], t0n, t1n, 142)
    check("(대조) 보간 없이는 칸 폭 < 표본 간격에서 빈 칸이 실제로 생긴다", None in raw_lab[: raw_lab.index(None, 0) + 1] and sum(1 for k in raw_lab[:-3] if k is None) > 5)
    check("bands_text: 칸 폭 < 표본 간격이어도 띠에 빈 칸(░) 없음(끝의 아직 표본 없는 칸 제외)", "░" not in first_band.rstrip("░"), first_band)
    check("bands_text: 상태·PSR·전원·범례", "PSR" in bt.plain and "전원" in bt.plain and "초록 low=깊은 절전" in bt.plain)
    check("chart: 작은 높이·빈 데이터에서도 예외 없음", len(pv.chart([], t0, t1, 30, 3)[0].plain) > 0)
finish("usagegraph")
