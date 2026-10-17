#!/usr/bin/env python3
"""vkb CLI 통합 시험: 가짜 hyprctl/systemctl/posture 로 show/hide/size/auto/apply-posture 흐름을 확인."""
import json, os, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
T = tempfile.mkdtemp()
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("  FAIL", name, extra)
def script(name, body):
    p = f"{T}/{name}"; open(p, "w").write("#!/usr/bin/env python3\n" + body); os.chmod(p, 0o755); return p

# 가짜 hyprctl: clients/monitors/layers 는 파일에서, dispatch 는 호출 기록
open(f"{T}/clients.json", "w").write(json.dumps([
    {"address": "0xb", "at": [100, 700], "size": [800, 700], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0},
    {"address": "0xa", "at": [100, 100], "size": [800, 400], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0}]))
open(f"{T}/monitors.json", "w").write(json.dumps([{"id": 0, "name": "eDP-1", "x": 0, "y": 0, "focused": True}]))
hypr = script("hyprctl", f'''
import sys, json, os
T = "{T}"; a = sys.argv[1:]
if a[0] == "dispatch": open(T + "/calls.log", "a").write(a[1] + "\\n"); sys.exit(0)
if a[0] == "layers": print(json.dumps({{"eDP-1": {{"levels": {{"3": ([{{"namespace": "wvkbd", "x": 0, "y": 1240, "w": 2560, "h": 360}}] if os.path.exists(T + "/visible") else [])}}}}}})); sys.exit(0)
print(open(T + "/" + a[0] + ".json").read())
''')
# 가짜 systemctl: 시그널로 가시성 플래그를 바꿈, restart 는 기록
sysctl = script("systemctl", f'''
import sys, os
T = "{T}"; a = sys.argv[1:]
if "show" in a: print("4242"); sys.exit(0)
if "is-active" in a: sys.exit(0)
if "restart" in a: open(T + "/restarts.log", "a").write("restart\\n"); os.path.exists(T + "/visible") and os.remove(T + "/visible"); sys.exit(0)
if "kill" in a:
    sig = [x for x in a if x.startswith("--signal=")][0].split("=")[1]
    open(T + "/signals.log", "a").write(sig + "\\n")
    if sig == "SIGUSR2": open(T + "/visible", "w").close()
    elif sig == "SIGUSR1" and os.path.exists(T + "/visible"): os.remove(T + "/visible")
    sys.exit(0)
''')
pkill = script("pkill", f'''
import sys
open("{T}/pkill.log", "a").write(" ".join(sys.argv[1:]) + "\\n")
''')
posture = script("posture", 'import os,sys; print(open(os.environ["FAKE_MODE_FILE"]).read().strip())')
env = dict(os.environ, PATH=T + os.pathsep + os.environ["PATH"], VKB_HYPRCTL=hypr, VKB_SYSTEMCTL=sysctl, VKB_POSTURE=posture, VKB_CONFIG_DIR=f"{T}/conf", VKB_STATE_DIR=f"{T}/state", FAKE_MODE_FILE=f"{T}/mode", PYTHONDONTWRITEBYTECODE="1")
def vkb(*a): return subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", *a], capture_output=True, text=True, env=env)
def log(n): return open(f"{T}/{n}.log").read().splitlines() if os.path.exists(f"{T}/{n}.log") else []
def reset_logs():
    for n in ("calls", "signals", "restarts", "pkill"):
        try: os.remove(f"{T}/{n}.log")
        except OSError: pass

# 보이기: SIGUSR2 + 가려지는 창(0xb)만 맞춤
r = vkb("show")
check("show: 성공", r.returncode == 0, r.stderr)
check("show: SIGUSR2 전송", log("signals") == ["SIGUSR2"], str(log("signals")))
calls = log("calls")
check("show: 가려지는 창 0xb 의 크기를 줄임(높이 540)", any("0xb" in c and "resize" in c and "y = 540" in c for c in calls), str(calls))
check("show: 가려지지 않는 창 0xa 는 건드리지 않음", not any("0xa" in c for c in calls), str(calls))
check("fit 기록이 남음(원본/맞춘 값)", json.load(open(f"{T}/state/fit.json"))["0xb"] == {"orig": [100, 700, 800, 700], "fitted": [100, 700, 800, 540]})
check("status: 보임", json.loads(vkb("status", "--json").stdout)["visible"] is True)

# 숨기기: 맞춘 상태 그대로면 복원
open(f"{T}/clients.json", "w").write(json.dumps([
    {"address": "0xb", "at": [100, 700], "size": [800, 540], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0},
    {"address": "0xa", "at": [100, 100], "size": [800, 400], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0}]))
reset_logs(); r = vkb("hide")
check("hide: SIGUSR1 전송", log("signals") == ["SIGUSR1"], str(log("signals")))
check("hide: 0xb 를 원래 높이(700)로 복원", any("0xb" in c and "resize" in c and "y = 700" in c for c in log("calls")), str(log("calls")))
check("복원 뒤 fit 기록 비움", json.load(open(f"{T}/state/fit.json")) == {})
check("status: 숨김", json.loads(vkb("status", "--json").stdout)["visible"] is False)

# 사용자가 옮긴 창은 복원하지 않음
reset_logs(); vkb("show")
open(f"{T}/clients.json", "w").write(json.dumps([{"address": "0xb", "at": [300, 650], "size": [800, 540], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0}]))
reset_logs(); vkb("hide")
check("사용자가 옮긴 창은 숨겨도 복원하지 않음", not any("resize" in c for c in log("calls")), str(log("calls")))

# 크기
reset_logs(); r = vkb("size", "large")
check("size large: 설정 480 저장 + wvkbd 재시작", json.load(open(f"{T}/conf/config.json"))["height"] == 480 and log("restarts") == ["restart"], str(log("restarts")))
reset_logs(); vkb("size", "up")
check("이미 large 면 up 은 재시작 안 함", log("restarts") == [])
vkb("size", "down"); check("down 은 medium(360)", json.load(open(f"{T}/conf/config.json"))["height"] == 360)
check("숫자 크기 300", vkb("size", "300").returncode == 0 and json.load(open(f"{T}/conf/config.json"))["height"] == 300)
check("범위 밖(50)은 거부", vkb("size", "50").returncode == 2)

# 크기 순환(터치 버튼) / waybar JSON
vkb("size", "small"); reset_logs(); vkb("size", "cycle")
check("size cycle: small → medium(360)", json.load(open(f"{T}/conf/config.json"))["height"] == 360)
vkb("size", "cycle"); check("size cycle: medium → large(480)", json.load(open(f"{T}/conf/config.json"))["height"] == 480)
vkb("size", "cycle"); check("size cycle: large → small(240)", json.load(open(f"{T}/conf/config.json"))["height"] == 240)
vkb("size", "medium")
check("크기를 바꾸면 waybar 에 갱신 신호(RTMIN+8)", any("-RTMIN+8" in l for l in log("pkill")) if os.path.exists(f"{T}/pkill.log") else False)
open(f"{T}/visible", "w").close()
w = json.loads(vkb("waybar").stdout); check("waybar(보임): 클래스 on", w["class"] == "on" and w["text"] == "⌨", str(w))
w = json.loads(vkb("waybar", "size").stdout); check("waybar size(보임): M 표시", w["text"] == "M", str(w))
os.remove(f"{T}/visible")
w = json.loads(vkb("waybar").stdout); check("waybar(숨김): 클래스 off", w["class"] == "off", str(w))
check("waybar size(숨김): 빈 출력(모듈이 사라짐)", vkb("waybar", "size").stdout.strip() == "")

# 자세 연동
os.remove(f"{T}/visible") if os.path.exists(f"{T}/visible") else None
open(f"{T}/mode", "w").write("tablet\n"); reset_logs(); vkb("apply-posture")
check("tablet 이면 자동으로 보임", log("signals") == ["SIGUSR2"], str(log("signals")))
reset_logs(); vkb("apply-posture")
check("이미 보이면 아무것도 안 함(멱등)", log("signals") == [], str(log("signals")))
open(f"{T}/mode", "w").write("laptop\n"); reset_logs(); vkb("apply-posture")
check("laptop 이면 자동으로 숨김", log("signals") == ["SIGUSR1"], str(log("signals")))
vkb("auto", "off"); open(f"{T}/mode", "w").write("tablet\n"); reset_logs(); vkb("apply-posture")
check("auto off 면 자세가 바뀌어도 건드리지 않음", log("signals") == [], str(log("signals")))
r = subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", "show"], capture_output=True, text=True, env=dict(env, VKB_SYSTEMCTL=script("systemctl2", "import sys; sys.exit(3 if 'is-active' in sys.argv else 0)")))
check("서비스가 없으면 오류 메시지와 종료 코드 1", r.returncode == 1 and "실행 중이 아닙니다" in r.stderr, r.stderr)
print(f"\nvkb CLI {ok} 통과 / {bad} 실패")
sys.exit(1 if bad else 0)
