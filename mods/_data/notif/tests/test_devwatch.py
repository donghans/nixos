#!/usr/bin/env python3
"""devwatch 시험: pw-dump 스트림 해석, 외부 장치/헤드폰만 알림, 재생성 무시, 출력+입력 묶음, udev(USB/전원), 마운트."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import devwatch as dw
from harness import checker, tmpdir
check, finish = checker()

def node(i, name, cls, bus="", desc=""):
    return {"id": i, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": cls, "node.name": name, "node.description": desc or name, "device.bus": bus}}}

# JSON 스트림
vals, rest = dw.json_arrays('[{"a":1}]\n[{"b":2}]\n[{"c"')
check("json_arrays: 완성된 배열 둘을 읽고 덜 온 조각은 남김", vals == [[{"a": 1}], [{"b": 2}]] and rest == '[{"c"', f"{vals} {rest!r}")
check("json_arrays: 빈 입력", dw.json_arrays("  \n") == ([], ""))

# 오디오
t = dw.AudioTracker()
init = [node(1, "alsa_output.usb-Dock.analog-stereo", "Audio/Sink", "usb", "MSI DOCK"), node(2, "alsa_output.pci.HiFi__Speaker__sink", "Audio/Sink", "pci", "Speaker")]
check("시작할 때 이미 있는 장치는 알리지 않음", t.feed(init, initial=True) == [])
ev = t.feed([node(3, "alsa_input.usb-Mic", "Audio/Source", "usb", "USB Mic")])
check("USB 마이크 추가 → add 이벤트(입력, 외부 장치)", ev == [("add", "USB Mic", "입력", "alsa_input.usb-Mic", False)], str(ev))
check("내장 카드의 스피커/마이크가 새로 생겨도(설정 다시 읽기) 알리지 않음", t.feed([node(4, "alsa_output.pci.HiFi__Speaker__sink", "Audio/Sink", "pci", "Speaker"), node(5, "alsa_input.pci.HiFi__Mic1__source", "Audio/Source", "pci", "DMic")]) == [])
ev = t.feed([node(6, "alsa_output.pci.HiFi__Headphones__sink", "Audio/Sink", "pci", "Headphones")])
check("내장 카드라도 헤드폰 노드는 이벤트(내장 표시)", ev and ev[0][0] == "add" and ev[0][1] == "Headphones" and ev[0][4] is True, str(ev))
check("같은 노드가 다시 오면(갱신) 중복 알림 없음", t.feed([node(3, "alsa_input.usb-Mic", "Audio/Source", "usb", "USB Mic")]) == [])
ev = t.feed([{"id": 3, "info": None}])
check("제거({id, info:null}) → remove 이벤트", ev == [("remove", "USB Mic", "입력", "alsa_input.usb-Mic", False)], str(ev))
check("제거된 번호는 잊음(다시 오면 add)", t.feed([node(3, "alsa_input.usb-Mic", "Audio/Source", "usb", "USB Mic")])[0][0] == "add")
check("알 수 없는 번호의 제거/오디오가 아닌 객체는 무시", t.feed([{"id": 99, "info": None}, {"id": 7, "type": "PipeWire:Interface:Device", "info": {"props": {}}}]) == [])
check("블루투스 노드는 알림 대상", dw.audio_interesting({"name": "bluez_output.AA", "desc": "Buds", "bus": "bluetooth", "kind": "출력"}))
check("가상 노드(Stream)는 노드로 안 봄", dw.AudioTracker.node_of(node(8, "x", "Stream/Output/Audio", "usb")) is None)

# 묶음/재생성
sent = []
eng = dw.Engine(lambda *a: sent.append(a))
eng.add("audio", "add", "Dock", "출력", t=0); eng.add("audio", "add", "Dock", "입력", t=0.5)
eng.poll(1.0); n0 = len(sent)
eng.poll(2.1)
check("같은 장치의 출력/입력은 한 알림으로 묶음(묶는 시간이 지난 뒤에만 보냄)", n0 == 0 and sent == [("audio", "add", "Dock", ["출력", "입력"], "")], str(sent))
sent.clear()
eng.add("audio", "remove", "Dock", "출력", t=10)
check("해제 직후 다시 생기면 재생성으로 보고 둘 다 버림", eng.add("audio", "add", "Dock", "출력", t=11) == "recreated" and (eng.poll(20) == 0) and sent == [])
eng.add("audio", "remove", "Buds", "출력", t=30); eng.poll(31)
check("해제는 3초 기다린 뒤에 알림", sent == [], str(sent)); eng.poll(33.5)
check("기다려도 안 돌아오면 해제 알림", sent == [("audio", "remove", "Buds", ["출력"], "")], str(sent))
sent.clear(); eng.add("usb", "add", "Keyboard", t=0); eng.poll(0.4)
check("USB 는 거의 바로 알림", sent == [("usb", "add", "Keyboard", [], "")], str(sent))

# 내장 헤드폰 깜빡임(설정을 다시 읽을 때 잠깐 생겼다 사라짐)
sent.clear(); eng2 = dw.Engine(lambda *a: sent.append(a))
eng2.add_internal("audio", "add", "Headphones", "출력", t=0); eng2.poll(3)
check("내장 헤드폰: 6초 안에 사라지면(깜빡임) 연결도 해제도 알리지 않음", eng2.add_internal("audio", "remove", "Headphones", "출력", t=4) == "flap" and eng2.poll(30) == 0 and sent == [])
check("내장 헤드폰: 알린 적 없는 노드의 해제는 무시(시작 전부터 있던 노드가 사라지는 경우)", eng2.add_internal("audio", "remove", "Headphones", "출력", t=40) == "ignored" and eng2.poll(60) == 0)
eng2.add_internal("audio", "add", "Headphones", "출력", t=100); eng2.poll(103); n1 = len(sent); eng2.poll(106.5)
check("내장 헤드폰: 6초 이상 유지되면 연결 알림", n1 == 0 and sent == [("audio", "add", "Headphones", ["출력"], "")], str(sent))
sent.clear(); eng2.add_internal("audio", "remove", "Headphones", "출력", t=200); eng2.poll(204)
check("내장 헤드폰: 연결을 알린 노드가 사라지면 해제 알림", sent == [("audio", "remove", "Headphones", ["출력"], "")], str(sent))

# udev
blk = """UDEV  [100.1] add      /devices/pci0000:00/usb1/1-2 (usb)
ACTION=add
DEVPATH=/devices/pci0000:00/usb1/1-2
SUBSYSTEM=usb
DEVTYPE=usb_device
TYPE=0/0/0
ID_MODEL=USB_DISK_3.0
ID_VENDOR=SanDisk
ID_VENDOR_FROM_DATABASE=SanDisk Corp.

UDEV  [100.2] add      /devices/pci0000:00/usb1/1-2/1-2:1.0 (usb)
ACTION=add
SUBSYSTEM=usb
DEVTYPE=usb_interface

UDEV  [100.3] add      /devices/pci0000:00/usb1/1-3 (usb)
ACTION=add
SUBSYSTEM=usb
DEVTYPE=usb_device
TYPE=9/0/1
ID_MODEL=Hub

UDEV  [101.0] change   /devices/LNXSYSTM/ACPI0003 (power_supply)
ACTION=change
SUBSYSTEM=power_supply
DEVPATH=/devices/ACPI

UDEV  [102.0] remove   /devices/pci0000:00/usb1/1-2 (usb)
ACTION=remove
SUBSYSTEM=usb
DEVTYPE=usb_device
TYPE=0/0/0
ID_MODEL=USB_DISK_3.0
ID_VENDOR_FROM_DATABASE=SanDisk Corp.
"""
evs, rest = dw.parse_udev(blk + "\nUDEV  [103.0] add")
check("udev 블록을 이벤트로 나누고 덜 온 마지막은 남김", len(evs) == 5 and rest.startswith("UDEV  [103.0]"), f"{len(evs)} {rest!r}")
us = [dw.usb_event(e) for e in evs]
check("USB: 장치만(인터페이스/허브 제외), 이름은 제조사+모델, 추가/제거", us == [("add", "SanDisk Corp. USB DISK 3.0"), None, None, None, ("remove", "SanDisk Corp. USB DISK 3.0")], str(us))

# 전원
d = tmpdir()
def mk(name, **kw):
    os.makedirs(f"{d}/{name}", exist_ok=True)
    for k, v in kw.items(): open(f"{d}/{name}/{k}", "w").write(str(v) + "\n")
mk("ADP1", type="Mains", online=1); mk("BAT1", type="Battery", capacity=87, status="Charging"); mk("ucsi-source-psy-USBC000:002", type="USB", online=1, scope="Device")
st = dw.power_state(d)
check("전원: 어댑터 연결 + 배터리 %/상태", st == {"ac": True, "pct": 87, "status": "Charging"}, str(st))
mk("ADP1", type="Mains", online=0); mk("ucsi-source-psy-USBC000:002", type="USB", online=1, scope="Device")
check("전원: ADP1 이 꺼지면 USB-C 포트(scope=Device)가 online 이어도 배터리 사용으로 봄", dw.power_state(d)["ac"] is False)
check("전원: 경로가 없으면 안전한 기본값", dw.power_state(f"{d}/none") == {"ac": False, "pct": None, "status": ""})

# 마운트
mi = ("36 1 8:1 / / rw - ext4 /dev/nvme0n1p2 rw\n"
      "90 36 8:17 / /run/media/donghans/MY\\040DISK rw,relatime - vfat /dev/sdb1 rw\n"
      "91 36 0:50 / /home/donghans/mnt rw - fuse.sshfs x rw\n"
      "92 36 8:33 / /mnt/backup rw - ext4 /dev/sdc1 rw\n")
m = dw.parse_mounts(mi)
check("마운트: 이동식 위치(/run/media, /mnt)만, 이름의 \\040 은 공백으로", m == {"/run/media/donghans/MY DISK": ("vfat", "/dev/sdb1"), "/mnt/backup": ("ext4", "/dev/sdc1")}, str(m))

# 표시
check("표시: 오디오 연결(출력·입력)", dw.render("audio", "add", "MSI DOCK", ["출력", "입력"], "") == ("오디오 장치 연결: MSI DOCK", "출력 · 입력", "audio-headphones"))
check("표시: 전원(라벨 없음, 본문에 배터리)", dw.render("power", "remove", "", [], "배터리 80%") == ("배터리로 전환", "배터리 80%", "battery"))
check("표시: 마운트(본문에 종류·경로)", dw.render("mount", "add", "MY DISK", [], "vfat · /run/media/x/MY DISK")[0] == "마운트: MY DISK")
finish("devwatch")
