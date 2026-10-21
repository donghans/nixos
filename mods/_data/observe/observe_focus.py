#!/usr/bin/env python3
"""observe_focus — Hyprland 이벤트 소켓(.socket2)을 읽어 **창 수명**과 **포커스 구간**을 스팬으로 남긴다(앱 수정 없이 "어느 앱을 쓰던 구간인가").
  windows:window:<class>   창이 열려 있던 동안(부모)      속성: ws
  windows:focus:<class>    그 창이 포커스였던 동안(자식)   → observectl trace --comp windows --by 로 앱별 포커스 시간·에너지
개인정보: **창 제목은 기록하지 않는다**(메일 제목·URL 이 들어갈 수 있음). 창 class(앱 이름)와 작업공간 이름만 본다.
이벤트가 올 때만 깨어난다(소켓을 막고 읽음). Hyprland 가 끝나 소켓이 닫히면 열린 구간을 닫고 종료한다.
사용: observe_focus.py   (환경: HYPRLAND_INSTANCE_SIGNATURE 또는 $XDG_RUNTIME_DIR/hypr/* 중 가장 최근 것)"""
from __future__ import annotations

import glob
import json
import os
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from observe_events import Events, new_id


def norm_addr(a):
    return (a or "").strip().lower().removeprefix("0x")


def clean_class(c):
    c = (c or "").strip()
    if c in ("", "?"):
        return "?"
    return re.sub(r"[^\w.\-+]", "_", c)[:40]


class FocusTracker:
    """이벤트 → 스팬 상태 기계(소켓·시계 없이 시험 가능). emit(level, 이름, **필드) 로 기록하고 lookup(address) → class 를 모를 때 부른다."""

    def __init__(self, emit, lookup=lambda addr: None):
        self.emit, self.lookup = emit, lookup
        self.windows = {}     # address → {class, ws, span, trace}
        self.focus = None     # {address, span, trace, t0}

    def _begin(self, name, span, trace, parent, **kv):
        self.emit("info", name + ".begin", span=span, trace=trace, parent=parent, **kv)

    def _end(self, name, span, trace, parent, t0, **kv):
        self.emit("info", name + ".end", span=span, trace=trace, parent=parent, ms=round((time.monotonic() - t0) * 1000, 1), **kv)

    def open_window(self, addr, cls, ws):
        addr = norm_addr(addr)
        if not addr or addr in self.windows:
            return
        sid = new_id()
        w = {"class": clean_class(cls), "ws": ws, "span": sid, "trace": sid, "t0": time.monotonic()}
        self.windows[addr] = w
        self._begin("window:" + w["class"], sid, sid, None, ws=ws)

    def close_window(self, addr):
        addr = norm_addr(addr)
        if self.focus and self.focus["address"] == addr:
            self.set_focus(None)
        w = self.windows.pop(addr, None)
        if w:
            self._end("window:" + w["class"], w["span"], w["trace"], None, w["t0"], ws=w["ws"])

    def set_focus(self, addr):
        addr = norm_addr(addr) or None
        if self.focus and self.focus["address"] == addr:
            return
        if self.focus:
            f, w = self.focus, self.windows.get(self.focus["address"])
            self._end("focus:" + f["class"], f["span"], f["trace"], f["parent"], f["t0"])
            self.focus = None
        if not addr:
            return
        w = self.windows.get(addr)
        if w is None:                                  # 서비스가 뜨기 전에 있던 창 → class 를 조회해 창 스팬부터 연다(시작 시각은 '관측 시작')
            self.open_window(addr, self.lookup(addr) or "?", "?")
            w = self.windows.get(addr)
        if w is None:
            return
        sid = new_id()
        self.focus = {"address": addr, "span": sid, "trace": w["trace"], "parent": w["span"], "class": w["class"], "t0": time.monotonic()}
        self._begin("focus:" + w["class"], sid, w["trace"], w["span"])

    def handle(self, name, data):
        if name == "openwindow":
            p = data.split(",", 3)                     # ADDRESS,WORKSPACE,CLASS,TITLE — 제목은 버린다
            if len(p) >= 3:
                self.open_window(p[0], p[2], p[1])
        elif name == "closewindow":
            self.close_window(data)
        elif name == "activewindowv2":
            self.set_focus(data)

    def close_all(self):
        self.set_focus(None)
        for addr in list(self.windows):
            self.close_window(addr)


def hypr_json(*args):
    try:
        return json.loads(subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def snapshot(tracker):
    """시작 시점의 창 목록과 활성 창을 반영한다."""
    for c in hypr_json("clients") or []:
        tracker.open_window(c.get("address", ""), c.get("class", "?"), str((c.get("workspace") or {}).get("name", "?")))
    a = hypr_json("activewindow")
    if isinstance(a, dict) and a.get("address"):
        tracker.set_focus(a["address"])


def socket_path():
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return f"{rt}/hypr/{sig}/.socket2.sock"
    c = sorted(glob.glob(f"{rt}/hypr/*/.socket2.sock"), key=os.path.getmtime)
    return c[-1] if c else None


def lookup_class(addr):
    for c in hypr_json("clients") or []:
        if norm_addr(c.get("address")) == addr:
            return c.get("class")
    return None


def run(path=None, events=None, do_snapshot=True):
    path = path or socket_path()
    if not path or not os.path.exists(path):
        sys.exit("Hyprland 이벤트 소켓을 찾을 수 없음(Hyprland 세션 안에서 실행)")
    ev = events or Events("windows")
    tracker = FocusTracker(lambda lvl, name, **kv: ev.emit(lvl, name, **kv), lookup_class)
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    if do_snapshot:
        snapshot(tracker)
    buf = b""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                name, _, data = line.decode(errors="replace").partition(">>")
                tracker.handle(name, data)
    finally:
        tracker.close_all()


def _terminate(_sig, _frm):
    raise SystemExit(0)                                # finally(열린 스팬 닫기)가 실행되도록 — 기본 SIGTERM 은 정리 없이 끝난다


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    try:
        run()
    except KeyboardInterrupt:
        pass
