#!/usr/bin/env python3
"""claude-sessions 시험(실제 tmux 서버·pty): 세션 생성·목록·미리보기·정리 · claude-tmux 래퍼(감쌀지 판단, 붙기/분리/종료, kitty 닫힘 시 정리와 다른 접속이 있을 때 유지) · UI(Textual Pilot).
필요: tmux. 없으면 건너뛴다(CLAUDE_TMUX_BIN 으로 지정 가능). UI 부분은 textual 이 있어야 한다."""
import asyncio, glob, os, pty, select, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit")); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_uikit"))
from harness import checker
check, finish = checker()

TMUX = os.environ.get("CLAUDE_TMUX_BIN") or next(iter(sorted(glob.glob("/nix/store/*-tmux-3*/bin/tmux"))), None)
if not TMUX or not os.path.exists(TMUX):
    print("tmux 를 못 찾아 건너뜀"); sys.exit(0)

TMP = tempfile.mkdtemp(prefix="clsess-")
SOCK = f"cltest-{os.getpid()}"
FAKE = os.path.join(TMP, "fake-claude")
open(FAKE, "w").write('#!/bin/sh\necho "FAKE-READY args=$*"\nif [ "$FAKE_EXIT" = 1 ]; then exit 0; fi\nexec sleep 600\n')
os.chmod(FAKE, 0o755)
WORK = os.path.join(TMP, "my.proj")          # 이름에 '.' 가 있어 정리(sanitize)가 필요
os.makedirs(WORK)
os.environ.update(CLAUDE_TMUX_BIN=TMUX, CLAUDE_TMUX_SOCKET=SOCK, CLAUDE_RUN_BIN=FAKE, TERM="xterm-256color", PYTHONDONTWRITEBYTECODE="1")
os.environ.pop("TMUX", None); os.environ.pop("CLAUDE_TMUX", None)
import tmuxsess as ts

WRAP = os.path.join(ROOT, "claude-tmux")


def kill_server():
    subprocess.run([TMUX, "-L", SOCK, "kill-server"], capture_output=True)


def wait(cond, timeout=8.0, step=0.1):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Term:
    """pty 안에서 명령을 실행하고 출력을 모은다(kitty 창 흉내). close() 는 창을 닫는 것(마스터 닫기 → SIGHUP)."""
    def __init__(self, argv, cwd=None, env=None):
        self.buf = b""
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            if cwd:
                os.chdir(cwd)
            os.execvpe(argv[0], argv, dict(os.environ, **(env or {})))
        os.set_inheritable(self.fd, False)       # 다음에 fork 하는 pty 가 이 마스터를 물려받아 닫아도 SIGHUP 이 안 가는 일을 막는다
        import fcntl, struct, termios
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))

    def pump(self, secs=0.2):
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    d = os.read(self.fd, 65536)
                except OSError:
                    return
                if not d:
                    return
                self.buf += d

    def wait_for(self, text, timeout=8.0):
        t = time.time()
        while time.time() - t < timeout:
            self.pump(0.15)
            if text.encode() in self.buf:
                return True
        return False

    def send(self, data: bytes):
        os.write(self.fd, data)

    def exited(self, timeout=6.0):
        t = time.time()
        while time.time() - t < timeout:
            try:
                p, st = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if p:
                return os.waitstatus_to_exitcode(st)
            self.pump(0.1)
        return None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def kill(self):
        try:
            os.kill(self.pid, signal.SIGKILL); os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        self.close()


def names():
    return [s.name for s in ts.list_sessions()]


try:
    # --- 코어
    check("list_sessions: 서버가 없으면 빈 목록", ts.list_sessions() == [])
    n1 = ts.create(WORK, ["--resume", "abc"])
    check("create: claude- 접두·디렉터리 이름(점은 -)·시각", n1.startswith("claude-my-proj-") and len(n1.split("-")[-1]) == 6, n1)
    check("create: 같은 초에 만들면 이름이 겹치지 않음", ts.create(WORK, name=ts.new_name(WORK)) != n1)
    wait(lambda: all(s.path == WORK and s.command != "tmux" for s in ts.list_sessions()))     # 막 만든 pane 은 실행이 시작되기 전엔 서버 정보를 보인다
    ss = {s.name: s for s in ts.list_sessions()}
    check("list_sessions: 만든 세션 2개, 작업 디렉터리·붙은 곳 0", n1 in ss and len(ss) == 2 and ss[n1].path == WORK and ss[n1].attached == 0 and ss[n1].clients == [], str(ss.get(n1)))
    check("list_sessions: 최근 활동 순", [s.activity for s in ts.list_sessions()] == sorted((s.activity for s in ts.list_sessions()), reverse=True))
    check("preview: 세션 안에서 실행된 claude 의 화면(인자 전달 확인)", wait(lambda: "FAKE-READY args=--resume abc" in ts.preview(n1)), ts.preview(n1))
    check("exists/resolve: 이름·접두·번호", ts.exists(n1) and ts.resolve(n1) == n1 and ts.resolve("1") in names() and ts.resolve("zzz") is None)
    check("resolve: 모호한 접두는 None", ts.resolve("claude-my") is None)
    try: ts.create(os.path.join(TMP, "없는디렉터리")); check("create: 없는 디렉터리는 RuntimeError", False)
    except RuntimeError: check("create: 없는 디렉터리는 RuntimeError", True)
    check("kill: 정리하면 목록에서 사라짐", ts.kill(n1) and n1 not in names() and not ts.kill(n1))
    subprocess.run([TMUX, "-L", SOCK, "new-session", "-d", "-s", "other", "--", "sleep", "300"])
    check("list_sessions: claude- 접두가 아닌 세션은 목록에서 제외", "other" not in names())
    kill_server()

    # --- 래퍼: 감쌀지 판단(터미널이 아니면 항상 아니오)
    def wants(*a, env=None, tty=False):
        if tty:
            t = Term([WRAP, "--wants", *a], cwd=WORK, env=env)
            rc = t.exited(); t.close(); return rc
        return subprocess.run([WRAP, "--wants", *a], env=dict(os.environ, **(env or {})), stdin=subprocess.DEVNULL, capture_output=True).returncode
    check("wants: 터미널이 아니면 감싸지 않음(1)", wants() == 1)
    check("wants(tty): 인자 없음·--resume·여러 단어 프롬프트는 감쌈(0)", wants(tty=True) == 0 and wants("--resume", "x", tty=True) == 0 and wants("fix the bug", tty=True) == 0)
    check("wants(tty): -p/--print/--version/--help 는 감싸지 않음(1)", all(wants(a, tty=True) == 1 for a in ("-p", "--print", "--version", "--help", "-h", "-v")) and wants("--model", "x", "-p", "hi", tty=True) == 1)
    check("wants(tty): 서브커맨드(mcp·config·update)는 감싸지 않음(1)", all(wants(a, tty=True) == 1 for a in ("mcp", "config", "update", "doctor")))
    check("wants(tty): CLAUDE_TMUX=0 이면 감싸지 않음", wants(tty=True, env={"CLAUDE_TMUX": "0"}) == 1)
    check("wants(tty): 이미 tmux 안이면 감싸지 않음", wants(tty=True, env={"TMUX": "/tmp/x,1,0"}) == 1)

    # --- 래퍼: 붙기 → F12 분리 → 세션 유지 → 다시 붙기
    a = Term([WRAP, "--model", "x"], cwd=WORK)
    check("claude-tmux: 새 세션에 붙어 claude 화면이 보임", a.wait_for("FAKE-READY args=--model x"), a.buf[-300:].decode(errors="replace"))
    check("claude-tmux: 세션이 만들어지고 붙은 곳 1", wait(lambda: len(ts.list_sessions()) == 1 and ts.list_sessions()[0].attached == 1), str(names()))
    sname = names()[0]
    check("claude-tmux: 분리 안내가 화면에 표시", a.wait_for("F12"), a.buf[-300:].decode(errors="replace"))
    a.send(b"\x1b[24~")
    check("F12: 분리하면 래퍼가 정상 종료(0)", a.exited() == 0)
    check("F12: 분리해도 세션은 계속 돈다(붙은 곳 0)", sname in names() and ts.list_sessions()[0].attached == 0)
    a.close()

    # --- 여러 곳에서 동시에 붙기(미러링): 두 번째 터미널이 같은 세션에 붙음
    b1 = Term(ts.attach_cmd(sname)[:-4]); b2 = Term(ts.attach_cmd(sname)[:-4])
    check("동시 접속: 한 세션에 클라이언트 2개", wait(lambda: ts.list_sessions()[0].attached == 2), str(ts.list_sessions()[0].attached))
    cl = ts.list_sessions()[0].clients
    check("동시 접속: 클라이언트 출처·크기 조회", len(cl) == 2 and all(c.origin in ("kitty", "ssh", "tty") and "x" in c.size for c in cl), str(cl))
    check("detach_all: 모든 접속을 뗌(세션은 유지)", ts.detach_all(sname) and wait(lambda: ts.list_sessions()[0].attached == 0) and sname in names())
    b1.kill(); b2.kill()

    # --- kitty 창 닫힘: 다른 접속이 없으면 세션 정리
    kill_server()
    k = Term([WRAP], cwd=WORK)
    check("창 닫기 준비: 세션에 붙음", k.wait_for("FAKE-READY") and wait(lambda: len(names()) == 1))
    k.close()                                   # 마스터를 닫으면 자식에게 SIGHUP — kitty 창을 닫은 것과 같다
    check("kitty 닫힘(다른 접속 없음): 세션도 정리됨", wait(lambda: names() == [], 8), str(names()))
    k.kill()

    # --- kitty 닫힘 + 다른 곳(ssh 흉내)이 붙어 있음: 세션 유지
    kill_server()
    k = Term([WRAP], cwd=WORK)
    k.wait_for("FAKE-READY"); wait(lambda: len(names()) == 1)
    sname = names()[0]
    other = Term(ts.attach_cmd(sname)[:-4])
    check("다른 접속 준비: 클라이언트 2개", wait(lambda: ts.list_sessions()[0].attached == 2))
    k.close()
    time.sleep(2.0)
    check("kitty 닫힘(다른 접속 있음): 세션 유지, 붙은 곳 1", names() == [sname] and ts.list_sessions()[0].attached == 1, f"{names()} {[s.attached for s in ts.list_sessions()]}")
    other.kill(); k.kill()

    # --- claude 종료: 세션도 끝나고 래퍼가 돌아옴
    kill_server()
    e = Term([WRAP], cwd=WORK, env={"FAKE_EXIT": "1"})
    check("claude 가 끝나면 래퍼가 돌아오고 세션도 없어짐", e.exited(10) is not None and names() == [], str(names()))
    e.kill()
    # --- UI / CLI (textual 이 있을 때만)
    try:
        import textual  # noqa: F401
        HAVE_UI = True
    except ImportError:
        HAVE_UI = False
        print("textual 이 없어 UI 시험은 건너뜀")
    if HAVE_UI:
        import claude_sessions as cu
        kill_server()
        s1 = ts.create(WORK, name="claude-ui-a"); s2 = ts.create(WORK, ["--resume", "zz"], name="claude-ui-b")
        wait(lambda: all("FAKE-READY" in ts.preview(n) for n in (s1, s2)))

        def rows(app):
            return app.query_one("#list").row_count

        def ptxt(app):
            r = app.query_one("#preview").render()
            return getattr(r, "plain", None) or str(r)

        async def settle(pilot, cond, timeout=8.0):
            t = time.time()
            while time.time() - t < timeout:
                if cond():
                    return True
                await pilot.pause(0.15)
            return cond()

        async def ui_run():
            app = cu.SessionsUI(start_dir=WORK)
            attached = []
            app.run_attach = lambda name: (attached.append(name), app.refresh_data())      # suspend 는 헤드리스에서 못 쓰므로 붙기 호출만 기록
            async with app.run_test(size=(150, 42)) as pilot:
                await settle(pilot, lambda: rows(app) == 2)
                check("UI: 세션 2개가 목록에 나옴(분리됨 표시)", rows(app) == 2 and "분리됨" in str(app.query_one("#list").get_row_at(0)[4]), str(app.query_one("#list").get_row_at(0)))
                await settle(pilot, lambda: "FAKE-READY" in ptxt(app))
                check("UI: 선택한 세션의 화면 미리보기", "FAKE-READY" in ptxt(app) and app.selected() in app.query_one("#preview-box").border_title, ptxt(app)[:80])
                first = app.selected()
                await pilot.press("down"); await pilot.pause(0.4)
                check("UI: 커서를 옮기면 미리보기 대상이 바뀜", app.selected() != first and app.selected() in app.query_one("#preview-box").border_title)
                await pilot.press("enter"); await pilot.pause(0.4)
                check("UI: Enter → 선택한 세션에 붙기", attached == [app.selected()], str(attached))
                # 붙은 곳 표시 + d 로 모두 떼기
                cl = Term(ts.attach_cmd(s1)[:-4])
                await settle(pilot, lambda: (app.refresh_data() or True) and ts.list_sessions() and any(x.attached for x in ts.list_sessions()))
                app.refresh_data(); await pilot.pause(0.3)
                shown = [str(app.query_one("#list").get_row_at(i)[4]) for i in range(rows(app))]
                check("UI: 붙은 곳 표시(출처·크기)", any(("kitty" in x or "tty" in x or "ssh" in x) and "x" in x for x in shown), str(shown))
                app.query_one("#list").move_cursor(row=[s.name for s in ts.list_sessions()].index(s1)); await pilot.pause(0.3)
                await pilot.press("d"); await settle(pilot, lambda: all(x.attached == 0 for x in ts.list_sessions()))
                check("UI: d → 붙은 곳을 모두 뗌(세션은 유지)", all(x.attached == 0 for x in ts.list_sessions()) and rows(app) == 2)
                cl.kill()
                # 새 세션
                await pilot.press("n"); await pilot.pause(0.4)
                check("UI: n → 새 세션 대화상자(기본 디렉터리 = 시작 위치)", isinstance(app.screen, cu.NewScreen) and app.screen.query_one("#new-dir").value == WORK)
                await pilot.press("enter"); await pilot.pause(0.2)
                for ch in "--resume q": await pilot.press("minus" if ch == "-" else ("space" if ch == " " else ch))
                await pilot.press("enter"); await settle(pilot, lambda: len(ts.list_sessions()) == 3)
                newn = next(n for n in names() if n not in (s1, s2))
                check("UI: 새 세션이 만들어지고 붙기 호출(인자 전달)", len(ts.list_sessions()) == 3 and attached[-1] == newn and wait(lambda: "args=--resume q" in ts.preview(newn)), f"{attached} {ts.preview(newn)[:60]}")
                await pilot.press("n"); await pilot.pause(0.3)
                app.screen.query_one("#new-dir").value = os.path.join(TMP, "없는곳")
                await pilot.press("enter"); await pilot.press("enter"); await pilot.pause(0.5)
                check("UI: 없는 디렉터리는 세션을 만들지 않고 화면이 유지됨", len(ts.list_sessions()) == 3 and app.is_running)
                await pilot.press("escape"); await pilot.pause(0.3)
                check("UI: Esc 로 대화상자 닫힘", not isinstance(app.screen, cu.NewScreen))
                # 정리
                app.query_one("#list").move_cursor(row=[s.name for s in ts.list_sessions()].index(newn)); await pilot.pause(0.3)
                await pilot.press("x"); await pilot.pause(0.3)
                check("UI: x → 확인 대화상자", isinstance(app.screen, cu.ConfirmScreen))
                await pilot.press("n"); await pilot.pause(0.3)
                check("UI: 아니오면 세션 유지", newn in names())
                await pilot.press("x"); await pilot.pause(0.3); await pilot.press("y"); await settle(pilot, lambda: newn not in names())
                check("UI: 예 → 세션이 정리되고 목록에서 사라짐", newn not in names() and rows(app) == 2)
                await pilot.press("f1"); await pilot.pause(0.3)
                check("UI: F1 도움말", app.screen.__class__.__name__ == "HelpScreen"); await pilot.press("escape"); await pilot.pause(0.2)
                ts.kill(s1); ts.kill(s2); await pilot.press("r"); await settle(pilot, lambda: rows(app) == 0)
                check("UI: 세션이 모두 없어지면 빈 목록과 안내", rows(app) == 0 and "없음" in app.query_one("#list").border_title and ptxt(app).strip())
        asyncio.run(ui_run())

        # CLI
        s1 = ts.create(WORK, name="claude-cli-a")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "claude_sessions.py"), "ls"], capture_output=True, text=True, env=os.environ)
        check("CLI ls: 세션 이름·번호·분리됨", out.returncode == 0 and "claude-cli-a" in out.stdout and " 1 " in out.stdout and "분리됨" in out.stdout, out.stdout)
        bad = subprocess.run([sys.executable, os.path.join(ROOT, "claude_sessions.py"), "attach", "없는세션"], capture_output=True, text=True, env=os.environ)
        check("CLI attach: 없는 세션은 종료 코드 1과 안내", bad.returncode == 1 and "찾지 못했" in bad.stderr)
        nt = subprocess.run([sys.executable, os.path.join(ROOT, "claude_sessions.py")], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=os.environ)
        check("CLI: 터미널이 아니면 UI 를 띄우지 않고 안내(종료 코드 1)", nt.returncode == 1 and "ls" in nt.stderr)
        c = Term([sys.executable, os.path.join(ROOT, "claude_sessions.py"), "attach", "cli-a"])
        check("CLI attach: 접두로 붙어서 claude 화면이 보임", c.wait_for("FAKE-READY"))
        c.send(b"\x1b[24~"); check("CLI attach: F12 분리 후 정상 종료", c.exited() == 0 and "claude-cli-a" in names()); c.close()
        ts.kill("claude-cli-a")
        n = Term([sys.executable, os.path.join(ROOT, "claude_sessions.py"), "new", WORK, "--", "--model", "x"])
        check("CLI new: 새 세션을 만들고 붙음(인자 전달)", n.wait_for("FAKE-READY args=--model x") and len(names()) == 1, n.buf[-200:].decode(errors="replace"))
        n.send(b"\x1b[24~"); n.exited(); n.close()
finally:
    kill_server()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
finish("claude-sessions 코어")
