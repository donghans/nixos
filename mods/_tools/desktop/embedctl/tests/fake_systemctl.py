#!/usr/bin/env python3
"""시험용 가짜 systemctl — `start [--no-ask-password] embedctl-root@<동작>.service` 만 흉내 낸다.
환경변수: EMBEDCTL_RUN(결과 디렉터리) · FAKE_RESULT(결과 JSON 의 필드 파일) · FAKE_RC(종료 코드, 기본 0) · FAKE_SKEW(결과 time 에 더할 초, 기본 0; 음수면 오래된 결과)
· FAKE_NO_RESULT=1(성공하지만 결과 파일을 만들지 않음) · FAKE_LOG(호출 인자를 한 줄씩 덧붙일 파일)."""
import json, os, sys, time

args = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(" ".join(args) + "\n")
unit = next((x for x in args if x.startswith("embedctl-root@")), None)
rc = int(os.environ.get("FAKE_RC", "0"))
if rc and os.environ.get("FAKE_RESULT_ON_FAIL") and unit:      # helper 가 실패 이유를 결과 파일에 남기고 비정상 종료하는 경우
    inst = unit[len("embedctl-root@"):-len(".service")]
    res = json.load(open(os.environ["FAKE_RESULT"]))
    res.update(instance=inst, time=time.time())
    os.makedirs(os.environ["EMBEDCTL_RUN"], exist_ok=True)
    json.dump(res, open(os.path.join(os.environ["EMBEDCTL_RUN"], "last-%s.json" % inst), "w"))
if rc:
    print("Failed to start %s: Interactive authentication required." % unit, file=sys.stderr)
    sys.exit(rc)
if unit and not os.environ.get("FAKE_NO_RESULT"):
    inst = unit[len("embedctl-root@"):-len(".service")]
    res = json.load(open(os.environ["FAKE_RESULT"]))
    res.update(instance=inst, time=time.time() + float(os.environ.get("FAKE_SKEW", "0")))
    run = os.environ["EMBEDCTL_RUN"]
    os.makedirs(run, exist_ok=True)
    json.dump(res, open(os.path.join(run, "last-%s.json" % inst), "w"))
sys.exit(0)
