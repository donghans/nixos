"""한 세션: 자식 프로세스 하나, 비동기 읽기·쓰기 태스크, 상태기계, 대기 중 요청 표. 설계: plan llm-trust/11-p5prime-2-session-host §5-1·§5-3.
벤더를 모른다(어댑터가 줄을 번역). Python 3.10+ 표준 라이브러리(asyncio)만.

수명: 생성 → `await start()` → 명령(`send`·`interrupt`·`answer_*`·`close`·`kill`) → 이벤트는 `events()` 로 읽는다 → SessionEnded 가 마지막.
상태(UI 힌트일 뿐 정합성의 근거는 백엔드 줄이다): starting → idle ⇄ busy ⇄ waiting_request → closing → closed, 예기치 않은 종료는 crashed.
- starting→idle 은 프로세스 기동 직후(첫 메시지를 보낼 수 있다). 첫 메시지 전에는 백엔드가 아무것도 내지 않는다(S0 확인, §5-1 정정) — session_ready 는 첫 send 뒤에 온다.
- busy: send 뒤 turn_result 까지(백엔드 대기열에 쌓인 send 도 센다). 훅 줄은 turn_result 뒤에도 오지만 상태는 turn_result 직후 idle.
- waiting_request: 미해결 permission_request·question_request 가 있는 동안.
- 종료 사유(SessionEnded.reason): 우리가 close 한 것 closed · kill 한 것 killed · 예기치 않은 종료 중 종료 코드 0 은 eof, 그 밖은 crashed.
자식은 새 프로세스 그룹(start_new_session)으로 띄우고, 신호는 **자기 자식의 그룹에만** 보낸다(이름·패턴 종료 없음).
정책(자동 허용·거부·대기 상한)은 S4, 다중 세션·고아 정리는 S5 몫이다 — 여기서는 요청을 표에 두고 소비자가 answer_* 로 답할 때까지 기다린다.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Callable, Optional

import events as E
from adapter import Adapter

STATES = ("starting", "idle", "busy", "waiting_request", "closing", "closed", "crashed")
_LINE_LIMIT = 1 << 26        # init 줄이 크다(도구·스킬 목록). 64MB
_STDERR_MAX = 50             # 표준오류 줄 중 notice 로 올리는 최대 수(그 뒤는 개수만)


class Session:
    def __init__(self, adapter: Adapter, spec: Optional[dict] = None, host_session: str = "s1",
                 keep_history: bool = False, term_wait: float = 5.0):
        self.adapter = adapter
        self.spec = dict(spec or {})
        self.host_session = host_session
        self.state = "starting"
        self.pending: dict = {}              # req id → PermissionRequest | QuestionRequest (미해결)
        self.history: list = []              # keep_history 일 때만 모든 이벤트
        self.policy = self.spec.get("policy")
        self.exit_code: Optional[int] = None
        self.end_reason: Optional[str] = None
        self._keep = keep_history
        self._term_wait = term_wait
        self._seq = 0
        self._q: asyncio.Queue = asyncio.Queue()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._wq: asyncio.Queue = asyncio.Queue()    # 쓰기 큐: bytes 줄 또는 None(표준입력 닫기)
        self._tasks: list = []
        self._inflight = 0                   # send 한 뒤 turn_result 를 못 받은 수
        self._closing = False
        self._killed = False
        self._stderr_n = 0
        self._started = False
        self._exited = asyncio.Event()       # SessionEnded 까지 낸 뒤

    # ------------------------------------------------------------ 이벤트
    def _emit(self, ev: E.Event) -> E.Event:
        self._seq += 1
        ev.seq = self._seq
        ev.ts = time.time()
        if not ev.host_session:
            ev.host_session = self.host_session
        if ev.backend_session is None:
            ev.backend_session = getattr(self.adapter, "backend_session", None)
        if self._keep:
            self.history.append(ev)
        self._q.put_nowait(ev)
        return ev

    def _own(self, cls, **kw) -> E.Event:
        return self._emit(cls(host_session=self.host_session, backend_session=getattr(self.adapter, "backend_session", None), **kw))

    def _notice(self, level: str, text: str, **extra) -> None:
        self._own(E.Notice, level=level, text=text, extra=extra)

    async def events(self):
        """이벤트를 도착 순서로 내는 비동기 반복자. SessionEnded 까지 내고 끝난다. 소비자는 하나여야 한다."""
        while True:
            ev = await self._q.get()
            if ev is None:
                self._q.put_nowait(None)     # 나중에 다시 불러도 끝나게
                return
            yield ev

    async def next_event(self, timeout: Optional[float] = None) -> Optional[E.Event]:
        """다음 이벤트 하나. 세션이 끝나 더 없으면 None, 시간이 지나면 asyncio.TimeoutError."""
        ev = await asyncio.wait_for(self._q.get(), timeout)
        if ev is None:
            self._q.put_nowait(None)
        return ev

    async def collect_until(self, pred: Callable[[E.Event], bool], timeout: float = 10.0) -> list:
        """pred 가 참인 이벤트가 나올 때까지 읽은 이벤트들(그 이벤트 포함). 끝나거나 시간이 지나면 TimeoutError(읽은 것은 e.args[1])."""
        end = time.monotonic() + timeout
        got: list = []
        while True:
            left = end - time.monotonic()
            try:
                ev = await self.next_event(max(left, 0.001))
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError("조건에 맞는 이벤트가 오지 않음", got)
            if ev is None:
                raise asyncio.TimeoutError("세션이 끝남", got)
            got.append(ev)
            if pred(ev):
                return got

    # ------------------------------------------------------------ 기동
    async def start(self) -> None:
        if self._started:
            raise RuntimeError("이미 start 했다")
        self._started = True
        argv = self.adapter.argv(self.spec)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=self.adapter.env(self.spec), cwd=self.spec.get("cwd") or None, start_new_session=True, limit=_LINE_LIMIT)
        except OSError as e:
            self._notice("error", f"백엔드를 띄우지 못함: {e}")
            self._finish("crashed", None)
            return
        self.state = "idle"
        self._tasks = [asyncio.create_task(self._read_loop()), asyncio.create_task(self._err_loop()), asyncio.create_task(self._write_loop())]

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    @property
    def running(self) -> bool:
        return self._proc is not None and not self._exited.is_set()

    # ------------------------------------------------------------ 읽기·쓰기 태스크
    async def _read_loop(self) -> None:
        r = self._proc.stdout
        while True:
            try:
                raw = await r.readline()
            except ValueError as e:      # 한 줄이 한도를 넘음: 그 줄은 잃었다
                self._notice("error", f"백엔드 출력 줄이 너무 길어 버림: {e}")
                continue
            if not raw:
                break
            try:
                evs = self.adapter.decode(raw.decode("utf-8", "replace").rstrip("\r\n"))
            except Exception as e:       # 어댑터 버그가 세션을 죽이지 않게
                self._notice("error", f"어댑터 decode 실패: {type(e).__name__}: {e}")
                continue
            for ev in evs:
                self._handle(self._emit(ev))
        rc = await self._proc.wait()
        try:    # 표준오류의 남은 줄이 SessionEnded 뒤로 밀리지 않게(손주 프로세스가 붙들고 있으면 1초만 기다린다)
            await asyncio.wait_for(asyncio.shield(self._tasks[1]), 1.0)
        except (asyncio.TimeoutError, Exception):
            pass
        self._finish(None, rc)

    async def _err_loop(self) -> None:
        r = self._proc.stderr
        while True:
            raw = await r.readline()
            if not raw:
                return
            self._stderr_n += 1
            if self._stderr_n <= _STDERR_MAX:
                self._notice("warn", "백엔드 표준오류: " + raw.decode("utf-8", "replace").rstrip()[:500], stream="stderr")
            elif self._stderr_n == _STDERR_MAX + 1:
                self._notice("warn", f"백엔드 표준오류가 {_STDERR_MAX}줄을 넘어 이후는 알리지 않음", stream="stderr")

    async def _write_loop(self) -> None:
        w = self._proc.stdin
        while True:
            item = await self._wq.get()
            if item is None:
                break
            try:
                w.write(item)
                await w.drain()
            except (BrokenPipeError, ConnectionResetError):
                self._notice("warn", "백엔드 표준입력이 닫혀 있어 쓰지 못함")
                break
        try:
            w.close()
        except Exception:
            pass

    def _write(self, line: str) -> None:
        self._wq.put_nowait(line.encode("utf-8") + b"\n")

    # ------------------------------------------------------------ 상태기계
    def _handle(self, ev: E.Event) -> None:
        if isinstance(ev, (E.PermissionRequest, E.QuestionRequest)):
            self.pending[ev.req] = ev
            if not self._closing:
                self.state = "waiting_request"
        elif isinstance(ev, E.TurnStarted):
            if self.state == "idle":
                self.state = "busy"
        elif isinstance(ev, E.TurnResult):
            self._inflight = max(0, self._inflight - 1)
            for req in list(self.pending):    # 턴이 끝났으면 백엔드는 더 이상 답을 기다리지 않는다(중단 등)
                self._resolve(req, "deny", "session_end", "턴이 끝나 요청이 취소됨")
            if not self._closing:
                self.state = "busy" if self._inflight else "idle"

    def _resolve(self, req: str, outcome: str, by: str, message: Optional[str] = None) -> None:
        self.pending.pop(req, None)
        self._own(E.RequestResolved, req=req, outcome=outcome, by=by, message=message)

    def _finish(self, reason: Optional[str], rc: Optional[int]) -> None:
        if self._exited.is_set():
            return
        if reason is None:
            reason = "killed" if self._killed else "closed" if self._closing else "eof" if rc == 0 else "crashed"
        self.exit_code, self.end_reason = rc, reason
        for req in list(self.pending):
            self._resolve(req, "deny", "session_end", "세션이 끝나 요청이 취소됨")
        self.state = "crashed" if reason == "crashed" else "closed"
        self._own(E.SessionEnded, reason=reason, exit_code=rc)
        self._wq.put_nowait(None)
        self._q.put_nowait(None)
        self._exited.set()

    # ------------------------------------------------------------ 명령
    def _require_running(self) -> None:
        if not self.running or self._closing:
            raise RuntimeError(f"세션이 명령을 받을 수 없는 상태({self.state})")

    async def command(self, cmd: E.Command) -> bool:
        """명령 하나를 실행한다. answer_* 는 모르는 req 면 False(경고 notice), 그 밖은 True."""
        if isinstance(cmd, E.Send):
            self._require_running()
            lines = self.adapter.encode(cmd)
            self._inflight += 1
            if self.state == "idle":
                self.state = "busy"
            for ln in lines:
                self._write(ln)
            return True
        if isinstance(cmd, E.Interrupt):
            self._require_running()
            for ln in self.adapter.encode(cmd):
                self._write(ln)
            return True
        if isinstance(cmd, (E.AnswerPermission, E.AnswerQuestion)):
            self._require_running()
            if cmd.req not in self.pending:
                self._notice("warn", f"미해결 요청이 아니라 답을 보내지 않음: {cmd.req}")
                return False
            for ln in self.adapter.encode(cmd):
                self._write(ln)
            if isinstance(cmd, E.AnswerPermission):
                self._resolve(cmd.req, "allow" if cmd.allow else "deny", "user", cmd.message)
            else:
                self._resolve(cmd.req, "answered", "user")
            if not self.pending and not self._closing:
                self.state = "busy"
            return True
        if isinstance(cmd, E.SetPolicy):
            self.policy = cmd.policy
            return True
        if isinstance(cmd, E.Close):
            await self.close(cmd.grace if cmd.grace is not None else 10.0)
            return True
        if isinstance(cmd, E.Kill):
            await self.kill()
            return True
        if isinstance(cmd, E.Start):
            raise ValueError("start 는 Session.start() 로 한다")
        raise ValueError(f"알 수 없는 명령: {type(cmd).__name__}")

    async def send(self, text: str) -> None:
        await self.command(E.Send(text=text))

    async def interrupt(self) -> None:
        await self.command(E.Interrupt())

    async def answer_permission(self, req: str, allow: bool, message: Optional[str] = None, updated_input=None) -> bool:
        return await self.command(E.AnswerPermission(req=req, allow=allow, message=message, updated_input=updated_input))

    async def answer_question(self, req: str, answers: dict, free_text: Optional[str] = None) -> bool:
        return await self.command(E.AnswerQuestion(req=req, answers=answers, free_text=free_text))

    # ------------------------------------------------------------ 종료(§5-3, 자기 자식만)
    def _signal_group(self, sig: int) -> None:
        p = self._proc
        if p is not None and p.returncode is None:      # 이미 끝난 프로세스의 그룹에는 보내지 않는다(PID 재사용 방지)
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                pass

    async def _wait_exit(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._exited.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def close(self, grace: float = 10.0) -> None:
        """정상 종료: ① 표준입력 닫기 ② grace 대기 ③ SIGTERM ④ term_wait 뒤 SIGKILL. 진행 중인 턴은 먼저 interrupt() 하는 것이 깔끔하다."""
        if not self._started or self._exited.is_set():
            return
        if not self._closing:
            self._closing = True
            self.state = "closing"
            self._wq.put_nowait(None)
        if await self._wait_exit(grace):
            return
        self._notice("warn", f"표준입력을 닫고 {grace:g}초 안에 끝나지 않아 SIGTERM 을 보냄")
        self._signal_group(signal.SIGTERM)
        if await self._wait_exit(self._term_wait):
            return
        self._notice("warn", f"SIGTERM 뒤 {self._term_wait:g}초 안에 끝나지 않아 SIGKILL 을 보냄")
        self._signal_group(signal.SIGKILL)
        await self._wait_exit(self._term_wait + 5)

    async def kill(self) -> None:
        """즉시 강제 종료(자기 자식 그룹의 SIGKILL)."""
        if not self._started or self._exited.is_set():
            return
        self._killed = True
        self._closing = True
        self.state = "closing"
        self._signal_group(signal.SIGKILL)
        await self._wait_exit(10)

    async def wait_closed(self, timeout: Optional[float] = None) -> bool:
        try:
            await asyncio.wait_for(self._exited.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
