#!/usr/bin/env python3
"""abab_lib.sh 시험(가짜 observectl·가짜 덮개/AC 파일): 정상 흐름, 신호 때 복구 후 종료, 도중 덮개 변경 중단, 조건 검증 실패 중단, 복구는 정확히 한 번."""
import os, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
check, finish = checker()
LIB = os.path.join(ROOT, "examples", "abab_lib.sh")
T = tempfile.mkdtemp(prefix="abab-test-")
LOG, LID, AC, RESTORED, STATE = (os.path.join(T, n) for n in ("calls.log", "lid", "ac", "restored", "state"))

def setup(lid="state:      closed\n", ac="0\n"):
    for f in (LOG, RESTORED, STATE):
        if os.path.exists(f):
            os.unlink(f)
    open(LID, "w").write(lid); open(AC, "w").write(ac); open(STATE, "w").write("A")
    fake = os.path.join(T, "observectl")
    open(fake, "w").write('#!/bin/sh\necho "$@" >> %s\n' % LOG); os.chmod(fake, 0o755)

CFG = '''
. %s
OBS=%s
abab_set_a()    { echo A > %s; }
abab_set_b()    { echo B > %s; }
abab_verify_a() { [ "$(cat %s)" = A ]; }
abab_verify_b() { [ "$(cat %s)" = B ]; }
abab_restore()  { echo x >> %s; }
abab_run
''' % (LIB, os.path.join(T, "observectl"), STATE, STATE, STATE, STATE, RESTORED)

def run(cfg=CFG, env_extra=None, wait=True, timeout=20, **kw):
    script = os.path.join(T, "run.sh"); open(script, "w").write(cfg)
    env = {**os.environ, "ABAB_LID_FILE": LID, "ABAB_AC_FILE": AC, "SEG": "1", "PAIRS": "2", "SETTLE": "0", **(env_extra or {})}
    p = subprocess.Popen(["sh", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    return p

def calls():
    return open(LOG).read().strip().split("\n") if os.path.exists(LOG) else []

# --- 정상 흐름
setup()
p = run(); out, _ = p.communicate(timeout=30)
c = calls()
check("정상: 종료 코드 0", p.returncode == 0, out)
check("정상: 표지 A B A B 순서 후 마지막에 ab 호출", [x.split()[1] for x in c if x.startswith("mark A") or x.startswith("mark B")] == ["A", "B", "A", "B"] and c[-1].startswith("ab ") or any(x.startswith("ab ") for x in c), "\n".join(c))
ab = next(x for x in c if x.startswith("ab "))
check("정상: ab 에 --require dev.lid=closed·pw.ac=0 이 자동으로 붙음", "--require dev.lid=closed" in ab and "--require pw.ac=0" in ab and "--min-samples 3" in ab, ab)
check("정상: 복구가 정확히 한 번", open(RESTORED).read().count("x") == 1 and "mark --clear" in "\n".join(c))

# --- 신호: 복구하고 **끝난다**(다음 단계로 가지 않음), sleep 도 바로 깨어남
for sig, name, code in ((signal.SIGTERM, "TERM", 143), (signal.SIGINT, "INT", 130)):
    setup()
    p = run(env_extra={"SEG": "30"}, start_new_session=True)
    for _ in range(80):                                    # 첫 구간(A)이 시작돼 표지가 남을 때까지(최대 8초) 기다린 뒤 신호를 보낸다
        if any(x.startswith("mark A") for x in calls()):
            break
        time.sleep(0.1)
    t0 = time.time()
    (os.killpg if sig == signal.SIGINT else os.kill)(p.pid, sig)
    try:
        rc = p.wait(timeout=8)
        dt = time.time() - t0
    except subprocess.TimeoutExpired:
        p.kill(); rc, dt = None, 99
    started = [x for x in calls() if x.startswith("mark A") or x.startswith("mark B")]
    check(f"{name}: 8초 안에 끝남(30초 sleep 을 기다리지 않음)·종료 코드 {code}", rc == code and dt < 6, f"rc={rc} dt={dt:.1f}")
    check(f"{name}: 복구가 한 번 실행되고 다음 구간(B)으로 진행하지 않음", open(RESTORED).read().count("x") == 1 and len(started) == 1, f"restored={open(RESTORED).read()!r} marks={started}")
    check(f"{name}: 표지를 지움", "mark --clear" in calls())

# --- 도중에 덮개가 열림 → 즉시 중단(이후 구간 안 잼), 복구 실행
setup()
p = run(env_extra={"SEG": "3"})
time.sleep(1.5)
open(LID, "w").write("state:      open\n")
out, _ = p.communicate(timeout=20)
check("덮개 변경: 종료 코드 4 로 중단", p.returncode == 4 and "조건이 바뀜" in out, f"rc={p.returncode}\n{out}")
check("덮개 변경: 최종 ab 를 호출하지 않고 복구는 한 번", not any(x.startswith("ab ") for x in calls()) and open(RESTORED).read().count("x") == 1)

# --- AC 변경도 같은 처리
setup()
p = run(env_extra={"SEG": "3"})
time.sleep(1.5)
open(AC, "w").write("1\n")
out, _ = p.communicate(timeout=20)
check("AC 변경: 중단", p.returncode == 4, out)

# --- 조건 적용 후 검증 실패(조건이 실제로 안 바뀜) → 중단, 복구
bad_cfg = CFG.replace("abab_verify_b() { [ \"$(cat %s)\" = B ]; }" % STATE, "abab_verify_b() { false; }")
setup()
p = run(bad_cfg)
out, _ = p.communicate(timeout=20)
check("검증 실패: 종료 코드 3·'실제로 적용되지 않음' 안내", p.returncode == 3 and "실제로 적용되지 않음" in out, f"rc={p.returncode}\n{out}")
check("검증 실패: B 표지를 남기지 않고 복구", not any(x.startswith("mark B") for x in calls()) and open(RESTORED).read().count("x") == 1)

# --- 조건 적용 명령 자체가 실패
fail_cfg = CFG.replace("abab_set_a()    { echo A > %s; }" % STATE, "abab_set_a()    { return 1; }")
setup()
p = run(fail_cfg)
out, _ = p.communicate(timeout=20)
check("적용 실패: 종료 코드 3", p.returncode == 3 and "적용 실패" in out, out)

# --- AC 모드: AC 를 꽂은 채 `tlp bat` 적용, 끝나면 `tlp start` 로 복구
TLPLOG = os.path.join(T, "tlp.log")
def tlp_stub():
    if os.path.exists(TLPLOG):
        os.unlink(TLPLOG)
    fake = os.path.join(T, "tlp"); open(fake, "w").write('#!/bin/sh\necho "$@" >> %s\n' % TLPLOG); os.chmod(fake, 0o755)
    return fake
setup(ac="1\n")
p = run(env_extra={"ABAB_AC_MODE": "1", "TLP_CMD": tlp_stub()}); out, _ = p.communicate(timeout=30)
tl = open(TLPLOG).read().split()
ab = next(x for x in calls() if x.startswith("ab "))
check("AC 모드: tlp bat 으로 시작하고 끝에 tlp start 로 복구, AC=1 을 요구하는 --require", p.returncode == 0 and tl[0] == "bat" and tl[-1] == "start" and "--require pw.ac=1" in ab, out + str(tl))
setup(ac="0\n")
p = run(env_extra={"ABAB_AC_MODE": "1", "TLP_CMD": tlp_stub()}); out, _ = p.communicate(timeout=30)
check("AC 모드: AC 가 빠져 있으면 거부(종료 코드 4)하고 tlp 를 건드리지 않음", p.returncode == 4 and not os.path.exists(TLPLOG), out)

# --- 예제 스크립트가 문법·함수 계약을 지킴
r = subprocess.run(["sh", "-n", os.path.join(ROOT, "examples", "netdata_abab.sh")])
check("netdata_abab.sh 문법", r.returncode == 0)
finish("abab_lib")
