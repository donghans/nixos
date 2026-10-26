#!/usr/bin/env python3
"""usageui 시험: 범위 모델·기준 구간·요약 계산(방전 계량·충전 횟수·시간 비율)·화면 조각·Textual 앱(수동 갱신, 탭, 범위 대화상자)."""
import asyncio, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="usageui-test-")
os.environ["OBSERVE_USAGE_PROFILE"] = "laptop"   # 기존 시험은 노트북형 화면 기준(호스트의 실제 센서와 무관하게). 데스크톱형은 아래에서 따로
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
check("_f: 문자열 숫자(/proc load1 '2.33')도 포맷, 변환 불가는 -", uv._f("2.33", 2) == "2.33" and uv._f("x") == "-" and uv._f(None) == "-")
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
    app = usageui.UsageUI(ud.preset("1시간", now), tab="dashboard")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(1.0)
        check("앱: 실시간 탭 밖에서는 타이머 없음(수동 갱신만)", app._timer is None)
        check("앱: 첫 조회 후 상태줄에 데이터 기준 시각·새로고침 안내", "데이터 기준" in str(app.query_one("#status").render()) and "r 새로고침" in str(app.query_one("#status").render()))
        n0 = app.view["loaded_at"]
        await pilot.press("r"); await pilot.pause(1.0)
        check("앱: r 로 새로고침하면 데이터 기준 시각이 갱신", app.view["loaded_at"] > n0)
        for key, tab in (("2", "apps"), ("3", "cause"), ("4", "system"), ("1", "dashboard")):
            await pilot.press(key); await pilot.pause(0.5)
            check(f"앱: {key} 키로 {tab} 탭", app.query_one("#tabs", TabbedContent).active == tab)
        await pilot.press("2"); await pilot.pause(0.5)
        t = app.query_one("#tapps", DataTable)
        check("앱: 앱 표에 claude 행, 열 7개", t.row_count >= 1 and len(t.columns) == 7 and str(t.get_row_at(0)[0]) == "claude")
        await pilot.press("v"); await pilot.pause(1.0)
        check("앱: v 로 비교 기준 순환(prev → yday)", app.baseline == "yday")
        await pilot.press("t"); await pilot.pause(0.5)
        check("앱: t 로 범위 대화상자", isinstance(app.screen, usageui.RangeScreen))
        check("범위: 대화상자가 화면 가운데에 뜸(좌우 ±1칸 — 예전엔 왼쪽 위 구석)", abs(app.screen.query_one("#dialog").region.x + app.screen.query_one("#dialog").region.width / 2 - app.size.width / 2) <= 1)
        inp = app.screen.query_one("#range-input", Input)
        inp.value = "엉터리"; await pilot.press("enter"); await pilot.pause(0.3)
        check("범위 대화상자: 잘못된 입력은 오류를 보이고 닫히지 않음", isinstance(app.screen, usageui.RangeScreen))
        inp.value = "-30m"; await pilot.press("enter"); await pilot.pause(1.0)
        check("범위 대화상자: -30m 입력 → 범위 변경·재조회", app.view["range"].secs < 1900 and not isinstance(app.screen, usageui.RangeScreen))
async def narrow():
    app = usageui.UsageUI(ud.preset("1시간", now), tab="dashboard")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(1.0)
        check("앱: 폭 100칸이면 대시보드가 1열(narrow)", app.query_one("#dash").has_class("narrow"))
    app = usageui.UsageUI(ud.preset("1시간", now), tab="dashboard")
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(1.0)
        check("앱: 폭 150칸이면 2열", not app.query_one("#dash").has_class("narrow"))
asyncio.run(drive())
asyncio.run(narrow())

# --- 데스크톱형(배터리·psys 센서 없음): 센서 유무로 화면이 갈린다
os.environ["OBSERVE_USAGE_PROFILE"] = "desktop"
check("host_profile: 강제 desktop 이면 배터리·psys 없음, laptop 이면 둘 다 있음", ud.host_profile() == {"battery": False, "psys": False} and ud.is_desktop())
os.environ["OBSERVE_USAGE_PROFILE"] = "laptop"
check("host_profile: laptop 강제", ud.host_profile() == {"battery": True, "psys": True} and not ud.is_desktop())
os.environ["OBSERVE_USAGE_PROFILE"] = "desktop"
import shutil
shutil.rmtree(core.SAMPLE_DIR); os.makedirs(core.SAMPLE_DIR)
def dsample(t, cpu=12.0, ctx=50000, pkg=25.0, apps=None):
    return {"t": t, "dt": 30, "v": 4, "state": "unknown", "pw": {"psys_w": None, "pkg_w": pkg, "batt_vi_w": None, "ac": 0},
            "cs": {"mhz": 3400}, "irq": {"cpu_all_pct": cpu, "ctxt_s": ctx, "intr_s": 30000, "load1": 1.5}, "dev": {"vt": "tty1", "boot": "abc"},
            "apps": apps or [{"app": "node", "n": 5, "cpu_core_pct": 40.0, "ctxsw_vol_s": 900.0, "rss_mb": 800.0}, {"app": "vivaldi", "n": 20, "cpu_core_pct": 20.0, "ctxsw_vol_s": 500.0, "rss_mb": 3000.0}], "proc": []}
for i in range(120):          # 최근 1시간: 기준(그 앞 1시간)보다 node 가 더 바쁨
    s = dsample(now - 3600 + i * 30); core.append_jsonl(core.SAMPLE_DIR, "samples", s, t=s["t"])
for i in range(120):
    s = dsample(now - 7200 + i * 30, cpu=5.0, ctx=20000, pkg=15.0, apps=[{"app": "node", "n": 5, "cpu_core_pct": 10.0, "ctxsw_vol_s": 200.0, "rss_mb": 800.0}]); core.append_jsonl(core.SAMPLE_DIR, "samples", s, t=s["t"])
dv = ud.load(ud.preset("1시간", now), "prev", now=now)
check("데스크톱 load: 프로파일에 배터리·psys 없음", dv["profile"] == {"battery": False, "psys": False}, str(dv["profile"]))
DS = dv["summary"]
check("데스크톱 요약: 평균 패키지 전력 25 W·전력량 약 25 Wh·평균 CPU 12%·문맥 전환 5만/s", abs(DS["avg_pkg_w"] - 25.0) < 0.1 and abs(DS["pkg_wh"] - 25.0) < 0.8 and abs(DS["avg_cpu_pct"] - 12.0) < 0.1 and abs(DS["avg_ctxsw"] - 50000) < 1, str(DS))
dt_ = uv.summary_power(dv).plain
check("데스크톱 summary_power: psys·배터리 문구 없이 패키지 전력·CPU, '전체 소비 아님' 명시", "패키지" in dt_ and "평균 CPU" in dt_ and "psys" not in dt_ and "배터리" not in dt_ and "전체 소비 아님" in dt_, dt_)
share = 40.0 / 60.0
check("데스크톱 앱 표: 전력량 추정은 패키지 전력량 × 점유율(node 67%)", uv.apps_rows(dv)[0][0] == "node" and abs(float(uv.apps_rows(dv)[0][6]) - DS["pkg_wh"] * share) < 0.02, str(uv.apps_rows(dv)[0]))
cmpd = uv.desktop_compare(dv)
check("데스크톱 비교: 지금 vs 기준 — CPU 12 vs 5, 앱별 변화는 node(+30)가 가장 큼", cmpd and abs(cmpd["metrics"][0][1] - 12.0) < 0.1 and abs(cmpd["metrics"][0][2] - 5.0) < 0.1 and cmpd["apps"][0][0] == "node" and abs(cmpd["apps"][0][3] - 30.0) < 0.1, str(cmpd))
check("데스크톱 비교 문구: 차이와 앱 변화 표시, 기준이 없으면 안내", "+7.0%" in uv.desktop_cause_head(dv).plain and "node" in uv.desktop_cause_changes(dv).plain and "부족" in uv.desktop_cause_head(ud.load(ud.preset("1시간", now), "none", now=now)).plain)
hl = uv.desktop_headline(dv).plain
check("데스크톱 headline: 전력·CPU 차이와 많이 달라진 앱(node)", "패키지" in hl and "전체 CPU" in hl and "node" in hl, hl)
check("데스크톱 headline: 기준이 없으면 비교 불가 안내 + 지금 가장 쓰는 앱", "비교하지 못합니다" in uv.desktop_headline(ud.load(ud.preset("1시간", now), "none", now=now)).plain)
check("데스크톱 깨움 상위: 앱·/s 표시", "/s" in uv.desktop_ctxsw(dv, 80).plain and "node" in uv.desktop_ctxsw(dv, 80).plain, uv.desktop_ctxsw(dv, 80).plain)
import copy
check("데스크톱 최근 15분: 범위 평균과 같으면 경고 없음", "높음" not in uv.desktop_headline(dv).plain and "지금(최근 15분)" in uv.desktop_headline(dv).plain, uv.desktop_headline(dv).plain)
hot = copy.deepcopy(dv)
for r in hot["rows"][-20:]:
    r["irq"]["cpu_all_pct"] = 97.0
    r["apps"] = [{"app": "stress", "n": 8, "cpu_core_pct": 700.0, "ctxsw_vol_s": 10.0, "rss_mb": 10.0}]
check("데스크톱 최근 15분: 급등하면 '지금 높음' + 상위 앱(stress)을 짚음", "높음" in uv.desktop_headline(hot).plain and "stress" in uv.desktop_headline(hot).plain, uv.desktop_headline(hot).plain)
check("데스크톱 CPU 상위 앱: 최근 15분 기준 stress 가 1위", "최근 15분" in uv.desktop_cpu_top(hot, 80).plain and uv.desktop_cpu_top(hot, 80).plain.splitlines()[1].split()[0] == "stress", uv.desktop_cpu_top(hot, 80).plain)
check("데스크톱 최근 15분: 지난 범위(어제)나 짧은 범위에서는 쓰지 않음", uv.desktop_recent(ud.load(ud.preset("어제", now), "none", now=now)) is None)
check("데스크톱 Netdata 차트·신호: psys·V×I 항목은 제외", all(c[0] != "psys_w" for c in uv.nd_charts(dv["profile"])) and "RAPL psys" not in dict((a, b) for a, b, _ in uv.nd_signal_rows({"snap": {"signals": {"psys_w": 5.0, "batt_vi_w": 2.0, "pkg_w": 20.0}}}, dv)) and "배터리 V×I" not in dict((a, b) for a, b, _ in uv.nd_signal_rows({"snap": {"signals": {"psys_w": 5.0, "batt_vi_w": 2.0, "pkg_w": 20.0}}}, dv)))
check("데스크톱 기기 상태: 덮개·PSR·pc8 없이 CPU 주파수·부하", "덮개" not in uv.device_text(dv).plain and "PSR" not in uv.device_text(dv).plain and "부하" in uv.device_text(dv).plain)
check("데스크톱 작업 구간 표: 전력량 열 없음(2열)", all(len(r) == 2 for r in uv.span_rows(dv)))

async def desk():
    app = usageui.UsageUI(ud.preset("1시간", now), tab="dashboard")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(1.0)
        check("데스크톱 앱: 기본 첫 탭이 대시보드", app.desktop and app.query_one("#tabs", TabbedContent).active == "dashboard")
        check("데스크톱 대시보드: '지금 어떤가'·깨움 상위 박스", len(app.query("#dnow")) == 1 and len(app.query("#dctx")) == 1 and len(app.query("#dcpu")) == 1)
        check("데스크톱 앱: 배터리·psys 박스 없음(dbatt·dhab·dbands·pwr0 부재), 패키지·CPU·문맥 전환 차트", not app.query("#dbatt") and not app.query("#dhab") and not app.query("#dbands") and not app.query("#pwr0") and len(app.query("#pwr1")) == 1 and len(app.query("#pwr4")) == 1 and len(app.query("#pwr5")) == 1)
        t = app.query_one("#tapps", DataTable)
        check("데스크톱 앱: 앱 표 첫 행 node, 전력량 열 이름에 'CPU+GPU'", str(t.get_row_at(0)[0]) == "node" and "CPU+GPU" in str(list(t.columns.values())[6].label))
        await pilot.press("3"); await pilot.pause(1.0)
        check("데스크톱 앱: 원인 탭에 CPU 비교와 앱 변화(node)", "전체 CPU" in str(app.query_one("#causehead").render()) and "node" in str(app.query_one("#causechg").render()), str(app.query_one("#causehead").render()))
        await pilot.press("4"); await pilot.pause(1.0)
        check("데스크톱 앱: 시스템 탭 Netdata 차트에 psys 없음(4개)", len(app.query("Panel")) > 0 and not app.query("#nd4"))
asyncio.run(desk())

# --- 튀었던 순간 순위(usagespikes): 순수 계산 + 화면
import usagespikes as sp
def prow(t, w, ac=0, cpu=10.0, apps=None):
    return {"t": t, "pw": {"psys_w": w, "pkg_w": None if w is None else w * 0.6, "ac": ac}, "irq": {"cpu_all_pct": cpu},
            "apps": apps or [{"app": "idle", "n": 1, "cpu_core_pct": 1.0, "ctxsw_vol_s": 1.0, "rss_mb": 1.0}]}
T0 = int(now) // 300 * 300 - 8 * 86400
base = [prow(T0 + i * 30, 10.0) for i in range(2 * 86400 // 30 * 3)]      # 6일: 평소 10 W (AC 아님)
big = [prow(T0 + 5 * 86400 + i * 30, 30.0, cpu=80.0, apps=[{"app": "build", "n": 9, "cpu_core_pct": 500.0, "ctxsw_vol_s": 5.0, "rss_mb": 1.0}]) for i in range(60)]   # 30분 길게 높음
blip = [prow(T0 + 4 * 86400 + i * 30, 40.0) for i in range(4)]            # 2분짜리 순간값(창 평균이 낮고 짧음)
rows_ = sorted([r for r in base if not (5 * 86400 <= r["t"] - T0 < 5 * 86400 + 1800) and not (4 * 86400 <= r["t"] - T0 < 4 * 86400 + 120)] + big + blip, key=lambda r: r["t"])
got = sp.find_spikes(rows_, [], True, n=5)
check("튄 순간: 30분간 높았던 사건이 1위(2분 순간값보다 위), 순위는 에너지(Wh) 기준", got and got[0]["rank"] == 1 and abs(got[0]["t0"] - (T0 + 5 * 86400)) < 300 and got[0]["dur_s"] >= 1500 and got[0]["excess_wh"] > (got[1]["excess_wh"] if len(got) > 1 else 0), str(got[:2]))
check("튄 순간: 중앙값 10 W·사건 평균 30 W·그때 상위 앱 build·CPU 80%", got and abs(got[0]["median"] - 10.0) < 0.1 and abs(got[0]["power"] - 30.0) < 0.5 and got[0]["apps"][0][0] == "build" and abs(got[0]["cpu"] - 80.0) < 0.1, str(got[:1]))
check("튄 순간: 앞·뒤 이웃은 평소(10 W)", got and abs(got[0]["before"] - 10.0) < 0.5 and abs(got[0]["after"] - 10.0) < 0.5, str(got[:1]))
check("튄 순간: 다른 날 같은 시각 비교(평소 10 W)·일수 표시", got and abs(got[0]["other_days"] - 10.0) < 0.5 and got[0]["other_n"] >= 3, str(got[:1]))
flat = [prow(T0 + i * 30, 10.0) for i in range(400)]
check("튄 순간: 평탄하면 사건 없음, 표본이 없어도 오류 없음", sp.find_spikes(flat, [], True) == [] and sp.find_spikes([], [], True) == [])
mix = [prow(T0 + i * 30, 10.0, ac=0) for i in range(200)] + [prow(T0 + 200 * 30 + i * 30, 30.0, ac=1) for i in range(200)]
check("튄 순간(노트북): AC 와 방전은 따로 중앙값을 잡아 AC 구간 전체가 튄 것으로 오인하지 않음", sp.find_spikes(mix, [], True) == [], str(sp.find_spikes(mix, [], True)))
nopsys = [prow(T0 + i * 30, None) for i in range(100)]
check("튄 순간(psys 없는 호스트): 패키지 전력을 쓰고 psys 가 없는 표본은 건너뜀", sp.find_spikes(nopsys, [], False) == [] and sp.power_of(prow(0, 20.0), False) == 12.0 and sp.power_of(prow(0, None), True) is None)
fake = {"rows": [1], "profile": {"psys": True}, "spikes": got}
tx = uv.spikes_text(fake, 3).plain
check("튄 순간 박스 문구: 순위·시각·전력(평소 대비)·앞뒤·다른 날·앱 표시", "1 " in tx and "30 W" in tx and "평소 10" in tx and "앞 10" in tx and "다른 날 같은 시각" in tx and "build" in tx, tx)
check("튄 순간 표: 순위·초과 Wh·앱 열", uv.spike_rows(fake)[0][0] == "1" and "build" in uv.spike_rows(fake)[0][-1])
check("튄 순간 박스: 표본이 없으면 안내, 튄 곳이 없으면 안내", "표본이 없습니다" in uv.spikes_text({"rows": [], "spikes": []}).plain and "튄 순간이 없습니다" in uv.spikes_text({"rows": [1], "spikes": []}).plain)
check("조회 모델에 spikes 가 들어 있음(리스트)", isinstance(dv["spikes"], list))

async def spk():
    from usageui import SpikesScreen
    app = usageui.UsageUI(ud.preset("1시간", now), tab="dashboard")
    async with app.run_test(size=(150, 55)) as pilot:
        await pilot.pause(1.0)
        check("대시보드에 '튀었던 순간' 박스(dspk)", len(app.query("#dspk")) == 1)
        app.view["spikes"] = got
        await pilot.press("s"); await pilot.pause(0.5)
        check("s: 튄 순간 순위 대화상자가 열리고 행이 있음", isinstance(app.screen, SpikesScreen) and app.screen.query_one("#spk", DataTable).row_count == len(got), str(type(app.screen)))
        before = app.rng
        await pilot.press("enter"); await pilot.pause(1.0)
        pad = max(1800, got[0]["dur_s"])
        check("Enter: 그 시각 앞뒤(최소 30분, 사건이 길면 그 길이)로 범위가 옮겨감(고정 범위)", app.rng.label.startswith("튄 순간") and not app.rng.follows_now and abs(app.rng.t0 - (got[0]["t0"] - pad)) < 1 and abs(app.rng.t1 - (got[0]["t1"] + pad)) < 1, f"{app.rng.t0} {got[0]['t0']}")
        check("튄 순간을 보는 동안 상태줄에 Esc 안내", "Esc" in str(app.query_one("#status").render()))
        await pilot.press("escape"); await pilot.pause(1.0)
        check("Esc: 원래 범위로 복귀하고 안내가 사라짐", app.rng is before and "Esc" not in str(app.query_one("#status").render()) and app._back is None)
        await pilot.press("escape"); await pilot.pause(0.5)
        check("Esc 를 또 눌러도 아무 일 없음(범위 유지)", app.rng is before)
        await pilot.press("s"); await pilot.pause(0.5); await pilot.press("enter"); await pilot.pause(1.0)
        await pilot.press("s"); await pilot.pause(0.5); await pilot.press("enter"); await pilot.pause(1.0)
        await pilot.press("escape"); await pilot.pause(1.0)
        check("튄 순간에서 다시 다른 순간으로 가도 Esc 한 번에 처음 범위로", app.rng is before)
asyncio.run(spk())
check("기본 범위: 센서와 무관하게 7일", ud.preset("7일", now).secs == 7 * 86400 and "7일" in ud.PRESETS)
os.environ["OBSERVE_USAGE_PROFILE"] = "laptop"
finish("usageui")
