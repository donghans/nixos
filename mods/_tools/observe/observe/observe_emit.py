#!/usr/bin/env python3
"""observe-emit — 셸 스크립트에서 구조화 이벤트와 구간(스팬)을 남긴다.

  observe-emit <컴포넌트> <수준> <이벤트> [키=값 ...]            이벤트 한 건   예) observe-emit lid-policy info lid lid=closed action=screen-off
  observe-emit span-run <컴포넌트> <이름> [키=값 ...] -- 명령 ...   명령을 실행하며 구간으로 기록(종료 코드를 그대로 돌려줌). 명령 인자는 기록하지 않고 실행 파일 이름만 남긴다.
                                                                    자식 프로세스는 OBSERVE_TRACE 로 이 구간을 부모로 이어받아 안쪽 구간이 트리로 붙는다.
  observe-emit span-begin <컴포넌트> <이름> [키=값 ...]            시작을 기록하고 토큰을 출력   tok=$(observe-emit span-begin nixup build)
  observe-emit span-end <토큰> [status=ok|fail] [키=값 ...]         끝을 기록
  observe-emit span-probe                                          (기능 확인: span-* 를 아는 버전이면 0)

값은 숫자면 숫자로, 아니면 문자열로 기록. 개인정보(입력한 글자·URL·명령 인자)는 넘기지 말 것.
조회: observectl trace"""
import os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from observe_events import Events, current, new_id

LEVELS = ("trace", "debug", "info", "warn", "error")


def parse_kv(items):
    kv = {}
    for x in items:
        k, _, v = x.partition("=")
        try:
            kv[k] = int(v)
        except ValueError:
            try:
                kv[k] = float(v)
            except ValueError:
                kv[k] = v
    return kv


def span_run(comp, name, kv, argv):
    """명령을 자식으로 실행하며 구간을 기록한다. 신호는 명령이 스스로 처리하게 둔다 — Ctrl-C 는 터미널이 같은 프로세스 그룹의 자식에게도 보내므로
    여기서는 무시하고 자식이 정리(trap/cleanup)를 마치고 끝나길 기다리며, SIGTERM/SIGHUP 은 자식에게 전달한다(자식을 강제로 죽이지 않는다)."""
    import signal
    tok = span_begin(comp, name, {"cmd": os.path.basename(argv[0]), **kv})
    trace, sid = tok.split("|")[:2]
    try:
        child = subprocess.Popen(argv, env={**os.environ, "OBSERVE_TRACE": f"{trace}:{sid}"})
    except FileNotFoundError:
        span_end(tok, {"status": "fail", "exit": 127})
        return 127
    old = {signal.SIGINT: signal.signal(signal.SIGINT, signal.SIG_IGN)}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        old[sig] = signal.signal(sig, lambda n, _f: child.send_signal(n))
    try:
        rc = child.wait()
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)
    rc = 128 - rc if rc < 0 else rc                                          # 신호로 끝났으면 셸 관례(128+신호 번호)
    span_end(tok, {"status": "ok" if rc == 0 else "fail", "exit": rc})       # 비정상 종료는 fail 로 남기고 종료 코드는 그대로 돌려준다
    return rc


def span_begin(comp, name, kv):
    parent = current()
    trace, parent_id = (parent[0], parent[1]) if parent else (new_id(), "")
    sid = new_id()
    t0 = time.time()
    Events(comp).emit("info", name + ".begin", span=sid, trace=trace, parent=parent_id or None, **kv)
    return "|".join([trace, sid, parent_id, repr(t0), comp, name])


def span_end(token, kv):
    trace, sid, parent_id, t0, comp, name = token.split("|", 5)
    status = kv.pop("status", "ok")
    ms = round((time.time() - float(t0)) * 1000, 1)
    Events(comp).emit("info" if status == "ok" else "error", name + (".end" if status == "ok" else ".fail"), span=sid, trace=trace, parent=parent_id or None, ms=ms, **kv)


def main(argv):
    if argv == ["span-probe"]:                       # 기능 확인용: 이 버전이 span-* 를 아는지(옛 버전은 사용법을 내고 1 로 끝남). 아무것도 기록하지 않는다.
        return 0
    if len(argv) >= 4 and argv[0] == "span-run" and "--" in argv:
        i = argv.index("--")
        if i < 3 or i + 1 >= len(argv):
            sys.exit(__doc__)
        return span_run(argv[1], argv[2], parse_kv(argv[3:i]), argv[i + 1:])
    if len(argv) >= 3 and argv[0] == "span-begin":
        print(span_begin(argv[1], argv[2], parse_kv(argv[3:])))
        return 0
    if len(argv) >= 2 and argv[0] == "span-end":
        span_end(argv[1], parse_kv(argv[2:]))
        return 0
    if len(argv) < 3 or argv[1] not in LEVELS:
        sys.exit(__doc__)
    Events(argv[0]).emit(argv[1], argv[2], **parse_kv(argv[3:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
