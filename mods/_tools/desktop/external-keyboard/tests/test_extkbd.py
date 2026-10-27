#!/usr/bin/env python3
"""extkbd 시험. 실제 장치/BlueZ 없이: 가짜 sysfs·/dev/input 트리와 가짜 udevadm/busctl/gdbus/정책 스크립트로 판정과 감시 데몬 프로세스를 시험한다."""
import json, os, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp()
SYS, DEV, BIN = (os.path.join(T, n) for n in ("sys", "dev", "bin"))
for d in (SYS, DEV, BIN):
    os.makedirs(d)


def w(path, text="", mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def node(n, devpath, name, uniq=""):
    """event<n> 노드: /dev/input 파일과 sysfs(부모 inputN 의 name/uniq)를 만든다."""
    w(os.path.join(DEV, f"event{n}"))
    os.makedirs(os.path.join(SYS, devpath.lstrip("/")), exist_ok=True)
    w(os.path.join(SYS, devpath.lstrip("/"), "..", "name"), name + "\n")
    w(os.path.join(SYS, devpath.lstrip("/"), "..", "uniq"), uniq + "\n")


def block(n, devpath, **props):
    base = {"DEVPATH": devpath, "DEVNAME": f"/dev/input/event{n}", "SUBSYSTEM": "input"}
    base.update(props)
    return "\n".join(f"{k}={v}" for k, v in base.items()) + "\n"      # 실제 udevadm 출력처럼 장치 사이에 빈 줄이 없다(DEVPATH 가 첫 줄)


w(os.path.join(BIN, "udevadm"), '#!/bin/sh\nif [ "$1" = info ]; then cat "$FAKE/udev_info.txt"; else exec tail -n 0 -F "$FAKE/udev_events.txt" 2>/dev/null; fi\n', 0o755)
w(os.path.join(BIN, "busctl"), '#!/bin/sh\n[ -f "$FAKE/busctl.json" ] || exit 1\ncat "$FAKE/busctl.json"\n', 0o755)
w(os.path.join(BIN, "gdbus"), '#!/bin/sh\nexec tail -n 0 -F "$FAKE/bluez_events.txt" 2>/dev/null\n', 0o755)
w(os.path.join(BIN, "policy"), '#!/bin/sh\necho run >> "$FAKE/policy.log"\n', 0o755)
for n in ("udev_events.txt", "bluez_events.txt", "policy.log"):
    w(os.path.join(T, n))
ENV = dict(os.environ, FAKE=T, EXTKBD_UDEVADM=os.path.join(BIN, "udevadm"), EXTKBD_BUSCTL=os.path.join(BIN, "busctl"), EXTKBD_GDBUS=os.path.join(BIN, "gdbus"),
           EXTKBD_POLICY=os.path.join(BIN, "policy"), EXTKBD_DEV_INPUT=DEV, EXTKBD_SYSFS=SYS, EXTKBD_DEBOUNCE="0.3", PYTHONDONTWRITEBYTECODE="1")
PY = [sys.executable, "-I", os.path.join(ROOT, "extkbd.py")]


def run(*a):
    return subprocess.run(PY + list(a), env=ENV, capture_output=True, text=True, timeout=20)


def bluez(mac, connected):
    w(os.path.join(T, "busctl.json"), json.dumps({"type": "a{oa{sa{sv}}}", "data": [{
        "/org/bluez": {}, "/org/bluez/hci0": {"org.bluez.Adapter1": {}},
        f"/org/bluez/hci0/dev_{mac.replace(':', '_')}": {"org.bluez.Device1": {"Address": {"type": "s", "data": mac}, "Connected": {"type": "b", "data": connected}}}}]}))


def setup(blocks):
    w(os.path.join(T, "udev_info.txt"), "".join(blocks))


# 노드: 0 내장(i8042), 1 블루투스 키보드, 2 블루투스 마우스 노드(키보드 아님), 3 터치스크린(USB, 키보드 아님), 4 USB 키보드, 5 전원 버튼(ACPI 키)
P_INT, P_BT, P_BTM, P_TS, P_USB, P_PWR = ("/devices/platform/i8042/serio0/input/input2/event0", "/devices/virtual/misc/uhid/0005:3554:FA07.000B/input/input40/event1",
    "/devices/virtual/misc/uhid/0005:3554:FA07.000B/input/input42/event2", "/devices/pci0000:00/usb3/3-8/input/input9/event3",
    "/devices/pci0000:00/usb1/1-2/input/input50/event4", "/devices/LNXSYSTM:00/PNP0C0C:00/input/input0/event5")
node(0, P_INT, "AT Translated Set 2 keyboard")
node(1, P_BT, "AULA-F87Pro 5.0 Keyboard", "d6:f0:27:b9:65:70")
node(2, P_BTM, "AULA-F87Pro 5.0 Mouse", "d6:f0:27:b9:65:70")
node(3, P_TS, "ELAN Touchscreen")
node(4, P_USB, "USB Keyboard")
node(5, P_PWR, "Power Button")
B_INT = block(0, P_INT, ID_INPUT_KEYBOARD="1", ID_BUS="i8042")
B_BT = block(1, P_BT, ID_INPUT_KEYBOARD="1", ID_BUS="bluetooth")
B_BTM = block(2, P_BTM, ID_INPUT_MOUSE="1", ID_BUS="bluetooth")
B_TS = block(3, P_TS, ID_INPUT_TABLET="1", ID_BUS="usb")
B_USB = block(4, P_USB, ID_INPUT_KEYBOARD="1", ID_BUS="usb")
B_PWR = block(5, P_PWR, ID_INPUT_KEY="1", ID_BUS="acpi")
MAC = "D6:F0:27:B9:65:70"

# ───── 순수 로직 ─────
import importlib.util
os.environ.update({k: v for k, v in ENV.items() if k.startswith("EXTKBD_")})
spec = importlib.util.spec_from_file_location("extkbd", os.path.join(ROOT, "extkbd.py"))
ek = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ek)
bl = ek.parse_blocks(B_INT + B_BT)
check("속성 블록 파싱(빈 줄 없는 실제 형식): 두 장치로 나뉘고 속성이 섞이지 않음", len(bl) == 2 and bl[1]["ID_BUS"] == "bluetooth" and bl[0]["ID_BUS"] == "i8042" and bl[0]["DEVNAME"] == "/dev/input/event0", str(bl))
bl2 = ek.parse_blocks(B_INT + "\n" + B_BT + "\n")
check("속성 블록 파싱(빈 줄 있는 형식도 허용)", len(bl2) == 2 and bl2[0]["ID_BUS"] == "i8042" and bl2[1]["ID_BUS"] == "bluetooth")
bl3 = ek.parse_blocks(B_BTM + B_INT)
check("키보드 속성이 없는 장치 다음 장치의 키보드 속성이 앞 장치로 새지 않음", "ID_INPUT_KEYBOARD" not in bl3[0] and bl3[1]["ID_INPUT_KEYBOARD"] == "1")
check("트리거(udev): 입력 장치 추가", ek.is_trigger("udev", "UDEV  [100.1] add      /devices/virtual/misc/uhid/x/input/input40/event26 (input)"))
check("트리거(udev): 제거", ek.is_trigger("udev", "UDEV  [100.1] remove   /devices/x/event26 (input)"))
check("트리거(udev): 머리말/다른 서브시스템은 무시", not ek.is_trigger("udev", "monitor will print the received events for:") and not ek.is_trigger("udev", "UDEV  [1.0] add /devices/x (usb)"))
check("트리거(udev): change 는 무시", not ek.is_trigger("udev", "UDEV  [1.0] change /devices/x/event3 (input)"))
check("트리거(BlueZ): Connected 변화", ek.is_trigger("bluez", "/org/bluez/hci0/dev_X: org.freedesktop.DBus.Properties.PropertiesChanged ('org.bluez.Device1', {'Connected': <false>}, @as [])"))
check("트리거(BlueZ): 장치 제거", ek.is_trigger("bluez", "/org/bluez: org.freedesktop.DBus.ObjectManager.InterfacesRemoved (...)"))
check("트리거(BlueZ): 배터리 등 다른 속성은 무시", not ek.is_trigger("bluez", "/org/bluez/hci0/dev_X: PropertiesChanged ('org.bluez.Battery1', {'Percentage': <byte 0x63>}, @as [])"))

# ───── 판정 (present / status) ─────
setup([B_INT, B_BT, B_BTM, B_TS, B_PWR]); bluez(MAC, True)
check("내장 + 블루투스 연결됨 → 있음", run("present").returncode == 0)
bluez(MAC, False)
check("블루투스 연결 끊김(uhid 노드는 남아 있음) → 없음", run("present").returncode == 1)
os.remove(os.path.join(T, "busctl.json"))
check("BlueZ 를 못 읽으면 → 없음(내장 키보드를 켜 둠)", run("present").returncode == 1)
bluez("11:22:33:44:55:66", True)
check("BlueZ 목록에 그 MAC 이 없으면 → 없음", run("present").returncode == 1)
bluez(MAC, True); w(os.path.join(SYS, P_BT.lstrip("/"), "..", "uniq"), "\n")
check("uniq(MAC)가 없으면 → 없음", run("present").returncode == 1)
w(os.path.join(SYS, P_BT.lstrip("/"), "..", "uniq"), "d6:f0:27:b9:65:70\n")
setup([B_INT, B_TS, B_PWR, B_BTM])
check("내장 키보드·터치스크린(USB 이지만 키보드 아님)·전원 버튼·블루투스 마우스 노드만 있으면 → 없음", run("present").returncode == 1)
setup([B_INT, B_USB])
check("USB 키보드 → 있음(블루투스 조회 없이도)", run("present").returncode == 0)
setup([B_INT]); check("내장 키보드만 → 없음", run("present").returncode == 1)
setup([]); check("입력 노드가 없어도 오류 없이 → 없음", run("present").returncode == 1)
w(os.path.join(T, "udev_info.txt"), "")
os.environ["EXTKBD_SYSFS"] = SYS
setup([B_INT, B_USB]); import shutil
shutil.rmtree(os.path.join(SYS, P_USB.lstrip("/")))
check("제거돼 sysfs 가 사라진 노드는 udev 정보가 남아 있어도 무시 → 없음", run("present").returncode == 1)
node(4, P_USB, "USB Keyboard")
fake_bad = os.path.join(BIN, "udevadm_bad"); w(fake_bad, "#!/bin/sh\nexit 3\n", 0o755)
r = subprocess.run(PY + ["present"], env=dict(ENV, EXTKBD_UDEVADM=fake_bad), capture_output=True, text=True, timeout=20)
check("udevadm 실패 → 없음(안전한 쪽)", r.returncode == 1)

setup([B_INT, B_BT, B_USB]); bluez(MAC, True)
st = run("status")
check("status 출력: 외부 표시·이유·결론", st.returncode == 0 and "AULA-F87Pro 5.0 Keyboard" in st.stdout and "블루투스 연결됨" in st.stdout and "USB Keyboard" in st.stdout and "있음 (내장 키보드를 끔)" in st.stdout, st.stdout)
bluez(MAC, False); setup([B_INT, B_BT])
st = run("status")
check("status: 연결 끊김 이유와 결론", "연결 끊김" in st.stdout and "없음 (내장 키보드를 켬)" in st.stdout, st.stdout)

# ───── 감시 데몬 (프로세스 전체) ─────
LOG = os.path.join(T, "policy.log")
def runs():
    with open(LOG) as f:
        return len(f.read().split())
def append(name, text):
    with open(os.path.join(T, name), "a") as f:
        f.write(text)

proc = subprocess.Popen(PY + ["watch"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
time.sleep(1.0)
check("시작할 때 정책을 한 번 실행", runs() == 1, str(runs()))
append("udev_events.txt", "UDEV  [1.0] change /devices/x/event3 (input)\nUDEV  [1.0] add /devices/y (usb)\n"); time.sleep(0.8)
check("무관한 이벤트에는 실행 안 함", runs() == 1, str(runs()))
append("udev_events.txt", "UDEV  [2.0] add      /devices/virtual/misc/uhid/x/input/input40 (input)\nUDEV  [2.0] add      /devices/virtual/misc/uhid/x/input/input40/event26 (input)\nUDEV  [2.1] add      /devices/virtual/misc/uhid/x/input/input41/event27 (input)\n")
time.sleep(0.15); check("디바운스 전에는 아직 실행 안 함", runs() == 1, str(runs()))
time.sleep(0.9)
check("이벤트 세 개가 몰려도 정책은 한 번만 실행", runs() == 2, str(runs()))
append("bluez_events.txt", "/org/bluez/hci0/dev_X: org.freedesktop.DBus.Properties.PropertiesChanged ('org.bluez.Device1', {'Connected': <false>}, @as [])\n"); time.sleep(1.0)
check("BlueZ Connected 변화에 실행", runs() == 3, str(runs()))
append("bluez_events.txt", "/org/bluez/hci0/dev_X: PropertiesChanged ('org.bluez.Battery1', {'Percentage': <byte 0x62>}, @as [])\n"); time.sleep(0.8)
check("BlueZ 배터리 변화에는 실행 안 함(깨어남 최소화)", runs() == 3, str(runs()))
tail_pids = subprocess.run(["pgrep", "-f", f"tail -n 0 -F {T}"], capture_output=True, text=True).stdout.split()
check("감시 자식 프로세스 2개가 떠 있음", len(tail_pids) == 2, str(tail_pids))
for p in tail_pids:                                    # 감시 대상 하나가 죽으면 데몬도 비정상 종료해야 서비스가 다시 띄운다
    os.kill(int(p), signal.SIGKILL)
    break
try:
    rc = proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    rc = None
check("감시 대상이 종료되면 데몬도 0 이 아닌 코드로 종료", rc not in (None, 0), str(rc))
leftover = subprocess.run(["pgrep", "-f", f"tail -n 0 -F {T}"], capture_output=True, text=True).stdout.split()
check("데몬이 종료하면 남은 자식도 정리", leftover == [], str(leftover))
for p in leftover:
    os.kill(int(p), signal.SIGKILL)

shutil.rmtree(T, ignore_errors=True)
finish("extkbd")
