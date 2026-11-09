#!/usr/bin/env python3
"""끝단 시험용 가짜 systemctl — `start … embedctl-root@<동작>.service` 를 받으면 **실제 helper 코드(embedhelper.main)** 를 메모리 속 EC 에뮬레이터 위에서 실행한다.
운영 코드에 시험용 분기를 넣지 않으려고 여기서 `embedlib.wmi_call` 을 바꿔 끼운다. EC 초기값은 환경변수 FAKE_EC(JSON: {"d7":…,"d2":…,"b98":…}), 펌웨어 원문은 FAKE_FW(기본 1592EMS1.111).
종료 코드는 helper 의 종료 코드를 그대로 돌려준다(systemd oneshot 이 비정상 종료하면 `systemctl start` 도 실패)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import embedlib as lib, embedhelper

unit = next((x for x in sys.argv[1:] if x.startswith("embedctl-root@")), None)
if not unit:
    sys.exit(1)
inst = unit[len("embedctl-root@"):-len(".service")]
ec = {0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}
NAME_TO_ADDR = {"d7": 0xD7, "d2": 0xD2, "b98": 0x98}      # FAKE_EC 의 키는 이름이다(`b98` 은 주소 0x98 — 16진수로 읽으면 0xB98 이 된다)
ec.update({NAME_TO_ADDR[k]: v for k, v in json.loads(os.environ.get("FAKE_EC", "{}")).items()})
fw = os.environ.get("FAKE_FW", "1592EMS1.1110629202209:52:28").encode()

def emu(method, req):
    if method == "get_ec":
        return (b"\x01\x81" + fw).ljust(32, b"\0")
    if method == "get_data":
        if os.environ.get("FAKE_EC_FAIL"):
            return bytes(32)
        return bytes([1, ec[req[0]]]).ljust(32, b"\0")
    raise AssertionError("읽기 전용 단계에서 쓰기 호출: " + method)

lib.wmi_call = emu
sys.exit(embedhelper.main(["embedhelper", inst]))
