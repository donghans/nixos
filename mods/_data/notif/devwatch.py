"""devwatch — 장치 연결/해제, 마운트/언마운트, 전원 어댑터 변화를 알림으로 알린다 (`notif devices`, user 서비스 notif-devices).

알림은 앱 이름 `devices`(낮은 긴급도)로 나가 알림 센터에 한곳으로 모인다. pasystray/udiskie 의 자체 알림을 대신한다.
  - 오디오: pw-dump -m 으로 PipeWire 노드를 지켜본다. **외부 장치(USB/블루투스)와 헤드폰/헤드셋 노드만** 알린다 —
    내장 카드(스피커/마이크)는 Hyprland 설정을 다시 읽을 때마다 노드가 다시 만들어져서(`hyprctl reload`, nixup) pasystray 가 매번 "새 장치"로 알렸기 때문.
    같은 장치의 출력/입력은 한 알림으로 묶고, 해제 직후 같은 장치가 다시 생기면(재생성) 둘 다 알리지 않는다.
  - USB: udev 의 usb_device 추가/제거(허브 제외).
  - 마운트: /proc/self/mountinfo 변화 중 /run/media, /media, /mnt 아래.
  - 전원: udev power_supply 이벤트마다 어댑터 연결 여부를 읽어 **바뀔 때만** 알림(배터리 잔량 포함).
시작할 때 이미 있는 장치/마운트는 알리지 않는다.
"""
import json
import os
import queue
import re
import select
import shutil
import subprocess
import threading
import time

HEADSET = re.compile(r"headphone|headset|earphone|earbud", re.I)
MOUNT_PREFIXES = ("/run/media/", "/media/", "/mnt/")
POWER_ROOT = os.environ.get("DEVWATCH_POWER_ROOT", "/sys/class/power_supply")
APP = "devices"
REMOVE_DELAY = 3.0       # 해제는 이만큼 기다렸다가 알림(그 사이 다시 생기면 재생성으로 보고 무시)
SETTLE = 6.0             # 내장 카드의 헤드폰 노드는 설정을 다시 읽을 때 잠깐 생겼다 사라지므로, 이만큼 유지돼야 "연결"로 봄
GROUP_DELAY = 1.5        # 같은 장치의 출력/입력을 한 알림으로 묶는 시간
QUICK = 0.3


# ───────────────────────── 오디오 ─────────────────────────
def audio_interesting(node: dict) -> bool:
    """알릴 만한 오디오 노드: 외부 장치(USB/블루투스) 또는 헤드폰/헤드셋."""
    return node["bus"] in ("usb", "bluetooth") or bool(HEADSET.search(node["name"] + " " + node["desc"]))


class AudioTracker:
    """pw-dump -m 이 내보내는 JSON 배열들을 받아 오디오 노드의 추가/제거를 이벤트로 바꾼다."""

    def __init__(self):
        self.nodes = {}                # id -> {"name","desc","bus","kind"}

    @staticmethod
    def node_of(obj: dict):
        props = (obj.get("info") or {}).get("props") or {}
        cls = props.get("media.class", "")
        if obj.get("type") != "PipeWire:Interface:Node" or not cls.startswith("Audio/") or "Sink" not in cls and "Source" not in cls:
            return None
        if cls.endswith("Virtual") or props.get("node.virtual"):
            return None
        return {"name": props.get("node.name", ""), "desc": props.get("node.description") or props.get("node.nick") or props.get("node.name", ""),
                "bus": props.get("device.bus", ""), "kind": "출력" if "Sink" in cls else "입력"}

    def feed(self, objs: list, initial: bool = False) -> list:
        """[(action, 라벨, 종류, 노드이름, 내장 카드 여부)] — 라벨은 장치 설명. initial 이면 알리지 않고 기억만."""
        events = []
        for o in objs:
            nid = o.get("id")
            if o.get("info", 0) is None:                        # 제거: {"id": N, "info": null}
                node = self.nodes.pop(nid, None)
                if node and not initial and audio_interesting(node):
                    events.append(("remove", node["desc"], node["kind"], node["name"], node["bus"] not in ("usb", "bluetooth")))
                continue
            node = self.node_of(o)
            if node and nid not in self.nodes:
                self.nodes[nid] = node
                if not initial and audio_interesting(node):
                    events.append(("add", node["desc"], node["kind"], node["name"], node["bus"] not in ("usb", "bluetooth")))
        return events


def json_arrays(buf: str):
    """이어 붙은 JSON 값들을 (값 목록, 남은 글자)로. 아직 덜 온 마지막 값은 남겨 둔다."""
    dec, out, i = json.JSONDecoder(), [], 0
    while True:
        while i < len(buf) and buf[i].isspace():
            i += 1
        if i >= len(buf):
            return out, ""
        try:
            val, j = dec.raw_decode(buf, i)
        except ValueError:
            return out, buf[i:]
        out.append(val)
        i = j


# ───────────────────────── udev (USB, 전원) ─────────────────────────
def parse_udev(text: str):
    """`udevadm monitor --property` 출력 → ([이벤트 dict], 남은 글자). 이벤트: 빈 줄로 끝나는 블록, 첫 줄 뒤에 KEY=VAL."""
    blocks, rest = text.split("\n\n"), ""
    if not text.endswith("\n\n"):
        rest = blocks.pop()
    events = []
    for b in blocks:
        props = {}
        for line in b.splitlines():
            if "=" in line and not line.startswith(("UDEV", "KERNEL", "monitor")):
                k, _, v = line.partition("=")
                props[k] = v
        if props.get("ACTION"):
            events.append(props)
    return events, rest


def usb_event(props: dict):
    """usb_device 추가/제거 → (action, 이름) 또는 None. 허브(TYPE 9/…)와 인터페이스 이벤트는 제외."""
    if props.get("SUBSYSTEM") != "usb" or props.get("DEVTYPE") != "usb_device" or props.get("ACTION") not in ("add", "remove"):
        return None
    if props.get("TYPE", "").startswith("9/"):
        return None
    model = (props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL") or props.get("PRODUCT", "?")).replace("_", " ")
    vendor = (props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR") or "").replace("_", " ")
    name = model if not vendor or vendor.split()[0].lower() in model.lower() else f"{vendor} {model}"
    return props["ACTION"], name


def power_state(root: str = POWER_ROOT) -> dict:
    """{"ac": 어댑터 연결 여부, "pct": 배터리 %, "status": 배터리 상태}"""
    ac, pct, status = False, None, ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return {"ac": False, "pct": None, "status": ""}
    for n in names:
        def rd(f):
            try:
                with open(f"{root}/{n}/{f}") as fh:
                    return fh.read().strip()
            except OSError:
                return ""
        typ = rd("type")
        if typ == "Battery":
            pct, status = rd("capacity"), rd("status")
        elif typ == "Mains" and rd("online") == "1":      # ADP1. (USB-C 포트의 ucsi-source-* 는 scope=Device 라서 보지 않음)
            ac = True
    return {"ac": ac, "pct": int(pct) if str(pct).isdigit() else None, "status": status}


# ───────────────────────── 마운트 ─────────────────────────
def parse_mounts(text: str) -> dict:
    """mountinfo → {마운트 지점: (파일시스템, 원본)} (/run/media 등 이동식 위치만)."""
    out = {}
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        f = left.split()
        if not sep or len(f) < 5:
            continue
        mp = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), f[4])
        if mp.startswith(MOUNT_PREFIXES):
            r = right.split()
            out[mp] = (r[0] if r else "?", r[1] if len(r) > 1 else "?")
    return out


# ───────────────────────── 알림 묶음/재생성 걸러내기 ─────────────────────────
class Engine:
    """이벤트를 잠깐 모아서(출력+입력 묶음) 한 번에 보내고, 해제 직후 다시 생긴 장치는 둘 다 버린다."""

    def __init__(self, send):
        self.send = send               # send(category, action, label, kinds(list[str]), body)
        self.pending = {}
        self.announced = set()         # 내장 카드 노드 중 "연결"을 알린 것(그 해제만 알림)

    def add_internal(self, category: str, action: str, label: str, kind: str = "", t: float = 0.0) -> str:
        """내장 카드 노드(헤드폰): 연결은 SETTLE 초 유지돼야 알리고, 그 전에 사라지면 둘 다 버린다. 알린 적 없는 노드의 해제는 알리지 않는다."""
        if action == "add":
            return self.add(category, "add", label, kind, t=t, delay=SETTLE)
        if (category, "add", label) in self.pending:
            del self.pending[(category, "add", label)]
            return "flap"
        if (category, label) in self.announced:
            return self.add(category, "remove", label, kind, t=t)
        return "ignored"

    def add(self, category: str, action: str, label: str, kind: str = "", body: str = "", t: float = 0.0, delay=None) -> str:
        if action == "add" and (category, "remove", label) in self.pending:
            del self.pending[(category, "remove", label)]         # 다시 만들어진 것: 해제도 연결도 알리지 않음
            return "recreated"
        d = delay if delay is not None else (REMOVE_DELAY if action == "remove" else GROUP_DELAY if kind else QUICK)
        p = self.pending.setdefault((category, action, label), {"kinds": set(), "due": t + d, "body": body})
        if kind:
            p["kinds"].add(kind)
        return "queued"

    def poll(self, t: float) -> int:
        due = [k for k, p in self.pending.items() if p["due"] <= t]
        for k in due:
            p = self.pending.pop(k)
            (self.announced.add if k[1] == "add" else self.announced.discard)((k[0], k[2]))
            self.send(k[0], k[1], k[2], sorted(p["kinds"], key=lambda x: ("출력", "입력").index(x) if x in ("출력", "입력") else 9), p["body"])
        return len(due)


MESSAGES = {
    ("audio", "add"): ("오디오 장치 연결", "audio-headphones"), ("audio", "remove"): ("오디오 장치 해제", "audio-headphones"),
    ("usb", "add"): ("USB 연결", "drive-removable-media-usb"), ("usb", "remove"): ("USB 해제", "drive-removable-media-usb"),
    ("mount", "add"): ("마운트", "drive-harddisk"), ("mount", "remove"): ("언마운트", "drive-harddisk"),
    ("power", "add"): ("전원 어댑터 연결", "ac-adapter"), ("power", "remove"): ("배터리로 전환", "battery"),
}


def render(category: str, action: str, label: str, kinds: list, body: str) -> tuple:
    """(제목, 본문, 아이콘)"""
    title, icon = MESSAGES[(category, action)]
    text = label if category in ("usb", "audio", "mount") else ""
    extra = " · ".join(x for x in (" · ".join(kinds), body) if x)
    return (f"{title}: {text}" if text else title), extra, icon


def notify_send(category, action, label, kinds, body) -> None:
    title, text, icon = render(category, action, label, kinds, body)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", APP, "-u", "low", "-i", icon, title, text])


# ───────────────────────── 실행 ─────────────────────────
def reader(cmd: list, tag: str, q: queue.Queue, parse) -> None:
    """명령의 출력을 계속 읽어 parse(글자 버퍼) -> (이벤트 목록, 남은 글자) 로 큐에 넣는다. 명령이 끝나면 잠시 뒤 다시 시작."""
    while True:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            buf, first = "", True
            while True:
                chunk = os.read(p.stdout.fileno(), 65536).decode("utf-8", "replace")
                if not chunk:
                    break
                evs, buf = parse(buf + chunk)
                if evs and first:                    # (다시) 시작하고 처음 받은 값은 "지금 있는 것 전체" — 알리지 않고 기억만
                    q.put((tag, evs[:1], True))
                    evs, first = evs[1:], False
                if evs:
                    q.put((tag, evs, False))
        except OSError:
            pass
        time.sleep(5)


def mount_watcher(q: queue.Queue) -> None:
    try:
        f = open("/proc/self/mountinfo")
    except OSError:
        return
    ep = select.epoll()
    ep.register(f.fileno(), select.EPOLLPRI | select.EPOLLERR)
    q.put(("mounts", parse_mounts(f.read()), True))
    while True:
        ep.poll()
        f.seek(0)
        q.put(("mounts", parse_mounts(f.read()), False))


def run(send=notify_send) -> int:
    q: queue.Queue = queue.Queue()
    eng, audio = Engine(send), AudioTracker()
    threading.Thread(target=reader, args=(["pw-dump", "-m"], "pw", q, json_arrays), daemon=True).start()
    threading.Thread(target=reader, args=(["udevadm", "monitor", "--udev", "--property", "--subsystem-match=usb", "--subsystem-match=power_supply"], "udev", q, parse_udev), daemon=True).start()
    threading.Thread(target=mount_watcher, args=(q,), daemon=True).start()
    mounts, power = {}, power_state()
    while True:
        now = time.monotonic()
        try:
            tag, data, first = q.get(timeout=0.5)
        except queue.Empty:
            eng.poll(time.monotonic())
            continue
        if tag == "pw":
            if first:
                audio.nodes.clear()              # PipeWire 가 다시 시작됐을 수 있음(번호 재사용)
            for batch in data:
                for action, label, kind, _name, internal in audio.feed(batch, initial=first):
                    (eng.add_internal if internal else eng.add)("audio", action, label, kind, t=now)
        elif tag == "udev":
            for props in data:
                u = usb_event(props)
                if u:
                    eng.add("usb", u[0], u[1], t=now)
                if props.get("SUBSYSTEM") == "power_supply":
                    st = power_state()
                    if st["ac"] != power["ac"]:
                        eng.add("power", "add" if st["ac"] else "remove", "", body=f"배터리 {st['pct']}%" if st["pct"] is not None else "", t=now)
                    power = st
        elif tag == "mounts":
            if not first:                        # 처음 읽은 것은 시작 전부터 있던 마운트
                for mp in sorted(set(data) - set(mounts)):
                    eng.add("mount", "add", os.path.basename(mp), body=f"{data[mp][0]} · {mp}", t=now)
                for mp in sorted(set(mounts) - set(data)):
                    eng.add("mount", "remove", os.path.basename(mp), body=mp, t=now)
            mounts = data
        eng.poll(time.monotonic())
