import asyncio, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import displayctl as dc
import displayui as ui
from textual.widgets import DataTable, OptionList, Select
from textual.worker import WorkerCancelled

FS = os.environ["FAKE_STATE"]
results = []
def check(name, cond, detail=""):
    results.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
def kill_units():
    import subprocess
    subprocess.run([os.environ["DISPLAYCTL_SYSTEMCTL"], "--user", "stop", f"{dc.TIMER_UNIT}.timer", f"{dc.TIMER_UNIT}.service"], capture_output=True)
def reset():
    kill_units()
    for f in (FS, FS + ".events", FS + ".windows"):
        if os.path.exists(f): os.remove(f)
    shutil.rmtree(os.environ["DISPLAYCTL_STATE"], ignore_errors=True); shutil.rmtree(os.environ["DISPLAYCTL_CONF"], ignore_errors=True)
def mons(): return {m.name: m for m in dc.get_monitors()}
async def settle(pilot, n=30):
    # (고정 대기만으로는 시스템이 바쁠 때 적용 스레드가 끝나기 전에 검사하게 되므로, 워커가 끝나기를 먼저 기다림.
    #  --quick 처럼 앱이 스스로 종료된 뒤에는 기다릴 것이 없으므로 건너뜀)
    async def idle():
        if pilot.app.is_running:
            try:
                await pilot.app.workers.wait_for_complete()
            except WorkerCancelled:  # --quick 은 적용 직후 앱이 종료하며 워커가 취소됨
                pass
    for _ in range(3):
        await idle()
        await pilot.pause(0.05)
    for _ in range(n): await pilot.pause(0.05)
    await idle()
    await pilot.pause(0.1)
def opt_ids(app):
    ol = app.query_one("#modes", OptionList); return [ol.get_option_at_index(i).id for i in range(ol.option_count)]
def pick(app, oid):
    ol = app.query_one("#modes", OptionList); ol.highlighted = [i for i in range(ol.option_count) if ol.get_option_at_index(i).id == oid][0]; ol.action_select()
def shown(app, wid):  # 화면에 실제로 표시되는 라벨 (옵션 목록이 아니라)
    return str(app.query_one("#" + wid, Select).query_one("SelectCurrent").label)

async def t_basic():
    reset(); app = ui.DisplayUI(focus="mode")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); ids = opt_ids(app)
        check("모드 목록: 레이아웃 4 + 내장 프리셋", "layout:mirror" in ids and "preset:presentation-1080p" in ids and "preset:laptop-1200p" in ids and "reset" in ids)
        check("시작 포커스: 모드 목록", app.focused.id == "modes")
        ol0 = app.query_one("#modes", OptionList)
        check("선택 줄(커서)이 지금 모드(확장)에 있음 → 바로 Enter 가능", ol0.highlighted is not None and ol0.get_option_at_index(ol0.highlighted).id == "layout:extend", str(ol0.highlighted))
        check("모니터 표 2개, 외장이 기본 선택", app.query_one("#mons", DataTable).row_count == 2 and app.sel == "DP-4", str(app.sel))
        check("해상도/주사율 값이 현재 모드", app.query_one("#res", Select).value == "3840x2560" and app.query_one("#hz", Select).value == "60")
        check("화면에 표시되는 해상도/주사율 라벨이 '모니터 지원(★)'", "★" in shown(app, "res") and "★" in shown(app, "hz"), f"{shown(app,'res')!r} {shown(app,'hz')!r}")
        hz = [str(l) for l, _ in app.query_one("#hz", Select)._options]
        check("주사율 후보: 50(지원), 48/45/30(사용자 지정)", any(l.startswith("50 Hz") and "★" in l for l in hz) and all(any(l.startswith(f"{x} Hz") and "사용자 지정" in l for l in hz) for x in (48, 45, 30)))
        res = [str(l) for l, _ in app.query_one("#res", Select)._options]
        check("1920x1200 은 사용자 지정 후보", any(l.startswith("1920x1200") and "사용자 지정" in l for l in res))
    for focus in ("refresh", "mode"):
        app = ui.DisplayUI(focus=focus)
        async with app.run_test(size=(140, 42)) as pilot:
            await settle(pilot); check(f"focus={focus} 에서도 화면 라벨이 ★", "★" in shown(app, "res") and "★" in shown(app, "hz"), f"{shown(app,'hz')!r}")

async def t_focus():
    reset()
    for focus, wid in (("refresh", "hz"), ("resolution", "res"), ("position", "rel"), ("scale", "scale"), ("monitors", "mons")):
        app = ui.DisplayUI(focus=focus)
        async with app.run_test(size=(140, 42)) as pilot:
            await settle(pilot, 10); check(f"--focus {focus} → #{wid}", app.focused is not None and app.focused.id == wid)
    app = ui.DisplayUI(focus="mode")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot, 10)
        for key, wid in (("r", "hz"), ("s", "res"), ("c", "scale"), ("p", "rel"), ("m", "modes")):
            await pilot.press(key); await settle(pilot, 3); check(f"키 {key} → #{wid}", app.focused.id == wid)

async def t_cursor():
    # 저장된 구성이 있으면 그 모드에 커서가 있어야 함
    reset(); dc.go(dc.op_layout("mirror"), quiet=True)
    app = ui.DisplayUI(focus="mode")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); ol = app.query_one("#modes", OptionList)
        check("저장된 구성(미러)이 있으면 미러에 커서", ol.get_option_at_index(ol.highlighted).id == "layout:mirror")
        await pilot.press("down"); await settle(pilot, 3)
        check("↓ 한 번으로 다음 항목(노트북만)", ol.get_option_at_index(ol.highlighted).id == "layout:internal")
    reset(); app = ui.DisplayUI(focus="mode", quick=True)
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); await pilot.press("down", "enter"); await settle(pilot, 25)
        check("SUPER+P 흐름: ↓ Enter 로 '미러' 적용 후 종료", not app.is_running and mons()["eDP-1"].mirror_of == "DP-4")

async def t_layout_quick():
    reset(); app = ui.DisplayUI(focus="mode")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot)
        pick(app, "layout:mirror"); await settle(pilot, 20); check("미러 선택", mons()["eDP-1"].mirror_of == "DP-4" and dc.load_state()["layout"] == "mirror")
        pick(app, "layout:internal"); await settle(pilot, 20); check("노트북만", mons()["DP-4"].disabled)
        pick(app, "layout:extend"); await settle(pilot, 20); m = mons(); check("확장", not m["eDP-1"].disabled and not m["DP-4"].disabled and m["eDP-1"].mirror_of is None)
    reset(); app = ui.DisplayUI(focus="mode", quick=True)
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); pick(app, "layout:external"); await settle(pilot, 25); check("--quick: 선택 후 앱 종료", not app.is_running)
    check("--quick: 외부만 적용", mons()["eDP-1"].disabled and not mons()["DP-4"].disabled)

async def t_apply_confirm():
    reset(); app = ui.DisplayUI(focus="refresh")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot)
        app.query_one("#res", Select).value = "1920x1080"; await settle(pilot, 5)
        check("해상도 변경 시 주사율 목록 갱신", "60" in [v for _, v in app.query_one("#hz", Select)._options])
        app.query_one("#hz", Select).value = "60"; await pilot.press("a"); await settle(pilot, 10)
        check("적용 직후 외장 1920x1080 + 확인 창", mons()["DP-4"].width == 1920 and app.screen.__class__.__name__ == "Confirm")
        check("확인 창이 떠 있는 동안 별도 타이머가 예약됨(pending 기록)", os.path.exists(dc.PENDING_FILE))
        await pilot.press("enter"); await settle(pilot, 10)
        check("유지 → 저장 + 예약 취소(pending 없음)", dc.load_state()["monitors"]["DP-4"]["mode"].startswith("1920x1080") and not os.path.exists(dc.PENDING_FILE))
        app.query_one("#res", Select).value = "1280x720"; await settle(pilot, 3); await pilot.press("a"); await settle(pilot, 10)
        check("적용(1280x720)", mons()["DP-4"].width == 1280)
        await pilot.press("escape"); await settle(pilot, 10); check("Esc → 이전(1920x1080) 복귀", mons()["DP-4"].width == 1920)
        app.query_one("#res", Select).value = "1600x900"; await settle(pilot, 3); await pilot.press("a"); await settle(pilot, 10)
        check("적용(1600x900)", mons()["DP-4"].width == 1600)
        await pilot.pause(3.6); await settle(pilot, 20); check("시간 초과 → 자동 되돌림 + pending 정리", mons()["DP-4"].width == 1920 and not os.path.exists(dc.PENDING_FILE))

async def t_misc():
    reset(); app = ui.DisplayUI(focus="refresh")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); app.sel = "eDP-1"; app.fill_form(); await settle(pilot, 5)
        app.query_one("#hz", Select).value = "45"; await pilot.press("a"); await settle(pilot, 10)
        txt = str(app.screen.query_one("#cmsg").render()) if app.screen.__class__.__name__ == "Confirm" else ""
        check("내장 45Hz: 확인 창에 거부 경고", "45" in txt and "받아들이지" in txt, txt); await pilot.press("enter"); await settle(pilot, 10)
    reset(); app = ui.DisplayUI(focus="monitors")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot, 10); await pilot.press("up"); await settle(pilot, 10)
        check("표에서 ↑ → 내장 선택, 설정이 따라 바뀜", app.sel == "eDP-1" and app.query_one("#res", Select).value == "2560x1600")
    reset(); app = ui.DisplayUI(focus="position")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot)
        app.query_one("#res", Select).value = "1920x1080"; await settle(pilot, 3); app.query_one("#hz", Select).value = "60"
        app.query_one("#rel", Select).value = "right"; app.query_one("#of", Select).value = "eDP-1"; app.query_one("#align", Select).value = "center"
        await pilot.press("a"); await settle(pilot, 10); await pilot.press("enter"); await settle(pilot, 10)
        m = mons(); check("위치: 내장 오른쪽·가운데 (2560,260)", (m["DP-4"].x, m["DP-4"].y) == (2560, 260))
    app2 = ui.DisplayUI(focus="position")
    async with app2.run_test(size=(140, 42)) as pilot:
        await settle(pilot); check("저장된 위치 설정이 복원됨", (app2.query_one("#rel", Select).value, app2.query_one("#of", Select).value, app2.query_one("#align", Select).value) == ("right", "eDP-1", "center"))
    reset(); app = ui.DisplayUI(focus="mode")
    async with app.run_test(size=(140, 42)) as pilot:
        await settle(pilot); pick(app, "preset:presentation-1080p"); await settle(pilot, 15)
        check("프리젠테이션: 확인 창", app.screen.__class__.__name__ == "Confirm"); await pilot.press("enter"); await settle(pilot, 10)
        m = mons(); check("프리젠테이션 1080p(외장 1920x1080 + 미러)", m["DP-4"].width == 1920 and m["eDP-1"].mirror_of == "DP-4")
        check("복귀 항목 생김", "back" in opt_ids(app)); pick(app, "back"); await settle(pilot, 15)
        m = mons(); check("복귀: 3840x2560 + 확장", m["DP-4"].width == 3840 and m["eDP-1"].mirror_of is None)
        await pilot.press("S"); await settle(pilot, 5); check("프리셋 저장 입력창", app.screen.__class__.__name__ == "NameInput")
        await pilot.press(*"mine"); await pilot.press("enter"); await settle(pilot, 10)
        check("사용자 프리셋 저장·표시", "mine" in dc.load_presets() and "preset:mine" in opt_ids(app))
    for w, narrow in ((80, True), (150, False)):
        app = ui.DisplayUI(focus="mode")
        async with app.run_test(size=(w, 40)) as pilot:
            await settle(pilot, 10); check(f"폭 {w}: narrow={narrow}", app.has_class("narrow") == narrow)

async def main():
    only = os.environ.get("ONLY")
    for t in [x for x in (t_basic, t_focus, t_cursor, t_layout_quick, t_apply_confirm, t_misc) if not only or x.__name__ == only]:
        try: await t()
        except Exception:
            import traceback; traceback.print_exc(); results.append(False); print("FAIL (예외)", t.__name__)
    kill_units()
    print(f"\nTUI {sum(results)}/{len(results)} 통과"); return 0 if all(results) else 1
sys.exit(asyncio.run(main()))
