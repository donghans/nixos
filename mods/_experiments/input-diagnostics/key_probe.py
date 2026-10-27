#!/usr/bin/env python3
"""key_probe — 키보드 장치에서 **지정한 키의 눌림 횟수와 전체 키 이벤트 개수만** 센다(누른 글자 내용은 읽지도 기록하지도 않는다). root 로 실행(/dev/input).
특정 키가 안 먹을 때 "키 신호가 커널까지 올라오는가"를 가르는 용도: 올라오면 입력기/터미널/앱 문제, 0 이면 키보드 하드웨어/EC/펌웨어 문제.

  sudo key_probe.py [초=60] [키이름,...=backspace,left,right,up,down,brightnessdown,brightnessup] [장치 이름(쉼표 구분, 기본: 키보드/MSI WMI/Intel HID/Video Bus)]
  예) 15초 동안: sudo key_probe.py 15   (그동안 Backspace, →, 밝기 올림/내림을 몇 번씩 누른다)
**하드웨어 단계 판별용 지표도 같이 낸다**: `irq1_delta`(i8042 키보드 인터럽트 증가 수 — PS/2 키보드 신호가 하드웨어에서 커널까지 오는지), `gpe6e_delta`(EC 이벤트 인터럽트 증가 수 — 밝기/Fn 키 계열).
  키를 눌렀는데 irq1_delta 가 0 이면 키보드/EC 가 신호를 안 보내는 것, irq1_delta 가 늘었는데 키 이벤트가 0 이면 커널 입력층에서 버려지는 것, 이벤트가 있는데 화면에서 안 먹으면 Hyprland/입력기 문제.
결과는 표준출력 한 줄(JSON)이고, 눌러 달라고 한 횟수와 비교하면 된다. 다른 키는 `other_events`(개수)로만 합산된다."""
import glob, json, os, select, struct, sys, time

CODES = {"brightnessdown": 224, "brightnessup": 225, "backspace": 14, "left": 105, "right": 106, "up": 103, "down": 108, "enter": 28, "esc": 1, "tab": 15, "delete": 111, "space": 57, "comma": 51, "dot": 52, "a": 30, "s": 31, "d": 32}
FMT = "llHHi"


def find_device(name: str):
    for d in sorted(glob.glob("/sys/class/input/event*")):
        try:
            if open(d + "/device/name").read().strip() == name:
                return "/dev/input/" + os.path.basename(d)
        except OSError:
            pass
    return None


DEFAULT_DEVICES = ["AT Translated Set 2 keyboard", "MSI WMI hotkeys", "Intel HID 5 button array", "Video Bus"]


def find_devices(names):
    """장치 이름 목록 → {이름: /dev/input/eventN 목록}. 같은 이름이 둘 이상이면(Video Bus 등) 모두 돌려준다."""
    found = {n: [] for n in names}
    for d in sorted(glob.glob("/sys/class/input/event*")):
        try:
            nm = open(d + "/device/name").read().strip()
        except OSError:
            continue
        if nm in found:
            found[nm].append("/dev/input/" + os.path.basename(d))
    return found


def read_counter(path, key=None):
    """/proc/interrupts 의 IRQ 번호 합계(CPU 열 전부) 또는 /sys/firmware/acpi/interrupts/gpe 파일의 첫 숫자."""
    try:
        txt = open(path).read()
    except OSError:
        return None
    if path == "/proc/interrupts":
        for line in txt.splitlines():
            parts = line.split()
            if parts and parts[0] == key + ":":
                return sum(int(x) for x in parts[1:] if x.isdigit())
        return None
    return int(txt.split()[0]) if txt.split() else None


def count_events(data: bytes, watch: dict, counts: dict) -> None:
    """data: input_event 구조체 묶음. watch: {코드: 이름}. EV_KEY 눌림(value=1)만 이름별로, 나머지 키 이벤트는 other_events 로 센다."""
    size = struct.calcsize(FMT)
    for i in range(0, len(data) - size + 1, size):
        _, _, typ, code, val = struct.unpack(FMT, data[i:i + size])
        if typ != 1:
            continue
        if code in watch:
            if val == 1:
                counts[watch[code]] += 1
        else:
            counts["other_events"] += 1


def main(argv):
    seconds = int(argv[0]) if argv else 60
    names = (argv[1] if len(argv) > 1 else "backspace,left,right,up,down,brightnessdown,brightnessup").split(",")
    watch = {CODES[n]: n for n in names}
    devnames = argv[2].split(",") if len(argv) > 2 else DEFAULT_DEVICES
    devs = find_devices(devnames)
    fds, counts = {}, {}
    for nm, paths in devs.items():
        for pth in paths:
            fds[os.open(pth, os.O_RDONLY | os.O_NONBLOCK)] = nm
        if paths:
            counts[nm] = {n: 0 for n in names}
            counts[nm]["other_events"] = 0
    if not fds:
        print("키보드 장치를 찾지 못했습니다", file=sys.stderr)
        return 1
    irq0, gpe0 = read_counter("/proc/interrupts", "1"), read_counter("/sys/firmware/acpi/interrupts/gpe6E")
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select(list(fds), [], [], 1.0)
        for fd in r:
            count_events(os.read(fd, struct.calcsize(FMT) * 64), watch, counts[fds[fd]])
    irq1, gpe1 = read_counter("/proc/interrupts", "1"), read_counter("/sys/firmware/acpi/interrupts/gpe6E")
    print(json.dumps({"seconds": seconds, "devices": counts,
                      "irq1_delta": None if None in (irq0, irq1) else irq1 - irq0,
                      "gpe6e_delta": None if None in (gpe0, gpe1) else gpe1 - gpe0,
                      "lid": open("/proc/acpi/button/lid/LID0/state").read().split()[-1], "vt": open("/sys/class/tty/tty0/active").read().strip()},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
