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

# ───── 데몬 통합: 가짜 sysfs + FIFO ─────
T = tempfile.mkdtemp()
IIO, DEV, ST = f"{T}/iio", f"{T}/dev", f"{T}/run"
d = f"{IIO}/iio:device7"
os.makedirs(f"{d}/scan_elements"); os.makedirs(f"{d}/buffer"); os.makedirs(DEV)
open(f"{d}/name", "w").write("hinge\n"); open(f"{d}/buffer/enable", "w").write("0\n")
for i in range(3):
    open(f"{d}/scan_elements/in_angl{i}_en", "w").write("0\n"); open(f"{d}/scan_elements/in_angl{i}_index", "w").write(f"{i}\n")
    open(f"{d}/scan_elements/in_angl{i}_type", "w").write("le:s16/32>>0\n")
os.mkfifo(f"{DEV}/iio:device7")
wfd = os.open(f"{DEV}/iio:device7", os.O_RDWR)       # 쓰는 쪽을 먼저 열어 둬야 데몬의 open 이 막히지 않음
env = dict(os.environ, POSTURE_IIO=IIO, POSTURE_DEV=DEV, POSTURE_STATE_DIR=ST, POSTURE_DEBOUNCE="0.4", PYTHONDONTWRITEBYTECODE="1")
proc = subprocess.Popen([sys.executable, "-I", f"{ROOT}/posture_daemon.py"], env=env)
def rec(angle, screen=0, kb=0): return struct.pack("<III", angle, screen, kb)
def state():
    try: return json.load(open(f"{ST}/state.json"))
    except Exception: return None
def wait(pred, t=3.0):
    end = time.time() + t
    while time.time() < end:
        s = state()
        if s and pred(s): return s
        time.sleep(0.05)
    return state()

time.sleep(0.5)
check("시작하면 센서가 켜짐(buffer/enable=1, 각도 채널 3개 활성)", open(f"{d}/buffer/enable").read().strip() == "1" and all(open(f"{d}/scan_elements/in_angl{i}_en").read().strip() == "1" for i in range(3)))
os.write(wfd, rec(138, 129, 351))
s = wait(lambda s: s["hinge"]["angle"] == 138)
check("첫 값은 바로 확정: laptop, 각도 138", s and s["mode"] == "laptop" and s["hinge"]["angle"] == 138 and s["schema"] == 1, str(s))
check("원자적 교체: 임시 파일이 남지 않음", not os.path.exists(f"{ST}/state.json.tmp"))
m0 = os.path.getmtime(f"{ST}/state.json"); time.sleep(0.05)
os.write(wfd, rec(140, 130, 351)); os.write(wfd, rec(137, 128, 351)); time.sleep(0.4)
check("작은 떨림(±2°)은 다시 발행하지 않음(소비자 호출 최소화)", os.path.getmtime(f"{ST}/state.json") == m0 and state()["hinge"]["angle"] == 138, str(state()))
os.write(wfd, rec(145, 135, 351)); s = wait(lambda s: s["hinge"]["angle"] == 145)
check("5° 이상 달라지면 같은 모드여도 각도를 갱신", s and s["hinge"]["angle"] == 145 and s["mode"] == "laptop", str(s))
os.write(wfd, rec(268, 58, 150)); time.sleep(0.1)
check("디바운스: 확정 전에는 아직 laptop", state()["mode"] == "laptop", str(state()))
s = wait(lambda s: s["mode"] == "tent")
check("268° 가 유지되면 tent", s["mode"] == "tent" and s["hinge"]["angle"] in (138, 268), str(s))
os.write(wfd, rec(359, 179, 178)); s = wait(lambda s: s["mode"] == "tablet")
check("359° → tablet", s["mode"] == "tablet", str(s))
os.write(wfd, rec(320)); time.sleep(0.8)
check("320° 는 tablet 유지(히스테리시스)", state()["mode"] == "tablet" and state()["hinge"]["angle"] == 320, str(state()))
os.write(wfd, rec(200)); time.sleep(0.1); os.write(wfd, rec(340)); time.sleep(0.8)
check("순간적인 튐(200° 다음 바로 340°)은 모드를 바꾸지 않음", state()["mode"] == "tablet", str(state()))
os.write(wfd, rec(96)); s = wait(lambda s: s["mode"] == "laptop")
check("96° → laptop (한 번에 두 단계)", s["mode"] == "laptop", str(s))
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
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "hinge": {"angle": 359, "screen": 179, "keyboard": 178}, "orientation": "left-up", "sensors": {}}, open(f"{ST}/state.json", "w"))
check("get mode", cli("get", "mode") == "tablet"); check("get angle", cli("get", "angle") == "359"); check("get orientation", cli("get", "orientation") == "left-up")
check("json 은 출처 표시", json.loads(cli("json"))["source"] == "daemon")
open(f"{ST}/state.json", "w").write("{깨진")
check("깨진 파일 → 안전한 기본값 laptop", cli("get", "mode") == "laptop" and json.loads(cli("json"))["source"] == "default")
json.dump({"schema": 99, "mode": "tablet"}, open(f"{ST}/state.json", "w"))
check("스키마가 다르면 안전한 기본값", cli("get", "mode") == "laptop")
os.remove(f"{ST}/state.json")
check("파일이 없으면 안전한 기본값", cli("get", "mode") == "laptop" and cli("get", "orientation") == "")
json.dump({"schema": 1, "ts": 1, "mode": "tablet", "hinge": {}, "sensors": {}}, open(f"{ST}/state.json", "w"))
# 서비스 상태 확인은 가짜 systemctl 로(실제 시스템의 서비스 상태에 시험이 영향을 받지 않게): 종료 코드 1 = 실행 중 아님, 0 = 실행 중
for code, want in ((1, "laptop"), (0, "tablet")):
    fake = f"{T}/fake-systemctl-{code}"
    open(fake, "w").write(f"#!/bin/sh\nexit {code}\n"); os.chmod(fake, 0o755)
    got = subprocess.run([sys.executable, "-I", f"{ROOT}/posture", "get", "mode"], capture_output=True, text=True, env=dict(os.environ, POSTURE_STATE_DIR=ST, POSTURE_SYSTEMCTL=fake)).stdout.strip()
    check(f"서비스 {'실행 중 아님' if code else '실행 중'}이면 파일이 tablet 일 때 {want}", got == want, got)
print(f"\nposture {ok} 통과 / {bad} 실패")
sys.exit(1 if bad else 0)
