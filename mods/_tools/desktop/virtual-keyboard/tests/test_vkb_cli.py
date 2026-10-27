#!/usr/bin/env python3
"""vkb CLI 통합 시험: 가짜 hyprctl/systemctl/posture 로 show/hide/size/auto/apply-posture 흐름을 확인. (가짜 도구는 mods/_tools/_lib/testkit 공용)"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
from fakes import Sandbox
check, finish = checker()
sb = Sandbox(); T = sb.dir

# 가짜 hyprctl 이 돌려줄 창/모니터. layers 는 FAKE_DIR/visible 이 있을 때만 wvkbd 가 있는 것으로, dispatch 는 calls.log 에 기록
sb.write_json("clients.json", [
    {"address": "0xb", "at": [100, 700], "size": [800, 700], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0},
    {"address": "0xa", "at": [100, 100], "size": [800, 400], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0}])
sb.write_json("monitors.json", [{"id": 0, "name": "eDP-1", "x": 0, "y": 0, "focused": True, "width": 2560, "height": 1600, "scale": 1.0, "transform": 0, "physicalWidth": 340, "physicalHeight": 220}])
env = sb.env(VKB_HYPRCTL=sb.path("hyprctl"), VKB_SYSTEMCTL=sb.path("systemctl"), VKB_POSTURE=sb.path("posture"), VKB_CONFIG_DIR=f"{T}/conf", VKB_STATE_DIR=f"{T}/state")
def vkb(*a): return subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", *a], capture_output=True, text=True, env=env)
def log(n): return sb.log(n)
def reset_logs(): sb.reset_logs()

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
conf = lambda: json.load(open(f"{T}/conf/config.json"))
reset_logs(); r = vkb("size", "large")
check("size large: 설정 저장 + wvkbd 재시작", conf()["size"] == "large" and log("restarts") == ["restart"], str(log("restarts")))
reset_logs(); vkb("size", "up")
check("이미 large 면 up 은 재시작 안 함", log("restarts") == [])
vkb("size", "down"); check("down 은 medium", conf()["size"] == "medium")
check("숫자 크기 9mm", vkb("size", "9").returncode == 0 and conf()["size"] == 9.0)
check("범위 밖(50, 3)은 거부", vkb("size", "50").returncode == 2 and vkb("size", "3").returncode == 2)
check("10 은 medium 이름으로 저장", vkb("size", "10").returncode == 0 and conf()["size"] == "medium")

# 크기 순환(터치 버튼) / waybar JSON
vkb("size", "small"); reset_logs(); vkb("size", "cycle")
check("size cycle: small → medium", conf()["size"] == "medium")
vkb("size", "cycle"); check("size cycle: medium → large", conf()["size"] == "large")
vkb("size", "cycle"); check("size cycle: large → small", conf()["size"] == "small")
vkb("size", "medium")
check("크기를 바꾸면 waybar 에 갱신 신호(RTMIN+8)", any("-RTMIN+8" in l for l in log("pkill")) if os.path.exists(f"{T}/pkill.log") else False)

# 키 폭 설정
reset_logs(); check("keywidth 20: 저장 + 재시작", vkb("keywidth", "20").returncode == 0 and conf()["key_mm"] == 20.0 and log("restarts") == ["restart"], str(log("restarts")))
check("keywidth 20 이면 폭 2259", vkb("args").stdout.split("\n")[vkb("args").stdout.split("\n").index("--width") + 1] == "2259")
check("keywidth 범위 밖은 거부", vkb("keywidth", "3").returncode == 2 and vkb("keywidth", "x").returncode == 2)
vkb("keywidth", "16")

# wvkbd 시작 인자: 화면 물리 크기로 계산
args = vkb("args").stdout.split("\n")
check("args: 가로 5줄 376 / 세로 6줄 452 / 글자 18 / 숨김 시작", args[:6] == ["-H", "452", "-L", "376", "--fn", "NanumGothic 18"] and "--hidden" in args, str(args))
check("args: 폭 1807(도킹도 좁게), 여백 12, 도킹이면 --float 없음", args[args.index("--width") + 1] == "1807" and args[args.index("--float-margin") + 1] == "12" and "--float" not in args, str(args))
vkb("layers", "full"); check("args: 레이어 지정", "-l" in vkb("args").stdout.split("\n")); vkb("layers", "")

# 노트북 모드: 키보드가 숨겨져 있으면 버튼이 안 보임, 떠 있으면 보임. 텐트/태블릿은 항상 보임
sb.write("mode", "laptop\n")
check("waybar(laptop+숨김): 빈 출력", vkb("waybar").stdout.strip() == "" and vkb("waybar", "mode").stdout.strip() == "")
open(f"{T}/visible", "w").close()
w = json.loads(vkb("waybar").stdout); check("waybar(laptop+보임): 클래스 on", w["class"] == "on" and w["text"] == "⌨", str(w))
w = json.loads(vkb("waybar", "size").stdout); check("waybar size(보임): M 표시", w["text"] == "M", str(w))
w = json.loads(vkb("waybar", "mode").stdout); check("waybar mode(도킹): off", w["class"] == "off" and w["text"] == "⧉", str(w))
os.remove(f"{T}/visible")
sb.write("mode", "tablet\n")
w = json.loads(vkb("waybar").stdout); check("waybar(tablet+숨김): 클래스 off 로 보임", w["class"] == "off", str(w))
check("waybar size/mode(숨김): 빈 출력(모듈이 사라짐)", vkb("waybar", "size").stdout.strip() == "" and vkb("waybar", "mode").stdout.strip() == "")

# 도킹/플로팅: 시그널은 wvkbd 로, 설정 저장과 창 맞춤은 wvkbd 가 부르는 훅(mode-changed)에서
open(f"{T}/visible", "w").close(); reset_logs()
vkb("show"); reset_logs()
check("mode float: SIGRTMIN+3 전송(설정은 아직 그대로)", vkb("mode", "float").returncode == 0 and log("signals") == ["SIGRTMIN+3"] and conf()["mode"] == "dock", str(log("signals")))
check("이미 그 모드면 아무것도 안 함", (reset_logs(), vkb("mode", "dock"))[1].returncode == 0 and log("signals") == [])
check("잘못된 모드는 거부", vkb("mode", "x").returncode == 2)
reset_logs(); vkb("mode", "toggle"); check("mode toggle(도킹→플로팅): SIGRTMIN+3", log("signals") == ["SIGRTMIN+3"], str(log("signals")))
reset_logs()
r = subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", "mode-changed"], capture_output=True, text=True, env=dict(env, WVKBD_MODE="float"))
check("훅(float): 설정 저장 + 맞춰 둔 창 원복 + waybar 갱신", r.returncode == 0 and conf()["mode"] == "float" and any("-RTMIN+8" in l for l in log("pkill")), r.stderr)
check("float 이면 args 에 --float", "--float" in vkb("args").stdout.split("\n"))
reset_logs(); vkb("hide"); reset_logs(); vkb("show")
check("플로팅에서 show 는 창을 맞추지 않음(resize 없음)", not any("resize" in c for c in log("calls")), str(log("calls")))
w = json.loads(vkb("waybar", "mode").stdout); check("waybar mode(플로팅): on", w["class"] == "on", str(w))
open(f"{T}/clients.json", "w").write(json.dumps([{"address": "0xb", "at": [100, 700], "size": [800, 700], "floating": True, "hidden": False, "fullscreen": 0, "monitor": 0}]))
open(f"{T}/visible", "w").close(); reset_logs()
subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", "mode-changed"], capture_output=True, text=True, env=dict(env, WVKBD_MODE="dock"))
check("훅(dock): 키보드가 보이면 다시 창을 맞춤(0xb)", conf()["mode"] == "dock" and any("0xb" in c for c in log("calls")), str(log("calls")))
check("훅: 알 수 없는 모드는 거부", subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", "mode-changed"], capture_output=True, text=True, env=dict(env, WVKBD_MODE="zzz")).returncode == 2)
os.path.exists(f"{T}/visible") and os.remove(f"{T}/visible")

# 사용 모드 연동
os.remove(f"{T}/visible") if os.path.exists(f"{T}/visible") else None
sb.write("mode", "tablet\n"); reset_logs(); vkb("apply-posture")
check("tablet 이면 자동으로 보임", log("signals") == ["SIGUSR2"], str(log("signals")))
reset_logs(); vkb("apply-posture")
check("이미 보이면 아무것도 안 함(멱등)", log("signals") == [], str(log("signals")))
sb.write("mode", "laptop\n"); reset_logs(); vkb("apply-posture")
check("laptop 이면 자동으로 숨김", log("signals") == ["SIGUSR1"], str(log("signals")))
vkb("auto", "off"); sb.write("mode", "tablet\n"); reset_logs(); vkb("apply-posture")
check("auto off 면 사용 모드가 바뀌어도 건드리지 않음", log("signals") == [], str(log("signals")))
dead = Sandbox(); dead.write_json("rc.json", {"is-active": 3})          # 서비스가 실행 중이 아닌 시스템
r = subprocess.run([sys.executable, "-I", f"{ROOT}/vkb.py", "show"], capture_output=True, text=True, env=dict(env, VKB_SYSTEMCTL=dead.path("systemctl"), FAKE_DIR=dead.dir))
check("서비스가 없으면 오류 메시지와 종료 코드 1", r.returncode == 1 and "실행 중이 아닙니다" in r.stderr, r.stderr)
finish("vkb CLI")
