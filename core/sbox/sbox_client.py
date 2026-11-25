#!/usr/bin/env python3
"""sbox — ct 안에서 에이전트·사용자가 쓰는 **실행 요청 창구**(plan sbox-project-policy R6). 선언된 작업 이름만 taskd 에 요청한다.
사용: sbox list | sbox run NAME | sbox status NAME | sbox logs NAME | sbox stop NAME   (인자·환경을 얹을 수 없다 — 작업은 사람이 승인해 선언한 것뿐)"""
import json, os, socket, sys

SOCK = os.environ.get("SBOX_TASKD_SOCKET", "/run/sbox-taskd/sock")


def ask(req):
    c = socket.socket(socket.AF_UNIX)
    try:
        c.connect(SOCK)
    except OSError as e:
        print(f"sbox: 실행자(taskd)에 연결하지 못했습니다({SOCK}): {e}", file=sys.stderr)
        sys.exit(2)
    c.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    rc = 0
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
            if "o" in r:
                sys.stdout.write(r["o"]); sys.stdout.flush()
            elif "error" in r:
                print(f"sbox: 거부됨 — {r['error']}" + (f"\n  {r['hint']}" if r.get("hint") else ""), file=sys.stderr)
                rc = 3
            elif "tasks" in r:
                for n, t in sorted(r["tasks"].items()):
                    print(f"{n:<16} {t['kind']:<8} {' '.join(t['argv'])}" + (f"   (정의 파일: {', '.join(t['pins'])})" if t["pins"] else ""))
            elif "exit" in r:
                rc = r["exit"] if not r.get("timeout") else 124
                if r.get("timeout"):
                    print("sbox: 시간 제한을 넘어 끊겼습니다", file=sys.stderr)
            elif "running" in r:
                print("실행 중" if r["running"] else "실행 중 아님")
            elif r.get("ok"):
                print("시작함" + (f" (pid {r['pid']})" if r.get("pid") else "") + (" — 이미 실행 중이었음" if r.get("already") else "")) if "pid" in r else None
    return rc


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 0
    op = a[0]
    if op == "list":
        return ask({"op": "list"})
    if op in ("run", "status", "logs", "stop") and len(a) == 2:
        return ask({"op": op, "task": a[1]})
    print("사용: sbox list | sbox run NAME | sbox status NAME | sbox logs NAME | sbox stop NAME", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
