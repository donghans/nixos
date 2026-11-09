"""이벤트 로그·보존 삭제·비용 누적·시험용 원본 줄 녹화. 설계: plan llm-trust/11-p5prime-2-session-host §8·§10(단계 S6).
Python 3.10+ 표준 라이브러리만. 벤더를 모른다.

- EventLog: `<root>/<host_session>/events.jsonl`(파일 0600, 폴더 0700). 한 줄 = 이벤트 하나(`Event.to_dict()`). `text_delta` 는 기본 제외(분량).
  **이 로그에는 도구 입력·메시지 본문이 들어 있어 비밀·고객 데이터가 섞일 수 있다** — 그래서 0600·짧은 보존이고, ctx 로 올리는 코드는 없다
  (ctx 는 이미 transcript 에서 적재한다). 로그를 못 써도(디스크 가득 등) 세션은 죽지 않는다(`errors` 로 센다).
  같은 host_session 이름은 호스트가 다시 떠도 같은 파일에 이어 쓴다 — 시작할 때 `log_open` 줄(host_id·pid)을 남겨 구분한다.
- 기본 위치: `$XDG_STATE_HOME/llm-host` 없으면 `~/.local/state/llm-host`(이 저장소의 displayctl·hypr 도 같은 관례).
- purge_logs(root, days=14): `events.jsonl` 이 days 일보다 오래 안 바뀐 세션 폴더를 지운다. 지우는 것은 root 바로 아래 폴더의
  `events.jsonl` 과 그 폴더(비었을 때)뿐이고, 심볼릭 링크는 건드리지 않는다.
- CostTracker: turn_result.cost_delta 를 더한다(누적 `cost_total` 은 마지막 값). `total_cost_usd` 는 클라이언트 추정치라 청구와 다를 수 있다.
  --resume 한 세션은 어댑터의 cost_delta 가 이 프로세스 안 증가분만이므로 합계도 이번 호스트 실행분이다.
- RecordingAdapter: 시험용. 어댑터를 감싸 날 줄을 `{"t","dir","line"}` JSON 줄로 녹화한다(in=호스트가 보낸 줄, out=백엔드가 낸 줄,
  out_unparsed=JSON 이 아닌 줄) — tests/fixtures 와 같은 형식. **원본이라 개인 경로·세션 id 가 들어 있으니 저장소에 그대로 두지 않는다**(0600).
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import events as E

DEFAULT_RETENTION_DAYS = 14        # D-8 추천값
LOG_NAME = "events.jsonl"
DEFAULT_EXCLUDE = frozenset({"text_delta"})


def default_log_root() -> str:
    base = os.environ.get("XDG_STATE_HOME")
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "llm-host")


def _dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), default=str)


def _open_private_append(path: str):
    """없으면 0600 으로 만들고, 있으면 권한을 0600 으로 되돌려 연다(umask 와 무관)."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, "a", encoding="utf-8")


class EventLog:
    def __init__(self, host_session: str, root: Optional[str] = None, include: bool = False, exclude=DEFAULT_EXCLUDE,
                 host_id: Optional[str] = None):
        if not host_session or "/" in host_session or host_session in (".", "..") or "\0" in host_session:
            raise ValueError(f"host_session 이름이 폴더 이름으로 쓸 수 없다: {host_session!r}")
        self.host_session = host_session
        self.root = root or default_log_root()
        self.dir = os.path.join(self.root, host_session)
        self.path = os.path.join(self.dir, LOG_NAME)
        self.exclude = frozenset() if include else frozenset(exclude)
        self.errors = 0
        self.written = 0
        self.skipped = 0
        self._f = None
        self._closed = False
        self._host_id = host_id

    def _ensure(self) -> None:
        if self._f is not None:
            return
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self._f = _open_private_append(self.path)
        self._f.write(_dumps({"kind": "log_open", "ts": time.time(), "host_session": self.host_session,
                              "host_id": self._host_id, "pid": os.getpid(), "excluded": sorted(self.exclude)}) + "\n")

    def record(self, ev: E.Event) -> bool:
        """이벤트 하나를 쓴다. 제외 종류면 False. 쓰기 실패는 삼키고 errors 만 센다."""
        if self._closed:
            return False
        if ev.kind in self.exclude:
            self.skipped += 1
            return False
        try:
            self._ensure()
            self._f.write(_dumps(ev.to_dict()) + "\n")
            self._f.flush()
            self.written += 1
            return True
        except (OSError, ValueError, TypeError):
            self.errors += 1
            return False

    __call__ = record

    def close(self) -> None:
        self._closed = True
        if self._f is not None:
            try:
                self._f.close()
            except OSError:
                pass
            self._f = None


def read_log(path: str) -> list:
    """로그 파일을 dict 목록으로 읽는다(깨진 꼬리 줄은 건너뜀)."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return out


def purge_logs(root: Optional[str] = None, days: float = DEFAULT_RETENTION_DAYS, now: Optional[float] = None) -> list:
    """days 일보다 오래 안 바뀐 `<root>/<세션>/events.jsonl` 을 지우고(폴더가 비면 폴더도) 지운 폴더 이름을 돌려준다."""
    if days is None or days < 0:
        raise ValueError("days 는 0 이상")
    root = root or default_log_root()
    cutoff = (time.time() if now is None else now) - days * 86400
    removed: list = []
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        return removed
    for name in names:
        d = os.path.join(root, name)
        f = os.path.join(d, LOG_NAME)
        try:
            if os.path.islink(d) or not os.path.isdir(d):
                continue
            st = os.lstat(f)
            if not os.path.isfile(f) or os.path.islink(f) or st.st_mtime >= cutoff:
                continue
            os.unlink(f)
            removed.append(name)
            try:
                os.rmdir(d)               # 다른 파일이 남아 있으면 그대로 둔다
            except OSError:
                pass
        except OSError:
            continue
    return removed


class CostTracker:
    def __init__(self):
        self.total = 0.0           # cost_delta 의 합
        self.last_total: Optional[float] = None   # 백엔드가 보고한 마지막 누적
        self.turns = 0             # turn_result 수
        self.priced_turns = 0      # cost_delta 가 있던 턴 수

    def add(self, ev: E.Event) -> None:
        if not isinstance(ev, E.TurnResult):
            return
        self.turns += 1
        if ev.cost_delta is not None:
            self.total += ev.cost_delta
            self.priced_turns += 1
        if ev.cost_total is not None:
            self.last_total = ev.cost_total

    def summary(self) -> dict:
        return {"total": round(self.total, 10), "last_cost_total": self.last_total, "turns": self.turns, "priced_turns": self.priced_turns}


class RecordingAdapter:
    """어댑터를 감싸 날 줄을 녹화한다. 나머지 속성은 안쪽 어댑터로 넘긴다."""

    def __init__(self, inner, path: str):
        self._inner = inner
        self.path = path
        self._t0 = time.monotonic()
        os.makedirs(os.path.dirname(os.path.abspath(path)), mode=0o700, exist_ok=True)
        self._f = _open_private_append(path)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _rec(self, d: str, line) -> None:
        try:
            self._f.write(_dumps({"t": round(time.monotonic() - self._t0, 3), "dir": d, "line": line}) + "\n")
            self._f.flush()
        except (OSError, ValueError):
            pass

    def decode(self, line):
        if isinstance(line, (bytes, bytearray)):
            line = bytes(line).decode("utf-8", "replace")
        if isinstance(line, str):
            s = line.strip()
            if s:
                try:
                    self._rec("out", json.loads(s))
                except ValueError:
                    self._rec("out_unparsed", line)
        else:
            self._rec("out", line)
        return self._inner.decode(line)

    def encode(self, command):
        lines = self._inner.encode(command)
        for ln in lines:
            try:
                self._rec("in", json.loads(ln))
            except ValueError:
                self._rec("in", ln)
        return lines

    def note(self, text: str) -> None:
        self._rec("note", text)

    def close(self) -> None:
        try:
            self._f.close()
        except OSError:
            pass
