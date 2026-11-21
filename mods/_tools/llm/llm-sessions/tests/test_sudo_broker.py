#!/usr/bin/env python3
"""sudo 중계(sudo_broker.py)의 실행 기록 시험 — 가짜 sudo 로 실제 소켓 왕복을 돌린다(root 불필요).
지키는 것: 기록이 ① 환경 변수 값(비밀)을 남기지 않고 ② 인자는 앞부분과 길이만 남기며 ③ 파일 0600·폴더 0700 이고 ④ 기록이 실패해도 sudo 실행을 막지 않고 ⑤ 실행 실패도 남기며 ⑥ 크기 상한에서 회전한다.
(중계는 root 로 가는 길이라 기록이 조용히 틀리거나 비밀을 남기면 알아채기 어렵다 — plan/sudo-isolation 단계 1)"""
import json, os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()

BROKER = os.path.join(ROOT, "sudo_broker.py")
TMP = tempfile.mkdtemp(prefix="sudobroker-")
FAKE = os.path.join(TMP, "fakesudo.sh")
open(FAKE, "w").write('#!/bin/sh\necho "fakesudo:$*"\nexit ${FAKE_RC:-0}\n')
os.chmod(FAKE, 0o755)
SECRET = "TOP-SECRET-ENV-VALUE"


def start(sudo, log, name):
    sock = os.path.join(TMP, name + ".sock")
    env = dict(os.environ, SUDO_BROKER_SUDO=sudo, SUDO_BROKER_LOG=log)
    p = subprocess.Popen([sys.executable, "-I", BROKER, "serve", sock], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if os.path.exists(sock):
            break
        time.sleep(0.1)
    subprocess.run([sys.executable, "-I", BROKER, "lease", sock, str(os.getpid())], check=False)   # 이 시험 프로세스를 임대로 등록(끝나면 중계도 스스로 끝남)
    return p, sock


def run(sock, *args, env_extra=None):
    env = dict(os.environ, SECRET_ENV=SECRET, CLAUDE_CODE_SESSION_ID="sess-test", **(env_extra or {}))
    r = subprocess.run([sys.executable, "-I", BROKER, "run", sock, *args], env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def lines(path):
    return [json.loads(l) for l in open(path).read().splitlines() if l.strip()]


# 1) 기록 내용·권한·비밀 미포함·인자 절단
log1 = os.path.join(TMP, "state1", "claude-sudo", "broker.log")
p1, s1 = start(FAKE, log1, "b1")
rc, out, _ = run(s1, "-n", "journalctl", "-u", "foo")
check("실행: 가짜 sudo 의 출력과 종료 코드가 그대로 전달됨", rc == 0 and "fakesudo:-n journalctl -u foo" in out, out)
rc, _, _ = run(s1, "-n", "echo", "A" * 200)
recs = lines(log1) if os.path.exists(log1) else []
check("기록: 요청마다 한 줄", len(recs) == 2, str(len(recs)))
if len(recs) == 2:
    r0, r1 = recs
    check("기록: 인자·세션·종료 코드", r0["argv"] == "-n journalctl -u foo" and r0["argv_len"] == 20 and r0["session"] == "sess-test" and r0["rc"] == 0, str(r0))
    check("기록: 긴 인자는 앞 80자만, 전체 길이는 남김", len(r1["argv"]) == 80 and r1["argv_len"] > 200, f"{len(r1['argv'])} {r1['argv_len']}")
    check("기록: 요청한 프로세스(PID·이름) 정보가 있음", r0["peer_pid"] > 0 and r0["peer_comm"] != "", str(r0))
check("기록: 환경 변수 값(비밀)이 파일 어디에도 없음", SECRET not in open(log1).read())
check("기록: 파일 0600·폴더 0700", (os.stat(log1).st_mode & 0o777) == 0o600 and (os.stat(os.path.dirname(log1)).st_mode & 0o777) == 0o700,
      f"{oct(os.stat(log1).st_mode & 0o777)} {oct(os.stat(os.path.dirname(log1)).st_mode & 0o777)}")

# 2) 회전
with open(log1, "a") as f:
    f.write("x" * ((1 << 20) + 10) + "\n")
run(s1, "-n", "id")
check("회전: 1MiB 를 넘기면 broker.log.1 로 옮기고 새로 시작", os.path.exists(log1 + ".1") and len(lines(log1)) == 1, str(os.listdir(os.path.dirname(log1))))
p1.terminate()

# 3) sudo 가 실패(비 0 종료)해도 기록하고 코드를 그대로 돌려줌
log2 = os.path.join(TMP, "state2", "claude-sudo", "broker.log")
p2, s2 = start(FAKE, log2, "b2")
rc, _, _ = run(s2, "-n", "false", env_extra={"FAKE_RC": "3"})
check("비 0 종료: 코드 3 이 클라이언트에 전달되고 기록됨", rc == 3 and lines(log2)[-1]["rc"] == 3, f"rc={rc}")
p2.terminate()

# 4) 실행 파일 자체가 없을 때(실행 실패)도 기록
log3 = os.path.join(TMP, "state3", "claude-sudo", "broker.log")
p3, s3 = start("/nonexistent-sudo", log3, "b3")
rc, _, err = run(s3, "-n", "id")
check("실행 실패: 종료 코드 127 과 안내, 기록 남음", rc == 127 and "실행 실패" in err and os.path.exists(log3) and lines(log3)[-1]["rc"] == 127, f"rc={rc} {err!r}")
p3.terminate()

# 5) 기록을 못 남겨도 sudo 는 정상 동작(기록 경로가 파일 아래라 폴더를 못 만듦)
blocker = os.path.join(TMP, "afile")
open(blocker, "w").write("x")
p4, s4 = start(FAKE, os.path.join(blocker, "sub", "broker.log"), "b4")
rc, out, _ = run(s4, "-n", "still-works")
check("기록 실패가 sudo 실행을 막지 않음", rc == 0 and "fakesudo:-n still-works" in out, f"rc={rc} {out!r}")
p4.terminate()

import shutil
shutil.rmtree(TMP, ignore_errors=True)
finish("sudo-broker 기록")
