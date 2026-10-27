#!/usr/bin/env python3
"""extkbd — 외부 키보드(유선 USB / 2.4G 수신기 / 블루투스) 연결 여부 판정과 감시. 설계/근거: mods/_tools/desktop/external-keyboard/README.md

  extkbd present   외부 키보드가 있으면 종료 코드 0, 없으면 1 (어떤 오류든 1: 판정이 불확실하면 내장 키보드를 켜 둔다)
  extkbd status    입력 노드별 판정과 이유(진단용)
  extkbd watch     입력 장치 추가/제거와 블루투스 연결 변화를 지켜보다가 POLICY(hypr-input-policy)를 다시 실행(이벤트 구동, 폴링 없음)

판정: ID_INPUT_KEYBOARD=1 이고 ID_BUS 가 usb|bluetooth 인 입력 노드. 블루투스는 BlueZ 에서 그 MAC(노드의 uniq)의 Connected 가 true 로 확인돼야 한다.
"""
import json
import os
import select
import subprocess
import sys
import time

UDEVADM = os.environ.get("EXTKBD_UDEVADM", "udevadm")
BUSCTL = os.environ.get("EXTKBD_BUSCTL", "busctl")
GDBUS = os.environ.get("EXTKBD_GDBUS", "gdbus")
POLICY = os.environ.get("EXTKBD_POLICY", "hypr-input-policy")
DEV_INPUT = os.environ.get("EXTKBD_DEV_INPUT", "/dev/input")
SYSFS = os.environ.get("EXTKBD_SYSFS", "/sys")
DEBOUNCE = float(os.environ.get("EXTKBD_DEBOUNCE", "1.0"))   # 이벤트가 몰려 와도 정책은 마지막 이벤트 뒤 이만큼 지나 한 번만 실행
EXTERNAL_BUSES = ("usb", "bluetooth")


def parse_blocks(text: str) -> list:
    """`udevadm info -q property A B …` 출력 → [{KEY: VAL}].
    실측(2026-10-27, systemd 260): 장치 사이에 **빈 줄이 없다** — 장치마다 첫 줄이 `DEVPATH=` 이라 그 줄에서 새 장치가 시작된다. 빈 줄이 있는 출력(다른 버전)도 같이 받는다."""
    blocks, cur = [], {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if not line.strip() or (sep and k == "DEVPATH" and cur):
            if cur:
                blocks.append(cur)
                cur = {}
            if not line.strip():
                continue
        if sep:
            cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def input_props() -> list:
    """모든 입력 이벤트 노드의 udev 속성. 한 번의 호출로 읽는다(노드마다 부르면 느리다)."""
    try:
        nodes = sorted(os.path.join(DEV_INPUT, n) for n in os.listdir(DEV_INPUT) if n.startswith("event"))
    except OSError:
        return []
    if not nodes:
        return []
    out = subprocess.run([UDEVADM, "info", "-q", "property", *nodes], capture_output=True, text=True, timeout=10, check=True).stdout
    return [b for b in parse_blocks(out) if b.get("SUBSYSTEM") == "input"]


def bt_connected():
    """{대문자 MAC: Connected} — BlueZ 에서 읽는다. 읽지 못하면 None(모름)."""
    try:
        out = subprocess.run([BUSCTL, "--system", "--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        objs = json.loads(out)["data"][0]
        res = {}
        for ifaces in objs.values():
            dev = ifaces.get("org.bluez.Device1")
            if dev:
                res[dev["Address"]["data"].upper()] = bool(dev["Connected"]["data"])
        return res
    except Exception:
        return None


def sysfs_attr(devpath: str, name: str) -> str:
    """이벤트 노드(…/inputN/eventM)의 부모 입력 장치(inputN)가 가진 sysfs 속성."""
    try:
        with open(os.path.join(SYSFS, devpath.lstrip("/"), "..", name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def classify(props: dict, bt) -> tuple:
    """(외부 키보드 여부, 이유). bt 는 bt_connected() 의 값."""
    if props.get("ID_INPUT_KEYBOARD") != "1":
        return False, "키보드 아님"
    bus = props.get("ID_BUS", "")
    if bus not in EXTERNAL_BUSES:
        return False, f"내장/가상 버스({bus or '없음'})"
    devpath = props.get("DEVPATH", "")
    if not os.path.isdir(os.path.join(SYSFS, devpath.lstrip("/"))):
        return False, "노드가 이미 사라짐"
    if bus == "usb":
        return True, "USB"
    mac = sysfs_attr(devpath, "uniq").upper()
    if not mac:
        return False, "블루투스: uniq(MAC) 없음 → 연결 확인 불가"
    if bt is None:
        return False, "블루투스: BlueZ 에서 상태를 못 읽음 → 연결 확인 불가"
    if mac not in bt:
        return False, f"블루투스: BlueZ 에 {mac} 없음"
    return (True, f"블루투스 연결됨({mac})") if bt[mac] else (False, f"블루투스 연결 끊김({mac})")


def scan() -> list:
    """[(노드, 이름, 버스, 외부 키보드 여부, 이유)] — ID_INPUT_KEYBOARD=1 인 노드만."""
    props = [p for p in input_props() if p.get("ID_INPUT_KEYBOARD") == "1"]
    bt = bt_connected() if any(p.get("ID_BUS") == "bluetooth" for p in props) else {}
    rows = []
    for p in props:
        ext, why = classify(p, bt)
        rows.append((p.get("DEVNAME", "?"), sysfs_attr(p.get("DEVPATH", ""), "name") or "?", p.get("ID_BUS", "?"), ext, why))
    return rows


def present() -> bool:
    try:
        return any(r[3] for r in scan())
    except Exception:
        return False


def cmd_status() -> int:
    try:
        rows = scan()
    except Exception as e:
        print(f"입력 장치를 읽지 못함: {e}")
        return 1
    for node, name, bus, ext, why in rows:
        print(f"{'외부' if ext else '    '} {node:<20} {bus:<10} {name}  — {why}")
    print("→ 외부 키보드:", "있음 (내장 키보드를 끔)" if any(r[3] for r in rows) else "없음 (내장 키보드를 켬)")
    return 0


def is_trigger(source: str, line: str) -> bool:
    """감시 대상 이벤트 줄인가. udev: 입력 장치 추가/제거. BlueZ: 연결 상태 변화나 장치 제거."""
    if source == "udev":
        return "(input)" in line and (" add " in line or " remove " in line)
    return "Connected" in line or "InterfacesRemoved" in line


def run_policy() -> None:
    try:
        subprocess.run([POLICY], timeout=30, check=False)
    except Exception as e:
        print(f"extkbd: 정책 실행 실패: {e}", file=sys.stderr, flush=True)


def cmd_watch() -> int:
    children = {
        "udev": subprocess.Popen([UDEVADM, "monitor", "--udev", "--subsystem-match=input"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL),
        "bluez": subprocess.Popen([GDBUS, "monitor", "--system", "--dest", "org.bluez"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL),
    }
    fds = {p.stdout.fileno(): (name, bytearray()) for name, p in children.items()}
    run_policy()                                   # 시작 때 한 번: 그 사이 놓친 변화를 맞춘다
    deadline = None
    try:
        while True:
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select(list(fds), [], [], timeout)
            if not ready:                          # 디바운스 만료
                deadline = None
                run_policy()
                continue
            for fd in ready:
                name, buf = fds[fd]
                chunk = os.read(fd, 65536)
                if not chunk:                      # 감시 대상이 종료: 같이 종료해서 서비스가 다시 띄우고 시작 때 다시 맞춘다
                    print(f"extkbd: {name} 감시가 종료됨", file=sys.stderr, flush=True)
                    return 1
                buf += chunk
                while b"\n" in buf:
                    raw, _, rest = bytes(buf).partition(b"\n")
                    buf[:] = rest
                    if is_trigger(name, raw.decode("utf-8", "replace")):
                        deadline = time.monotonic() + DEBOUNCE
    finally:
        for p in children.values():
            if p.poll() is None:
                p.terminate()


def main(argv: list) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "present":
        return 0 if present() else 1
    if cmd == "status":
        return cmd_status()
    if cmd == "watch":
        return cmd_watch()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
