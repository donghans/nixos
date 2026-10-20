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
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe_core as core


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

    def span(self, event, **kv):
        return _Span(self, event, kv)


class _Span:
    """with ev.span("apply", ...): 시작/끝/소요 시간(ms)과 예외를 기록."""
    def __init__(self, ev, event, kv):
        self.ev, self.event, self.kv = ev, event, kv

    def __enter__(self):
        self.t0 = time.monotonic()
        self.ev.debug(self.event + ".begin", **self.kv)
        return self

    def __exit__(self, et, e, tb):
        ms = round((time.monotonic() - self.t0) * 1000, 1)
        if et:
            self.ev.error(self.event + ".fail", ms=ms, exc=f"{et.__name__}: {e}", **self.kv)
        else:
            self.ev.debug(self.event + ".end", ms=ms, **self.kv)
        return False
