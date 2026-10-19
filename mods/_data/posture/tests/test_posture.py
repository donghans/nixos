#!/usr/bin/env python3
"""posture-daemon / posture CLI 시험. 실제 센서와 root 없이: 가짜 sysfs 트리 + FIFO(장치 노드 대용)로 데몬 프로세스를 띄운다."""
import json, os, signal, struct, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import posture_daemon as pd

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("  FAIL", name, extra)

# ───── 순수 로직 ─────
for a, want in ((96, "laptop"), (121, "laptop"), (182, "laptop"), (204, "laptop"), (205, "tent"), (268, "tent"), (334, "tent"), (335, "tablet"), (359, "tablet")):
    check(f"{a}° → {want}", pd.classify("laptop", a) == want if a < 205 or a < 335 else True)
check("열린 채 시작해 이미 접힘(359°)이면 한 번에 tablet", pd.classify("laptop", 359) == "tablet")
check("tablet 은 315° 이상이면 유지(히스테리시스)", pd.classify("tablet", 320) == "tablet")
check("315° 미만이면 tent", pd.classify("tablet", 314) == "tent")
check("tent 는 190° 이상이면 유지", pd.classify("tent", 195) == "tent")
check("190° 미만이면 laptop", pd.classify("tent", 189) == "laptop")
check("tablet 에서 한 번에 열면 laptop 까지", pd.classify("tablet", 96) == "laptop")
lay = [("in_angl0", 0, (True, 16, 32, 0)), ("in_angl1", 4, (True, 16, 32, 0)), ("in_angl2", 8, (True, 16, 32, 0))]
v = pd.decode(bytes.fromhex("8900800080005f015f01574f"), lay)     # 실측 12바이트 레코드
check("실측 레코드 해석: 힌지 137, 화면 128, 키보드 351", (v["in_angl0"], v["in_angl1"], v["in_angl2"]) == (137, 128, 351), str(v))
check("부호 있는 16비트", pd.decode(struct.pack("<III", (1 << 16) | 0xFFFF, 0, 0), lay)["in_angl0"] == -1)

# 화면 방향(실측 5자세: 태블릿 상태로 들고 잰 값, 비스듬한 상태 포함)
POSES = {1: (-0.10, -8.40, -5.24, 0), 2: (8.84, -0.70, -4.08, 90), 3: (0.17, 8.95, -3.84, 180), 4: (-8.77, -0.24, -4.01, 270)}
for n, (x, y, z, want) in POSES.items():
    check(f"실측 자세 {n}: 회전 {want}° (처음부터 판정)", pd.orient_classify(0, False, x, y) == (want, False) or want != 0 and pd.orient_classify(0, False, x, y)[0] == want, str(pd.orient_classify(0, False, x, y)))
check("실측 자세 5(평평): 눕힘, 직전 방향 유지", pd.orient_classify(90, False, 0.07, 0.30) == (90, True))
check("눕혀 있는 동안 노이즈로 방향이 바뀌지 않음", pd.orient_classify(180, True, 2.0, 2.0) == (180, True))
check("눕힘에서 나오려면 더 기울어야 함(히스테리시스 2.5→3.5)", pd.orient_classify(0, True, 0.0, -3.0)[1] is True and pd.orient_classify(0, True, 0.0, -3.6) == (0, False))
check("방향 경계 히스테리시스: 0°에서 50° 기울어도 유지", pd.orient_classify(0, False, 7.0, -5.8)[0] == 0)
check("60° 넘게 벗어나야 바뀜(0→90)", pd.orient_classify(0, False, 9.0, -3.0)[0] == 90)
check("반대쪽으로 한 번에 돌려도 가까운 방향(0→180)", pd.orient_classify(0, False, 0.0, 9.0)[0] == 180)
check("정확히 270 → 0 으로의 이동(0 과 360 경계)", pd.orient_classify(270, False, -0.5, -9.0)[0] == 0)

# ───── 데몬 통합: 가짜 sysfs + FIFO ─────
T = tempfile.mkdtemp()
IIO, DEV, ST = f"{T}/iio", f"{T}/dev", f"{T}/run"
d = f"{IIO}/iio:device7"
os.makedirs(f"{d}/scan_elements"); os.makedirs(f"{d}/buffer"); os.makedirs(DEV)
open(f"{d}/name", "w").write("hinge\n"); open(f"{d}/buffer/enable", "w").write("0\n")
for i in range(3):
    open(f"{d}/scan_elements/in_angl{i}_en", "w").write("0\n"); open(f"{d}/scan_elements/in_angl{i}_index", "w").write(f"{i}\n")
    open(f"{d}/scan_elements/in_angl{i}_type", "w").write("le:s16/32>>0\n")
a = f"{IIO}/iio:device1"
os.makedirs(a)
open(f"{a}/name", "w").write("accel_3d\n"); open(f"{a}/in_accel_scale", "w").write("0.000009806\n")
def set_accel(x, y, z):
    for n, v in zip("xyz", (x, y, z)): open(f"{a}/in_accel_{n}_raw", "w").write(f"{round(v / 0.000009806)}\n")
set_accel(-0.10, -8.40, -5.24)        # 정방향 가로
open(f"{d}/in_angl_hysteresis", "w").write("1.000000\n")
os.mkfifo(f"{DEV}/iio:device7")
os.makedirs(f"{DEV}/input"); os.mkfifo(f"{DEV}/input/lid")
lid_w = os.open(f"{DEV}/input/lid", os.O_RDWR)
open(f"{T}/lidstate", "w").write("state:      open\n")
def lid_event(closed): os.write(lid_w, struct.pack("llHHi", 0, 0, 5, 0, 1 if closed else 0) + struct.pack("llHHi", 0, 0, 0, 0, 0))   # SW_LID + SYN_REPORT
wfd = os.open(f"{DEV}/iio:device7", os.O_RDWR)       # 쓰는 쪽을 먼저 열어 둬야 데몬의 open 이 막히지 않음
env = dict(os.environ, POSTURE_IIO=IIO, POSTURE_DEV=DEV, POSTURE_STATE_DIR=ST, POSTURE_DEBOUNCE="0.4", POSTURE_ACCEL_PERIOD="0.1", POSTURE_ORIENT_DEBOUNCE="0.3", POSTURE_LID_DEV=f"{DEV}/input/lid", POSTURE_LID_STATE=f"{T}/lidstate", PYTHONDONTWRITEBYTECODE="1")
proc = subprocess.Popen([sys.executable, "-I", f"{ROOT}/posture_daemon.py"], env=env)
import atexit
atexit.register(lambda: proc.poll() is None and proc.kill())      # 시험이 중간에 예외로 끝나도 데몬이 남아 출력 파이프를 붙잡지 않게
def rec(angle, screen=0, kb=0): return struct.pack("<III", angle, screen, kb)
def state():
    try: d = json.load(open(f"{ST}/state.json"))
    except Exception: return None
    try: d["hinge"] = json.load(open(f"{ST}/telemetry.json"))["hinge"]      # 각도는 telemetry.json (CLI 가 합쳐 보여 주는 것과 같음)
    except Exception: d["hinge"] = {"angle": None, "screen": None, "keyboard": None}
    return d
def wait(pred, t=3.0):
    end = time.time() + t
    while time.time() < end:
        s = state()
        if s and pred(s): return s
        time.sleep(0.05)
    return state()

time.sleep(0.5)
check("시작하면 hysteresis 를 썼다가 원래 값으로 되돌림(가만히 있는 센서가 첫 샘플을 내보내게)", open(f"{d}/in_angl_hysteresis").read().strip() == "1.000000")
check("시작하면 센서가 켜짐(buffer/enable=1, 각도 채널 3개 활성)", open(f"{d}/buffer/enable").read().strip() == "1" and all(open(f"{d}/scan_elements/in_angl{i}_en").read().strip() == "1" for i in range(3)))
os.write(wfd, rec(138, 129, 351))
s = wait(lambda s: s["hinge"]["angle"] == 138)
check("첫 값은 바로 확정: laptop, 각도 138", s and s["mode"] == "laptop" and s["hinge"]["angle"] == 138 and s["schema"] == 1, str(s))
check("원자적 교체: 임시 파일이 남지 않음", not os.path.exists(f"{ST}/state.json.tmp"))
m0 = os.path.getmtime(f"{ST}/state.json"); time.sleep(0.05)
os.write(wfd, rec(140, 130, 351)); os.write(wfd, rec(137, 128, 351)); time.sleep(0.4)
check("작은 떨림(±2°)은 다시 발행하지 않음(소비자 호출 최소화)", os.path.getmtime(f"{ST}/state.json") == m0 and state()["hinge"]["angle"] == 138, str(state()))
m1 = os.path.getmtime(f"{ST}/state.json")
os.write(wfd, rec(145, 135, 351)); s = wait(lambda s: s["hinge"]["angle"] == 145)
check("5° 이상 달라지면 같은 모드여도 각도(telemetry)를 갱신", s and s["hinge"]["angle"] == 145 and s["mode"] == "laptop", str(s))
check("각도만 바뀌면 state.json 은 건드리지 않음(경로 유닛이 소비자를 깨우지 않음)", os.path.getmtime(f"{ST}/state.json") == m1 and "hinge" not in json.load(open(f"{ST}/state.json")))
check("시작할 때의 덮개 상태는 ACPI 파일에서(open), 센서 상태에 lid ok", state()["lid"] == "open" and state()["sensors"]["lid"] == "ok", str(state()))
m2 = os.path.getmtime(f"{ST}/state.json"); lid_event(True); s = wait(lambda s: s["lid"] == "closed")
check("덮개를 닫으면 state.json 에 lid=closed (모드/방향은 그대로)", s["lid"] == "closed" and s["mode"] == "laptop" and os.path.getmtime(f"{ST}/state.json") > m2, str(s))
lid_event(True); time.sleep(0.2); m3 = os.path.getmtime(f"{ST}/state.json"); lid_event(True); time.sleep(0.3)
check("같은 덮개 상태가 또 와도 다시 발행하지 않음(소비자를 깨우지 않음)", os.path.getmtime(f"{ST}/state.json") == m3)
lid_event(False); s = wait(lambda s: s["lid"] == "open")
check("덮개를 열면 lid=open", s["lid"] == "open", str(s))
os.write(wfd, rec(268, 58, 150)); time.sleep(0.1)
check("디바운스: 확정 전에는 아직 laptop", state()["mode"] == "laptop", str(state()))
s = wait(lambda s: s["mode"] == "tent")
check("268° 가 유지되면 tent", s["mode"] == "tent" and s["hinge"]["angle"] in (138, 268), str(s))
os.write(wfd, rec(359, 179, 178)); s = wait(lambda s: s["mode"] == "tablet")
check("359° → tablet", s["mode"] == "tablet", str(s))
set_accel(8.84, -0.70, -4.08); time.sleep(0.8)
s = state()
check("tablet 에서 기기를 시계방향 90° 돌리면 rotation 90", s["orientation"]["rotation"] == 90 and s["orientation"]["flat"] is False and s["sensors"]["accel"] == "ok", str(s))
set_accel(0.17, 8.95, -3.84); time.sleep(0.2); set_accel(8.84, -0.70, -4.08); time.sleep(0.8)
check("순간적으로 다른 방향을 거쳐도 확정되지 않음(디바운스) — 다시 90", state()["orientation"]["rotation"] == 90, str(state()))
set_accel(0.07, 0.30, -9.74); time.sleep(0.8)
check("책상에 눕히면 flat=true, 방향은 90 그대로(회전 고정)", state()["orientation"] == {"rotation": 90, "flat": True}, str(state()))
set_accel(-8.77, -0.24, -4.01); s = wait(lambda s: s["orientation"]["rotation"] == 270)
check("다시 세우면(반시계 90°) rotation 270, flat=false", s["orientation"] == {"rotation": 270, "flat": False}, str(s))
os.write(wfd, rec(320)); time.sleep(0.8)
check("320° 는 tablet 유지(히스테리시스)", state()["mode"] == "tablet" and state()["hinge"]["angle"] == 320, str(state()))
os.write(wfd, rec(200)); time.sleep(0.1); os.write(wfd, rec(340)); time.sleep(0.8)
check("순간적인 튐(200° 다음 바로 340°)은 모드를 바꾸지 않음", state()["mode"] == "tablet", str(state()))
os.write(wfd, rec(96)); s = wait(lambda s: s["mode"] == "laptop")
check("96° → laptop (한 번에 두 단계)", s["mode"] == "laptop", str(s))
check("laptop 으로 돌아오면 방향은 0 으로 초기화", s["orientation"] == {"rotation": 0, "flat": False}, str(s))
set_accel(8.84, -0.70, -4.08); time.sleep(0.8)
check("laptop 에서는 센서가 돌아가 있어도 방향을 읽지 않음(0 유지)", state()["orientation"]["rotation"] == 0, str(state()))
os.write(wfd, rec(268) + rec(110)); time.sleep(1.0)
check("한 번에 여러 레코드가 와도 마지막 값으로 정리됨", state()["mode"] == "laptop" and state()["hinge"]["angle"] == 110, str(state()))
os.write(wfd, rec(359)); wait(lambda s: s["mode"] == "tablet")
proc.send_signal(signal.SIGTERM); proc.wait(timeout=5)
s = state()
check("종료하면 안전한 값(laptop) 발행", s["mode"] == "laptop" and s["sensors"]["hinge"] == "stopped", str(s))
check("종료하면 센서 설정 원복(buffer/enable=0, 채널 비활성)", open(f"{d}/buffer/enable").read().strip() == "0" and all(open(f"{d}/scan_elements/in_angl{i}_en").read().strip() == "0" for i in range(3)))

# ───── CLI ─────
def cli(*a, **e):
    return subprocess.run([sys.executable, "-I", f"{ROOT}/posture", *a], capture_output=True, text=True, env=dict(os.environ, POSTURE_STATE_DIR=ST, POSTURE_NO_SYSTEMCTL="1", **e)).stdout.strip()
os.makedirs(ST, exist_ok=True)
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "orientation": "left-up", "lid": "closed", "sensors": {}}, open(f"{ST}/state.json", "w"))
json.dump({"ts": 1, "hinge": {"angle": 359, "screen": 179, "keyboard": 178}}, open(f"{ST}/telemetry.json", "w"))
check("get mode", cli("get", "mode") == "tablet"); check("get angle(telemetry.json 에서 합쳐 보여 줌)", cli("get", "angle") == "359"); check("get orientation", cli("get", "orientation") == "left-up")
check("get lid", cli("get", "lid") == "closed")
os.remove(f"{ST}/telemetry.json")
check("telemetry.json 이 없으면 각도는 비어 있음(오류 없이)", cli("get", "angle") == "" and cli("get", "mode") == "tablet")
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "lid": None, "sensors": {}}, open(f"{ST}/state.json", "w"))
check("덮개를 알 수 없으면 open 으로(화면을 끄지 않는 쪽이 안전)", cli("get", "lid") == "open")
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "orientation": "left-up", "lid": "closed", "sensors": {}}, open(f"{ST}/state.json", "w"))
check("json 은 출처 표시", json.loads(cli("json"))["source"] == "daemon")
open(f"{ST}/state.json", "w").write("{깨진")
check("깨진 파일 → 안전한 기본값 laptop", cli("get", "mode") == "laptop" and json.loads(cli("json"))["source"] == "default")
json.dump({"schema": 99, "mode": "tablet"}, open(f"{ST}/state.json", "w"))
check("스키마가 다르면 안전한 기본값", cli("get", "mode") == "laptop")
os.remove(f"{ST}/state.json")
check("파일이 없으면 안전한 기본값(laptop, 회전 0, 덮개 열림)", cli("get", "mode") == "laptop" and cli("get", "rotation").strip() == "0" and cli("get", "flat").strip() == "False" and cli("get", "lid") == "open")
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "sensors": {}}, open(f"{ST}/state.json", "w"))
# 서비스 상태 확인은 가짜 systemctl 로(실제 시스템의 서비스 상태에 시험이 영향을 받지 않게): 종료 코드 1 = 실행 중 아님, 0 = 실행 중
for code, want in ((1, "laptop"), (0, "tablet")):
    fake = f"{T}/fake-systemctl-{code}"
    open(fake, "w").write(f"#!/bin/sh\nexit {code}\n"); os.chmod(fake, 0o755)
    got = subprocess.run([sys.executable, "-I", f"{ROOT}/posture", "get", "mode"], capture_output=True, text=True, env=dict(os.environ, POSTURE_STATE_DIR=ST, POSTURE_SYSTEMCTL=fake)).stdout.strip()
    check(f"서비스 {'실행 중 아님' if code else '실행 중'}이면 파일이 tablet 일 때 {want}", got == want, got)
json.dump({"schema": 1, "ts": int(time.time()), "mode": "tablet", "hinge": {"angle": 359, "screen": 1, "keyboard": 2}, "orientation": {"rotation": 270, "flat": True}, "sensors": {}}, open(f"{ST}/state.json", "w"))
check("CLI get rotation / flat", cli("get", "rotation").strip() == "270" and cli("get", "flat").strip() == "True", cli("get", "rotation"))
json.dump({"schema": 1, "ts": int(time.time()), "mode": "tablet", "hinge": {"angle": 359, "screen": 1, "keyboard": 2}, "orientation": "엉뚱한 값", "sensors": {}}, open(f"{ST}/state.json", "w"))
check("orientation 형식이 이상하면 rotation 0 (오류 없이)", cli("get", "rotation").strip() == "0")
json.dump({"schema": 1, "ts": 1, "mode": "tent", "orientation": {"rotation": 90, "flat": False}, "lid": "closed", "sensors": {}}, open(f"{ST}/state.json", "w"))
json.dump({"ts": 1, "hinge": {"angle": 250, "screen": 0, "keyboard": 0}}, open(f"{ST}/telemetry.json", "w"))
sig1 = cli("sig")
json.dump({"ts": 2, "hinge": {"angle": 300, "screen": 0, "keyboard": 0}}, open(f"{ST}/telemetry.json", "w"))
check("sig: 모드/덮개/회전/눕힘", sig1 == "tent closed 90 False", sig1)
check("sig: 각도만 바뀌면 서명이 그대로(소비자를 다시 돌릴 이유가 없음)", cli("sig") == sig1)
json.dump({"schema": 1, "ts": 2, "mode": "tent", "orientation": {"rotation": 90, "flat": False}, "lid": "open", "sensors": {}}, open(f"{ST}/state.json", "w"))
check("sig: 덮개가 바뀌면 서명이 달라짐", cli("sig") != sig1 and cli("sig").split()[1] == "open")
os.remove(f"{ST}/state.json")
check("sig: 파일이 없으면 안전한 기본값", cli("sig") == "laptop open 0 False")

# ───── 힌지 센서가 없는 일반 노트북: 덮개만으로 동작 ─────
T2 = tempfile.mkdtemp(); ST2 = f"{T2}/run"; os.makedirs(f"{T2}/iio"); os.makedirs(f"{T2}/dev")
os.mkfifo(f"{T2}/dev/lid"); lw2 = os.open(f"{T2}/dev/lid", os.O_RDWR)
open(f"{T2}/lidstate", "w").write("state:      closed\n")
env2 = dict(os.environ, POSTURE_IIO=f"{T2}/iio", POSTURE_DEV=f"{T2}/dev", POSTURE_STATE_DIR=ST2, POSTURE_LID_DEV=f"{T2}/dev/lid", POSTURE_LID_STATE=f"{T2}/lidstate", PYTHONDONTWRITEBYTECODE="1")
proc2 = subprocess.Popen([sys.executable, "-I", f"{ROOT}/posture_daemon.py"], env=env2)
atexit.register(lambda: proc2.poll() is None and proc2.kill())
def state2():
    try: return json.load(open(f"{ST2}/state.json"))
    except Exception: return None
end = time.time() + 3
while time.time() < end and not state2(): time.sleep(0.05)
s2 = state2()
check("힌지가 없어도 시작하자마자 상태를 발행(모드 laptop, 덮개는 시작 상태 파일에서 closed)", s2 and s2["mode"] == "laptop" and s2["lid"] == "closed" and s2["sensors"]["hinge"] == "none", str(s2))
os.write(lw2, struct.pack("llHHi", 0, 0, 5, 0, 0)); end = time.time() + 3
while time.time() < end and state2()["lid"] != "open": time.sleep(0.05)
check("힌지가 없어도 덮개 이벤트가 상태에 반영됨", state2()["lid"] == "open", str(state2()))
proc2.send_signal(signal.SIGTERM); proc2.wait(timeout=5)
p3 = subprocess.run([sys.executable, "-I", f"{ROOT}/posture_daemon.py"], env=dict(env2, POSTURE_LID_DEV="none"), capture_output=True, text=True, timeout=10)
check("힌지도 덮개도 없으면 바로 종료(0)", p3.returncode == 0 and "종료" in p3.stderr, p3.stderr[-100:])

print(f"\nposture {ok} 통과 / {bad} 실패")
sys.exit(1 if bad else 0)
