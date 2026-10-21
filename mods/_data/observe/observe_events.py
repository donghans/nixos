"""observe_events — 우리 유틸리티가 쓰는 **구조화 이벤트 로그**(TRACE~ERROR). 표준 라이브러리만.

사용:
    from observe_events import Events
    ev = Events("displayui")
    ev.debug("key", key="enter", focus="res")
    with ev.span("apply", mode="2560x1600@60"):
        ...
수준은 제어 파일(components)에서 읽는다 — 프로그램을 다시 시작하지 않고 `observectl level displayui trace` 로 바꿀 수 있다(1초 캐시).
기록 위치: ~/.local/state/observe/events-YYYYMMDD.jsonl (사용자 소유). 개인정보 원칙: 입력창에 친 글자·URL·명령 인자는 넘기지 말 것.
오류가 나도 호출한 프로그램을 죽이지 않는다(기록 실패는 조용히 무시).
"""
import contextvars, os, secrets, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe_core as core

# --- 스팬 문맥: (trace_id, span_id). 같은 프로세스 안에서는 contextvar, 자식 프로세스로는 환경변수 OBSERVE_TRACE="trace:span" 로 이어진다.
_CUR = contextvars.ContextVar("observe_span", default=None)


def new_id():
    return secrets.token_hex(4)


def current():
    """지금 열려 있는 스팬 (trace, span) 또는 없으면 None. 이 프로세스에 없으면 부모 프로세스가 넘긴 OBSERVE_TRACE 를 본다."""
    cur = _CUR.get()
    if cur:
        return cur
    t, _, s = os.environ.get("OBSERVE_TRACE", "").partition(":")
    return (t, s) if t and s else None


def child_env(extra=None):
    """자식 프로세스에 넘길 환경(현재 스팬을 부모로 이어 줌)."""
    env = dict(os.environ if extra is None else extra)
    cur = current()
    if cur:
        env["OBSERVE_TRACE"] = f"{cur[0]}:{cur[1]}"
    return env


class Events:
    def __init__(self, component, ctl_path=None):
        self.component = component
        self._ctl_path = ctl_path
        self._ctl, self._ctl_t = None, 0.0

    def _level(self):
        now = time.monotonic()
        if self._ctl is None or now - self._ctl_t > 1.0:
            self._ctl, self._ctl_t = core.read_control(self._ctl_path), now
        return core.level_for(self.component, self._ctl)

    def emit(self, level, event, **kv):
        lv = core.LEVELS[level]
        try:
            if lv < self._level():
                return False
            core.append_jsonl(core.state_dir(), "events", {"t": round(time.time(), 3), "mono": round(time.monotonic(), 3), "pid": os.getpid(),
                                                            "comp": self.component, "lvl": level, "ev": event, **kv})
            return True
        except Exception:
            return False

    def trace(self, event, **kv): return self.emit("trace", event, **kv)
    def debug(self, event, **kv): return self.emit("debug", event, **kv)
    def info(self, event, **kv): return self.emit("info", event, **kv)
    def warn(self, event, **kv): return self.emit("warn", event, **kv)
    def error(self, event, **kv): return self.emit("error", event, **kv)

    def span(self, event, level="debug", **kv):
        """구간(스팬) 기록. 시작/끝 이벤트에 span·trace·parent 가 붙어 observectl trace 가 부모-자식 트리와 구간별 에너지를 만든다.
        기본 수준 debug(컴포넌트를 debug 로 켠 경우만 기록), 항상 남기려면 level="info"."""
        return _Span(self, event, kv, level)


class _Span:
    """with ev.span("apply", ...) as sp: 시작/끝/소요 시간(ms)·예외·부모 연결을 기록. sp.set(k=v) 로 끝 이벤트에 속성 추가, sp.env() 로 자식 프로세스에 넘길 환경."""
    def __init__(self, ev, event, kv, level="debug"):
        self.ev, self.event, self.kv, self.level, self.extra = ev, event, kv, level, {}

    def set(self, **kv):
        self.extra.update(kv)

    def ids(self):
        return {"span": self.id, "trace": self.trace, "parent": self.parent}

    def env(self):
        return {"OBSERVE_TRACE": f"{self.trace}:{self.id}"}

    def __enter__(self):
        parent = current()
        self.trace, self.parent = (parent[0], parent[1]) if parent else (new_id(), None)
        self.id = new_id()
        self._tok = _CUR.set((self.trace, self.id))
        self.t0 = time.monotonic()
        self.ev.emit(self.level, self.event + ".begin", **self.ids(), **self.kv)
        return self

    def __exit__(self, et, e, tb):
        ms = round((time.monotonic() - self.t0) * 1000, 1)
        try:
            _CUR.reset(self._tok)
        except ValueError:
            pass
        if et:
            self.ev.emit("error", self.event + ".fail", **{**self.kv, **self.extra}, **self.ids(), ms=ms, exc=f"{et.__name__}: {e}")
        else:
            self.ev.emit(self.level, self.event + ".end", **{**self.kv, **self.extra}, **self.ids(), ms=ms)
        return False
