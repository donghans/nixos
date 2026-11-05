"""전원별 밝기 기억·복원 + 배터리 유휴 낮춤 시험 (가짜 sysfs + 가짜 brightnessctl)"""
import os, sys, tempfile
T = tempfile.mkdtemp()
D = os.path.dirname(os.path.abspath(__file__))
os.environ.update(
    DISPLAYCTL_STATE=T + "/state", DISPLAYCTL_RUNTIME=T + "/run", DISPLAYCTL_POWER_SUPPLY=T + "/ps", DISPLAYCTL_BACKLIGHT=T + "/bl",
    DISPLAYCTL_BRIGHTNESSCTL=D + "/fake_brightnessctl.sh", FAKE_BL=T + "/bl/intel")
os.makedirs(T + "/run"); os.makedirs(T + "/ps/ADP1"); os.makedirs(T + "/bl/intel")
sys.path.insert(0, os.path.dirname(D))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(D))), "_lib", "testkit"))
import displayctl as dc
from dispctl import brightness as b
from harness import checker
check, finish = checker(verbose=True)

def w(path, v): open(path, "w").write(str(v))
def ac(on): w(T + "/ps/ADP1/online", 1 if on else 0)
def bl(v): w(T + "/bl/intel/brightness", v)
def cur(): return b.read_brightness()[0]
w(T + "/ps/ADP1/type", "Mains"); w(T + "/bl/intel/max_brightness", 1000)
W = b.Watcher()

# 첫 관측: AC, 1000(100%) — 아무것도 바꾸지 않고 기억만
ac(True); bl(1000); W.tick()
check("첫 관측은 밝기를 건드리지 않고 AC 밝기를 기억", cur() == 1000 and b.load_conf()["mem"] == {"ac": 1000})
bl(800); W.tick(); check("AC 에서 사용자가 밝기를 바꾸면 AC 기억이 갱신", b.load_conf()["mem"]["ac"] == 800)
# AC → 배터리: 배터리 기억이 아직 없으니 그대로, 그 값이 배터리 기억이 됨
ac(False); W.tick(); check("배터리 첫 전환: 밝기 유지 + 배터리 기억 생성", cur() == 800 and b.load_conf()["mem"]["bat"] == 800)
bl(50); W.tick(); check("배터리에서 5% 로 바꿈 → 배터리 기억 50", b.load_conf()["mem"]["bat"] == 50 and b.load_conf()["mem"]["ac"] == 800)
ac(True); W.tick(); check("AC 로 전환 → AC 마지막 밝기(800)로 복귀", cur() == 800)
ac(False); W.tick(); check("배터리로 전환 → 배터리 마지막 밝기(50)로 복귀", cur() == 50)

# 유휴 낮춤
bl(600); W.tick()
check("기본값(5%, 60초): 다른 대기 시간 리스너는 무시", b.idle(30) is False and cur() == 600)
check("60초 리스너: 5%(=50)로 낮춤", b.idle(60) is True and cur() == 50)
W.tick(); check("낮춘 밝기는 배터리 기억으로 저장하지 않음", b.load_conf()["mem"]["bat"] == 600)
check("wake → 원래 밝기 복원", b.wake() is True and cur() == 600)
check("두 번째 wake 는 아무것도 안 함", b.wake() is False)
b.set_conf(level=15, delay=30); check("설정 15%/30초", b.idle(60) is False and b.idle(30) is True and cur() == 150)
b.wake()
b.set_paused(True); check("이번 배터리 끄기 → 낮추지 않음", b.idle(30) is False and cur() == 600)
ac(True); W.tick(); ac(False); W.tick()
check("AC 를 거치면 끄기가 풀려 다시 낮춤", b.status()["paused"] is False and b.idle(30) is True)
# 낮춘 상태에서 AC 연결 → 낮춤 해제 + AC 밝기
ac(True); W.tick(); check("낮춘 채 AC 연결 → AC 기억(800)로, 낮춤 상태 해제", cur() == 800 and b.status()["dimmed"] is False)
check("AC 에서는 낮추지 않음", b.idle(30) is False)
# 이미 더 어두우면 건드리지 않음 / 덮개 닫힘(0)
ac(False); W.tick(); bl(100); W.tick(); b.set_conf(level=25); check("이미 25% 보다 어두우면 낮추지 않음(올리지 않음)", b.idle(30) is False and cur() == 100)
# 덮개 닫힘 중 전원 전환은 열린 뒤에 적용
bl(0); ac(True); W.tick(); check("덮개 닫힘(0) 중에는 복원을 미룸", cur() == 0)
bl(300); W.tick(); check("덮개가 열려 밝기가 돌아오면 AC 기억(800)을 적용", cur() == 800)
# 설정 값 검증
try: b.set_conf(level=7); ok = False
except SystemExit: ok = True
check("허용되지 않은 밝기 값 거부", ok)
rc = dc.main(["brightness", "status", "--json"]); check("CLI status", rc == 0)
finish("밝기 기억·절전 낮춤")
