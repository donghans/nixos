#!/usr/bin/env python3
"""qa-desktop(VM) 안에서 가상 데스크톱을 전환한다 — Mutter RemoteDesktop 의 가상 키 입력으로 GNOME 단축키를 보낸다.

사용: ws.py right|left|home|escape   (right/left = 옆 데스크톱, home = 데스크톱 1 로 강제, escape = 열려 있는 GNOME 개요(Activities) 닫기)
- 사람 대신 데스크톱을 바꿔서 창이 안 보이는 상태를 재현하거나(렌더링·스크린샷 시험), 현재 데스크톱을 알려진 값(1)으로 맞춘다.
- home 은 Super+Home 이 아니라 Ctrl+Alt+← 를 여러 번 보낸다: Super+Home 으로 보냈을 때 이후 캡처가 실제 데스크톱이 아니라 GNOME 개요(Activities) 화면이던 적이 있다
  (2026-10-23: genple QA 시험, 직접 재현 1회. 다른 시험 4회는 재현되지 않아 **조건 미확정인 간헐 현상** — Super 키를 떼는 동작이 GNOME 의 「개요 열기」와 겹치는 것으로 추정).
  Super 를 쓰지 않으면 그 가능성이 없다. 개요가 이미 열려 있으면 먼저 `ws.py escape`.
- 설치할 것이 없다(VM 의 python3 + gi). VM 의 GNOME 세션에서 실행해야 한다
  (ssh 로 들어왔다면 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus 필요).
- 단축키는 GNOME 기본값(switch-to-workspace-right/left = Ctrl+Alt+→/←) 기준이다. 가상 데스크톱은 맨 끝에서 더 가도 순환하지 않는다(그래서 home = ← 를 충분히 반복).
"""
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

CTRL, ALT = 0xFFE3, 0xFFE9
RIGHT, LEFT, ESC = 0xFF53, 0xFF51, 0xFF1B
# 이름 → [(눌러 둘 수식키들, 키)] 순서대로. home 은 왼쪽으로 충분히(가상 데스크톱 최대 몇 개든 1 번에 닿도록) 반복한다.
COMBOS = {
    "right": [([CTRL, ALT], RIGHT)],
    "left": [([CTRL, ALT], LEFT)],
    "home": [([CTRL, ALT], LEFT)] * 8,
    "escape": [([], ESC)],
}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMBOS:
        sys.exit("usage: ws.py right|left|home|escape")
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    dest = "org.gnome.Mutter.RemoteDesktop"
    rd = Gio.DBusProxy.new_sync(bus, 0, None, dest, "/org/gnome/Mutter/RemoteDesktop", dest, None)
    path = rd.call_sync("CreateSession", None, 0, -1, None).unpack()[0]
    sess = Gio.DBusProxy.new_sync(bus, 0, None, dest, path, dest + ".Session", None)
    sess.call_sync("Start", None, 0, -1, None)

    def press(sym, down):
        sess.call_sync("NotifyKeyboardKeysym", GLib.Variant("(ub)", (sym, down)), 0, -1, None)

    for mods, key in COMBOS[name]:
        for m in mods:
            press(m, True)
        press(key, True)
        time.sleep(0.05)
        press(key, False)
        for m in reversed(mods):
            press(m, False)
        time.sleep(0.25)  # 전환 애니메이션 동안 다음 키가 씹히지 않게
    time.sleep(0.3)  # 키 이벤트가 소비되기 전에 세션을 닫지 않도록
    sess.call_sync("Stop", None, 0, -1, None)
    print("sent", name)


main()
