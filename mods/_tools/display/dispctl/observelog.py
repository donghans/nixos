"""observectl 이벤트 로그 연결(shim). observectl 모듈을 못 찾으면 아무것도 안 하는 대체 객체를 돌려줘서 화면 관리 동작에는 영향이 없다.
탐색 순서: 이 패키지의 상위 디렉터리(Nix 배포: displayui.py 와 같은 곳에 observe_core/observe_events 를 복사), 저장소 상대 경로(../../observectl), 환경변수 OBSERVE_PY."""
import os
import sys


class _Null:
    def __getattr__(self, name):
        if name == "span":
            return lambda *a, **k: _NullSpan()
        return lambda *a, **k: False


class _NullSpan:
    id = trace = parent = None

    def set(self, **kv):
        pass

    def ids(self):
        return {}

    def env(self):
        return {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def events(component: str):
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, ".."), os.path.join(here, "..", "..", "observe"), os.environ.get("OBSERVE_PY", "")):
        if cand and os.path.exists(os.path.join(cand, "observe_events.py")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            try:
                from observe_events import Events
                return Events(component)
            except Exception:
                break
    return _Null()
