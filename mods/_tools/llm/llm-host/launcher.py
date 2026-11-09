"""래퍼 재현: 쉘 함수 `claude` 가 하는 일(훅 설정 주입·sudo 환경)을 호스트가 한 곳에서 한다. 설계: ctx 문서 plan llm-trust/11-p5prime-2-session-host §7·§9 S8.

원칙(모두 S8 에서 실제 확인한 것에 근거, README 「래퍼·sudo」 절):
- **쉘 함수는 부르지 않는다.** 실행 파일은 `claude-run`(nix 가 만든 스크립트)이다. 표준입력이 파이프이면 claude-run 은 sudo 부분을 건너뛰고
  `--settings <훅 설정>` 을 앞에 붙여 실제 claude 를 부른다 → 훅 주입은 claude-run 이 하고, sudo 환경(CLAUDE_SUDO_SOCK·PATH 앞붙임)은 이 모듈이 붙인다.
- claude-run 의 위치: 인자 > PATH 의 `claude-tmux` 스크립트 글에서 읽은 `CLAUDE_RUN_BIN=`(현재 프로필, 독립 호스트용, nix 수정 없음) > 환경변수 CLAUDE_RUN_BIN(llmui 경유 호스트에 있으나 세션 시작 뒤 nixup 하면 옛 세대를 가리킬 수 있다).
  sudo 래퍼(claudeSudoBin)·sudo-claude-auth 의 store 경로는 claude-run 스크립트 글(`export PATH=<dir>:$PATH`·`<경로>/sudo-claude-auth --lease`)에서 읽는다.
  글 모양에 의존하므로 못 읽으면 추측하지 않고 sudo 없는 세션으로 시작하며 notice 를 낸다(지금 nix 파일의 모양과 같은지는 시험이 본다).
- **비밀번호를 읽지 않는다**(D-6). sudo 인증은 실행기(P5′-3 llmui)가 터미널에서 먼저 받고 `sudo_ready=True` 로 넘긴다. 이 모듈이 하는 일은
  ① `sudo-claude-auth --lease <호스트 PID>` 를 표준입력 /dev/null 로 부르는 것(티켓이 유효하면 0, 아니면 터미널이 아니라 1 로 끝나고 아무것도 묻지 않는다)
  ② 쓰기 없는 `sudo true` 로 중계가 실제로 되는지 확인하는 것뿐이다.
- 인증이 없거나 확인이 안 되면 sudo 환경 없이 시작하고 notice(warn, 「sudo 중계 없음…」)를 낸다. 거짓으로 환경만 붙이지 않는다.
- claude-run 을 못 찾으면 기본은 **거부**(LauncherError). 훅 설정에는 확인을 강제하는 permissions.ask(ctx doc delete·procctl apply 등)가 들어 있어
  없이 시작하면 안전 규칙이 빠지기 때문이다. `allow_no_hooks=True` 로 명시하면 일반 claude 로 시작하고 notice(warn).
- 세션 중 만료는 Bash 의 sudo 가 낸 안내문(「claude-sudo: … sudo-claude-auth 실행을 요청」)을 tool_result 에서 감지해 notice 로 올린다(`sudo_hint`, **힌트용** — 문구 일치).
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import events as E

SUDO_NOTICE = "sudo 중계 없음 — 이 세션의 Bash 에서 sudo 를 쓸 수 없다(실행기가 터미널에서 sudo-claude-auth 로 인증한 뒤 시작해야 한다)"
HINT_TEXT = ("sudo 인증이 없거나 만료됨 — 세션의 Bash 가 sudo 중계 안내문을 받았다. "
             "사용자가 아무 터미널에서 `sudo-claude-auth` 를 실행해야 한다(문구 일치로 감지한 힌트)")
_HINT_MARKERS = ("claude-sudo:",)
_HINT_KEYS = ("sudo-claude-auth", "sudo 중계가 없음", "sudo 인증이 없거나 만료")
_READ_MAX = 1 << 16


class LauncherError(Exception):
    """시작해서는 안 되는 경우(claude-run 을 못 찾음 등). 메시지는 사람이 읽는다."""


@dataclass
class LaunchPlan:
    exe: list                                   # Adapter.argv 의 spec["exe"]
    env_extra: dict = field(default_factory=dict)
    notices: list = field(default_factory=list)  # [(level, text)] — Session 이 시작할 때 notice 로 낸다
    info: dict = field(default_factory=dict)     # 진단: claude_run·found_by·settings·sudo_bin_dir·sudo_auth·sudo_sock·sudo(bool)·hooks(bool)


# ---------------------------------------------------------------- 찾기
def _read_text(path: str, limit: int = _READ_MAX) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _is_exe(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _is_sock(path: Optional[str]) -> bool:
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except (OSError, TypeError):
        return False


def find_claude_run(env: Optional[dict] = None, explicit: Optional[str] = None) -> tuple:
    """(경로 또는 None, 찾은 방법). 방법: explicit·claude-tmux·env·none. 실행 가능한 파일만 인정한다(낡은 환경변수가 가리키는 사라진 경로는 건너뜀)."""
    env = os.environ if env is None else env
    if explicit:
        return (explicit, "explicit") if _is_exe(explicit) else (None, "explicit-missing")
    path = env.get("PATH", "")
    tmux = shutil.which("claude-tmux", path=path) or (os.path.join(env.get("HOME", ""), ".nix-profile/bin/claude-tmux") if env.get("HOME") else None)
    text = _read_text(tmux) if tmux else None
    if text:    # 지금 프로필(최신 세대)의 값. 환경변수보다 먼저 본다: 세션 시작 뒤 nixup 하면 환경변수는 옛 세대를 가리킨다(S8 실측)
        m = re.search(r"\bCLAUDE_RUN_BIN=(/\S+)", text)
        if m and _is_exe(m.group(1)):
            return m.group(1), "claude-tmux"
    v = env.get("CLAUDE_RUN_BIN")
    if _is_exe(v):
        return v, "env"
    return None, "none"


def parse_claude_run(path: str) -> dict:
    """claude-run 스크립트 글에서 {settings, sudo_bin_dir, sudo_auth} 를 읽는다(없는 것은 None). 글이 아니면(바이너리 등) 전부 None."""
    text = _read_text(path) or ""
    out = {"settings": None, "sudo_bin_dir": None, "sudo_auth": None}
    m = re.search(r"--settings\s+(/\S+)", text)
    if m and os.path.isfile(m.group(1)):
        out["settings"] = m.group(1)
    m = re.search(r"export PATH=(/\S+?):\$PATH", text)
    if m and _is_exe(os.path.join(m.group(1), "sudo")):
        out["sudo_bin_dir"] = m.group(1)
    m = re.search(r"(/\S*sudo-claude-auth)\s+--lease", text)
    if m and _is_exe(m.group(1)):
        out["sudo_auth"] = m.group(1)
    return out


def sudo_sock_path(env: Optional[dict] = None) -> str:
    """쉘 함수·claude-run 과 같은 규칙: ${XDG_RUNTIME_DIR:-/tmp}/claude-sudo.sock (환경에 CLAUDE_SUDO_SOCK 이 있으면 그것)."""
    env = os.environ if env is None else env
    return env.get("CLAUDE_SUDO_SOCK") or os.path.join(env.get("XDG_RUNTIME_DIR") or "/tmp", "claude-sudo.sock")


# ---------------------------------------------------------------- sudo (비밀번호를 읽지 않는다)
def acquire_lease(sudo_auth: str, sock: str, pid: Optional[int] = None, timeout: float = 20.0) -> tuple:
    """`sudo-claude-auth --lease <pid>` 를 표준입력 /dev/null 로 부른다. 티켓이 유효하면 (True, ""), 아니면 (False, 사유).
    표준입력이 터미널이 아니라서 비밀번호를 묻는 일이 없다. 중계가 없으면 sudo-claude-auth 가 setsid 로 띄운다(기존 동작)."""
    pid = os.getpid() if pid is None else pid
    env = {**os.environ, "CLAUDE_SUDO_SOCK": sock}
    try:
        r = subprocess.run([sudo_auth, "--lease", str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"sudo-claude-auth 실행 실패: {type(e).__name__}: {e}"
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr.decode("utf-8", "replace").strip() or f"종료 코드 {r.returncode}")[:300]


def probe_sudo(sudo_bin_dir: str, sock: str, timeout: float = 20.0) -> tuple:
    """중계로 쓰기 없는 `sudo true` 를 실행해 본다. (성공 여부, 사유)."""
    env = {**os.environ, "CLAUDE_SUDO_SOCK": sock}
    try:
        r = subprocess.run([os.path.join(sudo_bin_dir, "sudo"), "true"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"
    return r.returncode == 0, r.stderr.decode("utf-8", "replace").strip()[:300]


# ---------------------------------------------------------------- 계획
def prepare(*, sudo_ready: bool = False, allow_no_hooks: bool = False, claude_run: Optional[str] = None, env: Optional[dict] = None,
            base_path: Optional[str] = None, host_pid: Optional[int] = None, verify_sudo: bool = True) -> LaunchPlan:
    """호스트가 띄울 실행 파일·추가 환경·notice 를 정한다. 파일은 읽고 (sudo_ready 일 때만) sudo-claude-auth·sudo true 를 부를 뿐 아무것도 쓰지 않는다.
    env 는 탐색에 쓸 환경(기본 os.environ), base_path 는 자식 PATH 의 바탕(기본 env 의 PATH — ClaudeAdapter.env 가 쓰는 os.environ["PATH"] 와 같아야 한다)."""
    env = os.environ if env is None else env
    plan = LaunchPlan(exe=[], info={"sudo": False, "hooks": False})
    path, how = find_claude_run(env, claude_run)
    plan.info.update(claude_run=path, found_by=how)
    if not path:
        if not allow_no_hooks:
            raise LauncherError(f"claude-run 을 찾지 못해(찾은 방법: {how}) 시작하지 않는다 — 훅 설정(확인 강제 규칙 포함)을 붙일 수 없다. "
                                "CLAUDE_RUN_BIN 을 주거나 allow_no_hooks=True 로 명시해야 한다")
        plan.exe = [shutil.which("claude", path=env.get("PATH", "")) or "claude"]
        plan.notices.append(("warn", "claude-run 을 찾지 못해 훅 설정 없이 일반 claude 로 시작함(allow_no_hooks) — ctx 훅·확인 강제 규칙·상태 표시줄 없음"))
        plan.notices.append(("warn", SUDO_NOTICE))
        return plan
    plan.exe = [path]
    parsed = parse_claude_run(path)
    plan.info.update(settings=parsed["settings"], sudo_bin_dir=parsed["sudo_bin_dir"], sudo_auth=parsed["sudo_auth"])
    plan.info["hooks"] = bool(parsed["settings"])
    if not parsed["settings"]:
        plan.notices.append(("warn", "claude-run 글에서 훅 설정 경로를 읽지 못함 — 훅이 붙는지 확인되지 않았다(claude-run 모양이 바뀌었을 수 있음)"))
    sock = sudo_sock_path(env)
    plan.info["sudo_sock"] = sock
    why = None
    if not sudo_ready:
        why = "sudo_ready 가 아님(실행기가 터미널에서 인증하지 않았다)"
    elif not parsed["sudo_bin_dir"]:
        why = "claude-run 글에서 sudo 래퍼 위치를 읽지 못함(이 claude-run 에는 sudo 부분이 없거나 모양이 바뀜)"
    elif not _is_sock(sock):
        why = f"중계 소켓이 없음: {sock}"
    else:
        if parsed["sudo_auth"]:
            ok, msg = acquire_lease(parsed["sudo_auth"], sock, host_pid)
            if not ok:
                why = f"임대·인증 확인 실패: {msg}"
        if why is None and verify_sudo:
            ok, msg = probe_sudo(parsed["sudo_bin_dir"], sock)
            if not ok:
                why = f"쓰기 없는 sudo true 가 실패: {msg}"
    if why is None:
        bp = base_path if base_path is not None else env.get("PATH", "")
        parts = [parsed["sudo_bin_dir"]] + [p for p in bp.split(os.pathsep) if p and p != parsed["sudo_bin_dir"]]
        plan.env_extra.update({"CLAUDE_SUDO_SOCK": sock, "PATH": os.pathsep.join(parts)})
        plan.info["sudo"] = True
    else:
        plan.info["sudo_why_not"] = why
        plan.notices.append(("warn", f"{SUDO_NOTICE} [{why}]"))
    return plan


def apply(spec: dict, plan: LaunchPlan) -> dict:
    """spec 사본에 plan 을 적용해 돌려준다: exe(이미 있으면 존중하지 않고 덮어씀)·env_extra 병합(소비자가 준 값이 우선하지 않는다 — sudo 환경은 plan 이 정함)·launch_notices."""
    s = dict(spec)
    s["exe"] = list(plan.exe)
    env = dict(s.get("env_extra") or {})
    env.update(plan.env_extra)
    s["env_extra"] = env
    s["launch_notices"] = list(s.get("launch_notices") or []) + list(plan.notices)
    return s


def launch_spec(spec: dict, **kw) -> tuple:
    """prepare + apply. (새 spec, plan)."""
    plan = prepare(**kw)
    return apply(spec, plan), plan


# ---------------------------------------------------------------- 세션 중 만료 감지(힌트)
def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c.get("text") if isinstance(c, dict) else c) for c in content)
    if isinstance(content, dict):
        return _text_of(content.get("text"))
    return ""


def sudo_hint(ev) -> Optional[E.Notice]:
    """tool_result 에 sudo 중계 안내문이 있으면 Notice(warn), 아니면 None. 문구 일치라 취약하다 — 힌트로만 쓴다."""
    if not isinstance(ev, E.ToolResult):
        return None
    t = _text_of(ev.content)
    if any(m in t for m in _HINT_MARKERS) and any(k in t for k in _HINT_KEYS):
        return E.Notice(level="warn", text=HINT_TEXT, extra={"hint": "sudo", "call": ev.call})
    return None
