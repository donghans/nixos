#!/usr/bin/python3 -I
"""sbox 명령 관문 셸(plan sbox-project-policy §4-2c-2 L2, 로드맵 ㉑ S3) — ct 안에서 Claude Code 의 Bash 도구가 쓰는 **셸 자리**에 앉는다(관리 설정 `env.CLAUDE_CODE_SHELL`).

하는 일: Claude Code 가 셸에 넘기는 호출 3종 중 ① `-c env`(환경 조회) ② 세션 시작 때 스냅샷 파일을 만드는 호출은 진짜 bash 로 그대로 넘기고,
③ **명령 실행 호출**(`source <스냅샷> … && eval '<사용자 명령>' < /dev/null && pwd -P >| <cwd 파일>`)에서 사용자 명령만 뽑아
   · **단순 명령 하나**(따옴표 말고 셸 문법 없음 — `;` `&&` `|` `>` `$()` 백틱 글롭 등이 하나라도 있으면 거절)이고
   · argv 가 `/etc/sbox/gate.json` 의 `direct` 목록(읽기 전용 점검 몇 가지)과 **한 토큰도 다르지 않으면** bash 없이 argv 로 직접 실행하고,
   · 아니면 `taskd` 의 `exec-argv` 로 위임한다(taskd 가 선언된 작업의 argv 와 한 토큰도 다르지 않을 때만 실행).
   그 밖의 것, 그리고 **모르는 호출 형식은 전부 거절**한다(fail-closed — Claude Code 를 올려 형식이 바뀌면 전부 거절되어 눈에 띈다; 카나리가 그것을 설치 때 잡는다).
거절은 종료 코드 126 + 안내 문구(허용된 명령 목록)로 에이전트에게 돌려준다. 환경변수로 이 동작을 바꿀 수 없다(경로는 상수, 설정은 root 소유 파일만).

이 파일은 **호스트에서 만들어 ct 에 root 소유 755 로 설치**한다(`sboxctl gate`). 셸 이름에 `bash` 가 들어가야 Claude Code 가 쓴다(U6 — 아니면 조용히 무시되어 관문이 꺼진다).
표준 라이브러리만 쓴다."""
import json, os, re, shlex, socket, subprocess, sys

GATE_CONFIG = "/etc/sbox/gate.json"
TASKD_SOCKET = "/run/sbox-taskd/sock"
REAL_BASH = ("/bin/bash", "/usr/bin/bash")
FIXED_PATH = ("/usr/local/bin", "/usr/bin", "/bin")      # direct 명령의 실행 파일을 찾는 고정 경로(환경변수 PATH 를 믿지 않는다)
DENY_RC = 126
DEFAULT_DIRECT = [["pwd"], ["ls"], ["git", "status"]]     # gate.json 이 없을 때의 읽기 전용 점검(정확한 argv 만)

# ---- Claude Code 호출 형식(2.1.326·2.1.329 에서 관측, tests/fixtures/claude_call_forms.json)
SNAP_PATH = r"/[A-Za-z0-9_./-]+/\.claude/shell-snapshots/snapshot-bash-\d+-[a-z0-9]+\.sh"
SNAP_FIRST_RE = re.compile(r"SNAPSHOT_FILE=" + SNAP_PATH + r"\n")
SNAP_MARKER = 'echo "# Snapshot file" >| "$SNAPSHOT_FILE"'
_FRAG = r"(?:\\builtin shopt -u extglob 2>/dev/null \|\| true|\{ \\builtin unalias -- '[A-Za-z0-9_]+'; \\builtin unset -f -- '[A-Za-z0-9_]+'; \} >/dev/null 2>&1 \|\| true)"
CMD_RE = re.compile(r"source (?P<snap>" + SNAP_PATH + r") 2>/dev/null \|\| true && (?:" + _FRAG + r"(?: && " + _FRAG + r")* && )?eval (?P<q>.*) < /dev/null && pwd -P >\| (?P<cwd>/tmp/claude-[0-9a-f]+-cwd)", re.S)
# 명령 문자열에 이 문자가 하나라도 있으면(따옴표 제외) 셸 문법이 개입한다고 보고 거절 — 이것들이 없으면 bash 의 해석과 shlex 의 해석이 같다
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")          # taskd 의 작업 이름 형식과 같다
FORBIDDEN = re.compile(r"[$`\\;&|<>(){}*?\[\]~!#\n\r\t\x00]")


def load_config(path=GATE_CONFIG, require_root=True):
    """설정(direct 목록). root 소유·그룹/기타 쓰기 불가가 아니면 무시하고 기본값(fail-closed 쪽 — 기본값은 읽기 전용 점검뿐)."""
    cfg = {"direct": [list(x) for x in DEFAULT_DIRECT]}
    try:
        st = os.stat(path)
    except OSError:
        return cfg
    if require_root and (st.st_uid != 0 or st.st_mode & 0o022):
        return cfg
    try:
        data = json.load(open(path))
        direct = data.get("direct")
        if isinstance(direct, list) and all(isinstance(a, list) and a and all(isinstance(x, str) and x for x in a) for a in direct):
            cfg["direct"] = direct
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


def parse_command(q):
    """eval 뒤의 인용된 문자열 q → (argv, 오류). q 는 셸 인용(`'…'`, 따옴표 이스케이프는 `'"'"'` 등 어떤 형식이든)으로 사용자 명령 하나를 감싼 것이다."""
    try:
        toks = shlex.split(q, posix=True)
    except ValueError:
        return None, "인용을 해석할 수 없다"
    if len(toks) != 1:
        return None, "명령이 하나의 인용 문자열이 아니다"
    cmd = toks[0]
    if not cmd.strip():
        return None, "빈 명령"
    if FORBIDDEN.search(cmd):
        return None, "허용되지 않는 셸 문법이다(단순 명령 하나만 — `;` `&&` `|` 리다이렉션 `$` 글롭 등 불가)"
    try:
        argv = shlex.split(cmd, posix=True)
    except ValueError:
        return None, "명령의 인용이 닫히지 않았다"
    if not argv:
        return None, "빈 명령"
    return argv, ""


def sbox_request(argv):
    """`sbox list|run|status|logs|stop NAME` → taskd 요청(인자 형식이 맞을 때만, 아니면 None)."""
    if argv == ["sbox", "list"]:
        return {"op": "list"}
    if len(argv) == 3 and argv[0] == "sbox" and argv[1] in ("run", "status", "logs", "stop") and NAME_RE.fullmatch(argv[2]):
        return {"op": argv[1], "task": argv[2]}
    return None


def decide(args, cfg):
    """셸이 받은 인자 → {kind: pass|run|deny, …}. 부작용 없음(시험이 고정 입력으로 직접 부른다)."""
    if args == ["-c", "env"]:
        return {"kind": "pass", "why": "env"}
    if len(args) == 3 and args[0] == "-c" and args[1] == "-l" and SNAP_FIRST_RE.match(args[2]) and SNAP_MARKER in args[2]:
        return {"kind": "pass", "why": "snapshot"}
    if len(args) == 2 and args[0] == "-c":
        m = CMD_RE.fullmatch(args[1])
        if not m:
            return {"kind": "deny", "why": "unknown-form", "msg": "알 수 없는 호출 형식이라 거절합니다(Claude Code 버전이 관문과 맞지 않을 수 있음)"}
        argv, err = parse_command(m.group("q"))
        if argv is None:
            return {"kind": "deny", "why": "syntax", "msg": err}
        if argv[0] == "sbox":                          # `sbox list|run|status|logs|stop NAME` — taskd 에만 말을 거는 창구라 관문이 직접 요청으로 바꾼다
            req = sbox_request(argv)
            if req is None:
                return {"kind": "deny", "why": "syntax", "msg": "sbox 사용법: sbox list | sbox run NAME | sbox status NAME | sbox logs NAME | sbox stop NAME"}
            return {"kind": "run", "argv": argv, "direct": False, "req": req, "cwd_file": m.group("cwd"), "why": "sbox"}
        direct = argv in cfg["direct"]
        return {"kind": "run", "argv": argv, "direct": direct, "req": {"op": "exec-argv", "argv": argv}, "cwd_file": m.group("cwd"), "why": "direct" if direct else "delegate"}
    return {"kind": "deny", "why": "unknown-form", "msg": "알 수 없는 호출 형식이라 거절합니다"}


def which_fixed(name):
    if "/" in name:
        return None                                    # direct 는 이름만(경로로 PATH 검색을 피하는 호출은 거절)
    for d in FIXED_PATH:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def delegate(req, sock_path, out, err):
    """taskd 에 요청(exec-argv 또는 sbox 창구의 list·run·status·logs·stop)을 보내 출력을 그대로 중계한다. 종료 코드를 돌려준다(거부·연결 실패는 126)."""
    c = socket.socket(socket.AF_UNIX)
    try:
        c.connect(sock_path)
    except OSError as e:
        err.write(f"sbox-gate: 실행자(taskd)에 연결하지 못해 거절합니다({sock_path}): {e}\n")
        return DENY_RC
    try:
        c.sendall((json.dumps(req) + "\n").encode())
        buf, rc, got = b"", None, False
        while True:
            chunk = c.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                r = json.loads(line)
                got = True
                if "o" in r:
                    out.write(r["o"]); out.flush()
                elif "error" in r:
                    err.write(f"sbox-gate: 거절됨 — {r['error']}\n")
                    if r.get("hint"):
                        err.write(f"  {r['hint']}\n")
                    if r.get("allowed"):
                        err.write("  허용된 명령:\n" + "".join(f"    {' '.join(a['argv'])}   ({a['task']})\n" for a in r["allowed"]))
                    return DENY_RC
                elif "exit" in r:
                    rc = r["exit"] if not r.get("timeout") else 124
                    if r.get("timeout"):
                        err.write("sbox-gate: 시간 제한을 넘어 끊겼습니다\n")
                elif "tasks" in r:
                    for nm, tk in sorted(r["tasks"].items()):
                        out.write(f"{nm:<16} {tk['kind']:<8} {' '.join(tk['argv'])}" + (f"   (정의 파일: {', '.join(tk['pins'])})" if tk.get("pins") else "") + "\n")
                    rc = 0
                elif "running" in r:
                    out.write("실행 중\n" if r["running"] else "실행 중 아님\n")
                    rc = 0
                elif r.get("ok"):
                    out.write("시작함" + (f" (pid {r['pid']})" if r.get("pid") else "") + (" — 이미 실행 중이었음" if r.get("already") else "") + "\n")
                    rc = 0
        if rc is None:
            if req.get("op") in ("exec-argv", "run") or not got:     # 실행 요청은 종료 정보가 있어야 성공 — 없이 끊기면(taskd 가 죽음 등) 실패로 본다
                err.write("sbox-gate: 실행자(taskd)의 응답이 끝나지 않아 실패로 처리합니다\n")
                return DENY_RC
            return 0                                    # logs 처럼 출력만 오는 조회는 정상
        return rc
    except (OSError, ValueError) as e:
        err.write(f"sbox-gate: 실행자(taskd)와 통신하지 못해 거절합니다: {e}\n")
        return DENY_RC
    finally:
        c.close()


def write_cwd(cwd_file):
    """Claude Code 가 명령 뒤에 읽는 cwd 파일(`pwd -P >| 파일`)을 같은 방식으로 쓴다."""
    with open(cwd_file, "w") as f:
        f.write(os.path.realpath(os.getcwd()) + "\n")


def run(args, cfg, sock_path=TASKD_SOCKET, out=None, err=None):
    """호출 하나를 처리한다. 진짜 bash 로 넘겨야 하면 ("exec", 경로, 인자)를, 아니면 종료 코드를 돌려준다."""
    out = out or sys.stdout
    err = err or sys.stderr
    d = decide(args, cfg)
    if d["kind"] == "pass":
        for b in REAL_BASH:
            if os.access(b, os.X_OK):
                return ("exec", b, args)
        err.write("sbox-gate: bash 를 찾지 못해 거절합니다\n")
        return DENY_RC
    if d["kind"] == "deny":
        err.write(f"sbox-gate: {d['msg']}\n")
        if d["why"] == "syntax":
            err.write("  (허용된 명령 목록은 `sbox list` 로 볼 수 있습니다)\n")
        return DENY_RC
    argv = d["argv"]
    if d["direct"]:
        exe = which_fixed(argv[0])
        if exe is None:
            err.write(f"sbox-gate: 실행 파일을 찾지 못합니다: {argv[0]}\n")
            return DENY_RC
        rc = subprocess.run([exe] + argv[1:], stdin=subprocess.DEVNULL, stdout=out, stderr=err).returncode if out is sys.stdout else _run_capture(exe, argv, out, err)
    else:
        rc = delegate(d["req"], sock_path, out, err)
    if rc == 0:
        try:
            write_cwd(d["cwd_file"])
        except OSError as e:
            err.write(f"sbox-gate: cwd 파일을 쓰지 못했습니다: {e}\n")
            return DENY_RC
    return rc


def _run_capture(exe, argv, out, err):
    r = subprocess.run([exe] + argv[1:], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    out.write(r.stdout); err.write(r.stderr)
    return r.returncode


def main(argv):
    try:
        res = run(argv, load_config())
    except Exception as e:                       # 판정 중 예외는 거절(fail-closed)
        sys.stderr.write(f"sbox-gate: 내부 오류로 거절합니다: {type(e).__name__}\n")
        return DENY_RC
    if isinstance(res, tuple):
        os.execv(res[1], [res[1]] + res[2])
    return res


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
