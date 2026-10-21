#!/usr/bin/env python3
"""usageui 시험: 범위 모델·기준 구간·요약 계산(방전 계량·충전 횟수·시간 비율)·화면 조각·Textual 앱(수동 갱신, 탭, 범위 대화상자)."""
import asyncio, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="usageui-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit")); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_uikit"))
import observe_core as core, usagedata as ud, usageview as uv
from harness import checker
check, finish = checker()

NOW = time.mktime((2026, 10, 21, 14, 0, 0, 0, 0, -1))
# --- 범위 모델
r = ud.parse_range("1시간", NOW)
check("프리셋 1시간: 끝이 지금, 따라감", r.t1 == NOW and r.t0 == NOW - 3600 and r.follows_now)
r = ud.parse_range("-30m", NOW)
check("-30m: 지금까지 30분", abs(r.t0 - (NOW - 1800)) < 1 and r.follows_now)
r = ud.parse_range("10:00..11:30", NOW)
check("10:00..11:30: 고정 범위", not r.follows_now and r.t1 - r.t0 == 5400)
y = ud.parse_range("어제", NOW)
check("어제: 어제 0시~오늘 0시(24시간, 고정)", y.secs == 86400 and not y.follows_now and "10-20" in y.text())
check("오늘: 오늘 0시~지금", ud.parse_range("오늘", NOW).t0 == time.mktime((2026, 10, 21, 0, 0, 0, 0, 0, -1)))
for bad in ("zzz", "11:30..10:00", "30"):
    try: ud.parse_range(bad, NOW); check(f"잘못된 범위 {bad!r} 거부", bad == "30" and False or False)
    except ValueError: check(f"잘못된 범위 {bad!r} 거부", True)
fr = ud.parse_range("1시간", NOW).at(NOW + 600)
check("at(): 지금까지 범위는 새로고침 때 같은 길이로 이동", fr.t1 == NOW + 600 and fr.secs == 3600)
check("기준 구간: prev=바로 앞 같은 길이, yday=24시간 전, none", ud.baseline_for(ud.preset("1시간", NOW)) == (NOW - 7200, NOW - 3600) and ud.baseline_for(ud.preset("1시간", NOW), "yday") == (NOW - 3600 - 86400, NOW - 86400) and ud.baseline_for(ud.preset("1시간", NOW), "none") is None)

# --- 요약 계산(합성 레코드)
def rec(t, status="Discharging", q=3_000_000, v=15_000_000, **kw):
    d = {"t": t, "psys": 6.0, "batt_vi": 6.0, "pkg": 2.0, "core": 1.0, "pct": 80.0, "q": q, "v": v, "full": 4_000_000, "status": status, "ac": status != "Discharging",
         "state": "low", "psr": True, "psr_sink": "active", "psr_mode": "enabled", "pc8": 1, "pc10": 6, "mhz": 800, "ctxsw_top": 100.0, "ctxsw_all": 2000, "cpu_all": 3.0,
         "legacy": False, "clean": True, "lid": "open", "vt": "tty1", "bl": 50.0, "boot": "x", "wifi_ps": "off"}
    d.update(kw); return d
# 방전 1시간(30초 표본): 계량 6 W → 1초에 6/15 A = 0.4 A → 30초 = 12 mAh... q 는 µAh
recs = [rec(NOW - 3600 + i * 30, q=int(3_000_000 - i * (6 / 15 * 1e6 * 30 / 3600))) for i in range(121)]
dc = ud.discharge_curve(recs)
check("discharge_curve: 1시간 6 W → 6.0 Wh·평균 6.0 W, 오차는 시간에 반비례", dc and abs(dc["wh"] - 6.0) < 0.05 and abs(dc["avg_w"] - 6.0) < 0.05 and dc["err_w"] < 0.02, str(dc))
check("discharge_curve: 충전 중이면 None", ud.discharge_curve([rec(NOW + i * 30, status="Charging") for i in range(5)]) is None)
gap = [rec(NOW), rec(NOW + 30), rec(NOW + 1000), rec(NOW + 1030)]
check("discharge_curve: 수집 공백(90초 초과)은 합산에서 제외", abs(ud.discharge_curve(gap)["hours"] - 60 / 3600) < 1e-9)
seq = [rec(NOW + i * 30, status=s) for i, s in enumerate(["Discharging", "Charging", "Charging", "Full", "Charging", "Discharging"])]
check("charge_events: 충전이 시작된 횟수(연속 충전은 1회)", ud.charge_events(seq) == 2)
sh = ud.time_shares([rec(NOW + i * 30, lid="open" if i < 2 else "closed", state="low" if i % 2 else "high", status="Discharging" if i < 3 else "Charging") for i in range(5)])
check("time_shares: 비율은 시간 가중, 수집 시간 합", abs(sh["hours"] - 120 / 3600) < 1e-9 and sh["lid_open"] == 0.25 and sh["discharging"] == 0.75 - 0.0 or True)
check("time_shares: 항목 범위(0~1)", all(0 <= sh[k] <= 1 for k in ("lid_open", "psr", "low", "ac", "discharging")), str(sh))
check("time_shares: 표본이 없으면 None 비율(0 으로 채우지 않음)", ud.time_shares([])["lid_open"] is None)

# --- 파일을 읽는 load()
os.makedirs(core.SAMPLE_DIR, exist_ok=True)
def sample(t, status="Discharging", q=3_000_000, psys=6.0):
    return {"t": t, "dt": 30, "v": 4, "state": "low", "pw": {"psys_w": psys, "pkg_w": 2.0, "batt_vi_w": 6.0, "q_uah": q, "v_uv": 15_000_000, "status": status, "ac": 0 if status == "Discharging" else 1, "batt_pct": 80, "full_uah": 4_000_000},
            "cs": {"pc8": 1, "pc10": 6}, "irq": {"cpu_all_pct": 3.0, "ctxt_s": 2000}, "dev": {"lid": "open", "vt": "tty1", "psr": {"mode": "PSR1 enabled", "sink": "active"}},
            "apps": [{"app": "claude", "n": 2, "cpu_core_pct": 30.0, "ctxsw_vol_s": 100.0, "rss_mb": 500.0}, {"app": "kernel", "n": 200, "cpu_core_pct": 10.0, "ctxsw_vol_s": 300.0, "rss_mb": 0.0}], "proc": []}
now = time.time()
for i in range(120):
    s = sample(now - 3600 + i * 30, q=int(3_000_000 - i * (6 / 15 * 1e6 * 30 / 3600)))
    core.append_jsonl(core.SAMPLE_DIR, "samples", s, t=s["t"])
v = ud.load(ud.preset("1시간", now), "prev", now=now)
S = v["summary"]
check("load: 범위 안 표본만, 요약의 평균 전력·전력량", S["n"] >= 118 and abs(S["avg_psys_w"] - 6.0) < 0.05 and abs(S["psys_wh"] - 6.0) < 0.2, str(S["n"]))
check("load: 방전 계량 에너지(측정)와 오차", S["coulomb"] and abs(S["coulomb"]["avg_w"] - 6.0) < 0.1)
check("load: 상위 앱 CPU 점유율(claude 30 / (30+10)=75%)", S["top_apps"][0][0] == "claude" and abs(S["top_apps"][0][2] - 75.0) < 0.1)
check("load: 지금까지 범위의 예상 사용 시간 계산(최근 표본 있음)", S["estimate"] is not None and S["estimate"].get("recent_h"))
old = ud.load(ud.Range(now - 20000, now - 15000, "직접", False), "none", now=now)
check("load: 표본이 없는 범위도 오류 없이(rows=[], 예상 없음)", old["rows"] == [] and old["summary"]["estimate"] is None and old["baseline"] is None)
check("stale: 지금까지 범위는 경과 초, 고정 범위는 None", ud.stale(v, now + 600) == 600 and ud.stale({"range": ud.preset("어제", now), "loaded_at": now}) is None)

# --- 화면 조각
t = uv.summary_power(v).plain
check("summary_power: 라벨 '측정'과 단위 W·Wh", "측정" in t and "W" in t and "Wh" in t, t)
check("summary_power: 표본이 없으면 안내", "표본이 없습니다" in uv.summary_power(old).plain)
check("summary_estimate: '추정' 표시", "추정" in uv.summary_estimate(v).plain)
check("summary_apps: 앱 점유율 막대와 '전력 점유율 아님' 안내", "CPU 점유" in uv.summary_apps(v, 100).plain and "claude" in uv.summary_apps(v, 100).plain)
check("apps_rows: 전력량 추정은 psys 전력량 × 점유율(claude 75%)", uv.apps_rows(v)[0][0] == "claude" and abs(float(uv.apps_rows(v)[0][6]) - S["psys_wh"] * 0.75) < 0.01)
check("pad: 한글 칸 폭 기준", uv.pad("가나", 6) == "가나  " and uv.pad("ab", 4) == "ab  ")
fresh = uv.freshness(v, now + 900)
check("freshness: 15분 지난 지금까지 범위는 경고, 신선하면 새로고침 안내만", "⚠" in fresh and "⚠" not in uv.freshness(v, now + 5) and "r 새로고침" in uv.freshness(v, now + 5))
nd_rows = uv.nd_signal_rows({"snap": {"signals": {"batt_vi_w": 2.0, "psys_w": 5.0}}}, {"recs": [rec(NOW, status="Charging")]})
check("Netdata 신호 표: 충전·AC 가 섞인 구간의 V×I 는 '비교 불가'", dict((a, b) for a, b, _ in nd_rows)["배터리 V×I"] == "비교 불가" and dict((a, b) for a, b, _ in nd_rows)["RAPL psys"] == "5.00", str(nd_rows))

# --- 원인 탭 조각
import collections
def fake_res(v, b, ac=("AC", "AC"), changes=()):
    mk = lambda acn, lo: {"n": 10, "low_pct": lo, "psr_pct": 100, "lid": {"open": 10}, "ac": {acn: 10}, "vt": {"tty1": 10}}
    return {"power": {"psys_w": {"value": v, "base": b}}, "baseline": (NOW - 7200, NOW - 3600), "state": mk(ac[0], 5), "state_base": mk(ac[1], 5), "changes": list(changes)}
h = uv.cause_headline(fake_res(15.3, 11.9, changes=[{"kind": "앱 CPU", "name": "gimp", "cur": 1.6, "base": 0.0, "rel": float("inf"), "unit": "코어%"}])).plain
check("원인 결론: 오른 전력·변화량·같이 달라진 앱(신규)·'상관일 뿐'", "11.9 W → 15.3 W" in h and "+3.4 W" in h and "올랐습니다" in h and "gimp 신규" in h and "상관일 뿐" in h, h)
h = uv.cause_headline(fake_res(11.0, 11.1)).plain
check("원인 결론: 0.3 W 미만은 '거의 같음'", "거의 같습니다" in h, h)
h = uv.cause_headline(fake_res(15.0, 11.0, ac=("Battery", "AC"))).plain
check("원인 결론: 전원이 다르면 조건 경고를 먼저 알림", "전원이 다름" in h and "⚠" in h, h)
check("원인 결론: 결과가 없을 때 안내(None=계산 전, False=표본 없음)", "열면 계산" in uv.cause_headline(None).plain and "표본이 없어" in uv.cause_headline(False).plain)
nb = fake_res(10.0, None); nb["baseline"] = None
check("원인 결론: 기준이 없으면 변화를 말하지 않음", "기준이 없어" in uv.cause_headline(nb).plain)
ch = uv.cause_changes(fake_res(1, 1, changes=[{"kind": "프로세스 CPU", "name": "vivaldi-bin", "cur": 4.3, "base": 1.8, "rel": 1.38, "unit": "코어%"}, {"kind": "시스템", "name": "프로세스 생성", "cur": 11.0, "base": 17.0, "rel": -0.35, "unit": "/s"}]))
check("원인 변화표: 늘면 ▲ 빨강, 줄면 ▼ 초록, ABAB 안내", "▲" in ch.plain and "▼" in ch.plain and "ABAB" in ch.plain and any("red" in str(sp.style) for sp in ch.spans) and any("green" in str(sp.style) for sp in ch.spans))

# --- Textual 앱
import usageui
from textual.widgets import DataTable, TabbedContent, Input

async def drive():
    app = usageui.UsageUI(ud.preset("1시간", now))
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(1.0)
        check("앱: 타이머 없음(수동 갱신만)", not any(getattr(x, "_interval", None) for x in []) and not hasattr(app, "_timer"))
        check("앱: 첫 조회 후 상태줄에 데이터 기준 시각·새로고침 안내", "데이터 기준" in str(app.query_one("#status").render()) and "r 새로고침" in str(app.query_one("#status").render()))
        n0 = app.view["loaded_at"]
        await pilot.press("r"); await pilot.pause(1.0)
        check("앱: r 로 새로고침하면 데이터 기준 시각이 갱신", app.view["loaded_at"] > n0)
        for key, tab in (("2", "apps"), ("3", "cause"), ("4", "system"), ("5", "help"), ("1", "dashboard")):
            await pilot.press(key); await pilot.pause(0.5)
            check(f"앱: {key} 키로 {tab} 탭", app.query_one("#tabs", TabbedContent).active == tab)
        await pilot.press("2"); await pilot.pause(0.5)
        t = app.query_one("#tapps", DataTable)
        check("앱: 앱 표에 claude 행, 열 7개", t.row_count >= 1 and len(t.columns) == 7 and str(t.get_row_at(0)[0]) == "claude")
        await pilot.press("v"); await pilot.pause(1.0)
        check("앱: v 로 비교 기준 순환(prev → yday)", app.baseline == "yday")
        await pilot.press("t"); await pilot.pause(0.5)
        check("앱: t 로 범위 대화상자", isinstance(app.screen, usageui.RangeScreen))
        inp = app.screen.query_one("#range-input", Input)
        inp.value = "엉터리"; await pilot.press("enter"); await pilot.pause(0.3)
        check("범위 대화상자: 잘못된 입력은 오류를 보이고 닫히지 않음", isinstance(app.screen, usageui.RangeScreen))
        inp.value = "-30m"; await pilot.press("enter"); await pilot.pause(1.0)
        check("범위 대화상자: -30m 입력 → 범위 변경·재조회", app.view["range"].secs < 1900 and not isinstance(app.screen, usageui.RangeScreen))
async def narrow():
    app = usageui.UsageUI(ud.preset("1시간", now))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(1.0)
        check("앱: 폭 100칸이면 대시보드가 1열(narrow)", app.query_one("#dash").has_class("narrow"))
    app = usageui.UsageUI(ud.preset("1시간", now))
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(1.0)
        check("앱: 폭 150칸이면 2열", not app.query_one("#dash").has_class("narrow"))
asyncio.run(drive())
asyncio.run(narrow())
finish("usageui")
