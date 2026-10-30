#!/usr/bin/env python3
"""tmuxsess — claude 전용 tmux 세션 조회·생성·정리(llm-sessions UI 와 CLI 가 공유). 화면 코드와 분리해 실제 tmux 서버로 시험한다.

전용 소켓(`tmux -L <소켓>`)과 전용 설정 파일(claude-tmux.conf)만 쓰므로 사용자의 일반 tmux 에는 손대지 않는다. 환경 변수:
  CLAUDE_TMUX_BIN(tmux 실행 파일) · CLAUDE_TMUX_SOCKET(기본 claude) · CLAUDE_TMUX_CONF(기본: 이 파일 옆 claude-tmux.conf) · CLAUDE_RUN_BIN(세션 안에서 실행할 것, 기본 claude-run)
  CLAUDE_SESSIONS_DEFAULT_ARGS(llm-sessions 로 만드는 새 세션에 기본으로 붙일 claude 인자, 기본 `--dangerously-skip-permissions`; 빈 값이면 아무것도 붙이지 않음) · CLAUDE_CTX_BIN(ctx 조회 명령, 기본 donghans)
세션 이름은 `claude-<작업 디렉터리 이름>-<시작 시각>` — 이 접두사가 붙은 세션만 목록에 나온다.
"""
from __future__ import annotations

import os
import re
import shlex
import socket as _socket
import subprocess
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = "claude-"
HINT = "분리: F12 또는 Ctrl+] d  ·  종료: claude 를 끝내면 세션도 끝남"


def tmux_bin() -> str:
    return os.environ.get("CLAUDE_TMUX_BIN", "tmux")


def socket() -> str:
    return os.environ.get("CLAUDE_TMUX_SOCKET", "claude")


def conf() -> str:
    return os.environ.get("CLAUDE_TMUX_CONF", os.path.join(HERE, "claude-tmux.conf"))


def run_bin() -> str:
    return os.environ.get("CLAUDE_RUN_BIN", "claude-run")


def base_cmd() -> list[str]:
    return [tmux_bin(), "-L", socket(), "-f", conf()]


def tmux(*args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run([*base_cmd(), *args], capture_output=True, text=True, timeout=timeout)


@dataclass
class Client:
    tty: str
    pid: int
    size: str
    origin: str          # ssh | kitty | tty


@dataclass
class Session:
    name: str
    created: float
    activity: float
    attached: int
    path: str
    command: str
    clients: list[Client] = field(default_factory=list)


def client_origin(pid: int) -> str:
    """붙어 있는 tmux 클라이언트가 ssh 에서 왔는지 kitty 에서 왔는지 — 그 프로세스 환경에서 읽는다(같은 사용자만 읽을 수 있음)."""
    try:
        env = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        return "tty"
    keys = {e.split(b"=", 1)[0] for e in env}
    if b"SSH_CONNECTION" in keys or b"SSH_TTY" in keys:
        return "ssh"
    if b"KITTY_WINDOW_ID" in keys:
        return "kitty"
    return "tty"


def list_sessions() -> list[Session]:
    """claude- 로 시작하는 세션(최근 활동 순). 서버가 없으면 빈 목록."""
    fmt = "#{session_name}\t#{session_created}\t#{session_activity}\t#{session_attached}\t#{pane_current_path}\t#{pane_current_command}"
    r = tmux("list-sessions", "-F", fmt)
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) < 6 or not p[0].startswith(PREFIX):
            continue
        out.append(Session(p[0], float(p[1] or 0), float(p[2] or 0), int(p[3] or 0), p[4], p[5]))
    by = {s.name: s for s in out}
    r = tmux("list-clients", "-F", "#{session_name}\t#{client_tty}\t#{client_pid}\t#{client_width}x#{client_height}")
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            p = line.split("\t")
            if len(p) == 4 and p[0] in by and p[2].isdigit():
                by[p[0]].clients.append(Client(p[1], int(p[2]), p[3], client_origin(int(p[2]))))
    return sorted(out, key=lambda s: -s.activity)


def preview(name: str, lines: int = 20) -> str:
    """세션 화면의 마지막 줄들(색 없는 글자만) — 어느 대화인지 알아보는 용도."""
    r = tmux("capture-pane", "-p", "-J", "-t", f"={name}:", "-S", f"-{lines * 3}")
    if r.returncode != 0:
        return ""
    rows = [x.rstrip() for x in r.stdout.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return "\n".join(rows[-lines:])


def sanitize(base: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-")
    return s[:30] or "work"


def new_name(directory: str, now: float | None = None) -> str:
    """claude-<디렉터리 이름>-<YYYYmmdd-HHMMSS>. 같은 초에 겹치면 -2, -3 …"""
    base = f"{PREFIX}{sanitize(os.path.basename(os.path.abspath(directory)))}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}"
    taken = {s.name for s in list_sessions()}
    name, i = base, 2
    while name in taken:
        name, i = f"{base}-{i}", i + 1
    return name


def create(directory: str, args: list[str] | None = None, name: str | None = None) -> str:
    """분리된 새 세션을 만든다(그 안에서 claude-run + args 실행). 만든 세션 이름을 돌려준다. 실패하면 RuntimeError."""
    if not os.path.isdir(directory):
        raise RuntimeError(f"디렉터리가 없습니다: {directory}")
    name = name or new_name(directory)
    r = tmux("new-session", "-d", "-s", name, "-c", directory, "--", run_bin(), *(args or []))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "tmux new-session 실패")
    return name


# 세션 간 통신(SendMessage 등)·root 작업(sudo)마다 승인을 묻지 않게, llm-sessions 가 만드는 세션은 권한 확인을 건너뛰는 것이 기본이다(사용자 결정 2026-10-30).
# 이미 권한 관련 인자를 직접 준 경우(`--permission-mode …` 등)에는 덧붙이지 않는다. 끄기: UI 에서 인자 칸을 비우거나, CLI `new --safe`, 또는 CLAUDE_SESSIONS_DEFAULT_ARGS= (빈 값).
PERMISSION_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--permission-mode")


def default_args() -> list[str]:
    return shlex.split(os.environ.get("CLAUDE_SESSIONS_DEFAULT_ARGS", "--dangerously-skip-permissions"))


def with_defaults(args: list[str] | None) -> list[str]:
    args = list(args or [])
    if any(a == f or a.startswith(f + "=") for a in args for f in PERMISSION_FLAGS):
        return args
    return [*default_args(), *args]


def repo_dirs(limit: int = 30, timeout: float = 5) -> list[tuple[str, str]]:
    """ctx DB(ctxui 가 보여 주는 저장소)에서 이 호스트의 작업 저장소 루트를 최근 사용 순으로 [(경로, 저장소 URL)]. 실제로 있는 디렉터리만.
    DB·명령에 못 붙으면 빈 목록(새 세션 대화상자는 현재 위치만으로도 쓸 수 있다). /tmp 아래(시험 산출물)·git worktree 사본은 뺀다."""
    host = re.sub(r"[^A-Za-z0-9._-]", "", _socket.gethostname())
    q = (f"SELECT repo_root, max(repo_url) FROM sessions WHERE host = '{host}' AND repo_root IS NOT NULL "
         "GROUP BY repo_root ORDER BY max(last_ts) DESC")
    try:
        r = subprocess.run([os.environ.get("CLAUDE_CTX_BIN", "donghans"), "ctx", "sql", "--limit", str(limit * 3), q],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines()[1:]:
        p = line.split("\t")
        path = p[0].strip()
        if not path.startswith("/") or path.startswith("/tmp/") or "/.claude/worktrees/" in path or not os.path.isdir(path):
            continue
        out.append((path, p[1].strip() if len(p) > 1 else ""))
    return out[:limit]


def dir_choices(cwd: str, repos: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """새 세션 디렉터리 후보 [(경로, 설명)] — 현재 위치가 맨 위(아직 모르는 곳이면 새로 등록되는 셈), 그 아래 ctx 에 있는 저장소."""
    known = {p: u for p, u in repos}
    out = [(cwd, "현재 위치" + ("" if cwd in known else " (새 위치)"))]
    out += [(p, u.removeprefix("https://github.com/") or "저장소") for p, u in repos if p != cwd]
    return out


def attach_cmd(name: str) -> list[str]:
    """붙는 명령(분리 안내를 잠깐 띄움). subprocess.run 으로 그대로 실행한다."""
    return [*base_cmd(), "attach-session", "-t", f"={name}", ";", "display-message", "-d", "3000", HINT]


def kill(name: str) -> bool:
    return tmux("kill-session", "-t", f"={name}").returncode == 0


def detach_all(name: str) -> bool:
    """그 세션에 붙은 모든 클라이언트를 뗀다(세션은 그대로)."""
    return tmux("detach-client", "-s", f"={name}").returncode == 0


def exists(name: str) -> bool:
    return tmux("has-session", "-t", f"={name}").returncode == 0


def resolve(spec: str) -> str | None:
    """이름 전체·접두사·목록 번호(1부터)로 세션을 찾는다. 모호하면 None."""
    ss = list_sessions()
    if spec.isdigit() and 1 <= int(spec) <= len(ss):
        return ss[int(spec) - 1].name
    hit = [s.name for s in ss if s.name == spec] or [s.name for s in ss if s.name.startswith(spec) or s.name.startswith(PREFIX + spec)]
    return hit[0] if len(hit) == 1 else None
