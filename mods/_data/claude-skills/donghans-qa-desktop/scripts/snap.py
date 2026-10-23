#!/usr/bin/env python3
"""qa-desktop(VM) 안에서 화면 전체를 PNG 로 저장한다 — Mutter ScreenCast + PipeWire + GStreamer.

사용: snap.py [출력.png]   (기본 /tmp/snap.png)
- `org.gnome.Shell.Screenshot` 은 AccessDenied 라서 못 쓴다. 화면 공유용 ScreenCast 는 열려 있다(설치할 것 없음: VM 의 python3 gi, gst-launch-1.0, pipewire).
- 찍는 동안 상단바에 화면 공유 표시(주황)가 잠깐 뜬다. 현재 **보이는** 데스크톱만 찍힌다(다른 데스크톱의 창은 안 나옴).
- ssh 로 들어왔다면 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus 필요.
- 모니터 이름은 Virtual-1(QEMU 가상 모니터). 다르면 MONITOR 환경변수로 지정한다.
"""
import os
import subprocess
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snap.png"
MONITOR = os.environ.get("MONITOR", "Virtual-1")
SC = "org.gnome.Mutter.ScreenCast"


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sc = Gio.DBusProxy.new_sync(bus, 0, None, SC, "/org/gnome/Mutter/ScreenCast", SC, None)
    sp = sc.call_sync("CreateSession", GLib.Variant("(a{sv})", ({},)), 0, -1, None).unpack()[0]
    sess = Gio.DBusProxy.new_sync(bus, 0, None, SC, sp, SC + ".Session", None)
    stream = sess.call_sync("RecordMonitor", GLib.Variant("(sa{sv})", (MONITOR, {})), 0, -1, None).unpack()[0]
    loop, node = GLib.MainLoop(), {}

    def on_signal(_conn, _sender, path, _iface, name, params, *_):
        if name == "PipeWireStreamAdded" and path == stream:
            node["id"] = params.unpack()[0]
            loop.quit()

    bus.signal_subscribe(SC, SC + ".Stream", "PipeWireStreamAdded", stream, None, Gio.DBusSignalFlags.NONE, on_signal)
    sess.call_sync("Start", None, 0, -1, None)
    GLib.timeout_add_seconds(8, loop.quit)
    loop.run()
    try:
        if "id" not in node:
            sys.exit("스트림이 열리지 않았다(8초)")
        # 첫 버퍼는 비어 있을 수 있어 몇 장 받은 뒤 snapshot 으로 마지막 한 장을 저장한다
        r = subprocess.run(
            ["gst-launch-1.0", "-q", "pipewiresrc", "path=%d" % node["id"], "num-buffers=3", "!", "videoconvert", "!",
             "pngenc", "snapshot=true", "!", "filesink", "location=" + OUT],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            sys.exit("gst 실패: " + r.stderr[-300:])
        print("saved", OUT)
    finally:
        sess.call_sync("Stop", None, 0, -1, None)


main()
