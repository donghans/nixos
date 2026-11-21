#!/usr/bin/env python3
"""claude 세션 전용 sudo 중계.

sudo 의 인증 캐시 키(tty 또는 부모 PID·세션)가 claude 의 Bash 도구에서는 명령마다 바뀌므로, 오래 사는 이 프로세스가
모든 sudo 를 자기 자식으로 실행해 키를 고정한다. setsid 로 띄워 터미널과 무관하게 살고, 소켓은 0600 이라 사용자만 붙을 수 있다.
머신에 하나뿐이며 llm-sessions UI 와 claude 세션들이 함께 쓴다(일반 터미널의 sudo 는 열리지 않는다). 수명은 임대한 프로세스들이 정한다.

  sudo_broker.py serve <소켓>            임대(lease)된 PID 가 하나도 살아 있지 않은 채 GRACE 초가 지나면 끝난다. 60초마다 `sudo -n -v` 로 캐시를 연장한다.
  sudo_broker.py lease <소켓> [PID]      PID(UI·claude-run 등)를 임대로 등록한다. PID 없이 부르면 연결 확인(ping)만 한다.
  sudo_broker.py run <소켓> <sudo 인자…>  stdin/stdout/stderr 와 cwd·환경을 넘겨 sudo 를 실행시키고 종료 코드를 그대로 돌려준다.

`run` 요청마다 `~/.local/state/claude-sudo/broker.log`(0600, 1MiB 회전)에 JSON 한 줄을 남긴다 — 시각·세션·작업 디렉터리·인자 앞 80자와 길이·종료 코드·소요 시간·요청한 프로세스(PID·이름·부모 이름).
환경 변수는 남기지 않고, 기록 실패는 sudo 실행에 영향을 주지 않는다(관찰만).

인증이 없어 `a password is required` 로 실패하면 stderr 끝에 안내를 덧붙인다(프롬프트 대기·우회를 막으려고).
"""
import array
import json
import os
import select
import shlex
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

SUDO = os.environ.get("SUDO_BROKER_SUDO", "/run/wrappers/bin/sudo")
# 실행 기록(관찰만 — 동작은 바꾸지 않는다). 목적: 어떤 일이 root 를 쓰는지 근거를 모은다(plan/sudo-isolation 단계 1).
# 같은 사용자의 프로세스가 읽을 수 있으므로 인자는 앞 ARGV_KEEP 자와 전체 길이만 남기고 환경 변수는 남기지 않는다(비밀이 인자 앞쪽에 있으면 남는다는 한계).
LOG = os.environ.get("SUDO_BROKER_LOG") or os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state"), "claude-sudo", "broker.log")
ARGV_KEEP = 80
LOG_MAX = 1 << 20  # 넘으면 broker.log.1 로 옮기고(한 세대만 보관) 새로 시작한다
LOG_LOCK = threading.Lock()
HINT = ("claude-sudo: sudo 인증이 없거나 만료됨 — 우회하거나 기다리지 말고 "
        "사용자에게 아무 터미널에서 `sudo-claude-auth` 실행을 요청할 것\n").encode()
RECV_MAX = 1 << 20
GRACE = 15  # 임대가 모두 사라진 뒤 끝나기까지 기다리는 초 — UI 가 끝나고 claude-run 이 임대하기 전 틈을 메운다
LEASES = set()
LEASES_LOCK = threading.Lock()


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def any_lease_alive():
    with LEASES_LOCK:
        LEASES.intersection_update({p for p in LEASES if pid_alive(p)})
        return bool(LEASES)


def keepalive():
    while True:
        threading.Event().wait(60)
        subprocess.run([SUDO, "-n", "-v"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def comm_of(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def ppid_of(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def log_request(conn, req, rc, sec):
    """요청 한 건을 JSON 한 줄로 남긴다. 실패해도 sudo 실행에는 영향이 없어야 하므로 모든 예외를 삼킨다."""
    try:
        pid, _uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        ppid = ppid_of(pid)
        argv = shlex.join([str(a) for a in req.get("args", [])])
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rc": rc, "sec": round(sec, 2),
               "session": (req.get("env") or {}).get("CLAUDE_CODE_SESSION_ID", ""),
               "cwd": req.get("cwd", ""), "argv": argv[:ARGV_KEEP], "argv_len": len(argv),
               "peer_pid": pid, "peer_comm": comm_of(pid), "peer_ppid": ppid, "peer_pcomm": comm_of(ppid)}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with LOG_LOCK:
            d = os.path.dirname(LOG)
            os.makedirs(d, mode=0o700, exist_ok=True)
            try:
                if os.path.getsize(LOG) > LOG_MAX:
                    os.replace(LOG, LOG + ".1")
            except OSError:
                pass
            fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line.encode())
            finally:
                os.close(fd)
    except Exception:
        pass


def handle(conn):
    fds = array.array("i")
    try:
        msg, anc, _, _ = conn.recvmsg(RECV_MAX, socket.CMSG_LEN(3 * fds.itemsize))
        for level, kind, data in anc:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds.frombytes(data[:len(data) - len(data) % fds.itemsize])
        req = json.loads(msg)
        if req.get("op") == "lease":
            if req.get("pid"):
                with LEASES_LOCK:
                    LEASES.add(int(req["pid"]))
            conn.send(b"0")
            return
        if len(fds) != 3:
            conn.send(b"255")
            return
        t0 = time.monotonic()
        try:
            p = subprocess.Popen([SUDO] + req["args"], stdin=fds[0], stdout=fds[1], stderr=subprocess.PIPE,
                                 cwd=req["cwd"], env=req["env"])
        except OSError as e:
            os.write(fds[2], f"claude-sudo: 실행 실패: {e}\n".encode())
            log_request(conn, req, 127, time.monotonic() - t0)
            conn.send(b"127")
            return
        tail = b""

        def pump():
            nonlocal tail
            for chunk in iter(lambda: p.stderr.read1(4096), b""):
                os.write(fds[2], chunk)
                tail = (tail + chunk)[-4096:]

        t = threading.Thread(target=pump)
        t.start()
        while p.poll() is None:
            ready, _, _ = select.select([conn], [], [], 0.2)
            if ready and conn.recv(1, socket.MSG_PEEK) == b"":  # 클라이언트가 먼저 끊김(타임아웃·취소)
                p.terminate()
                break
        rc = p.wait()
        t.join()
        if rc != 0 and b"a password is required" in tail:
            os.write(fds[2], HINT)
        log_request(conn, req, rc, time.monotonic() - t0)
        conn.send(str(rc).encode())
    except BrokenPipeError:  # 결과를 받기 전에 클라이언트가 끊김(취소·타임아웃)
        pass
    except Exception as e:  # 한 요청의 실패가 중계 전체를 죽이지 않게
        try:
            conn.send(b"255")
        except OSError:
            pass
        print(f"sudo_broker: {e}", file=sys.stderr)
    finally:
        for fd in fds:
            os.close(fd)
        conn.close()


def serve(path):
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    old = os.umask(0o177)
    srv.bind(path)
    os.umask(old)
    srv.listen(16)
    srv.settimeout(1)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # finally 의 소켓 정리가 돌게
    threading.Thread(target=keepalive, daemon=True).start()
    last_alive = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if any_lease_alive():
                last_alive = now
            elif now - last_alive > GRACE:
                break
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run(path, args):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        s.connect(path)
    except OSError as e:
        print(f"claude-sudo: 중계 프로세스에 연결하지 못함({path}): {e}", file=sys.stderr)
        return 255
    payload = json.dumps({"cwd": os.getcwd(), "args": args, "env": dict(os.environ)}).encode()
    s.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [0, 1, 2]))])
    data = s.recv(64)
    return int(data) if data else 255


def lease(path, pid):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        s.connect(path)
        s.send(json.dumps({"op": "lease", "pid": pid}).encode())
        return 0 if s.recv(64) == b"0" else 255
    except OSError:
        return 255


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "serve":
        serve(sys.argv[2])
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "lease":
        sys.exit(lease(sys.argv[2], int(sys.argv[3]) if len(sys.argv) == 4 else 0))
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        sys.exit(run(sys.argv[2], sys.argv[3:]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
