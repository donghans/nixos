#!/usr/bin/env python3
"""usageui 실시간 탭 시험: 샘플러(변화율·느린 항목 주기·세션 ctx 미호출·비용), 표시 조각, Textual 앱(탭 진입 때만 타이머, 이탈 때 정지, 포커스 상실 때 멈춤, 간격 자동 증가)."""
import asyncio, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="usagelive-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit")); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_uikit"))
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "claude-skills", "donghans-host-resources", "scripts"))
import hostmetrics as hm
import usagelive as lv
from harness import checker
check, finish = checker()

# --- 샘플러
called = {"ctx": 0}
orig = hm.ctx_last_chat
hm.ctx_last_chat = lambda sids: called.__setitem__("ctx", called["ctx"] + 1) or {}
sm = lv.LiveSampler(slow_every=0.5)
s0 = sm.sample()
check("첫 표본: measured=False, 구간 값은 None, 판정은 계산됨", s0["measured"] is False and s0["rates"]["pswpin"] is None and hm.verdict(s0)[0] in ("여유", "주의", "압박", "심각"))
check("첫 표본: 느린 항목(앱·cgroup·세션)이 이미 채워짐, 앱 CPU 는 아직 미측정", {"apps", "cons", "sessions"} <= set(s0) and s0["apps_measured"] is False)
time.sleep(0.6)
s1 = sm.sample()
check("둘째 표본: measured=True, 변화율 숫자, 코어별 사용률 리스트(코어 수와 같음)", s1["measured"] and s1["rates"]["pswpin"] >= 0 and len(s1["cores"]) == os.cpu_count() and all(v is None or 0 <= v <= 100.5 for v in s1["cores"]))
check("둘째 표본: 느린 주기(0.5s)가 지나 앱 CPU 가 측정됨", s1["apps_measured"] is True and s1["apps"] and all(a["cpu"] >= 0 for a in s1["apps"]))
check("네트워크·디스크 변화율은 {이름: (값, 값)} 이고 음수가 없음", all(r >= 0 for v in list(s1["net"].values()) + list(s1["disk"].values()) for r in v))
check("세션 수집이 ctx 저장소(subprocess)를 부르지 않음", called["ctx"] == 0)
s2 = sm.sample()
check("느린 주기 안의 표본은 느린 항목을 그대로 재사용(같은 객체)", s2["apps"] is s1["apps"] and s2["cons"] is s1["cons"])
check("한 번 재는 데 걸린 시간 기록(cost_ms)과 상한(느린 항목 포함 첫 표본도 2초 미만)", 0 < s2["cost_ms"] < 2000 and s0["cost_ms"] < 2000, f"{s0['cost_ms']:.0f}ms {s2['cost_ms']:.0f}ms")
check("rates: 누적값이 줄어든(재설정) 키는 빠짐", lv.rates({"a": (10, 10), "b": (1, 1)}, {"a": (5, 5), "b": (9, 9)}, 1.0) == {"a": (5.0, 5.0)})
check("rates: 직전 표본 없음·dt 0 이면 빈 dict", lv.rates({"a": (1, 1)}, None, 1) == {} and lv.rates({"a": (1, 1)}, {"a": (0, 0)}, 0) == {})

# --- 표시 조각
parts = lv.mem_segments(s1)
check("메모리 구성: 칸 합이 총량을 넘지 않고 7구간(ZRAM 점유 포함)", sum(b for _, b, _ in parts) <= s1["mem"]["total"] + 1 and len(parts) == 7 and parts[5][0].startswith("ZRAM"))
for w in (10, 37, 80):
    check(f"seg_bar: 폭 {w} 에 정확히 맞음", len(lv.seg_bar(parts, w).plain) == w)
for name, fn in (("판정", lv.render_verdict), ("압박", lv.render_pressure), ("세션", lv.render_sessions)):
    check(f"render {name}: 비어 있지 않은 Text", len(fn(s1).plain) > 10)
check("render 메모리·IO·상위: 비어 있지 않음", all(len(f(s1, 60).plain) > 10 for f in (lv.render_mem, lv.render_io, lv.render_top)))
check("render 메모리: 보수적 값과 MemAvailable 두 값을 모두 보임", "보수적" in lv.render_mem(s1, 60).plain and "MemAvailable" in lv.render_mem(s1, 60).plain)
check("render 첫 표본에서도 예외 없음", all(len(f(s0, 60).plain) > 5 for f in (lv.render_mem, lv.render_io, lv.render_top)))
check("human_bytes", lv.human_bytes(None) == "-" and lv.human_bytes(1536 * 1024, True) == "1.5 MiB/s" and lv.human_bytes(12) == "12 B")

# --- Textual 앱
import usagedata as ud, usageui
from textual.widgets import TabbedContent

def active(app):
    return app.query_one("#tabs", TabbedContent).active

async def drive():
    app = usageui.UsageUI(ud.preset("1시간", time.time()))
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(0.8)
        check("앱: 실시간 탭 밖에서는 타이머·샘플러 없음", app._timer is None and app.sampler is None)
        await pilot.press("6"); await pilot.pause(2.6)
        check("앱: 6 키로 live 탭 진입, 타이머 시작·샘플 도착", active(app) == "live" and app._timer is not None and app.live_sample is not None)
        n = app.sampler._t
        check("앱: 판정 박스에 내용이 그려짐", "판정" in str(app.query_one("#lverdict").border_title) and len(app.query_one("#lverdict")._text.plain) > 10)
        await pilot.pause(1.5)
        check("앱: 탭이 보이는 동안 표본이 계속 갱신됨", app.sampler._t > n)
        await pilot.press("1"); await pilot.pause(0.5)
        check("앱: 다른 탭으로 가면 타이머 정지", app._timer is None)
        t_stop = app.sampler._t; await pilot.pause(1.6)
        check("앱: 정지 후에는 표본이 늘지 않음", app.sampler._t == t_stop)
        await pilot.press("6"); await pilot.pause(1.5)
        check("앱: 다시 6 으로 오면 재개", app._timer is not None and app.sampler._t > t_stop)
        app.live_sec = 1.0
        app.live_sample = dict(app.live_sample, cost_ms=800.0)
        app._live_draw(app.live_sample)
        check("앱: 한 번 재는 시간이 길면(800ms) 간격을 자동으로 늘림(≥4초)", app.live_sec >= 4.0)
        app._live_stop()
async def narrow():
    app = usageui.UsageUI(ud.preset("1시간", time.time()), tab="live")
    async with app.run_test(size=(90, 40)) as pilot:
        await pilot.pause(2.0)
        check("앱: --tab live 로 시작하면 바로 실시간 탭, 폭 90칸이면 1열(narrow)", active(app) == "live" and app._timer is not None and app.query_one("#livebox").has_class("narrow"))
asyncio.run(drive())
asyncio.run(narrow())
finish("usagelive")
