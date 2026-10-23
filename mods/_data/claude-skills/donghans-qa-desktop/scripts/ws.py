#!/usr/bin/env python3
"""qa-desktop(VM) 안에서 가상 데스크톱을 전환한다 — Mutter RemoteDesktop 의 가상 키 입력으로 GNOME 단축키를 보낸다.

사용: ws.py right|left|home   (right/left = 옆 데스크톱, home = 데스크톱 1)
- 사람 대신 데스크톱을 바꿔서 창이 안 보이는 상태를 재현하거나(렌더링·스크린샷 시험), 현재 데스크톱을 알려진 값(1)으로 맞춘다.
- 설치할 것이 없다(VM 의 python3 + gi). VM 의 GNOME 세션에서 실행해야 한다
  (ssh 로 들어왔다면 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus 필요).
- 단축키는 GNOME 기본값(switch-to-workspace-right/left = Ctrl+Alt+→/←, switch-to-workspace-1 = Super+Home) 기준이다.
"""
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

CTRL, ALT, SUPER = 0xFFE3, 0xFFE9, 0xFFEB
RIGHT, LEFT, HOME = 0xFF53, 0xFF51, 0xFF50
COMBOS = {
    "right": ([CTRL, ALT], RIGHT),
    "left": ([CTRL, ALT], LEFT),
    "home": ([SUPER], HOME),
}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMBOS:
        sys.exit("usage: ws.py right|left|home")
    mods, key = COMBOS[name]
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    dest = "org.gnome.Mutter.RemoteDesktop"
    rd = Gio.DBusProxy.new_sync(bus, 0, None, dest, "/org/gnome/Mutter/RemoteDesktop", dest, None)
    path = rd.call_sync("CreateSession", None, 0, -1, None).unpack()[0]
    sess = Gio.DBusProxy.new_sync(bus, 0, None, dest, path, dest + ".Session", None)
    sess.call_sync("Start", None, 0, -1, None)

    def press(sym, down):
        sess.call_sync("NotifyKeyboardKeysym", GLib.Variant("(ub)", (sym, down)), 0, -1, None)

    for m in mods:
        press(m, True)
    press(key, True)
    time.sleep(0.05)
    press(key, False)
    for m in reversed(mods):
        press(m, False)
    time.sleep(0.3)  # 키 이벤트가 소비되기 전에 세션을 닫지 않도록
    sess.call_sync("Stop", None, 0, -1, None)
    print("sent", name)


main()
