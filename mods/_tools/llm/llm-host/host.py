"""다중 세션 관리·동시 상한·자식 레지스트리·고아 탐지. 설계: plan llm-trust/11-p5prime-2-session-host §5-2·§5-3 (단계 S5).
Python 3.10+ 표준 라이브러리만. 벤더를 모른다(어댑터는 factory 로 받는다).

- SessionHost(max_sessions, registry_dir, adapter_factory): 세션마다 독립 프로세스·독립 이벤트 큐(Session). 동시 상한을 넘으면 HostFull,
  같은 backend 세션(spec["resume"])을 호스트 안에서 두 세션이 쓰려 하면 DuplicateResume.
- 자식 레지스트리: `<registry_dir>/children.jsonl` 에 추가 기록(add·del)만 한다. add 는 자식 pid·시작 시각(/proc/<pid>/stat 의 starttime)·
  호스트 인스턴스(host_id·host_pid·host_starttime), 자식 환경에는 표지 LLM_HOST_ID=<host_id> 를 넣는다.
- 고아 탐지(scan_orphans): 레지스트리에 있고 **pid·starttime 이 같은 채 살아 있는데 그것을 띄운 호스트는 죽은** 자식만 고아로 보고한다.
  **죽이지 않는다**(알림만). 정리는 사람이 procctl plan→확인→apply 로 한다(D-14: 안내만). 이 파일에는 자식 아닌 프로세스에 보내는 신호가 없다.
- 종료는 Session.close(4단계)·Session.kill 에 맡긴다(자기 자식 그룹에만 신호).
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import events as E
from session import Session

DEFAULT_MAX_SESSIONS = 4          # D-9 임시값(데스크톱 4). 노트북 2 는 호출하는 쪽이 정한다. S7 측정 뒤 조정.
HOST_SESSION = "host"             # 호스트 자체 notice 의 host_session


class HostError(Exception):
    pass


class HostFull(HostError):
    pass


class DuplicateResume(HostError):
    pass


class DuplicateSession(HostError):
    pass


class HostClosed(HostError):
    pass


def proc_starttime(pid: int) -> Optional[int]:
    """/proc/<pid>/stat 의 starttime(22번째 필드, 부팅 후 clock tick). 없거나 좀비면 None."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    rest = data[data.rindex(")") + 2:].split()
    if len(rest) < 20 or rest[0] == "Z":
        return None
    return int(rest[19])


def default_registry_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isdir(base):
        return os.path.join(base, "llm-host")
    return os.path.join(tempfile.gettempdir(), f"llm-host-{os.getuid()}")


def _env_has_marker(pid: int, host_id: str) -> Optional[bool]:
    """자식 환경에 LLM_HOST_ID=<host_id> 가 있는가. 읽을 수 없으면 None(판정 보류)."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return f"LLM_HOST_ID={host_id}".encode() in f.read().split(b"\0")
    except OSError:
        return None


@dataclass
class Orphan:
    pid: int
    starttime: int
    host_id: str
    host_session: str
    label: Optional[str] = None
    started_at: Optional[float] = None
    marker_verified: Optional[bool] = None    # 환경 표지 확인 결과(None=읽을 수 없어 보류)


class Registry:
    """children.jsonl. 추가 기록만 하고(add·del), 읽을 때 접어서 현재 상태를 만든다. 파일 잠금(flock)으로 여러 호스트가 같이 쓴다."""

    def __init__(self, dir_: Optional[str] = None):
        self.dir = dir_ or default_registry_dir()
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.path = os.path.join(self.dir, "children.jsonl")
        self._lockpath = os.path.join(self.dir, "children.lock")

    def _lock(self):
        fd = os.open(self._lockpath, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    @staticmethod
    def _unlock(fd) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _fold(self) -> dict:
        cur: dict = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                for ln in f:
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue          # 쓰는 도중 호스트가 죽어 잘린 줄
                    if not isinstance(r, dict) or "pid" not in r or "starttime" not in r:
                        continue
                    key = (r["pid"], r["starttime"])
                    if r.get("op") == "add":
                        cur[key] = r
                    elif r.get("op") == "del":
                        cur.pop(key, None)
        except FileNotFoundError:
            pass
        return cur

    def entries(self) -> list:
        fd = self._lock()
        try:
            return list(self._fold().values())
        finally:
            self._unlock(fd)

    def add(self, rec: dict) -> None:
        self._append({"op": "add", **rec})

    def remove(self, pid: int, starttime: int) -> None:
        self._append({"op": "del", "pid": pid, "starttime": starttime})

    def _append(self, rec: dict) -> None:
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
        fd = self._lock()
        try:
            with open(self.path, "a+b") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:        # 쓰는 도중 죽은 호스트가 개행 없이 남긴 꼬리가 다음 줄에 붙어 두 줄이 같이 깨지지 않게
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        line = "\n" + line
                f.write(line.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
        finally:
            self._unlock(fd)

    def compact(self, keep: Callable[[dict], bool]) -> int:
        """keep 이 참인 항목만 남기고 파일을 다시 쓴다(원자적 교체). 버린 수를 돌려준다."""
        fd = self._lock()
        try:
            cur = self._fold()
            kept = [r for r in cur.values() if keep(r)]
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            return len(cur) - len(kept)
        finally:
            self._unlock(fd)


class SessionHost:
    def __init__(self, adapter_factory: Callable[[str], object], max_sessions: int = DEFAULT_MAX_SESSIONS,
                 registry_dir: Optional[str] = None, term_wait: float = 5.0, keep_history: bool = False):
        if max_sessions < 1:
            raise ValueError("max_sessions 는 1 이상")
        self.adapter_factory = adapter_factory
        self.max_sessions = max_sessions
        self.term_wait = term_wait
        self.keep_history = keep_history
        self.registry = Registry(registry_dir)
        self.host_id = uuid.uuid4().hex[:8]
        self.host_pid = os.getpid()
        self.host_starttime = proc_starttime(self.host_pid)
        self.notices: list = []                       # 호스트 자체 notice(고아 안내 등)
        self._sessions: dict = {}                     # host_session → Session
        self._starting: set = set()                   # start_session 중인 host_session(아직 _sessions 에 없다; 상한에는 센다)
        self._resume_ids: dict = {}                   # backend 세션 id(resume) → host_session
        self._watchers: dict = {}                     # host_session → 종료 감시 태스크
        self._reg_keys: dict = {}                     # host_session → (pid, starttime)
        self._n = 0
        self._closed = False

    # ------------------------------------------------------------ 조회
    @property
    def sessions(self) -> dict:
        return dict(self._sessions)

    def get(self, host_session: str) -> Optional[Session]:
        return self._sessions.get(host_session)

    @property
    def active(self) -> int:
        """상한에 세는 수: 끝나지 않은 세션 + 기동 중."""
        return sum(1 for s in self._sessions.values() if not s._exited.is_set()) + len(self._starting)

    def _notice(self, level: str, text: str, **extra) -> E.Notice:
        ev = E.Notice(host_session=HOST_SESSION, level=level, text=text, extra=extra)
        ev.seq = len(self.notices) + 1
        ev.ts = time.time()
        self.notices.append(ev)
        return ev

    # ------------------------------------------------------------ 시작
    async def start_session(self, spec: Optional[dict] = None, host_session: Optional[str] = None) -> Session:
        if self._closed:
            raise HostClosed("호스트가 닫혔다")
        spec = dict(spec or {})
        if self.active >= self.max_sessions:
            raise HostFull(f"동시 세션 상한 {self.max_sessions} 에 도달")
        resume = spec.get("resume")
        if resume and resume in self._resume_ids:
            raise DuplicateResume(f"backend 세션 {resume} 을 {self._resume_ids[resume]} 가 이미 쓰고 있다")
        if host_session is None:
            while True:
                self._n += 1
                host_session = f"s{self._n}"
                if host_session not in self._sessions and host_session not in self._starting:
                    break
        elif host_session in self._sessions or host_session in self._starting:
            raise DuplicateSession(f"host_session {host_session} 가 이미 있다")
        env_extra = dict(spec.get("env_extra") or {})
        env_extra["LLM_HOST_ID"] = self.host_id
        spec["env_extra"] = env_extra
        self._starting.add(host_session)              # await 전에 자리를 잡는다(동시 호출이 상한을 넘기지 못하게)
        if resume:
            self._resume_ids[resume] = host_session
        try:
            s = Session(self.adapter_factory(host_session), spec, host_session=host_session,
                        keep_history=self.keep_history, term_wait=self.term_wait)
            await s.start()
            self._sessions[host_session] = s
        except BaseException:
            if resume:
                self._resume_ids.pop(resume, None)
            raise
        finally:
            self._starting.discard(host_session)
        if s._exited.is_set():                        # 기동 실패(백엔드를 못 띄움): 레지스트리에 올리지 않는다
            self._forget_session(host_session)
            return s
        st = proc_starttime(s.pid) if s.pid else None
        if st is not None:
            self._reg_keys[host_session] = (s.pid, st)
            self.registry.add({"pid": s.pid, "starttime": st, "host_id": self.host_id, "host_pid": self.host_pid,
                               "host_starttime": self.host_starttime, "host_session": host_session,
                               "label": spec.get("label"), "started_at": time.time()})
        self._watchers[host_session] = asyncio.create_task(self._watch(host_session, s))
        return s

    async def _watch(self, host_session: str, s: Session) -> None:
        await s.wait_closed()
        # 프로세스는 끝났다. 레지스트리에서 지우고 상한에서 뺀다(세션 객체는 이벤트 소비를 위해 get 으로 계속 얻을 수 있게 둔다).
        key = self._reg_keys.pop(host_session, None)
        if key:
            self.registry.remove(*key)
        resume = s.spec.get("resume")
        if resume and self._resume_ids.get(resume) == host_session:
            self._resume_ids.pop(resume, None)

    def _forget_session(self, host_session: str) -> None:
        s = self._sessions.get(host_session)
        resume = s.spec.get("resume") if s else None
        if resume and self._resume_ids.get(resume) == host_session:
            self._resume_ids.pop(resume, None)

    def release(self, host_session: str) -> None:
        """끝난 세션 객체를 호스트 표에서 치운다(소비자가 이벤트를 다 읽은 뒤)."""
        s = self._sessions.get(host_session)
        if s is not None and s._exited.is_set():
            self._sessions.pop(host_session, None)
            self._watchers.pop(host_session, None)

    # ------------------------------------------------------------ 종료
    async def close_session(self, host_session: str, grace: float = 10.0) -> None:
        s = self._sessions.get(host_session)
        if s is not None:
            await s.close(grace)
            await self._settle(host_session)

    async def _settle(self, host_session: str) -> None:
        w = self._watchers.get(host_session)
        if w is not None:
            await asyncio.shield(w)

    async def close_all(self, grace: float = 10.0) -> None:
        """모든 세션을 병렬로 4단계 종료한다. 호스트는 이후 새 세션을 받지 않는다."""
        self._closed = True
        live = [h for h, s in self._sessions.items() if not s._exited.is_set()]
        await asyncio.gather(*(self.close_session(h, grace) for h in live))

    async def kill_all(self) -> None:
        self._closed = True
        live = [h for h, s in self._sessions.items() if not s._exited.is_set()]
        await asyncio.gather(*(self._kill(h) for h in live))

    async def _kill(self, host_session: str) -> None:
        await self._sessions[host_session].kill()
        await self._settle(host_session)

    async def __aenter__(self) -> "SessionHost":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close_all(grace=2.0)

    # ------------------------------------------------------------ 고아 탐지(알림만)
    def scan_orphans(self, compact: bool = True) -> list:
        """레지스트리를 훑어 고아(자식은 pid·starttime 이 같은 채 살아 있고, 띄운 호스트는 죽음)를 돌려준다. 죽이지 않는다.
        - 자식이 이미 죽었거나 pid 가 재사용돼 starttime 이 다르면 고아가 아니다(항목을 버린다).
        - 띄운 호스트가 아직 살아 있으면(다른 인스턴스, 또는 이 호스트 자신) 고아가 아니다(남긴다).
        - 환경 표지(LLM_HOST_ID)가 읽히는데 다르면 고아로 보지 않는다(pid 재사용 이중 방어).
        고아마다 호스트 notice 를 하나 남기고(self.notices), 정리 방법은 procctl 안내까지만 한다."""
        orphans: list = []
        dead: set = set()
        for r in self.registry.entries():
            key = (r["pid"], r["starttime"])
            if proc_starttime(r["pid"]) != r["starttime"]:
                dead.add(key)
                continue
            if r.get("host_id") == self.host_id:
                continue
            hp, hs = r.get("host_pid"), r.get("host_starttime")
            if hp is not None and hs is not None and proc_starttime(hp) == hs:
                continue                                   # 띄운 호스트가 살아 있다
            mv = _env_has_marker(r["pid"], r.get("host_id", ""))
            if mv is False:
                dead.add(key)                              # 같은 pid·starttime 인데 우리 표지가 없다: 우리 자식이 아니다
                continue
            orphans.append(Orphan(pid=r["pid"], starttime=r["starttime"], host_id=r.get("host_id", ""),
                                  host_session=r.get("host_session", ""), label=r.get("label"),
                                  started_at=r.get("started_at"), marker_verified=mv))
        if compact and dead:
            self.registry.compact(lambda r: (r["pid"], r["starttime"]) not in dead)
        for o in orphans:
            self._notice("warn", orphan_guidance(o), pid=o.pid, host_id=o.host_id, host_session=o.host_session)
        return orphans

    def forget_orphan(self, orphan: Orphan) -> None:
        """사람이 정리했거나 무시하기로 한 고아를 레지스트리에서 뺀다(프로세스는 건드리지 않는다)."""
        self.registry.remove(orphan.pid, orphan.starttime)


def orphan_guidance(o: Orphan) -> str:
    return (f"이전 호스트({o.host_id})가 띄운 자식 프로세스 pid {o.pid}(세션 {o.host_session}"
            + (f", {o.label}" if o.label else "") + ")가 아직 살아 있다. 호스트는 죽이지 않는다. "
            "정리하려면 procctl plan 으로 대상을 확인한 뒤 사용자 확인을 받아 procctl apply 를 쓴다.")
