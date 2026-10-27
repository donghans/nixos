import json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import displayctl as dc

FS = os.environ["FAKE_STATE"]
def kill_units():
    subprocess.run([os.environ["DISPLAYCTL_SYSTEMCTL"], "--user", "stop", f"{dc.TIMER_UNIT}.timer", f"{dc.TIMER_UNIT}.service"], capture_output=True)
def reset():
    kill_units()
    for f in (FS, FS + ".events", FS + ".windows"):
        if os.path.exists(f): os.remove(f)
    shutil.rmtree(os.environ["DISPLAYCTL_STATE"], ignore_errors=True); shutil.rmtree(os.environ["DISPLAYCTL_CONF"], ignore_errors=True)
def mons(): return {m.name: m for m in dc.get_monitors()}
def run(*a): return dc.main(list(a))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "_lib", "_testkit"))
from harness import checker
check, finish = checker(verbose=True)

reset(); m = mons()
check("모니터 2개, 내장/외장 구분", m["eDP-1"].internal and not m["DP-4"].internal)
check("지원 모드 파싱", (2560, 1600, 165.04) in m["eDP-1"].modes and len(m["DP-4"].modes) == 10)
reset(); run("layout", "extend"); m = mons()
check("확장: 내장 0,0 / 외장 -640,-2560(내장 위, 가운데 정렬: (2560-3840)/2)", (m["eDP-1"].x, m["eDP-1"].y, m["DP-4"].x, m["DP-4"].y) == (0, 0, -640, -2560))
run("layout", "mirror"); check("미러", mons()["eDP-1"].mirror_of == "DP-4")
run("layout", "extend"); m = mons(); check("미러 해제 후 확장", m["eDP-1"].mirror_of is None and not m["eDP-1"].disabled)
run("layout", "internal"); m = mons(); check("노트북만", m["DP-4"].disabled and not m["eDP-1"].disabled)
run("layout", "external"); m = mons(); check("외부만", m["eDP-1"].disabled and not m["DP-4"].disabled and (m["DP-4"].x, m["DP-4"].y) == (0, 0))
run("layout", "extend"); m = mons(); check("외부만 → 확장: 둘 다 켜짐", not m["eDP-1"].disabled and not m["DP-4"].disabled)
run("layout", "internal"); run("layout", "mirror"); m = mons(); check("노트북만 → 미러", not m["DP-4"].disabled and m["eDP-1"].mirror_of == "DP-4")

reset(); run("set", "DP-4", "--res", "1920x1080", "--hz", "60"); m = mons()
check("외장 1920x1080@60", (m["DP-4"].width, m["DP-4"].height, round(m["DP-4"].hz)) == (1920, 1080, 60))
check("내장 배치 유지(0,0), 외장은 줄어든 높이만큼 위(y=-1080)", (m["eDP-1"].x, m["eDP-1"].y, m["DP-4"].y) == (0, 0, -1080))
rc = run("set", "eDP-1", "--hz", "48"); check("내장 48Hz 허용", abs(mons()["eDP-1"].hz - 48) < 0.1 and rc == 0)
rc = run("set", "eDP-1", "--hz", "45"); check("내장 45Hz 는 거부되고 경고(rc=1)", abs(mons()["eDP-1"].hz - 48) < 0.1 and rc == 1)
rc = run("set", "DP-4", "--hz", "30"); check("거부된 값이 상태에 남지 않아 이후 작업에 경고가 없음", abs(mons()["DP-4"].hz - 30) < 0.1 and rc == 0)

reset(); run("set", "DP-4", "--scale", "2"); m = mons(); check("배율 2 → 외장이 내장 위 y=-1280", m["DP-4"].scale == 2 and m["DP-4"].y == -1280)
reset(); run("set", "DP-4", "--res", "1920x1080", "--hz", "60", "--pos", "right:eDP-1:center"); m = mons()
check("오른쪽·가운데: (2560,260)", (m["DP-4"].x, m["DP-4"].y) == (2560, 260))
run("set", "DP-4", "--pos", "below:eDP-1:end"); m = mons(); check("아래·끝: (640,1600)", (m["DP-4"].x, m["DP-4"].y) == (640, 1600))
run("set", "DP-4", "--pos", "left:eDP-1:start"); m = mons(); check("왼쪽·시작: (-1920,0)", (m["DP-4"].x, m["DP-4"].y) == (-1920, 0))

reset(); run("present", "1920x1080"); m = mons()
check("프리젠테이션: 외장 1920x1080 + 내장 미러", (m["DP-4"].width, m["DP-4"].height) == (1920, 1080) and m["eDP-1"].mirror_of == "DP-4")
run("present", "off"); m = mons()
check("프리젠테이션 해제: 원래 해상도/확장", (m["DP-4"].width, m["DP-4"].height) == (3840, 2560) and m["eDP-1"].mirror_of is None)
reset(); run("preset", "load", "laptop-1200p"); m = mons()
check("노트북 프리셋 1920x1200, 외장 꺼짐", (m["eDP-1"].width, m["eDP-1"].height) == (1920, 1200) and m["DP-4"].disabled)
run("back"); m = mons(); check("back: 2560x1600 + 외장 켜짐", (m["eDP-1"].width, m["eDP-1"].height) == (2560, 1600) and not m["DP-4"].disabled)

reset(); run("layout", "mirror"); run("set", "DP-4", "--res", "1920x1080", "--hz", "60")
subprocess.run([os.environ["DISPLAYCTL_HYPRCTL"], "reload"]); m = mons()
check("reload 로 기본 구성으로 돌아감(전제)", m["eDP-1"].mirror_of is None and m["DP-4"].width == 3840)
run("restore"); m = mons(); check("restore: 미러와 1920x1080 복원", m["eDP-1"].mirror_of == "DP-4" and m["DP-4"].width == 1920)

reset(); run("layout", "external")
d = [x for x in json.load(open(FS)) if x["name"] != "DP-4"]; d[0]["disabled"] = True; json.dump(d, open(FS, "w"))
run("restore"); check("외장 분리 + '외부만': 내장 다시 켜짐(화면이 모두 꺼지지 않음)", not mons()["eDP-1"].disabled)

reset(); run("set", "DP-4", "--res", "2560x1440", "--hz", "59.95"); run("preset", "save", "mine"); run("reset")
check("reset 후 기본 해상도", mons()["DP-4"].width == 3840 and dc.load_state() is None)
run("preset", "load", "mine"); check("사용자 프리셋 적용", mons()["DP-4"].width == 2560)

reset(); tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); check("트랜잭션 적용", mons()["DP-4"].width == 1280)
tx.revert(); m = mons(); check("revert: 원래 해상도/위치 + 상태 없음", m["DP-4"].width == 3840 and (m["DP-4"].x, m["DP-4"].y) == (0, -2560) and dc.load_state() is None)

reset(); json.dump([{"address": "0xaaa", "monitor": 0}, {"address": "0xbbb", "monitor": 1}], open(FS + ".windows", "w")); run("layout", "external")
ev = open(FS + ".events").read().splitlines(); win = {w["address"]: w["monitor"] for w in json.load(open(FS + ".windows"))}
check("외부만: 내장의 창이 외장으로 이동", win == {"0xaaa": 1, "0xbbb": 1}, str(win))
check("창 이동이 모니터 끄기보다 먼저", ev.index(next(e for e in ev if e.startswith("move 0xaaa"))) < ev.index("disable eDP-1"), str(ev))
check("외장의 창은 건드리지 않음", not any("0xbbb" in e for e in ev))
open(FS + ".events", "w").close(); run("layout", "extend")
check("확장으로 돌아갈 때는 창을 옮기지 않음", not any(e.startswith("move") for e in open(FS + ".events").read().splitlines()))

# 적용 순서: 겹침 경고(전환 중 같은 위치에서 겹침)를 피함
reset(); run("layout", "extend"); open(FS + ".events", "w").close(); run("layout", "external")
ev = open(FS + ".events").read().splitlines()
check("확장 → 외부만: 내장을 먼저 끄고 나서 외장을 0,0 으로 옮김", ev.index("disable eDP-1") < ev.index(next(e for e in ev if e.startswith("rule DP-4"))), str(ev))
open(FS + ".events", "w").close(); run("layout", "extend"); ev = open(FS + ".events").read().splitlines()
check("외부만 → 확장: 켜져 있던 외장을 먼저 옮기고 나서 내장을 켬", ev.index(next(e for e in ev if e.startswith("rule DP-4"))) < ev.index(next(e for e in ev if e.startswith("rule eDP-1"))), str(ev))
reset(); run("layout", "internal"); open(FS + ".events", "w").close(); run("layout", "external"); ev = open(FS + ".events").read().splitlines()
check("노트북만 → 외부만(남는 게 없음): 외장을 먼저 켜고 내장을 마지막에 끔", ev.index(next(e for e in ev if e.startswith("rule DP-4"))) < ev.index("disable eDP-1"), str(ev))

# 모든 레이아웃 전환 조합에서 켜진 모니터끼리 겹치는 순간이 없어야 함 (겹치면 화면에 경고 말풍선이 뜸)
LAYS = ["extend", "mirror", "internal", "external"]
bad = []
for a in LAYS:
    for b in LAYS:
        if a == b: continue
        reset(); run("layout", a); open(FS + ".events", "w").close(); run("layout", b)
        ev = open(FS + ".events").read().splitlines()
        if any(e.startswith("OVERLAP") for e in ev): bad.append(f"{a}→{b}")
        m = mons()
        want_on = {"extend": 2, "mirror": 2, "internal": 1, "external": 1}[b]
        if sum(1 for x in m.values() if not x.disabled) != want_on: bad.append(f"{a}→{b}(최종 상태)")
check(f"모든 레이아웃 전환 {len(LAYS)*(len(LAYS)-1)}가지에서 겹침 없음 + 최종 상태 정상", not bad, str(bad))
reset(); run("layout", "external"); open(FS + ".events", "w").close(); run("layout", "internal"); ev = open(FS + ".events").read().splitlines()
check("외부만 → 노트북만(맞바꿈): 임시 위치로 먼저 켜고 나서 외장을 끄고 최종 위치로", any(e.startswith("rule eDP-1 pos=2") or e.startswith("rule eDP-1 pos=3") for e in ev) and not any(e.startswith("OVERLAP") for e in ev), str(ev))
m = mons(); check("  최종 위치: 내장 0,0", (m["eDP-1"].x, m["eDP-1"].y) == (0, 0) and m["DP-4"].disabled)

# 해상도만 바꿀 때 주사율: 목록 밖 해상도에는 정수로 반올림(60.04 → 60), 지원 해상도에는 가장 가까운 지원 값
reset(); run("set", "eDP-1", "--res", "1920x1200")
check("--res 만 줘도 주사율이 정수로(1920x1200@60, 60.04 아님)", dc.load_state()["monitors"]["eDP-1"]["mode"] == "1920x1200@60", dc.load_state()["monitors"]["eDP-1"]["mode"])
reset(); run("set", "DP-4", "--res", "1920x1080"); check("지원 해상도는 가장 가까운 지원 주사율(60)", dc.load_state()["monitors"]["DP-4"]["mode"] == "1920x1080@60", dc.load_state()["monitors"]["DP-4"]["mode"])

# ───── 기본 가운데 정렬 / 확장 배치(--arrange) ─────
reset(); run("layout", "extend"); m = mons()
ext, lap = m["DP-4"], m["eDP-1"]
ew, eh = ext.logical(ext.mode, ext.scale); lw, lh = lap.logical(lap.mode, lap.scale)
check("기본 확장: 외부가 노트북 위에서 가운데 정렬", ext.y == -eh and ext.x - lap.x == (lw - ew) // 2, f"ext=({ext.x},{ext.y}) lap=({lap.x},{lap.y}) ew={ew} eh={eh} lw={lw}")
reset(); run("layout", "extend", "--arrange", "left"); m = mons(); ext, lap = m["DP-4"], m["eDP-1"]
ew, eh = ext.logical(ext.mode, ext.scale); lw, lh = lap.logical(lap.mode, lap.scale)
check("좌우(외부 왼쪽): 외부 오른쪽 끝이 노트북 왼쪽 끝이고 세로 가운데", ext.x + ew == lap.x and (ext.y + eh // 2) - (lap.y + lh // 2) in (0, -1, 1), f"ext=({ext.x},{ext.y}) lap=({lap.x},{lap.y})")
reset(); run("layout", "extend", "--arrange", "right"); m = mons(); ext, lap = m["DP-4"], m["eDP-1"]
ew, eh = ext.logical(ext.mode, ext.scale); lw, lh = lap.logical(lap.mode, lap.scale)
check("좌우(외부 오른쪽): 노트북 오른쪽 끝이 외부 왼쪽 끝이고 세로 가운데", lap.x + lw == ext.x and (ext.y + eh // 2) - (lap.y + lh // 2) in (0, -1, 1), f"ext=({ext.x},{ext.y}) lap=({lap.x},{lap.y})")
check("배치가 저장되고 current_arrange 가 알아봄", dc.current_arrange(dc.load_state(), dc.get_monitors()) == "right")
run("layout", "extend", "--arrange", "stack"); check("위아래로 되돌리면 위치 지정이 사라짐", not dc.load_state()["pos"] and dc.current_arrange(dc.load_state(), dc.get_monitors()) == "stack")
run("set", "DP-4", "--pos", "left:eDP-1:start"); check("직접 지정한 위치는 사용자 지정으로 인식", dc.current_arrange(dc.load_state(), dc.get_monitors()) == "custom")

# ───── 되돌리기 타이머(별도 프로세스) ─────
import time as _t
def pending(): return os.path.exists(dc.PENDING_FILE)
DC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "displayctl.py")

reset(); tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx.arm(1)
check("arm: 변경이 적용되고 대기 기록이 생김", pending() and mons()["DP-4"].width == 1280)
_t.sleep(3)
m = mons(); check("확인 없이 시간이 지나면 별도 프로세스가 원래대로 되돌림", m["DP-4"].width == 3840 and not pending() and dc.load_state() is None, f"{m['DP-4'].width} pending={pending()}")

reset(); tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx.arm(2); tx.commit(); _t.sleep(3.5)
check("확인(commit)하면 타이머가 취소되어 유지됨 + 구성 저장", mons()["DP-4"].width == 1280 and not pending() and dc.load_state()["monitors"]["DP-4"]["mode"].startswith("1280x720"))

reset()
subprocess.run([sys.executable, "-I", "-c", f"""
import os, sys
sys.path.insert(0, {os.path.dirname(DC)!r})
import displayctl as dc
tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx.arm(1)
os.kill(os.getpid(), 9)   # 부모(TUI/터미널)가 갑자기 죽는 상황
"""])
check("적용 직후 부모 프로세스가 죽은 상태", pending() and mons()["DP-4"].width == 1280)
_t.sleep(3)
check("부모가 죽어도 타이머가 되돌림 (핵심)", mons()["DP-4"].width == 3840 and not pending(), f"{mons()['DP-4'].width}")

reset(); tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx.arm(60); kill_units()  # 타이머가 사라진 상태(재부팅/재로그인) 흉내
run("restore")
check("확인 전 재로그인(restore): 변경을 복원하지 않고 이전 구성으로 되돌림", mons()["DP-4"].width == 3840 and not pending() and dc.load_state() is None)

reset(); run("layout", "mirror"); run("revert-pending")
check("대기 기록이 없으면 revert-pending 은 아무것도 안 함", mons()["eDP-1"].mirror_of == "DP-4" and dc.load_state()["layout"] == "mirror")

reset(); tx1 = dc.Transaction(); tx1.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx1.arm(60)
tx2 = dc.Transaction(); tx2.apply(dc.op_set("DP-4", "1600x900", 60, None, None)); tx2.arm(1); _t.sleep(3)
check("확인 전에 또 변경해도 처음(마지막으로 확인된) 구성으로 되돌림", mons()["DP-4"].width == 3840 and not pending(), f"{mons()['DP-4'].width}")

reset(); tx = dc.Transaction(); tx.apply(dc.op_set("DP-4", "1280x720", 60, None, None)); tx.arm(60)
run("confirm")
check("다른 프로세스에서 `displayctl confirm`: 유지 + 구성 저장 + 타이머 취소", mons()["DP-4"].width == 1280 and not pending() and dc.load_state()["monitors"]["DP-4"]["mode"].startswith("1280x720"))
_t.sleep(0.3)

reset(); r = subprocess.run(["sh", "-c", f"echo | {sys.executable} -I {DC} set DP-4 --res 1280x720 --hz 60 --confirm 2"], capture_output=True, text=True)
check("CLI set --confirm: Enter 를 누르면 유지", mons()["DP-4"].width == 1280 and not pending(), r.stderr[-120:])
reset(); r = subprocess.run(["sh", "-c", f"{sys.executable} -I {DC} set DP-4 --res 1280x720 --hz 60 --confirm 2 < /dev/null"], capture_output=True, text=True)
check("CLI set --confirm: 입력 없이 닫힘(EOF)은 확인으로 보지 않고 되돌림", mons()["DP-4"].width == 3840 and not pending(), r.stderr[-120:])
reset(); r = subprocess.run(["sh", "-c", f"sleep 4 | {sys.executable} -I {DC} set DP-4 --res 1280x720 --hz 60 --confirm 2"], capture_output=True, text=True)
check("CLI set --confirm: 시간 안에 입력이 없으면 되돌림", mons()["DP-4"].width == 3840 and not pending(), r.stderr[-120:])
kill_units()

# ───── 화면 회전 ─────
def setpos(mode, rot):
    json.dump({"mode": mode, "rotation": rot}, open(os.environ["TESTS_TMP"] + "/posture.json", "w"))
def overlaps(): return [l for l in open(FS + ".events").read().splitlines() if "OVERLAP" in l] if os.path.exists(FS + ".events") else []
reset(); run("layout", "extend"); rc = run("rotate", "1"); m = mons()
check("rotate 1: 내장 화면 transform=1, 상태에 기록", rc == 0 and m["eDP-1"].transform == 1 and dc.load_state()["monitors"]["eDP-1"]["transform"] == 1)
check("회전하면 확장 배치가 회전된 논리 크기(1600x2560)로 다시 계산돼 외장이 가운데 위에(x=(1600-3840)/2)", (m["DP-4"].x, m["DP-4"].y) == (-1120, -2560), str((m["DP-4"].x, m["DP-4"].y)))
check("회전해도 모니터끼리 겹치지 않음", not overlaps(), str(overlaps()))
run("layout", "internal"); check("레이아웃을 바꿔도 회전이 유지됨", mons()["eDP-1"].transform == 1)
run("layout", "extend"); run("restore"); check("restore 해도 회전이 유지됨(되돌리지 않음)", mons()["eDP-1"].transform == 1)
reset(); run("layout", "extend"); run("rotate", "3"); calls_before = len(open(FS + ".events").read().splitlines()) if os.path.exists(FS + ".events") else 0
run("rotate", "3"); calls_after = len(open(FS + ".events").read().splitlines()) if os.path.exists(FS + ".events") else 0
check("이미 그 방향이면 아무것도 적용하지 않음(깜빡임 방지)", calls_before == calls_after, f"{calls_before} {calls_after}")
check("rotate 잘못된 값은 거부(2)", run("rotate", "7") == 2 and run("rotate", "x") == 2)
reset(); run("layout", "extend"); setpos("tablet", 90); run("rotate", "auto"); check("rotate auto: tablet 에서 기기 시계 90° → transform 1", mons()["eDP-1"].transform == 1)
setpos("tablet", 270); run("rotate", "auto"); check("rotate auto: 270° → transform 3", mons()["eDP-1"].transform == 3)
setpos("tablet", 180); run("rotate", "auto"); check("rotate auto: 180° → transform 2", mons()["eDP-1"].transform == 2)
setpos("laptop", 90); run("rotate", "auto"); check("rotate auto: laptop 이면 회전값과 무관하게 0 으로 복귀", mons()["eDP-1"].transform == 0)
setpos("tablet", 90); run("rotate", "auto"); run("layout", "external"); rc = run("rotate", "auto")
check("꺼진 내장 화면은 회전하지 않음(오류 없이)", rc == 0 and mons()["eDP-1"].disabled)
reset(); run("layout", "mirror"); setpos("tablet", 90); rc = run("rotate", "auto")
check("미러인 내장 화면은 회전하지 않음", rc == 0 and mons()["eDP-1"].transform == 0)
def devlog(): return [l for l in open(FS + ".events").read().splitlines() if l.startswith("device ")] if os.path.exists(FS + ".events") else []
reset(); run("layout", "extend"); run("rotate", "1"); dl = devlog()
check("회전하면 터치스크린과 스타일러스 transform 도 같은 값(1)으로(터치가 화면을 따라 돎)", "device elan-touchscreen transform=1" in dl and "device elan-touchscreen-stylus transform=1" in dl, str(dl))
check("터치패드(mice)는 건드리지 않음", not any("touchpad" in l for l in dl), str(dl))
run("rotate", "0"); check("0 으로 돌리면 터치도 0", "device elan-touchscreen transform=0" in devlog()[-2:] or "device elan-touchscreen transform=0" in devlog(), str(devlog()))
run("rotate", "3"); run("restore"); check("restore(reload 뒤)에도 터치 transform 을 다시 맞춤", devlog()[-2:] == ["device elan-touchscreen transform=3", "device elan-touchscreen-stylus transform=3"], str(devlog()[-3:]))
reset(); run("layout", "internal"); run("rotate", "2"); run("layout", "external"); run("restore")
check("내장 화면이 꺼지면 터치 transform 은 0", devlog()[-1] == "device elan-touchscreen-stylus transform=0", str(devlog()[-2:]))
check("target_transform 순수 함수: laptop 은 항상 0", dc.target_transform(90, "laptop") == 0 and dc.target_transform(270, "tent") == 3 and dc.target_transform(45, "tablet") == 0)

r = subprocess.run([sys.executable, "-I", DC, "rotate", "auto"], capture_output=True, text=True, env=dict(os.environ, DISPLAYCTL_HYPRCTL=os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_hyprctl_down.sh")))
check("컴포지터가 없어 hyprctl 이 JSON 이 아닌 문장을 내도 rotate auto 는 오류 없이 종료(0)", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-120:])

# ── PC(내장 패널 없음): 첫 모니터가 메인, 나머지가 보조 ──
reset()
base = json.load(open(FS)) if os.path.exists(FS) else None
if base is None:
    run("layout", "extend"); base = json.load(open(FS))
for d, n in zip(base, ("DP-1", "DP-2")):
    d["name"] = n
d1, d2 = base
d1.update(x=0, y=0, width=2560, height=1600, refreshRate=60.0, availableModes=["2560x1600@60.00Hz"]); d2.update(x=0, y=-2560)
json.dump(base, open(FS, "w"))
mm = dc.get_monitors()
check("PC: 내장이 없으면 노트북 판정이 아님", not dc.has_internal(mm))
mains, subs = dc.split_roles(mm)
check("PC: 첫 모니터가 메인, 나머지가 보조", [m.name for m in mains] == ["DP-1"] and [m.name for m in subs] == ["DP-2"])
cfg, lay = dc.build(mm, dc.default_state())
check("PC: 기본 확장은 보조가 메인 오른쪽(노트북의 '외부 위' 기본이 아님)", cfg["DP-2"]["x"] == 2560 and cfg["DP-2"]["y"] == (1600 - 2560) // 2, str(cfg))
check("PC: 배치 기본값은 right", dc.current_arrange(None, mm) == "right")
cfg, lay = dc.build(mm, {**dc.default_state(), "layout": "mirror"})
check("PC: 미러는 메인이 보조를 복제", cfg["DP-1"].get("mirror") == "DP-2" and "mirror" not in cfg["DP-2"], str(cfg))
st = dc.op_layout("extend", "stack")
check("PC: 보조 위/메인 아래 배치", st["pos"]["DP-2"] == {"rel": "above", "of": "DP-1", "align": "center"}, str(st["pos"]))
check("PC: 배치를 정한 뒤 current_arrange 가 stack", dc.current_arrange(st, mm) == "stack")

finish("코어")
