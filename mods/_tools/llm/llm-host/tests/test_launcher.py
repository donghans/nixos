#!/usr/bin/env python3
"""llm-host launcher.py(S8)·launcher_real.py 판정 함수·세션 연결 시험. 비용 0: 가짜 claude-run·sudo-claude-auth·sudo·가짜 백엔드만 쓴다. sudo 비밀번호는 다루지 않는다.
실제 claude-run 을 띄우는 시험은 launcher_real.py(비용 있음, run-tests.sh 에 넣지 않는다). 이 시험은 그 판정이 틀린 결과를 거르는지(변이)와 탐색·계획 로직을 본다."""
import asyncio, json, os, shutil, socket, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import events as E
import launcher as L
import launcher_real as R
from claude_adapter import ClaudeAdapter
from session import Session

TMP = tempfile.mkdtemp(prefix="llmhost-s8-")


def sh(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)
    return path


def world(name, with_sudo=True, auth_rc=0, sudo_rc=0, make_sock=True):
    """가짜 nix store 한 벌: claude-run(글), 훅 설정, sudo 래퍼 디렉터리, sudo-claude-auth, claude-tmux(CLAUDE_RUN_BIN 을 적은 글), 중계 소켓."""
    d = os.path.join(TMP, name); os.makedirs(d)
    bins = os.path.join(d, "bin"); os.makedirs(bins)
    sdir = os.path.join(d, "sudodir"); os.makedirs(sdir)
    settings = os.path.join(d, "hooks.json"); open(settings, "w").write("{}")
    sh(os.path.join(sdir, "sudo"), f"echo \"$@\" >> {d}/sudo.args\nexit {sudo_rc}\n")
    auth = sh(os.path.join(d, "sudo-claude-auth"), f"echo \"$@\" > {d}/auth.args\n[ -t 0 ] && echo TTY > {d}/auth.tty\nexit {auth_rc}\n")
    sudo_part = f"""if [ -t 0 ]; then
  export CLAUDE_SUDO_SOCK="${{XDG_RUNTIME_DIR:-/tmp}}/claude-sudo.sock"
  {auth} --lease $$ || exit 1
  export PATH={sdir}:$PATH
fi
""" if with_sudo else "if [ -t 0 ]; then\n  sudo -v || exit 1\nfi\n"
    run = sh(os.path.join(d, "claude-run"), sudo_part + f"set -- --settings {settings} \"$@\"\n\nexec claude \"$@\"\n")
    sh(os.path.join(bins, "claude-tmux"), f"export CLAUDE_TMUX_BIN=/x CLAUDE_RUN_BIN={run} CLAUDE_CTX_BIN=/y\nexec bash /z \"$@\"\n")
    rt = os.path.join(d, "xdg"); os.makedirs(rt)
    sock = os.path.join(rt, "claude-sudo.sock")
    keep = None
    if make_sock:
        keep = socket.socket(socket.AF_UNIX); keep.bind(sock)
    env = {"PATH": bins + ":/usr/bin:/bin", "HOME": d, "XDG_RUNTIME_DIR": rt}
    return dict(d=d, run=run, settings=settings, sdir=sdir, auth=auth, bins=bins, sock=sock, env=env, keep=keep)


# ---------------------------------------------------------------- 찾기
W = world("w1")
check("claude-tmux 글에서 claude-run 을 읽음", L.find_claude_run(W["env"]) == (W["run"], "claude-tmux"))
check("explicit 이 우선", L.find_claude_run(W["env"], explicit=W["auth"]) == (W["auth"], "explicit"))
check("explicit 이 없는 파일이면 찾지 못함으로 끝(다른 방법으로 넘어가지 않는다)", L.find_claude_run(W["env"], explicit="/no/such")[0] is None)
stale = dict(W["env"], CLAUDE_RUN_BIN=W["auth"])
check("프로필(claude-tmux)이 환경변수보다 먼저(낡은 환경변수 방지)", L.find_claude_run(stale)[1] == "claude-tmux" and L.find_claude_run(stale)[0] == W["run"])
bare = {"PATH": "/usr/bin:/bin", "HOME": os.path.join(TMP, "nohome"), "CLAUDE_RUN_BIN": W["run"]}
check("claude-tmux 가 없으면 환경변수", L.find_claude_run(bare) == (W["run"], "env"))
check("환경변수가 가리키는 파일이 없으면 none", L.find_claude_run(dict(bare, CLAUDE_RUN_BIN="/no/such")) == (None, "none"))
check("아무것도 없으면 none", L.find_claude_run({"PATH": "/usr/bin", "HOME": "/nonexistent"}) == (None, "none"))
os.makedirs(os.path.join(TMP, "ct"))
sh(os.path.join(TMP, "ct", "claude-tmux"), "export CLAUDE_RUN_BIN=/no/such/claude-run\n")
check("claude-tmux 글에 경로가 있어도 파일이 없으면 건너뜀", L.find_claude_run({"PATH": os.path.join(TMP, "ct"), "HOME": "/nonexistent"}) == (None, "none"))

p = L.parse_claude_run(W["run"])
check("claude-run 글: settings·sudo 디렉터리·sudo-claude-auth 를 읽음", p == {"settings": W["settings"], "sudo_bin_dir": W["sdir"], "sudo_auth": W["auth"]}, str(p))
W2 = world("w2", with_sudo=False)
check("옛 모양(sudo 부분 없음)은 sudo 쪽이 None", L.parse_claude_run(W2["run"]) == {"settings": W2["settings"], "sudo_bin_dir": None, "sudo_auth": None})
bin_file = os.path.join(TMP, "bin.dat"); open(bin_file, "wb").write(b"\x00\x01\x02")
check("글이 아닌 파일은 전부 None", all(v is None for v in L.parse_claude_run(bin_file).values()))
check("없는 파일은 전부 None", all(v is None for v in L.parse_claude_run("/no/such").values()))
check("글 속 경로가 실제 파일이 아니면 읽지 않음(settings)", L.parse_claude_run(sh(os.path.join(TMP, "cr3"), "set -- --settings /no/such/h.json \"$@\"\n"))["settings"] is None)

# ---------------------------------------------------------------- 계획
try:
    L.prepare(env={"PATH": "/usr/bin", "HOME": "/nonexistent"}); raised = False
except L.LauncherError as e:
    raised = "claude-run" in str(e)
check("claude-run 이 없으면 기본은 거부(훅·확인 강제 규칙을 못 붙임)", raised)
pl = L.prepare(env={"PATH": "/usr/bin", "HOME": "/nonexistent"}, allow_no_hooks=True)
check("allow_no_hooks 면 일반 claude 로 시작 + 경고 2건(훅 없음·sudo 없음)", pl.exe[-1].endswith("claude") and len(pl.notices) == 2 and not pl.info["hooks"] and not pl.info["sudo"], str(pl))

pl = L.prepare(env=W["env"])
check("sudo_ready 아님: exe=claude-run, 훅 있음, sudo 환경 없음", pl.exe == [W["run"]] and pl.info["hooks"] and pl.env_extra == {} and not pl.info["sudo"])
check("sudo_ready 아님: notice 문구가 「sudo 중계 없음」으로 시작", len(pl.notices) == 1 and pl.notices[0][0] == "warn" and pl.notices[0][1].startswith("sudo 중계 없음"), str(pl.notices))
check("sudo_ready 아니면 sudo-claude-auth·sudo 를 부르지 않는다", not os.path.exists(os.path.join(W["d"], "auth.args")) and not os.path.exists(os.path.join(W["d"], "sudo.args")))

pl = L.prepare(env=W["env"], sudo_ready=True, host_pid=4242)
check("sudo_ready: CLAUDE_SUDO_SOCK 이 소켓 경로", pl.env_extra.get("CLAUDE_SUDO_SOCK") == W["sock"], str(pl.env_extra))
check("sudo_ready: PATH 앞이 sudo 래퍼 디렉터리, 원래 PATH 유지", pl.env_extra["PATH"].split(":")[0] == W["sdir"] and W["bins"] in pl.env_extra["PATH"])
check("sudo_ready: notice 없음, info.sudo 참", pl.notices == [] and pl.info["sudo"])
check("호스트 PID 로 임대(--lease 4242)", open(os.path.join(W["d"], "auth.args")).read().strip() == "--lease 4242")
check("sudo-claude-auth 는 표준입력이 터미널이 아닌 채 불림(비밀번호를 묻지 않는다)", not os.path.exists(os.path.join(W["d"], "auth.tty")))
check("쓰기 없는 `sudo true` 로 확인", open(os.path.join(W["d"], "sudo.args")).read().strip() == "true")
bp = L.prepare(env=W["env"], sudo_ready=True, base_path=W["sdir"] + ":/a:/b", verify_sudo=False)
check("base_path 에 이미 래퍼 디렉터리가 있어도 앞에 한 번만", bp.env_extra["PATH"] == f"{W['sdir']}:/a:/b")

Wa = world("wa", auth_rc=1)
pl = L.prepare(env=Wa["env"], sudo_ready=True)
check("임대·인증 실패면 sudo 환경 없이 + 경고(거짓으로 붙이지 않음)", not pl.info["sudo"] and pl.env_extra == {} and "임대·인증 확인 실패" in pl.notices[0][1], str(pl.notices))
Wb = world("wb", sudo_rc=1)
pl = L.prepare(env=Wb["env"], sudo_ready=True)
check("sudo true 가 실패하면 sudo 환경 없이 + 경고", not pl.info["sudo"] and "sudo true 가 실패" in pl.notices[0][1], str(pl.notices))
pl = L.prepare(env=Wb["env"], sudo_ready=True, verify_sudo=False)
check("verify_sudo=False 면 확인 없이 붙임", pl.info["sudo"])
Wc = world("wc", make_sock=False)
pl = L.prepare(env=Wc["env"], sudo_ready=True)
check("소켓이 없으면 sudo 환경 없이 + 경고", not pl.info["sudo"] and "소켓이 없음" in pl.notices[0][1])
check("소켓이 없으면 임대·sudo 를 부르지 않음", not os.path.exists(os.path.join(Wc["d"], "auth.args")))
pl = L.prepare(env=W2["env"], sudo_ready=True)
check("claude-run 에 sudo 부분이 없으면(옛 세대) sudo_ready 여도 sudo 없음 + 사유", not pl.info["sudo"] and "읽지 못함" in pl.notices[0][1], str(pl.notices))
check("sudo_ready 값만 믿고 환경을 붙이지 않는다(변이 확인: 소켓이 일반 파일)", not L.prepare(env=dict(W["env"], CLAUDE_SUDO_SOCK=W["settings"]), sudo_ready=True).info["sudo"])

# 임대 함수 단독
ok, msg = L.acquire_lease(W["auth"], W["sock"], 777)
check("acquire_lease 성공", ok and msg == "")
ok, msg = L.acquire_lease(Wa["auth"], Wa["sock"], 777)
check("acquire_lease 실패는 (False, 사유)", not ok)
ok, msg = L.acquire_lease("/no/such", W["sock"])
check("acquire_lease 실행 파일이 없어도 예외 없이 (False, 사유)", not ok and "실행 실패" in msg)

# apply
base = {"cwd": "/x", "exe": ["old"], "env_extra": {"A": "1", "PATH": "/mine"}, "launch_notices": [("info", "먼저")]}
pl = L.prepare(env=W["env"], sudo_ready=True, verify_sudo=False)
ns = L.apply(base, pl)
check("apply: exe 교체·env 병합(sudo 환경은 plan 우선)·notice 이어 붙임", ns["exe"] == [W["run"]] and ns["env_extra"]["A"] == "1" and ns["env_extra"]["PATH"].startswith(W["sdir"]) and ns["launch_notices"] == [("info", "먼저")])
check("apply: 원본 spec 은 바뀌지 않음", base["exe"] == ["old"] and base["env_extra"]["PATH"] == "/mine")
ns = L.apply(base, L.prepare(env=W["env"]))
check("apply: 알림이 launch_notices 에 쌓임", len(ns["launch_notices"]) == 2 and ns["launch_notices"][1][1].startswith("sudo 중계 없음"))

# ---------------------------------------------------------------- 힌트 감지
HINT1 = "claude-sudo: 이 세션에는 sudo 중계가 없음(터미널에서 띄운 claude 가 아님) — 사용자에게 알릴 것\nRC=1"
HINT2 = "claude-sudo: sudo 인증이 없거나 만료됨 — 우회하거나 기다리지 말고 사용자에게 아무 터미널에서 `sudo-claude-auth` 실행을 요청할 것"
check("힌트: 래퍼의 중계 없음 문구", L.sudo_hint(E.ToolResult(call="c", content=HINT1)) is not None)
check("힌트: 브로커의 만료 문구(블록 목록 content)", L.sudo_hint(E.ToolResult(call="c", content=[{"type": "text", "text": HINT2}])) is not None)
h = L.sudo_hint(E.ToolResult(call="c9", content=HINT2))
check("힌트 notice 는 warn 이고 extra 에 call 을 담음", h.level == "warn" and h.extra == {"hint": "sudo", "call": "c9"})
check("변이: 일반 출력은 힌트 아님", L.sudo_hint(E.ToolResult(call="c", content="hello\nRC=0")) is None)
check("변이: 마커 없이 sudo-claude-auth 만 언급하면 힌트 아님", L.sudo_hint(E.ToolResult(call="c", content="run sudo-claude-auth to learn")) is None)
check("변이: 마커만 있고 안내 키가 없으면 힌트 아님", L.sudo_hint(E.ToolResult(call="c", content="claude-sudo: unrelated")) is None)
check("변이: tool_result 가 아닌 이벤트는 힌트 아님", L.sudo_hint(E.Notice(level="warn", text=HINT1)) is None)
check("content 가 None 이어도 예외 없음", L.sudo_hint(E.ToolResult(call="c", content=None)) is None)

# ---------------------------------------------------------------- Session 연결(가짜 백엔드)
FAKE = os.path.join(ROOT, "fake_claude.py")
_n = [0]


def scenario(steps):
    _n[0] += 1
    p = os.path.join(TMP, f"sc{_n[0]}.jsonl")
    open(p, "w", encoding="utf-8").write("\n".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in steps) + "\n")
    return p


def tool_result_line(text, tid):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": True}]}}


async def sess_run(notices, texts):
    steps = [{"expect": {"stdin_type": "user"}}, {"emit": [tool_result_line(t, f"t{i}") for i, t in enumerate(texts)]}]
    spec = {"exe": [sys.executable, FAKE, scenario(steps), "--timeout", "8"], "cwd": TMP, "persist": False, "launch_notices": notices}
    s = Session(ClaudeAdapter("h1"), spec, host_session="h1", keep_history=True)
    await s.start()
    await s.send("go")
    await asyncio.sleep(1.0)
    await s.close(2)
    return s.history


h = asyncio.run(sess_run([("warn", "sudo 중계 없음 — 시험")], [HINT1, HINT2]))
notices = [e for e in h if e.kind == "notice"]
check("launch_notices 가 첫 이벤트로 나온다", h and h[0].kind == "notice" and h[0].text == "sudo 중계 없음 — 시험" and h[0].level == "warn")
hints = [e for e in notices if (e.extra or {}).get("hint") == "sudo"]
check("힌트 notice 는 세션당 한 번(tool_result 가 둘이어도)", len(hints) == 1, str([(e.text, e.extra) for e in notices]))
check("힌트 notice 는 해당 tool_result 뒤에 나온다", h.index(hints[0]) > min(i for i, e in enumerate(h) if e.kind == "tool_result"))
h2 = asyncio.run(sess_run([], ["ordinary output"]))
check("일반 출력이면 sudo notice 없음", not [e for e in h2 if e.kind == "notice" and (e.extra or {}).get("hint")])

# ---------------------------------------------------------------- launcher_real 판정(변이 포함)
SD, SK = "/store/sudo/bin", "/run/u/claude-sudo.sock"
TRs = lambda: E.TurnResult(ok=True, subtype="success", text="ok", cost_total=0.01, cost_delta=0.01)
tr = lambda txt: E.ToolResult(call="c", content=txt)
hk = [E.Hook(name="SessionStart:startup", phase="finished")]
good_no = hk + [tr(f"SOCK=[]\nSUDO=/run/wrappers/bin/sudo\nRC=1"), TRs()]
good_yes = hk + [tr(f"SOCK=[{SK}]\nSUDO={SD}/sudo\nRC=0"), TRs()]
check("a 통과: sudo 환경 없음·rc≠0", R.analyze_probe(good_no, False, SK, SD)[0])
check("b 통과: 래퍼·소켓·rc 0", R.analyze_probe(good_yes, True, SK, SD)[0])
check("변이(a): 소켓이 보임 → 실패", not R.analyze_probe(hk + [tr(f"SOCK=[{SK}]\nSUDO=/run/wrappers/bin/sudo\nRC=1"), TRs()], False, SK, SD)[0])
check("변이(a): 래퍼가 잡힘 → 실패", not R.analyze_probe(hk + [tr(f"SOCK=[]\nSUDO={SD}/sudo\nRC=1"), TRs()], False, SK, SD)[0])
check("변이(a): sudo 가 성공함 → 실패", not R.analyze_probe(hk + [tr(f"SOCK=[]\nSUDO=/run/wrappers/bin/sudo\nRC=0"), TRs()], False, SK, SD)[0])
check("변이(b): 일반 sudo 가 잡힘 → 실패", not R.analyze_probe(hk + [tr(f"SOCK=[{SK}]\nSUDO=/run/wrappers/bin/sudo\nRC=0"), TRs()], True, SK, SD)[0])
check("변이(b): rc≠0 → 실패", not R.analyze_probe(hk + [tr(f"SOCK=[{SK}]\nSUDO={SD}/sudo\nRC=1"), TRs()], True, SK, SD)[0])
check("변이: 훅 이벤트가 없음(--settings 가 안 붙음) → 실패", not R.analyze_probe([good_yes[1], TRs()], True, SK, SD)[0])
check("변이: raw 가 섞임 → 실패", not R.analyze_probe(good_yes + [E.Raw(payload={})], True, SK, SD)[0])
check("변이: 출력을 못 읽음 → 실패", not R.analyze_probe(hk + [tr("nothing"), TRs()], False, SK, SD)[0])
hint_ev = E.Notice(level="warn", text="x", extra={"hint": "sudo"})
check("c 통과: 안내문 notice 1건·rc≠0", R.analyze_hint([tr(HINT1), hint_ev])[0])
check("변이(c): notice 없음 → 실패", not R.analyze_hint([tr(HINT1)])[0])
check("변이(c): notice 2건 → 실패", not R.analyze_hint([tr(HINT1), hint_ev, hint_ev])[0])
check("변이(c): rc 0 → 실패", not R.analyze_hint([tr("RC=0"), hint_ev])[0])
check("프롬프트에 명령이 그대로 들어감", R.CMD_PROBE in R.prompt_for(R.CMD_PROBE))

shutil.rmtree(TMP, ignore_errors=True)
finish("launcher")
