#!/usr/bin/env python3
"""posture-daemon — 360도 힌지 노트북의 "자세"(힌지 각도 → 사용 모드)를 센서에서 읽어 한 곳에 발행한다. (root 로 실행)

발행: /run/posture/state.json  (원자적 교체. 스키마 버전 `schema`)
  {"schema": 1, "ts": <epoch 초>, "mode": "laptop|tent|tablet",
   "hinge": {"angle": 138, "screen": 129, "keyboard": 351},
   "orientation": null, "sensors": {"hinge": "ok"}}
가져가기는 `posture get mode` / `posture json`, 알림은 이 파일 변경을 보는 systemd 경로 유닛(core.posture.nix)이 한다.
이 프로세스는 값을 **계산해서 발행만** 하고, 어떤 소비자(입력 장치, 화면 회전 …)가 있는지 모른다.

왜 센서를 직접 읽나: 이 기기의 커널은 "태블릿 모드" 스위치(SW_TABLET_MODE)를 만들지 않고(덮개 스위치는 360도로 접어도 open),
힌지 센서 값은 평소 sysfs(in_angl*_raw)로는 0 이라 **버퍼(스트리밍) 모드로 켜야** 값이 온다(실측). 센서가 값이 바뀔 때만 샘플을 주므로
read() 에서 막혀 기다리면 되고 폴링이 없다(전력 부담이 작음).

모드 경계(실측 기반, 켜는 값과 끄는 값에 차이를 둬서 경계에서 깜빡이지 않게 함):
  laptop → tent   : 힌지 ≥ 205°        tent → laptop  : 힌지 < 190°
  tent   → tablet : 힌지 ≥ 335°        tablet → tent  : 힌지 < 315°
모드가 바뀌어도 DEBOUNCE 초 동안 유지돼야 확정(순간적인 튐 방지). 멈추면(SIGTERM) 안전한 값(laptop)을 발행하고 켠 센서 설정을 모두 원복한다.

시험용 환경변수: POSTURE_IIO(IIO sysfs 루트), POSTURE_DEV(장치 노드 디렉터리), POSTURE_STATE_DIR, POSTURE_DEBOUNCE(초)
"""
import json
import os
import select
import signal
import sys
import time

IIO = os.environ.get("POSTURE_IIO", "/sys/bus/iio/devices")
DEV = os.environ.get("POSTURE_DEV", "/dev")
STATE_DIR = os.environ.get("POSTURE_STATE_DIR", "/run/posture")
STATE = os.path.join(STATE_DIR, "state.json")
DEBOUNCE = float(os.environ.get("POSTURE_DEBOUNCE", "1.0"))
ANGLE_STEP = 5   # 같은 모드에서 각도가 이만큼 이상 달라질 때만 다시 발행(소비자를 깨우는 횟수를 줄임. 소비자에게 의미 있는 건 모드 변화)
SCHEMA = 1

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


def write(path: str, text: str) -> None:
    open(path, "w").write(text)


# ───────────────────────── 발행 ─────────────────────────
def publish(mode: str, hinge: dict | None, sensors: dict) -> None:
    """원자적 교체: 같은 디렉터리에 임시 파일을 쓰고 rename (읽는 쪽이 반쯤 쓰인 파일을 볼 수 없음)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    doc = {"schema": SCHEMA, "ts": int(time.time()), "mode": mode,
           "hinge": hinge or {"angle": None, "screen": None, "keyboard": None},
           "orientation": None, "sensors": sensors}
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATE)


def main() -> int:
    dev = find("hinge")
    if dev is None:
        print("힌지 센서(IIO `hinge`)가 없어서 종료합니다.", file=sys.stderr)
        return 0
    node = os.path.join(DEV, os.path.basename(dev))
    chans = [f[:-3] for f in os.listdir(f"{dev}/scan_elements") if f.startswith("in_angl") and f.endswith("_en")]
    write(f"{dev}/buffer/enable", "0")
    for n in chans:                           # 각도 3개만 켬(타임스탬프는 쓰지 않음)
        write(f"{dev}/scan_elements/{n}_en", "1")
    lay, size = layout(dev)
    write(f"{dev}/buffer/enable", "1")
    sensors = {"hinge": "ok"}

    def cleanup(*_):
        try:                                   # 켠 것을 모두 원복
            write(f"{dev}/buffer/enable", "0")
            for n in chans:
                write(f"{dev}/scan_elements/{n}_en", "0")
        except OSError:
            pass
        publish("laptop", None, {"hinge": "stopped"})   # 멈추면 안전한 값(키보드/터치패드 켜짐)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    fd = os.open(node, os.O_RDONLY)
    mode, hinge, pending, since, first, last_angle = "laptop", None, None, 0.0, True, None
    try:
        while True:
            timeout = None if pending is None else max(0.0, since + DEBOUNCE - time.monotonic())
            r, _, _ = select.select([fd], [], [], timeout)
            if r:
                data = os.read(fd, size * 16)
                for i in range(0, len(data) - size + 1, size):    # 한 번에 여러 레코드가 올 수 있음
                    v = decode(data[i:i + size], lay)
                    hinge = {"angle": v["in_angl0"], "screen": v["in_angl1"], "keyboard": v["in_angl2"]}
                    cand = classify(mode, hinge["angle"])
                    if first:                 # 시작 직후 첫 값은 바로 확정
                        mode, pending, first = cand, None, False
                        publish(mode, hinge, sensors)
                        last_angle = hinge["angle"]
                    elif cand == mode:
                        pending = None
                        if last_angle is None or abs(hinge["angle"] - last_angle) >= ANGLE_STEP:
                            publish(mode, hinge, sensors)   # 각도만 갱신(작은 떨림은 발행하지 않음)
                            last_angle = hinge["angle"]
                    elif pending != cand:
                        pending, since = cand, time.monotonic()
            elif pending is not None:
                mode, pending = pending, None
                publish(mode, hinge, sensors)
                last_angle = hinge["angle"]
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
