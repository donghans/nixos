#!/usr/bin/env python3
"""sbox 관문 카나리(정적) — **설치된** 관문(sbox-gate-bash)이 ct 안에서 실제로 맞게 동작하는지 점검한다(호스트에서 incus exec 로, 표준 라이브러리만).
LLM·claude 를 부르지 않는다(실제 claude 로 하는 점검은 S3c 의 설치·갱신 카나리). 점검: ① 설치 파일·관리 설정의 소유·권한·값 ② 셸 이름에 bash(U6)
③ 에이전트 사용자(uid 1000)로 호출 3종: env 통과 / 선언 밖 명령 거절(126·cwd 안 씀) / 셸 문법 거절 / 모르는 형식 거절 ④ taskd 가 있으면 위임이 닿는지(unknown-argv 응답).
사용: gate_canary.py CT   — 모두 통과하면 0, 하나라도 실패하면 1."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = "/usr/local/bin/sbox-gate-bash"
MANAGED = "/etc/claude-code/managed-settings.json"


def ix(ct, args, user=None, timeout=40):
    cmd = ["incus", "exec", ct] + (["--user", str(user), "--group", str(user), "--env", "HOME=/home/sbox"] if user else []) + ["--"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def form3(cwdfile, cmd):
    import shlex
    fx = json.load(open(os.path.join(HERE, "tests", "fixtures", "claude_call_forms.json")))
    base = fx["captures"][0]["calls"][2][1]
    return ["-c", base[:base.index("eval ")] + "eval " + shlex.quote(cmd) + " < /dev/null && pwd -P >| " + cwdfile]


def run_checks(ct, uid=1000):
    res = []

    def add(label, ok, detail=""):
        res.append((label, bool(ok), detail))

    rc, out, _ = ix(ct, ["stat", "-c", "%U %a", GATE])
    add("관문 파일이 root 소유 755", rc == 0 and out.strip() == "root 755", out.strip())
    rc, out, _ = ix(ct, ["stat", "-c", "%U %a", MANAGED])
    add("관리 설정이 root 소유 644(에이전트가 못 고침)", rc == 0 and out.strip() == "root 644", out.strip())
    rc, out, _ = ix(ct, ["cat", MANAGED])
    try:
        shell = json.loads(out).get("env", {}).get("CLAUDE_CODE_SHELL")
    except ValueError:
        shell = None
    add("관리 설정 env.CLAUDE_CODE_SHELL 이 관문 경로", shell == GATE, str(shell))
    add("셸 이름에 bash 가 들어 있다(U6 — 아니면 조용히 무시됨)", "bash" in os.path.basename(shell or "") or "zsh" in os.path.basename(shell or ""), os.path.basename(shell or ""))
    rc, out, err = ix(ct, [GATE, "-c", "env"], user=uid)
    add("에이전트 사용자로 -c env 는 bash 로 통과(환경 출력)", rc == 0 and "PATH=" in out, (out + err)[:100])
    cwd = "/tmp/claude-" + os.urandom(3).hex() + "-cwd"
    rc, out, err = ix(ct, [GATE] + form3(cwd, "sbox-canary-undeclared"), user=uid)
    gone = ix(ct, ["test", "-e", cwd])[0] != 0
    add("선언 밖 명령은 126 으로 거절되고 cwd 파일을 쓰지 않는다", rc == 126 and "sbox-gate" in err and gone, f"rc={rc} {err[:120]}")
    taskd = ix(ct, ["test", "-S", "/run/sbox-taskd/sock"])[0] == 0
    if taskd:
        add("taskd 에 위임이 닿는다(선언 밖 argv → unknown-argv 응답과 허용 목록)", "unknown-argv" in err and ("허용된 명령" in err or "[tasks]" in err), err[:160])
    else:
        add("(경고) taskd 가 없다 — 관문은 켜지지만 허용 명령이 없어 모든 명령이 거절된다(`sboxctl taskd` 먼저)", True, "")
    if taskd:
        rc, out, err = ix(ct, [GATE] + form3(cwd, "sbox list"), user=uid)
        add("`sbox list` 는 관문을 통과해 작업 목록이 나온다(거절 안내문이 가리키는 명령)", rc == 0, (out + err)[:120])
    rc, out, err = ix(ct, [GATE] + form3(cwd, "echo a; echo b"), user=uid)
    add("셸 문법(;)은 126 + 안내", rc == 126 and "셸 문법" in err, err[:100])
    rc, out, err = ix(ct, [GATE, "-c", "echo hi"], user=uid)
    add("모르는 호출 형식은 126(fail-closed)", rc == 126 and "알 수 없는 호출 형식" in err, err[:100])
    return res


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr); return 64
    res = run_checks(argv[0])
    bad = 0
    for label, ok, detail in res:
        print(("  ✔ " if ok else "  ✘ ") + label + ("" if ok or not detail else f"  — {detail}"))
        bad += not ok
    print(f"관문 카나리: {len(res) - bad}/{len(res)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
