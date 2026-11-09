#!/usr/bin/env python3
"""embedhelper — embedctl 의 root helper. systemd 템플릿 유닛 `embedctl-root@<동작>.service` 가 root 로 실행한다(`ExecStart=… embedhelper.py %i`).

인스턴스 이름이 곧 동작이다: status · charge-<N> · mode-<sport|comfort|eco> · boost-<on|off>. 이름은 `embedlib.INSTANCE_RE` 로 엄격히 검증하며
검증을 통과하지 못한 이름은 아무것도 하지 않고 종료 코드 2 로 끝난다(결과 파일도 만들지 않는다 — 파일 이름에 쓰이므로).
EC 접근 전체를 `/run/embedctl/lock` 의 flock 으로 직렬화하고, 결과는 `/run/embedctl/last-<인스턴스>.json` 에 남긴다(사용자 CLI 가 읽는다).
종료 코드: 0 성공 · 2 입력 오류·미구현 · 3 게이트 거부 · 4 EC 접근 실패 · 5 되읽기 불일치.

현재(계획 단계 2)는 `status` 만 구현돼 있다. 쓰기 동작은 단계 3.
"""
import fcntl
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import embedlib as lib   # noqa: E402


def dispatch(inst):
    try:
        if inst == "status":
            data = lib.collect_ec_direct()
            lib.write_result(inst, True, data=data)
            ec = data["ec"]
            print(f"embedctl-root status: fw={data['fw']} EC[0xD7]=0x{ec['d7']:02X} EC[0xD2]=0x{ec['d2']:02X} EC[0x98]=0x{ec['b98']:02X}")
            return 0
        msg = f"이 동작은 아직 구현되지 않았다: {inst} (계획 단계 3)"
        lib.write_result(inst, False, error=msg, code=2)
        print(msg, file=sys.stderr)
        return 2
    except lib.EcError as e:
        lib.write_result(inst, False, error=f"EC 접근 실패: {e}", code=4)
        print(f"EC 접근 실패: {e}", file=sys.stderr)
        return 4


def main(argv):
    inst = argv[1] if len(argv) == 2 else ""
    if not lib.INSTANCE_RE.match(inst):
        print(f"허용되지 않는 동작 이름: {inst!r}", file=sys.stderr)
        return 2
    run = lib.p_run()
    os.makedirs(run, exist_ok=True)       # 평소에는 tmpfiles 가 만든다. 개발 중 직접 실행해도 동작하게 한다
    with open(os.path.join(run, "lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return dispatch(inst)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
