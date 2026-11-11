#!/usr/bin/env python3
"""embedhelper — embedctl 의 root helper. systemd 템플릿 유닛 `embedctl-root@<동작>.service` 가 root 로 실행한다(`ExecStart=… embedhelper.py %i`).

인스턴스 이름이 곧 동작이다: charge-<N> · mode-<turbo|comfort|eco> · boost-<on|off>. 이름은 `embedlib.INSTANCE_RE` 로 엄격히 검증하며
검증을 통과하지 못한 이름은 아무것도 하지 않고 종료 코드 2 로 끝난다(결과 파일도 만들지 않는다 — 파일 이름에 쓰이므로).
읽기는 일반 사용자가 sysfs 로 직접 하므로 helper 에 `status` 동작은 없다(2026-11-12, lockdown 아래 sysfs 전환; plan/embedctl-lockdown 결정 6).
sysfs 접근 전체를 `/run/embedctl/lock` 의 flock 으로 직렬화하고, 결과는 `/run/embedctl/last-<인스턴스>.json` 에 남긴다(사용자 CLI 가 읽는다).
종료 코드: 0 성공 · 2 입력 오류 · 3 게이트 거부 · 4 sysfs 접근 실패 · 5 되읽기 불일치.

쓰기 동작은 `embedlib.apply_action` 이 한다: 게이트(기종 + 방금 읽은 msi-ec 펌웨어가 검증 목록에 있어야 함) → 쓰기 → 되읽기 확인.
어긋나면 모드·Cooler Boost 는 이전 값으로 되돌리려 시도하고 종료 코드 5 로 before/after 를 결과 파일에 남긴다.
"""
import fcntl
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import embedlib as lib   # noqa: E402


def _fmt(raw):
    return f"end={raw['end']} mode={raw['mode']!r} boost={raw['boost']!r}"


def fail(inst, code, msg, before=None, after=None):
    lib.write_result(inst, False, error=msg, code=code, before=before, after=after)
    print(msg, file=sys.stderr)
    return code


def dispatch(inst):
    try:
        before, after = lib.apply_action(inst)             # 게이트 → 쓰기 → 되읽기 확인(어긋나면 MismatchError)
        lib.write_result(inst, True, before=before, after=after, data={"action": inst})
        print(f"embedctl-root {inst}: {_fmt(before)} -> {_fmt(after)}")
        return 0
    except lib.InputError as e:
        return fail(inst, 2, str(e))
    except lib.GateError as e:
        return fail(inst, 3, str(e))
    except lib.MismatchError as e:
        return fail(inst, 5, str(e), e.before, e.after)
    except lib.EcError as e:
        return fail(inst, 4, f"sysfs 접근 실패: {e}")


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
