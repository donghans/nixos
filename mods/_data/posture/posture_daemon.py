#!/usr/bin/env python3
"""posture-daemon — 360도 힌지 노트북의 "사용 모드"(힌지 각도 → laptop/tent/tablet)를 센서에서 읽어 한 곳에 발행한다. (root 로 실행)

발행(둘 다 원자적 교체):
  /run/posture/state.json      소비자를 깨우는 값. **변할 때만** 갱신 — systemd 경로 유닛이 이 파일만 본다.
    {"schema": 1, "ts": <epoch 초>, "mode": "laptop|tent|tablet",
     "orientation": {"rotation": 0, "flat": false}, "lid": "open|closed|null",
     "sensors": {"hinge": "ok", "accel": "ok", "lid": "ok"}}
  /run/posture/telemetry.json  자주 바뀌지만 소비자를 깨울 필요 없는 값(힌지 각도). 감시하지 않음.
    {"ts": ..., "hinge": {"angle": 138, "screen": 129, "keyboard": 351}}
  (각도를 상태 파일에 두면 덮개를 여는 몇 초 동안 5° 마다 모든 소비자가 다시 실행됐다 — 실측으로 확인해서 분리함)
orientation.rotation: 기기를 시계방향으로 돌린 각도(0/90/180/270). 정방향 가로=0, 윗변이 오른쪽=90, 거꾸로=180, 윗변이 왼쪽=270.
  laptop 모드에서는 항상 0(센서도 읽지 않음). flat=true 이면 책상에 눕혀 놓은 상태라 방향을 정할 수 없어 직전 값을 유지 중.
lid: 덮개 스위치(evdev `Lid Switch`, SW_LID)로 읽은 덮개 상태. 시작할 때는 /proc/acpi/button/lid/*/state. 스위치가 없으면 null(소비자는 열림으로 취급).
힌지 센서가 없는 일반 노트북에서도 덮개 때문에 계속 돈다(둘 다 없으면 바로 종료).
가져가기는 `posture get mode|lid|rotation|angle` / `posture json`(두 파일을 합쳐서 보여 줌), 알림은 state.json 변경을 보는 systemd 경로 유닛(core.posture.nix)이 한다.
화면 방향은 화면(뚜껑)에 달린 가속도 센서(IIO `accel_3d`)로 판정한다. 중력 방향만 보면 되므로 센서 축 방향만 알면 된다(실측: 이 기기는 +x=화면 왼쪽, +y=화면 아래, -z=화면 앞쪽).
세워서 쓰는 중에만(tent/tablet) 약 3Hz 로 sysfs 를 읽고, laptop 이면 읽지 않는다. 경계 흔들림은 히스테리시스(15°)와 디바운스로 막는다.
이 프로세스는 값을 **계산해서 발행만** 하고, 어떤 소비자(입력 장치, 화면 회전 …)가 있는지 모른다.

왜 센서를 직접 읽나: 이 기기의 커널은 "태블릿 모드" 스위치(SW_TABLET_MODE)를 만들지 않고(덮개 스위치는 360도로 접어도 open),
힌지 센서 값은 평소 sysfs(in_angl*_raw)로는 0 이라 **버퍼(스트리밍) 모드로 켜야** 값이 온다(실측). 센서가 값이 바뀔 때만 샘플을 주므로
read() 에서 막혀 기다리면 되고 폴링이 없다(전력 부담이 작음). 단 가만히 있으면 첫 샘플도 안 오므로 시작할 때 hysteresis 를 썼다 되돌려 한 번 내보내게 한다.

모드 경계(실측 기반, 켜는 값과 끄는 값에 차이를 둬서 경계에서 깜빡이지 않게 함):
  laptop → tent   : 힌지 ≥ 205°        tent → laptop  : 힌지 < 190°
  tent   → tablet : 힌지 ≥ 335°        tablet → tent  : 힌지 < 315°
모드가 바뀌어도 DEBOUNCE 초 동안 유지돼야 확정(순간적인 튐 방지). 멈추면(SIGTERM) 안전한 값(laptop)을 발행하고 켠 센서 설정을 모두 원복한다.

시험용 환경변수: POSTURE_IIO(IIO sysfs 루트), POSTURE_DEV(장치 노드 디렉터리), POSTURE_STATE_DIR, POSTURE_DEBOUNCE(초), POSTURE_LID_DEV(덮개 evdev 노드/FIFO), POSTURE_LID_STATE(시작 덮개 상태 파일)
"""
import json
import os
import select
import signal
import struct
import sys
import time

IIO = os.environ.get("POSTURE_IIO", "/sys/bus/iio/devices")
DEV = os.environ.get("POSTURE_DEV", "/dev")
STATE_DIR = os.environ.get("POSTURE_STATE_DIR", "/run/posture")
STATE = os.path.join(STATE_DIR, "state.json")           # 소비자를 깨우는 상태(모드/방향/덮개). 경로 유닛이 감시
TELE = os.path.join(STATE_DIR, "telemetry.json")        # 자주 바뀌는 값(힌지 각도). 감시하지 않음
DEBOUNCE = float(os.environ.get("POSTURE_DEBOUNCE", "1.0"))
ANGLE_STEP = 5   # 같은 모드에서 각도가 이만큼 이상 달라질 때만 다시 발행(소비자를 깨우는 횟수를 줄임. 소비자에게 의미 있는 건 모드 변화)
SCHEMA = 1
ACCEL_PERIOD = float(os.environ.get("POSTURE_ACCEL_PERIOD", "0.33"))   # 가속도 읽는 간격(초). tent/tablet 에서만
ORIENT_DEBOUNCE = float(os.environ.get("POSTURE_ORIENT_DEBOUNCE", "0.8"))  # 새 방향이 이만큼 유지돼야 확정(손으로 들고 움직이는 동안 깜빡임 방지)
ORIENT_HYST = 15.0          # 현재 방향의 중심에서 45+15=60° 넘게 벗어나야 다른 방향으로 바뀜
FLAT_ENTER, FLAT_EXIT = 2.5, 3.5   # 화면 평면 방향 중력 성분(m/s²)이 이보다 작으면 "눕혀 놓음"(약 15° 이내). 들어갈 땐 낮게, 나올 땐 높게

# (이전 모드) → (다음 모드, 임계각)
UP = {"laptop": ("tent", 205), "tent": ("tablet", 335)}
DOWN = {"tent": ("laptop", 190), "tablet": ("tent", 315)}


def classify(cur: str, angle: float) -> str:
    """현재 모드와 각도로 다음 모드. 한 번에 여러 단계도 건너뛸 수 있음(예: 열린 채 시작해 이미 360도)."""
    mode = cur
    for _ in range(3):
        if mode in UP and angle >= UP[mode][1]:
            mode = UP[mode][0]
        elif mode in DOWN and angle < DOWN[mode][1]:
            mode = DOWN[mode][0]
        else:
            break
    return mode


def rotation_angle(x: float, y: float) -> float:
    """가속도(m/s²) x,y → 기기를 시계방향으로 돌린 각도(0~360). 센서 reading 은 '위'를 가리키며, 이 기기는 +x=화면 왼쪽, +y=화면 아래라
    화면 기준 위쪽 = (-x, -y). 정방향(윗변이 위)이면 y<0, 시계 90°(윗변이 오른쪽)이면 x>0."""
    import math
    return math.degrees(math.atan2(x, -y)) % 360


def orient_classify(cur: int, flat: bool, x: float, y: float) -> tuple[int, bool]:
    """현재 회전각(0/90/180/270)과 눕힘 여부에서, 새 가속도 값으로 다음 (회전각, 눕힘) 계산.
    눕힌 상태에서는 회전각을 그대로 둔다(평평한 책상에서 센서 노이즈로 돌아가지 않게)."""
    import math
    m = math.hypot(x, y)
    flat = m < (FLAT_EXIT if flat else FLAT_ENTER)
    if flat:
        return cur, True
    ang = rotation_angle(x, y)
    diff = abs((ang - cur + 180) % 360 - 180)         # 현재 방향 중심과의 각도 차(0~180)
    if diff < 45 + ORIENT_HYST:
        return cur, False
    return int(round(ang / 90.0)) % 4 * 90, False


# ───────────────────────── IIO 입출력 ─────────────────────────
def find(name: str) -> str | None:
    for d in sorted(os.listdir(IIO)):
        p = os.path.join(IIO, d)
        try:
            if open(os.path.join(p, "name")).read().strip() == name:
                return p
        except OSError:
            pass
    return None


def parse_type(t: str) -> tuple[bool, int, int, int]:
    """`le:s16/32>>0` → (부호 있음, 유효 비트, 저장 비트, 시프트)"""
    body = t.split(":", 1)[1]
    sign = body[0] == "s"
    real, rest = body[1:].split("/")
    store, shift = rest.split(">>")
    return sign, int(real), int(store), int(shift)


def layout(dev: str) -> tuple[list[tuple[str, int, tuple]], int]:
    """**켜진** 스캔 요소만 index 순으로: (이름, 오프셋, 형식), 레코드 크기. 각 요소는 자기 크기에 맞춰 정렬됨(IIO 규칙).
    (타임스탬프를 켜지 않으면 레코드는 12바이트 — 실측. 꺼진 채널까지 넣어 24바이트로 계산하면 레코드를 못 읽는다.)"""
    elems = []
    for f in os.listdir(os.path.join(dev, "scan_elements")):
        if f.endswith("_index"):
            n = f[:-6]
            if open(os.path.join(dev, "scan_elements", n + "_en")).read().strip() != "1":
                continue
            idx = int(open(os.path.join(dev, "scan_elements", f)).read())
            typ = parse_type(open(os.path.join(dev, "scan_elements", n + "_type")).read().strip())
            elems.append((idx, n, typ))
    out, off = [], 0
    for _, n, typ in sorted(elems):
        size = typ[2] // 8
        off = (off + size - 1) // size * size
        out.append((n, off, typ))
        off += size
    biggest = max(t[2] for _, _, t in out) // 8
    total = (off + biggest - 1) // biggest * biggest
    return out, total


def decode(buf: bytes, lay) -> dict:
    vals = {}
    for n, off, (sign, real, store, shift) in lay:
        raw = int.from_bytes(buf[off:off + store // 8], "little") >> shift
        raw &= (1 << real) - 1
        if sign and raw >= 1 << (real - 1):
            raw -= 1 << real
        vals[n] = raw
    return vals


def read_accel(dev: str, scale: float) -> tuple[float, float]:
    """화면 평면의 중력 성분(x, y)만 읽는다. 방향 판정에 z 는 쓰지 않고, 센서 허브에 질의하는 읽기 하나가 ~10ms 걸려서(실측: 3개 30ms/CPU 1.4ms) 안 읽는 쪽이 싸다."""
    return tuple(int(open(f"{dev}/in_accel_{a}_raw").read()) * scale for a in "xy")


def write(path: str, text: str) -> None:
    open(path, "w").write(text)


# ───────────────────────── 발행 ─────────────────────────
def write_atomic(path: str, doc: dict) -> None:
    """원자적 교체: 같은 디렉터리에 임시 파일을 쓰고 rename (읽는 쪽이 반쯤 쓰인 파일을 볼 수 없음)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def publish_state(mode: str, orient: dict | None, lid: str | None, sensors: dict) -> None:
    """소비자가 알아야 하는 값만(모드/방향/덮개). **변할 때만** 부른다 — 경로 유닛이 이 파일을 보고 소비자를 깨운다."""
    write_atomic(STATE, {"schema": SCHEMA, "ts": int(time.time()), "mode": mode,
                         "orientation": orient or {"rotation": 0, "flat": False}, "lid": lid, "sensors": sensors})


def publish_telemetry(hinge: dict | None) -> None:
    """힌지 각도처럼 자주 바뀌지만 소비자를 깨울 필요는 없는 값. 경로 유닛이 보지 않는다(`posture get angle` 이 읽음)."""
    write_atomic(TELE, {"ts": int(time.time()), "hinge": hinge or {"angle": None, "screen": None, "keyboard": None}})


# ───────────────────────── 덮개 스위치 ─────────────────────────
EV_SW, SW_LID = 5, 0
EV_FMT = "llHHi"                      # struct input_event: timeval(sec, usec), type, code, value
EV_SIZE = struct.calcsize(EV_FMT)


def find_lid_node() -> str | None:
    """덮개 스위치의 evdev 노드. 시험에서는 POSTURE_LID_DEV 로 FIFO 를 줄 수 있음."""
    forced = os.environ.get("POSTURE_LID_DEV")
    if forced == "none":                  # 시험용: 덮개 장치가 없는 기기를 흉내(이 기기의 실제 덮개 스위치를 읽지 않게)
        return None
    if forced:
        return forced
    base = "/sys/class/input"
    try:
        for d in sorted(os.listdir(base)):
            try:
                if open(f"{base}/{d}/name").read().strip() == "Lid Switch":
                    for e in os.listdir(f"{base}/{d}"):
                        if e.startswith("event"):
                            return os.path.join(DEV, "input", e)
            except OSError:
                continue
    except OSError:
        pass
    return None


def read_lid_file() -> str | None:
    """시작할 때의 덮개 상태(ACPI 버튼 파일: `state:      open`). 시험에서는 POSTURE_LID_STATE."""
    path = os.environ.get("POSTURE_LID_STATE")
    paths = [path] if path else sorted(__import__("glob").glob("/proc/acpi/button/lid/*/state"))
    for p in paths:
        try:
            v = open(p).read().split(":")[-1].strip()
            if v in ("open", "closed"):
                return v
        except OSError:
            continue
    return None


def decode_lid(data: bytes) -> str | None:
    """evdev 레코드들에서 마지막 덮개 이벤트(SW_LID: 1=닫힘) → "closed"/"open". 없으면 None."""
    lid = None
    for i in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
        _s, _u, typ, code, val = struct.unpack(EV_FMT, data[i:i + EV_SIZE])
        if typ == EV_SW and code == SW_LID:
            lid = "closed" if val else "open"
    return lid


def main() -> int:
    dev = find("hinge")
    lid_node = find_lid_node()
    if dev is None and lid_node is None:
        print("힌지 센서(IIO `hinge`)도 덮개 스위치도 없어서 종료합니다.", file=sys.stderr)
        return 0
    sensors = {"hinge": "none", "accel": "none", "lid": "none"}
    chans: list[str] = []
    lay, size, node = None, 0, None
    if dev is not None:
        node = os.path.join(DEV, os.path.basename(dev))
        chans = [f[:-3] for f in os.listdir(f"{dev}/scan_elements") if f.startswith("in_angl") and f.endswith("_en")]
        write(f"{dev}/buffer/enable", "0")
        for n in chans:                           # 각도 3개만 켬(타임스탬프는 쓰지 않음)
            write(f"{dev}/scan_elements/{n}_en", "1")
        lay, size = layout(dev)
        write(f"{dev}/buffer/enable", "1")
        sensors["hinge"] = "ok"
    accel = find("accel_3d") if dev is not None else None
    accel_scale = 1.0
    if accel:
        try:
            accel_scale = float(open(f"{accel}/in_accel_scale").read())
            read_accel(accel, accel_scale)
            sensors["accel"] = "ok"
        except (OSError, ValueError):
            accel, sensors["accel"] = None, "error"

    lid = read_lid_file() if lid_node else None
    lid_fd = None
    if lid_node:
        try:
            lid_fd = os.open(lid_node, os.O_RDONLY | os.O_NONBLOCK)
            sensors["lid"] = "ok"
        except OSError:
            sensors["lid"] = "error"

    def cleanup(*_):
        try:                                   # 켠 것을 모두 원복
            if dev is not None:
                write(f"{dev}/buffer/enable", "0")
                for n in chans:
                    write(f"{dev}/scan_elements/{n}_en", "0")
        except OSError:
            pass
        publish_state("laptop", None, None, {"hinge": "stopped"})   # 멈추면 안전한 값(키보드/터치패드 켜짐, 덮개 열림)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    fd = os.open(node, os.O_RDONLY) if node else None
    if dev is not None:
        # 센서는 값이 바뀔 때만 샘플을 준다. 힌지가 가만히 있는 채로 데몬이 시작/재시작되면(예: 접은 채 부팅) 첫 샘플이 영영 안 와서
        # 현재 모드를 모르게 된다(실측: 재시작 뒤 접힌 채 가만히 두면 'stopped/laptop' 으로 남고, hysteresis 를 0 으로 바꿨다 0.2초 이상 뒤 되돌리면 샘플이 나옴).
        # hysteresis 를 0 으로 썼다가 원래 값으로 돌려서 현재 값을 한 번 내보내게 한다. (장치 노드를 연 **뒤에** 해야 그 샘플을 받을 수 있음)
        try:
            hyst = open(f"{dev}/in_angl_hysteresis").read().strip()
            write(f"{dev}/in_angl_hysteresis", "0")
            time.sleep(0.3)               # 바로 되돌리면 샘플이 안 나온다(실측: 0.2~0.5초 쉬었다 되돌리면 나옴)
            write(f"{dev}/in_angl_hysteresis", hyst)
        except OSError:
            pass
    mode, hinge, pending, since, first, last_angle = "laptop", None, None, 0.0, dev is not None, None
    rot, flat, o_pend, o_since, next_poll = 0, False, None, 0.0, 0.0   # 화면 방향 상태(회전각, 눕힘, 대기 중인 새 방향, 다음 읽기 시각)
    ready = dev is None                 # 힌지 센서가 있으면 첫 샘플로 모드를 알기 전에는 상태를 발행하지 않음(접힌 채 시작할 때 laptop 이 잠깐 새 나가지 않게)

    def pub():
        if ready:
            publish_state(mode, {"rotation": rot, "flat": flat}, lid, sensors)

    def tele():
        publish_telemetry(hinge)

    if ready:
        pub()                           # 힌지가 없으면(일반 노트북) 시작하자마자 덮개 상태를 발행
    fds = [x for x in (fd, lid_fd) if x is not None]
    try:
        while True:
            now = time.monotonic()
            waits = []
            if pending is not None:
                waits.append(since + DEBOUNCE - now)
            if o_pend is not None:
                waits.append(o_since + ORIENT_DEBOUNCE - now)
            if accel and mode != "laptop":
                waits.append(next_poll - now)
            timeout = max(0.0, min(waits)) if waits else None
            r, _, _ = select.select(fds, [], [], timeout)
            if r:
                if lid_fd is not None and lid_fd in r:
                    try:
                        new_lid = decode_lid(os.read(lid_fd, EV_SIZE * 32))
                    except BlockingIOError:
                        new_lid = None
                    if new_lid and new_lid != lid:
                        lid = new_lid
                        pub()
                if fd is not None and fd in r:
                    data = os.read(fd, size * 16)
                    for i in range(0, len(data) - size + 1, size):    # 한 번에 여러 레코드가 올 수 있음
                        v = decode(data[i:i + size], lay)
                        hinge = {"angle": v["in_angl0"], "screen": v["in_angl1"], "keyboard": v["in_angl2"]}
                        cand = classify(mode, hinge["angle"])
                        if first:                 # 시작 직후 첫 값은 바로 확정
                            mode, pending, first, ready = cand, None, False, True
                            pub()
                            tele()
                            last_angle = hinge["angle"]
                        elif cand == mode:
                            pending = None
                            if last_angle is None or abs(hinge["angle"] - last_angle) >= ANGLE_STEP:
                                tele()   # 각도만 갱신: 소비자는 깨우지 않음(상태 파일은 그대로)
                                last_angle = hinge["angle"]
                        elif pending != cand:
                            pending, since = cand, time.monotonic()
            else:
                if pending is not None and time.monotonic() >= since + DEBOUNCE:
                    mode, pending = pending, None
                    if mode == "laptop":                 # 접어서 쓰던 방향은 의미가 없어짐: 가로 정방향으로
                        rot, flat, o_pend = 0, False, None
                    else:
                        next_poll = 0.0                  # 센서를 바로 읽어서 현재 방향을 반영
                    pub()
                    tele()
                    last_angle = hinge["angle"]
                if accel and mode != "laptop" and time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + ACCEL_PERIOD
                    try:
                        x, y = read_accel(accel, accel_scale)
                    except (OSError, ValueError):
                        sensors["accel"] = "error"
                        accel = None
                        pub()
                        continue
                    new_rot, new_flat = orient_classify(rot, flat, x, y)
                    if new_flat != flat:                 # 눕힘 여부만 바뀌어도 발행(소비자가 회전 고정 표시에 쓸 수 있음)
                        flat = new_flat
                        pub()
                    if new_rot == rot:
                        o_pend = None
                    elif o_pend != new_rot:
                        o_pend, o_since = new_rot, time.monotonic()
                if o_pend is not None and time.monotonic() >= o_since + ORIENT_DEBOUNCE:
                    rot, o_pend = o_pend, None
                    pub()
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
