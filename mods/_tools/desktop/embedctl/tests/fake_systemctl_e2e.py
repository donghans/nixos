#!/usr/bin/env python3
"""끝단 시험용 가짜 systemctl — `start … embedctl-root@<동작>.service` 를 받으면 **실제 helper 코드(embedhelper.main)** 를 메모리 속 EC 에뮬레이터 위에서 실행한다.
운영 코드에 시험용 분기를 넣지 않으려고 여기서 `embedlib.wmi_call`·`embedlib.sysfs_write_end` 를 바꿔 끼운다.
EC 상태는 호출 사이에 유지되도록 파일(FAKE_EC_STATE, JSON {"d7","d2","b98"})에 저장한다. 파일이 없으면 FAKE_EC(같은 모양) 또는 기본값(0x80·0xC1·0x02)으로 시작한다.
환경변수: FAKE_FW(펌웨어 원문, 기본 1592EMS1.1110629202209:52:28) · FAKE_EC_FAIL=1(get_data 실패) · FAKE_IGNORE_WRITES=1(쓰기를 받아들이지만 값이 안 바뀜)
· FAKE_SIDE_EFFECT=1(0xD2 를 쓰면 0x98 비트7 도 켜짐) · FAKE_SET_FAIL=1(set_data 실패 응답) · FAKE_FAIL_ON=<인스턴스>(그 동작만 EC 접근 실패로 끝냄)
· FAKE_WRITES_LOG=<파일>(set_data/sysfs 쓰기 호출을 한 줄씩 기록).
종료 코드는 helper 의 종료 코드를 그대로 돌려준다(systemd oneshot 이 비정상 종료하면 `systemctl start` 도 실패)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import embedlib as lib, embedhelper

unit = next((x for x in sys.argv[1:] if x.startswith("embedctl-root@")), None)
if not unit:
    sys.exit(1)
inst = unit[len("embedctl-root@"):-len(".service")]

NAME_TO_ADDR = {"d7": 0xD7, "d2": 0xD2, "b98": 0x98}      # 상태 파일·FAKE_EC 의 키는 이름이다(`b98` 은 주소 0x98 — 16진수로 읽으면 0xB98 이 된다)
state_path = os.environ.get("FAKE_EC_STATE")
if state_path and os.path.exists(state_path):
    src = json.load(open(state_path))
else:
    src = json.loads(os.environ.get("FAKE_EC", "{}"))
ec = {0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}
ec.update({NAME_TO_ADDR[k]: v for k, v in src.items()})
fw = os.environ.get("FAKE_FW", "1592EMS1.1110629202209:52:28").encode()
wlog = os.environ.get("FAKE_WRITES_LOG")

def log(line):
    if wlog:
        with open(wlog, "a") as f:
            f.write(line + "\n")

def emu(method, req):
    if method == "get_ec":
        return (b"\x01\x81" + fw).ljust(32, b"\0")
    if method == "get_data":
        if os.environ.get("FAKE_EC_FAIL"):
            return bytes(32)
        return bytes([1, ec[req[0]]]).ljust(32, b"\0")
    if method == "set_data":
        log(f"set_data 0x{req[0]:02X}=0x{req[1]:02X}")
        if os.environ.get("FAKE_SET_FAIL"):
            return bytes(32)
        if not os.environ.get("FAKE_IGNORE_WRITES"):
            ec[req[0]] = req[1]
            if os.environ.get("FAKE_SIDE_EFFECT") and req[0] == 0xD2:
                ec[0x98] |= 0x80
        return (b"\x01").ljust(32, b"\0")
    raise AssertionError("알 수 없는 WMI 메서드: " + method)

def fake_sysfs_write_end(n):
    log(f"sysfs end={n}")
    if os.environ.get("FAKE_IGNORE_WRITES"):
        return
    with open(lib.sysfs_end_path(), "w") as f:
        f.write(f"{int(n)}\n")
    with open(os.path.join(os.path.dirname(lib.sysfs_end_path()), "charge_control_start_threshold"), "w") as f:
        f.write(f"{int(n) - 10}\n")
    ec[0xD7] = 0x80 + int(n)                               # msi_ec 의 배터리 훅이 하는 일을 흉내 낸다

lib.wmi_call = emu
lib.sysfs_write_end = fake_sysfs_write_end
rc = 0
try:
    if inst == os.environ.get("FAKE_FAIL_ON"):
        lib.write_result(inst, False, error="EC 접근 실패: 시험용 강제 실패", code=4)
        rc = 4
    else:
        rc = embedhelper.main(["embedhelper", inst])
finally:
    if state_path:
        json.dump({"d7": ec[0xD7], "d2": ec[0xD2], "b98": ec[0x98]}, open(state_path, "w"))
sys.exit(rc)
