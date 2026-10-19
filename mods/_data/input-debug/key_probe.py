#!/usr/bin/env python3
"""key_probe — 키보드 장치에서 **지정한 키의 눌림 횟수와 전체 키 이벤트 개수만** 센다(누른 글자 내용은 읽지도 기록하지도 않는다). root 로 실행(/dev/input).
특정 키가 안 먹을 때 "키 신호가 커널까지 올라오는가"를 가르는 용도: 올라오면 입력기/터미널/앱 문제, 0 이면 키보드 하드웨어/EC/펌웨어 문제.

  sudo key_probe.py [초=60] [키이름,...=backspace,left,right,up,down] [장치 이름=AT Translated Set 2 keyboard]
  예) 5분 동안: sudo key_probe.py 300
결과는 표준출력 한 줄(JSON)이고, 눌러 달라고 한 횟수와 비교하면 된다. 다른 키는 `other_events`(개수)로만 합산된다."""
import glob, json, os, select, struct, sys, time

CODES = {"backspace": 14, "left": 105, "right": 106, "up": 103, "down": 108, "enter": 28, "esc": 1, "tab": 15, "delete": 111, "space": 57}
FMT = "llHHi"


def find_device(name: str):
    for d in sorted(glob.glob("/sys/class/input/event*")):
        try:
            if open(d + "/device/name").read().strip() == name:
                return "/dev/input/" + os.path.basename(d)
        except OSError:
            pass
    return None


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
    names = (argv[1] if len(argv) > 1 else "backspace,left,right,up,down").split(",")
    watch = {CODES[n]: n for n in names}
    dev = find_device(argv[2] if len(argv) > 2 else "AT Translated Set 2 keyboard")
    if not dev:
        print("키보드 장치를 찾지 못했습니다", file=sys.stderr)
        return 1
    counts = {n: 0 for n in names}
    counts["other_events"] = 0
    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 1.0)
        if r:
            count_events(os.read(fd, struct.calcsize(FMT) * 64), watch, counts)
    print(json.dumps({"device": dev, "seconds": seconds, **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
