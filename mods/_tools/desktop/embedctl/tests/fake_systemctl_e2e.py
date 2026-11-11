#!/usr/bin/env python3
"""끝단 시험용 가짜 systemctl — `start … embedctl-root@<동작>.service` 를 받으면 **실제 helper 코드(embedhelper.main)** 를 가짜 sysfs 트리(디스크의 파일들) 위에서 실행한다.
트리 경로는 호출한 쪽 환경변수(EMBEDCTL_MSIEC · EMBEDCTL_SYSFS_BAT · EMBEDCTL_DMI …)를 그대로 쓰므로 상태가 호출 사이에 파일로 유지된다.
운영 코드에 시험용 분기를 넣지 않으려고 여기서 `embedlib.sysfs_write` 를 바꿔 끼워 msi-ec 커널 모듈의 부수 효과를 흉내 낸다(충전 end 를 쓰면 start 가 end-10 으로 따라가고, 모드·부스트는 이름 그대로 저장).
환경변수: FAKE_IGNORE_WRITES=1(쓰기를 받아들이지만 값이 안 바뀜) · FAKE_SIDE_EFFECT=1(모드를 쓰면 cooler_boost 도 on 이 됨)
· FAKE_SET_FAIL=1(쓰기가 EcError 로 실패) · FAKE_FAIL_ON=<인스턴스>(그 동작만 sysfs 접근 실패로 끝냄) · FAKE_WRITES_LOG=<파일>(sysfs 쓰기 호출을 한 줄씩 기록).
종료 코드는 helper 의 종료 코드를 그대로 돌려준다(systemd oneshot 이 비정상 종료하면 `systemctl start` 도 실패)."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import embedlib as lib, embedhelper

unit = next((x for x in sys.argv[1:] if x.startswith("embedctl-root@")), None)
if not unit:
    sys.exit(1)
inst = unit[len("embedctl-root@"):-len(".service")]
wlog = os.environ.get("FAKE_WRITES_LOG")


def log(line):
    if wlog:
        with open(wlog, "a") as f:
            f.write(line + "\n")


def _put(path, text):
    with open(path, "w") as f:
        f.write(text)


def fake_sysfs_write(path, text):
    name = os.path.basename(path)
    log(f"sysfs {name}={text}")
    if os.environ.get("FAKE_SET_FAIL"):
        raise lib.EcError(f"sysfs 쓰기 실패({path}): 시험용 강제 실패")
    if os.environ.get("FAKE_IGNORE_WRITES"):
        return
    if name == "charge_control_end_threshold":
        n = int(text)
        _put(path, f"{n}\n")
        _put(os.path.join(os.path.dirname(path), "charge_control_start_threshold"), f"{n - 10}\n")     # msi-ec 의 배터리 훅
    else:
        _put(path, text + "\n")
        if os.environ.get("FAKE_SIDE_EFFECT") and name == "shift_mode":
            _put(os.path.join(os.path.dirname(path), "cooler_boost"), "on\n")


lib.sysfs_write = fake_sysfs_write
if inst == os.environ.get("FAKE_FAIL_ON"):
    lib.write_result(inst, False, error="sysfs 접근 실패: 시험용 강제 실패", code=4)
    sys.exit(4)
sys.exit(embedhelper.main(["embedhelper", inst]))
