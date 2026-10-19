"""잠금(flock), 상태 파일(state.json) 읽기/쓰기, 기본 상태."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os

# ───────────────────────── 잠금 ─────────────────────────
from .config import LOCK_FILE, STATE_DIR, STATE_FILE
from .hypr import Mon

_lock_depth = 0
_lock_fd = None


@contextlib.contextmanager
def locked():
    """상태/대기 기록을 만지는 동안의 배타 잠금. 같은 프로세스에서 중첩 호출해도 안전(같은 파일에 flock 을 두 번 걸면 교착)"""
    global _lock_depth, _lock_fd
    if _lock_depth == 0:
        os.makedirs(STATE_DIR, exist_ok=True)
        _lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX)
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if _lock_depth == 0:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
            _lock_fd = None


# ───────────────────────── 상태 파일 ─────────────────────────
def default_state() -> dict:
    return {"layout": "extend", "monitors": {}, "pos": {}, "before": None, "preset": None}


def load_state() -> dict | None:
    """저장된 사용자 구성. 없으면 None (= 설정 파일의 기본 구성을 그대로 둠)"""
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        base = default_state()
        base.update(st)
        return base
    except (OSError, ValueError):
        return None


def save_state(st: dict | None) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    if st is None:
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def seed(st: dict, mons: list[Mon]) -> dict:
    """상태에 아직 없는 모니터의 현재 모드/배율을 기록 (이후 레이아웃을 바꿔도 해상도 등이 유지되도록)"""
    for m in mons:
        if m.name not in st["monitors"] and not m.disabled and m.width and m.height:
            st["monitors"][m.name] = {"mode": m.mode, "scale": m.scale}
    return st
