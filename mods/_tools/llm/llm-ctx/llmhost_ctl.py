"""llmhost_ctl — llmui 9 「호스트」 탭(S1)이 llm-host(llm-trust 11)를 구동하는 어댑터. 화면(Textual)을 모르고, 파이썬 표준 라이브러리 + llm-host 만 쓴다.

구조: 별도 스레드가 asyncio 루프를 돌리며 llm-host 의 SessionHost 를 소유한다(UI 스레드는 막히지 않는다). 이벤트는 lock 으로 보호한 목록에 dict 로 쌓이고
UI 는 타이머로 drain() 해서 가져간다(스레드 사이에 위젯을 건드리지 않는다). 명령(start·send·close)은 즉시 돌아오고 오류는 notice 이벤트로 목록에 올라온다.

S1 범위: 세션 시작·텍스트 스트림·결과·비용. 권한·질문 요청은 이 단계에서 사용자가 답할 수 없으므로 **자동 거부**하고 notice 로 알린다(S2 에서 응답 화면). 중단은 S2.
llm-host 위치: 환경변수 LLMUI_HOST_DIR > 소스 트리의 ../llm-host (llm-host 는 아직 nix 에 등록되지 않았다 — 배포본에서는 환경변수로 가리킨다).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading

DEFAULT_LOG = "<default>"      # log_root 에 이 값을 주면 llm-host 의 기본 위치($XDG_STATE_HOME/llm-host). None 이면 이벤트 로그를 남기지 않는다


def find_host_dir() -> str | None:
    """llm-host 소스 폴더(환경변수 LLMUI_HOST_DIR 이 먼저). claude_adapter.py 가 있는 폴더만 인정한다."""
    cands = [os.environ.get("LLMUI_HOST_DIR"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm-host")]
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "claude_adapter.py")):
            return os.path.abspath(d)
    return None


def _import_host(d: str) -> dict:
    if d not in sys.path:
        sys.path.insert(0, d)
    import claude_adapter, events, host, launcher, policy, recorder  # noqa: E401
    return dict(claude_adapter=claude_adapter, events=events, host=host, launcher=launcher, policy=policy, recorder=recorder)


def availability() -> tuple[bool, str]:
    """(쓸 수 있나, 사유). 모듈을 실제로 읽어 본다."""
    d = find_host_dir()
    if not d:
        return False, "llm-host 를 찾지 못했다 — 소스 트리에서 실행하거나 환경변수 LLMUI_HOST_DIR 에 llm-host 폴더를 지정하라"
    try:
        _import_host(d)
    except Exception as e:                                          # noqa: BLE001
        return False, f"llm-host 를 읽지 못함: {e.__class__.__name__}: {e}"
    return True, d


class HostBridge:
    """세션 하나를 구동하는 어댑터(S1 은 한 번에 한 세션). 스레드 안전: start·send·close·drain·상태 읽기는 UI 스레드에서 불러도 된다."""

    def __init__(self, *, log_root: str | None = DEFAULT_LOG, use_launcher: bool = True, sudo_ready: bool = False, max_sessions: int = 4):
        ok, why = availability()
        if not ok:
            raise RuntimeError(why)
        self._m = _import_host(why)
        self.log_root = self._m["recorder"].default_log_root() if log_root == DEFAULT_LOG else log_root
        self.use_launcher = use_launcher
        self.sudo_ready = sudo_ready
        self._lock = threading.Lock()
        self._events: list = []          # drain 전 이벤트(dict)
        self.state = "none"              # none · starting · idle · busy · closed · crashed (화면 힌트)
        self.cost_total: float | None = None
        self.turns = 0
        self.session_label = ""
        self._session = None
        self._host = None
        self._max = max_sessions
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="llmhost-loop", daemon=True)
        self._thread.start()
        self._pump_task = None

    # ------------------------------------------------------------ 스레드
    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def done(f):
            try:
                f.result()
            except BaseException as e:                              # noqa: BLE001 — 명령 오류는 화면 notice 로
                self._local_notice("error", f"{e.__class__.__name__}: {e}")
        fut.add_done_callback(done)
        return fut

    def _push(self, ev) -> None:
        E = self._m["events"]
        d = json.loads(E.to_json(ev))
        with self._lock:
            self._events.append(d)
        k = d.get("kind")
        if k == "turn_result":
            self.turns += 1
            if d.get("cost_total") is not None:
                self.cost_total = d["cost_total"]
            self.state = "idle"
        elif k == "turn_started":
            self.state = "busy"
        elif k == "session_ended":
            self.state = "crashed" if d.get("reason") == "crashed" else "closed"

    def _local_notice(self, level: str, text: str) -> None:
        with self._lock:
            self._events.append({"kind": "notice", "level": level, "text": text, "seq": None, "extra": {"local": True}})

    # ------------------------------------------------------------ 공개 API
    def drain(self) -> list:
        """마지막 drain 뒤에 쌓인 이벤트(dict) 목록."""
        with self._lock:
            out, self._events = self._events, []
        return out

    @property
    def running(self) -> bool:
        return self._session is not None and self.state in ("starting", "idle", "busy")

    def start(self, cwd: str, model: str | None = None, permission_mode: str = "manual", exe=None, label: str = "", extra_spec: dict | None = None) -> str | None:
        """세션 시작을 예약한다. 바로 알 수 있는 거부 사유(이미 실행 중·bypass·폴더 없음)는 문자열로 돌려주고, 나머지 실패는 notice 이벤트로 온다."""
        if self.running:
            return "이미 세션이 실행 중이다(F3 으로 닫은 뒤 새로 시작)"
        if not os.path.isdir(cwd):
            return f"작업 폴더가 없다: {cwd}"
        spec = {"cwd": cwd, "permission_mode": permission_mode, "persist": True, "policy": {"request_timeout": 1800}}
        if model:
            spec["model"] = model
        if label:
            spec["label"] = label
        if exe:
            spec["exe"] = exe
        spec.update(extra_spec or {})
        bad = self._m["policy"].check_start(spec)           # 소비자 책임(llm-host README): bypass 계열은 시작하지 않는다
        if bad:
            return "시작하지 않음: " + "; ".join(bad)
        self.state = "starting"
        self.cost_total, self.turns = None, 0
        self._submit(self._start(spec))
        return None

    async def _start(self, spec: dict) -> None:
        m = self._m
        try:
            plan_notices: list = []
            if self.use_launcher:
                spec, plan = m["launcher"].launch_spec(spec, sudo_ready=self.sudo_ready)   # claude-run 을 못 찾으면 LauncherError(훅 없이 시작하지 않는다)
                plan_notices = list(plan.notices)
            if self._host is None:
                self._host = m["host"].SessionHost(lambda hs: m["claude_adapter"].ClaudeAdapter(hs), max_sessions=self._max, log_root=self.log_root)
            s = await self._host.start_session(spec)
        except BaseException as e:                                  # noqa: BLE001
            self.state = "none"
            self._local_notice("error", f"세션을 시작하지 못함: {e.__class__.__name__}: {e}")
            return
        self._session = s
        self.session_label = s.host_session
        self.state = "idle"
        for lvl, txt in plan_notices:
            self._local_notice(lvl, txt)
        self._pump_task = asyncio.ensure_future(self._pump(s))

    async def _pump(self, s) -> None:
        """세션 이벤트를 목록으로 옮긴다. 권한·질문 요청은 S1 에서 자동 거부(응답 화면은 S2)."""
        m = self._m
        E, P = m["events"], m["policy"]
        async for ev in s.events():
            self._push(ev)
            if isinstance(ev, E.PermissionRequest) or isinstance(ev, E.QuestionRequest):
                msg = P.deny_message("user_denied", user_reason="이 화면(llmui 호스트 탭 S1)은 아직 권한·질문에 응답하지 못한다. 도구 없이 답할 수 있는 만큼만 답하고, 필요한 도구·질문은 하지 못했다고 보고하라.")
                self._local_notice("warn", f"{'질문' if isinstance(ev, E.QuestionRequest) else '권한 요청'} [{ev.req}] 을 자동 거부했다(S1 은 응답을 지원하지 않음)")
                try:
                    await s.answer_permission(ev.req, False, message=msg)
                except Exception as e:                                # noqa: BLE001
                    self._local_notice("error", f"자동 거부 전송 실패: {e.__class__.__name__}: {e}")

    def send(self, text: str) -> str | None:
        """사용자 메시지를 보낸다. 거부 사유(세션 없음·빈 글)는 문자열로."""
        if not text.strip():
            return "빈 지시는 보내지 않는다"
        s = self._session
        if s is None or not self.running:
            return "실행 중인 세션이 없다(F2 로 시작)"
        self.state = "busy"
        with self._lock:
            self._events.append({"kind": "user_input", "text": text, "seq": None})
        self._submit(s.send(text))
        return None

    def close(self, grace: float = 5.0) -> None:
        s = self._session
        if s is not None and self.running:
            self.state = "closed"
            self._submit(s.close(grace=grace))

    def shutdown(self, wait: float = 10.0) -> None:
        """앱을 끝낼 때: 호스트의 모든 세션을 닫고(미해결 요청 deny) 루프를 멈춘다. 자식 프로세스를 남기지 않는다."""
        try:
            if self._host is not None:
                asyncio.run_coroutine_threadsafe(self._host.close_all(), self._loop).result(timeout=wait)
        except BaseException:                                       # noqa: BLE001
            try:
                asyncio.run_coroutine_threadsafe(self._host.kill_all(), self._loop).result(timeout=5.0)
            except BaseException:                                   # noqa: BLE001
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)

    def child_pids(self) -> list:
        s = self._session
        return [s.pid] if s is not None and s.pid else []
