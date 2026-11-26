#!/usr/bin/env python3
"""sbox 관문 카나리(정적) — **설치된** 관문(sbox-gate-bash)이 ct 안에서 실제로 맞게 동작하는지 점검한다(호스트에서 incus exec 로, 표준 라이브러리만).
LLM·claude 를 부르지 않는다(실제 claude 로 하는 점검은 S3c 의 설치·갱신 카나리). 점검: ① 설치 파일·관리 설정의 소유·권한·값 ② 셸 이름에 bash(U6)
③ 에이전트 사용자(uid 1000)로 호출 3종: env 통과 / 선언 밖 명령 거절(126·cwd 안 씀) / 셸 문법 거절 / 모르는 형식 거절 ④ taskd 가 있으면 위임이 닿는지(unknown-argv 응답).
사용: gate_canary.py CT   — 모두 통과하면 0, 하나라도 실패하면 1.
      gate_canary.py live-verdict FILE [--bypass]   — 실제 claude 카나리(`sboxctl gate NAME --canary`)가 모은 stream-json 출력을 판정한다: 0 통과 · 1 실패 · 2 못 쟀음(명령이 실행되지 않음·한도 등)."""
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


CANARY_CMD = "sbox-canary-undeclared"


def _result_text(content):
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content if isinstance(x, dict))
    return str(content)


def live_verdict(stream_text, bypass=False):
    """실제 claude 에게 선언 밖 명령(CANARY_CMD)을 실행시킨 stream-json 출력 → (상태, 이유). 상태: pass | fail | inconclusive.
    통과 = 관문이 호출됐고 거절했다(도구 결과에 `sbox-gate:` 문구). 실패 = 호출 형식이 안 맞거나(「알 수 없는 호출 형식」) 관문을 거치지 않았다(문구 없음 — 셸 고정이 안 먹음, U6·U10).
    못 쟀음 = 모델이 명령을 실행하지 않았거나 결과가 없음(한도·거부 등) — 통과로 세지 않는다.
    bypass=True(우회 변형: 설정·환경변수로 셸을 바꾸려는 시도) 에서는 **관문이 어떤 이유로든 거절했으면 통과**다 — 우회가 막힌 것이므로 「알 수 없는 호출 형식」도 방어 성공(예: CLAUDE_CODE_SHELL_PREFIX 로
    호출 형식이 달라지면 관문이 알아보지 못해 거절한다). 기본 점검(bypass=False)에서만 형식 불일치를 실패로 본다(어댑터가 현재 버전과 맞는지 확인하는 점검이기 때문)."""
    uses, results = {}, {}
    for line in stream_text.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        c = (j.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                uses[b["id"]] = (b.get("input") or {}).get("command", "")
            elif b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = _result_text(b.get("content"))
    hit = [i for i, cmd in uses.items() if cmd.strip().startswith(CANARY_CMD)]
    if not hit:
        return "inconclusive", "모델이 카나리 명령을 Bash 로 실행하지 않았다(한도·거부·다른 행동)"
    txt = results.get(hit[0])
    if txt is None:
        return "inconclusive", "카나리 명령의 결과가 없다"
    if "알 수 없는 호출 형식" in txt:
        if bypass:
            return "pass", "관문이 호출 형식을 알아보지 못해 거절했다 — 우회는 막혔다(fail-closed)"
        return "fail", "관문이 호출 형식을 알아보지 못했다 — Claude Code 버전이 어댑터와 맞지 않을 수 있다"
    if "sbox-gate:" in txt:
        return "pass", "관문이 호출되어 선언 밖 명령을 거절했다"
    return "fail", "관문을 거치지 않았다(결과에 sbox-gate 문구 없음: " + txt[:80].replace("\n", " ") + ") — 셸 고정이 적용되지 않았다"


def main(argv):
    if len(argv) in (2, 3) and argv[0] == "live-verdict":
        status, why = live_verdict(open(argv[1], encoding="utf-8", errors="replace").read(), bypass="--bypass" in argv[2:])
        print(f"{status}: {why}")
        return {"pass": 0, "fail": 1}.get(status, 2)
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
