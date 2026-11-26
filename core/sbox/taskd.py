#!/usr/bin/env python3
"""sbox taskd — ct 안에서 도는 **실행자**(plan sbox-project-policy R6, pilot §29-91). 에이전트는 셸 대신 이 데몬에 「선언된 작업 이름」만 요청한다.
- 작업은 root 소유 설정(/etc/sbox/tasks.json)에만 있다: 고정 argv·cwd·종류(oneshot|service)·**정의 파일 다이제스트(pins)**. 요청에는 이름 말고 아무것도 못 얹는다(인자·환경 없음).
- 실행 전에 pins 의 파일을 다시 해시해 승인 때 기록한 값과 다르면 **거부**한다(에이전트가 package.json 의 scripts 를 고쳐 승인된 이름의 뜻을 바꾸는 것을 막음 — 다시 승인은 사람이 호스트에서).
- **`exec-argv`(S3, R6b)**: 요청이 선언된 작업의 argv 와 **토큰 하나까지 같을 때만**(접두·와일드카드·순서 바꿈 없음) 그 작업을 실행한다 — 관문 셸(gate.py)이 에이전트의 평소 명령(`npm test`)을 이 요청으로 바꿔 보낸다. 요청에는 `op`·`argv` 말고 아무것도 못 얹고 pins·보호 경로 검사는 `run` 과 같다.
- 셸을 쓰지 않는다(argv 직접 실행). 새 세션(프로세스 그룹)·고정 환경·시간 제한·출력 상한. 소켓은 파일 권한과 SO_PEERCRED 로 허용된 uid 만.
표준 라이브러리만 쓴다(ct 의 python3 하나로 도는 것이 목적)."""
import argparse, hashlib, json, os, re, signal, socket, struct, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I 로 돌면 스크립트 폴더가 경로에 없다 — root 소유 폴더라 안전
import protect  # noqa: E402

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")
MAX_OUT = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 900
SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(root, rel):
    """rel(작업 사본 기준 상대 경로)이 root 밖으로 나가지 않는지 — 심볼릭 링크를 풀어 확인."""
    p = os.path.realpath(os.path.join(root, rel))
    r = os.path.realpath(root)
    return p if p == r or p.startswith(r + os.sep) else None


class Taskd:
    def __init__(self, cfg_path, log_path=None):
        self.cfg_path, self.log_path = cfg_path, log_path
        self.services = {}          # 이름 → Popen
        self.lock = threading.Lock()

    def cfg(self):
        with open(self.cfg_path) as f:
            return json.load(f)

    def log(self, rec):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **rec}
        line = json.dumps(rec, ensure_ascii=False)
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(line + "\n")
        else:
            print(line, flush=True)

    def check_pins(self, cfg, task):
        root = cfg["root"]
        for rel, want in (task.get("pins") or {}).items():
            p = inside(root, rel)
            if p is None:
                return f"pin-outside-root:{rel}"
            try:
                got = sha256_file(p)
            except OSError:
                return f"pin-missing:{rel}"
            if got != want:
                return f"pin-mismatch:{rel}"
        return ""

    def check_protect(self, cfg, mountinfo=None):
        """R7(가): ① 보호 패턴에 지금 맞는 경로가 설치 때 목록과 같은지(새 제어 파일이 생기면 거부 — 사람이 `sboxctl taskd` 로 갱신) ② 목록의 모든 경로가 읽기 전용 마운트인지(유닛이 안 돌았거나 설정이 어긋나면 거부)."""
        pats, listed = cfg.get("protect"), cfg.get("protected")
        if pats is None:
            return ""                              # 보호 설정이 없는 옛 설정 — 거부하지 않는다(R7 미적용 상태)
        root = cfg["root"]
        try:
            now = protect.expand(root, pats)
        except ValueError as e:
            return f"protect-invalid:{e}"
        new = sorted(set(now) - set(listed or []))
        if new:
            return "protect-stale:" + ",".join(new[:5])
        if mountinfo is None:
            try:
                mountinfo = open("/proc/self/mountinfo").read()
            except OSError:
                return "protect-unverifiable"
        for rel in listed or []:
            if not protect.mounted_ro(mountinfo, os.path.join(root, rel)):
                return f"protect-not-ro:{rel}"
        return ""

    def env(self, cfg, task):
        e = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
        e["HOME"] = cfg.get("home") or os.environ.get("HOME", "/")
        e.update({k: str(v) for k, v in (task.get("env") or {}).items()})
        return e

    def resolve(self, req):
        """요청 검증 → (task, 오류). 이름 외의 필드가 있으면 거부(인자·환경을 못 얹게)."""
        extra = set(req) - {"op", "task"}
        if extra:
            return None, "extra-fields:" + ",".join(sorted(extra))
        name = req.get("task", "")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            return None, "bad-name"
        cfg = self.cfg()
        task = cfg.get("tasks", {}).get(name)
        if task is None:
            return None, "unknown-task"
        return (cfg, name, task), ""

    def resolve_argv(self, req):
        """exec-argv 요청 검증 → ((cfg, name, task), 오류, 허용 argv 목록). 요청의 argv 가 선언된 작업의 argv 와 한 토큰도 다르지 않을 때만 그 작업을 돌려준다."""
        extra = set(req) - {"op", "argv"}
        if extra:
            return None, "extra-fields:" + ",".join(sorted(extra)), None
        argv = req.get("argv")
        if not (isinstance(argv, list) and 0 < len(argv) <= 64 and all(isinstance(x, str) and x and len(x) <= 2048 and "\x00" not in x for x in argv)):
            return None, "bad-argv", None
        cfg = self.cfg()
        tasks = cfg.get("tasks", {})
        hits = sorted(n for n, t in tasks.items() if t.get("argv") == argv)
        if not hits:
            return None, "unknown-argv", sorted((n, t.get("argv")) for n, t in tasks.items())
        return (cfg, hits[0], tasks[hits[0]]), "", None

    def run_oneshot(self, cfg, name, task, send):
        cwd = inside(cfg["root"], task.get("cwd", "."))
        if cwd is None:
            send({"error": "cwd-outside-root"}); return 126
        t0 = time.monotonic()
        p = subprocess.Popen(task["argv"], cwd=cwd, env=self.env(cfg, task), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        total, timed = 0, False
        timeout = int(task.get("timeout", DEFAULT_TIMEOUT))

        def killer():
            nonlocal timed
            timed = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        timer = threading.Timer(timeout, killer); timer.start()
        try:
            for chunk in iter(lambda: p.stdout.read1(65536), b""):
                total += len(chunk)
                if total <= MAX_OUT:
                    send({"o": chunk.decode("utf-8", "replace")})
                elif total - len(chunk) <= MAX_OUT:
                    send({"o": "\n[출력이 상한(8MiB)을 넘어 이후는 버림]\n"})
            rc = p.wait()
        finally:
            timer.cancel()
        send({"exit": rc, "timeout": timed, "secs": round(time.monotonic() - t0, 2)})
        return rc

    def start_service(self, cfg, name, task, send):
        with self.lock:
            cur = self.services.get(name)
            if cur is not None and cur.poll() is None:
                send({"ok": True, "already": True, "pid": cur.pid}); return
            cwd = inside(cfg["root"], task.get("cwd", "."))
            if cwd is None:
                send({"error": "cwd-outside-root"}); return
            logdir = cfg.get("logdir") or "/var/log/sbox-taskd"
            os.makedirs(logdir, exist_ok=True)
            lf = open(os.path.join(logdir, f"svc-{name}.log"), "ab")
            p = subprocess.Popen(task["argv"], cwd=cwd, env=self.env(cfg, task), stdin=subprocess.DEVNULL,
                                 stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            self.services[name] = p
        send({"ok": True, "pid": p.pid})

    def stop_service(self, name, send):
        with self.lock:
            p = self.services.get(name)
        if p is None or p.poll() is not None:
            send({"ok": True, "running": False}); return
        try:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL); p.wait()
        except OSError:
            pass
        send({"ok": True, "running": False})

    def handle(self, req, send, peer_uid):
        op = req.get("op")
        rec = {"op": op, "task": req.get("task"), "peer_uid": peer_uid}
        try:
            if op == "list":
                cfg = self.cfg()
                send({"tasks": {n: {"argv": t["argv"], "kind": t.get("kind", "oneshot"), "cwd": t.get("cwd", "."), "pins": sorted((t.get("pins") or {}))} for n, t in cfg.get("tasks", {}).items()}})
                rec["result"] = "ok"; return
            if op not in ("run", "status", "stop", "logs", "exec-argv"):
                send({"error": "bad-op"}); rec["result"] = "bad-op"; return
            if op == "exec-argv":
                r, err, allowed = self.resolve_argv(req)
                rec["argv"] = req.get("argv") if isinstance(req.get("argv"), list) else None
                if err:
                    resp = {"error": err}
                    if allowed is not None:
                        resp["allowed"] = [{"task": n, "argv": a} for n, a in allowed]
                        resp["hint"] = "선언되지 않은 명령입니다 — 필요하면 사람에게 `[tasks]` 추가를 요청하세요(호스트에서 `sboxctl taskd`)"
                    send(resp); rec["result"] = err; return
                op = "run"                       # 이후는 run 과 같은 경로(정의 파일·보호 경로 검사 포함)
            else:
                r, err = self.resolve(req)
                if err:
                    send({"error": err}); rec["result"] = err; return
            cfg, name, task = r
            rec["task"] = name
            kind = task.get("kind", "oneshot")
            if op == "run":
                bad = self.check_pins(cfg, task)
                if bad:
                    send({"error": bad, "hint": "정의 파일이 승인 때와 다릅니다 — 사람이 호스트에서 `sboxctl taskd … --approve` 로 다시 승인해야 실행됩니다"})
                    rec["result"] = bad; return
                bad = self.check_protect(cfg)
                if bad:
                    send({"error": bad, "hint": "보호 경로(제어 파일)가 설치 때와 다르거나 읽기 전용이 아닙니다 — 새 제어 파일이 생겼다면 사람이 호스트에서 `sboxctl taskd NAME` 로 갱신해야 실행됩니다"})
                    rec["result"] = bad; return
                if kind == "service":
                    self.start_service(cfg, name, task, send); rec["result"] = "started"
                else:
                    rc = self.run_oneshot(cfg, name, task, send); rec["result"] = f"exit={rc}"
            elif op == "status":
                p = self.services.get(name)
                send({"running": bool(p and p.poll() is None), "kind": kind}); rec["result"] = "ok"
            elif op == "stop":
                self.stop_service(name, send); rec["result"] = "stopped"
            elif op == "logs":
                path = os.path.join(cfg.get("logdir") or "/var/log/sbox-taskd", f"svc-{name}.log")
                try:
                    with open(path, "rb") as f:
                        f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 32768))
                        send({"o": f.read().decode("utf-8", "replace")})
                except OSError:
                    send({"o": ""})
                rec["result"] = "ok"
        except (BrokenPipeError, ConnectionError):
            rec["result"] = "client-gone"
        except Exception as e:                       # 한 요청의 예외가 데몬을 죽이지 않게
            rec["result"] = "error:" + type(e).__name__
            try:
                send({"error": "internal"})
            except Exception:
                pass
        finally:
            self.log(rec)


def serve(td, sock_path, allow_uids, mode=0o660, group=None):
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, mode)
    if group is not None:
        os.chown(sock_path, -1, group)
    srv.listen(16)

    def conn(c):
        try:
            cred = c.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _, uid, _ = struct.unpack("3i", cred)
            def send(obj):
                c.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode())
            if allow_uids is not None and uid not in allow_uids:
                send({"error": "uid-not-allowed"}); td.log({"op": "?", "peer_uid": uid, "result": "uid-not-allowed"}); return
            buf = b""
            while b"\n" not in buf and len(buf) < 4096:
                chunk = c.recv(4096)
                if not chunk:
                    break
                buf += chunk
            if not buf.strip():
                return                                       # 요청 없이 연결만 하고 끊은 클라이언트(준비 확인 등) — 오류 응답을 보내지 않고 조용히 끝낸다
            try:
                req = json.loads(buf.split(b"\n", 1)[0].decode())
                if not isinstance(req, dict):
                    raise ValueError
            except ValueError:
                try:
                    send({"error": "bad-request"})
                except OSError:                              # 보낸 뒤 바로 끊은 클라이언트
                    pass
                return
            td.handle(req, send, uid)
        finally:
            try:
                c.close()
            except OSError:
                pass

    while True:
        c, _ = srv.accept()
        threading.Thread(target=conn, args=(c,), daemon=True).start()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/run/sbox-taskd/sock")
    ap.add_argument("--config", default="/etc/sbox/tasks.json")
    ap.add_argument("--log", default="/var/log/sbox-taskd/taskd.log")
    ap.add_argument("--allow-uid", action="append", type=int, default=[], help="요청을 보낼 수 있는 uid(반복)")
    ap.add_argument("--group", type=int, default=None, help="소켓 파일의 gid")
    a = ap.parse_args(argv)
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    os.umask(0o002)
    serve(Taskd(a.config, a.log), a.socket, set(a.allow_uid) or None, group=a.group)


if __name__ == "__main__":
    main(sys.argv[1:])
