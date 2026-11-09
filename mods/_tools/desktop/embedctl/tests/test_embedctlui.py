#!/usr/bin/env python3
"""embedctlui 시험(헤드리스 Textual Pilot; 실제 EC·helper·systemctl 없이 가짜 helper 로):
상태 표시, 드롭다운으로 충전 상한·성능 모드 적용(helper 인스턴스 이름), 현재 상태와 같은 선택 무시, 실패 시 드롭다운이 실제 상태로 되돌아옴,
Cooler Boost 버튼/F8 과 켜짐 경고, 접근 불가·게이트 거부 시 조작 잠금, 스냅샷 저장/복원(계획 확인창 기본 「취소」), 종료 규칙, 도움말, 2초 갱신.
textual 이 있는 python 으로 `python3 -I` 실행(run-tests.sh 의 $PY)."""
import asyncio, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "uikit"), os.path.join(TOOLS, "_lib", "testkit"), os.path.join(TOOLS, "_lib", "ctlkit")):
    sys.path.insert(0, p)
T = tempfile.mkdtemp(prefix="embedctlui-test-")
for d in ("bat", "ac", "snaps"):
    os.makedirs(os.path.join(T, d))
for rel, text in (("bat/status", "Charging\n"), ("bat/capacity", "64\n"), ("ac/online", "1\n")):
    open(os.path.join(T, rel), "w").write(text)
os.environ.update(EMBEDCTL_SYSFS_BAT=f"{T}/bat", EMBEDCTL_SYSFS_AC=f"{T}/ac", EMBEDCTL_SNAPSHOT_DIR=f"{T}/snaps", XDG_STATE_HOME=T)
from harness import checker
import embedlib as lib
import embedctlui as ui
from textual.widgets import Button, OptionList, Select, Static
check, finish = checker()

# --- 가짜 EC/helper -----------------------------------------------------------------------------
S = {"limit": 100, "set": False, "mode": "comfort", "boost": False, "access": "helper", "gate": "verified", "fw": "1592EMS1.111"}
CALLS, FAIL = [], {}
FANS = {"v": [2840, 2711, 0, 0]}
def raw():
    return {"d7": 0x80 + S["limit"] if S["set"] else 0x80, "d2": 0xC0 | {"sport": 0, "comfort": 1, "eco": 2}[S["mode"]], "b98": 0x82 if S["boost"] else 0x02, "end": S["limit"] if S["set"] else 0}
def status():
    r = raw(); ok = S["access"] != "unavailable"
    return {"gate": {"board": "MS-1592", "board_ok": True, "fw": S["fw"] if ok else None, "fw_date": None, "fw_verified": S["gate"] == "verified", "state": S["gate"] if ok else "unknown"},
            "access": S["access"], "ec": ({"d7": r["d7"], "d2": r["d2"], "b98": r["b98"]} if ok else None),
            "charge": {"end": r["end"], "start": r["end"] - 10, "set": S["set"], "limit": S["limit"]},
            "mode": lib.decode_mode(r["d2"]) if ok else None, "boost": S["boost"] if ok else None,
            "fans": FANS["v"], "temp_pkg": 33.5, "power": {"ac": True, "status": "Charging", "capacity": 64},
            "warnings": [] if ok else ["helper 실패(시험용): 로컬 세션에서 실행해야 한다"]}
def fake_helper(inst, timeout=20):
    CALLS.append(inst)
    if FAIL.get(inst):
        raise lib.HelperError(FAIL[inst], code=3)
    kind, arg = lib.parse_instance(inst); before = raw()
    if kind == "charge": S.update(limit=arg, set=True)
    elif kind == "mode": S["mode"] = arg
    else: S["boost"] = (arg == "on")
    return {"ok": True, "before": before, "after": raw()}
lib.collect_status = status
lib.helper_call = fake_helper
lib.read_fans = lambda: FANS["v"]
lib.read_temp_pkg = lambda: 33.5

def text_of(app, wid):
    w = app.query_one(wid, Static)
    return str(w.render()) if hasattr(w, "render") else ""

async def drive():
    app = ui.EmbedUI()
    async with app.run_test(size=(120, 42)) as pilot:
        await pilot.pause(0.8)
        sc, sm = app.query_one("#sel-charge", Select), app.query_one("#sel-mode", Select)
        check("시작: 상태 줄에 기종·펌웨어·검증됨·helper", all(x in text_of(app, "#status") for x in ("MS-1592", "1592EMS1.111", "검증됨", "helper(polkit)")), text_of(app, "#status"))
        check("시작: 드롭다운이 현재 상태(충전 100, comfort)", sc.value == 100 and sm.value == "comfort", (sc.value, sm.value))
        check("시작: 시작만으로 쓰기 동작이 일어나지 않음(드롭다운 동기화가 되돌아오지 않음)", CALLS == [], CALLS)
        check("시작: Cooler Boost 꺼짐 표시, 경고 없음", "꺼짐" in text_of(app, "#boost-state") and not app.query_one("#boost-box").has_class("on"))
        live = text_of(app, "#live")
        check("팬·온도·전원 칸", "fan1 2840" in live and "33.5" in live and "AC 연결" in live and "Charging" in live, live)

        # 충전 상한
        sc.value = 80; await pilot.pause(0.8)
        check("충전 80 선택 → helper charge-80 한 번", CALLS == ["charge-80"], CALLS)
        check("충전 80: 화면 메시지에 → 80%", "→ 80%" in text_of(app, "#msg") and app.query_one("#msg").has_class("ok"), text_of(app, "#msg"))
        check("충전 80: 드롭다운 값 80 유지", sc.value == 80, sc.value)
        n = len(CALLS); await pilot.press("f5"); await pilot.pause(0.8)
        check("F5 새로고침은 쓰기를 일으키지 않음", len(CALLS) == n, CALLS)
        sc.post_message(Select.Changed(sc, 80)); await pilot.pause(0.5)
        check("현재와 같은 값의 Changed 이벤트(드롭다운이 되돌아온 경우)는 무시 — helper 호출 없음", len(CALLS) == n, CALLS)

        # 성능 모드
        sm.value = "eco"; await pilot.pause(0.8)
        check("eco 선택 → helper mode-eco", CALLS[-1] == "mode-eco" and sm.value == "eco", CALLS)
        n = len(CALLS); sm.post_message(Select.Changed(sm, "eco")); await pilot.pause(0.5)
        check("성능 모드도 현재와 같은 값의 Changed 이벤트는 무시", len(CALLS) == n, CALLS)

        # 실패 시 드롭다운이 실제 상태로 되돌아온다
        FAIL["mode-sport"] = "게이트 거부: 시험용"
        sm.value = "sport"; await pilot.pause(1.0)
        check("실패: 메시지에 종료 코드 3과 이유, 오류 스타일", "실패(종료 코드 3)" in text_of(app, "#msg") and "게이트 거부: 시험용" in text_of(app, "#msg") and app.query_one("#msg").has_class("err"), text_of(app, "#msg"))
        check("실패: 드롭다운이 실제 상태(eco)로 되돌아감", sm.value == "eco", sm.value)
        FAIL.clear()

        # Cooler Boost
        await pilot.press("f8"); await pilot.pause(0.8)
        check("F8 → helper boost-on, 켜짐 표시와 경고 스타일", CALLS[-1] == "boost-on" and "켜짐" in text_of(app, "#boost-state") and app.query_one("#boost-box").has_class("on"), (CALLS[-1], text_of(app, "#boost-state")))
        app.query_one("#btn-boost", Button).press(); await pilot.pause(0.8)
        check("버튼 → helper boost-off, 경고 해제", CALLS[-1] == "boost-off" and not app.query_one("#boost-box").has_class("on"), CALLS[-1])

        # 스냅샷 저장
        check("스냅샷 폴더가 비어 있음(자동 저장 없음)", lib.list_snapshots() == [])
        await pilot.press("f7"); await pilot.pause(0.4)
        check("저장된 스냅샷이 없으면 안내(대화상자 없음)", "저장된 스냅샷이 없다" in text_of(app, "#msg") and len(app.screen_stack) == 1, text_of(app, "#msg"))
        await pilot.press("f6"); await pilot.pause(0.5)
        snaps = lib.list_snapshots()
        saved = json.load(open(snaps[0])) if snaps else {}
        check("F6: 스냅샷 파일 저장(충전 80 · eco · boost 꺼짐)", len(snaps) == 1 and saved.get("charge", {}).get("limit") == 80 and saved.get("mode") == "eco" and saved.get("boost") is False, str(saved)[:200])
        check("F6: 저장 경로 안내", "스냅샷을 저장했다" in text_of(app, "#msg"))

        # 복원: 상태를 바꾼 뒤 스냅샷으로
        S.update(limit=60, set=True, mode="sport", boost=True); await pilot.press("f5"); await pilot.pause(0.8)
        n = len(CALLS)
        await pilot.press("f7"); await pilot.pause(0.5)
        check("F7: 스냅샷 선택 대화상자", type(app.screen).__name__ == "SnapshotPick" and app.screen.query_one("#snap-list", OptionList).option_count == 1, type(app.screen).__name__)
        await pilot.press("enter"); await pilot.pause(0.5)
        check("스냅샷 선택 → 복원 계획 확인창(기본 취소)", type(app.screen).__name__ == "ConfirmScreen" and app.focused.id == "quit-no", type(app.screen).__name__)
        await pilot.press("enter"); await pilot.pause(0.5)
        check("확인창에서 바로 Enter(= 취소)하면 아무것도 쓰지 않음", len(CALLS) == n and len(app.screen_stack) == 1, CALLS[n:])
        await pilot.press("f7"); await pilot.pause(0.4); await pilot.press("enter"); await pilot.pause(0.5)
        await pilot.press("escape"); await pilot.pause(0.4)
        check("확인창에서 Esc = 취소(아무것도 쓰지 않음)", len(CALLS) == n and len(app.screen_stack) == 1, CALLS[n:])
        await pilot.press("f7"); await pilot.pause(0.4); await pilot.press("enter"); await pilot.pause(0.5)
        await pilot.press("right"); await pilot.pause(0.2); await pilot.press("enter"); await pilot.pause(1.2)
        check("적용 선택 → charge-80, mode-eco, boost-off 순서로 helper", CALLS[n:] == ["charge-80", "mode-eco", "boost-off"], CALLS[n:])
        check("복원 완료 메시지와 실제 상태 반영(80 · eco · 꺼짐)", "복원 완료" in text_of(app, "#msg") and sc.value == 80 and sm.value == "eco" and not app.query_one("#boost-box").has_class("on"), text_of(app, "#msg"))
        n = len(CALLS)
        await pilot.press("f7"); await pilot.pause(0.4); await pilot.press("enter"); await pilot.pause(0.5)
        check("이미 같은 상태면 확인창 없이 안내", "할 일이 없다" in text_of(app, "#msg") and len(app.screen_stack) == 1 and len(CALLS) == n, text_of(app, "#msg"))
        # 복원 거부: 펌웨어가 다른 스냅샷
        S.update(limit=60, set=True); await pilot.press("f5"); await pilot.pause(0.8)
        bad = dict(saved); bad["gate"] = dict(saved["gate"], fw="1592EMS1.109"); json.dump(bad, open(f"{T}/snaps/zz-bad.json", "w"))
        await pilot.press("f7"); await pilot.pause(0.4); await pilot.press("enter"); await pilot.pause(0.5)   # 최신순 맨 위 = zz-bad
        check("펌웨어가 다른 스냅샷은 복원 거부(종료 코드 3 안내, 쓰기 없음)", "복원할 수 없다(종료 코드 3)" in text_of(app, "#msg") and len(CALLS) == n, text_of(app, "#msg"))
        os.remove(f"{T}/snaps/zz-bad.json")

        # 2초 갱신
        FANS["v"] = [8000, 7600, 0, 0]; app.tick(); await pilot.pause(0.3)
        check("tick: 팬 값이 갱신됨", "fan1 8000" in text_of(app, "#live"), text_of(app, "#live"))

        # 종료 규칙
        await pilot.press("question_mark"); await pilot.pause(0.4)
        check("? = 도움말 화면(키 목록에 F6·F7·F8)", type(app.screen).__name__ == "HelpScreen")
        await pilot.press("escape"); await pilot.pause(0.3)
        check("도움말은 Esc 로 닫힘(앱은 그대로)", len(app.screen_stack) == 1 and app.is_running)
        await pilot.press("escape"); await pilot.pause(0.4)
        check("Esc → 종료 확인창(기본 「아니오」)", type(app.screen).__name__ == "QuitConfirmScreen" and app.focused.id == "quit-no")
        await pilot.press("enter"); await pilot.pause(0.3)
        check("기본값(아니오)으로 Enter 하면 앱 유지", app.is_running and len(app.screen_stack) == 1)
        await pilot.press("escape"); await pilot.pause(0.3); await pilot.press("right"); await pilot.pause(0.2); await pilot.press("enter"); await pilot.pause(0.3)
        check("Esc → → → Enter = 종료", not app.is_running)

    # 접근 불가: 조작 잠금
    S.update(access="unavailable", limit=100, set=False, mode="comfort", boost=False, gate="verified"); CALLS.clear()
    app2 = ui.EmbedUI()
    async with app2.run_test(size=(120, 42)) as pilot:
        await pilot.pause(0.9)
        check("접근 불가: 상태 줄에 사용 불가와 이유", "사용 불가" in text_of(app2, "#status") and "로컬 세션" in text_of(app2, "#status"), text_of(app2, "#status"))
        check("접근 불가: 드롭다운·버튼 잠김, EC 항목은 알 수 없음", app2.query_one("#sel-charge", Select).disabled and app2.query_one("#sel-mode", Select).disabled and app2.query_one("#btn-boost", Button).disabled and "알 수 없음" in text_of(app2, "#boost-state"))
        await pilot.press("f8"); await pilot.pause(0.4)
        check("접근 불가: F8 이 아무것도 하지 않음", CALLS == [], CALLS)
        await pilot.press("f6"); await pilot.pause(0.4)
        check("접근 불가여도 스냅샷 저장은 되고 복원에 못 쓴다는 주의가 붙음", "복원에는 쓸 수 없다" in text_of(app2, "#msg"), text_of(app2, "#msg"))
        await pilot.press("ctrl+q"); await pilot.pause(0.3)
        check("Ctrl+Q 는 확인 없이 즉시 종료", not app2.is_running)

    # 게이트 거부(미검증 펌웨어): 읽기만
    S.update(access="helper", gate="unverified_fw", fw="1592EMS1.222"); CALLS.clear()
    app3 = ui.EmbedUI()
    async with app3.run_test(size=(120, 42)) as pilot:
        await pilot.pause(0.9)
        check("미검증 펌웨어: 상태 줄 「읽기만」, 조작 잠김, 값은 보임", "읽기만" in text_of(app3, "#status") and app3.query_one("#sel-mode", Select).disabled and app3.query_one("#sel-mode", Select).value == "comfort")
        app3.query_one("#sel-charge", Select).disabled = False
        app3.query_one("#sel-charge", Select).value = 70; await pilot.pause(0.5)
        check("미검증 펌웨어: 드롭다운을 억지로 바꿔도 쓰기 동작이 시작되지 않음", CALLS == [], CALLS)

asyncio.run(drive())
finish("embedctlui")
