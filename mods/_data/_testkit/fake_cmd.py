#!/usr/bin/env python3
"""데이터 기반 가짜 실행 파일. `Sandbox`(fakes.py)가 이 파일을 hyprctl/systemctl/pkill/posture/journalctl 이라는 이름의 심볼릭 링크로 깔아 둔다.
어떤 명령인지는 실행된 이름(argv[0] 의 basename)으로 정하고, 응답과 상태는 모두 FAKE_DIR 아래 파일로 정한다:

  hyprctl     -i <서명> …            FAKE_DIR/hypr/<서명> 디렉터리가 있으면 성공(없으면 1)
              dispatch <코드>        calls.log 에 기록
              eval <코드>            evals.log 에 기록, `ok` 출력
              layers -j              FAKE_DIR/visible 이 있으면 wvkbd 레이어 한 개(layer_geometry.json 또는 0,1240,2560x360), 없으면 빈 모니터
              <그 밖의 이름> -j       FAKE_DIR/<이름>.json 을 그대로 출력(없으면 [])
  systemctl   show-environment       FAKE_DIR/environment.txt 를 출력
              show …                 MainPID 로 FAKE_DIR/mainpid(없으면 4242) 출력
              is-active <유닛>        FAKE_DIR/rc.json 의 {"is-active": 코드} 가 있으면 그 코드, FAKE_DIR/active_units.txt 가 있으면 목록에 없는 유닛은 3, 아니면 0
              restart                restarts.log 에 기록, effects.json 의 "restart" 효과 적용(기본: visible 제거)
              kill --signal=SIG      signals.log 에 기록, effects.json[SIG] 효과 적용(기본: SIGUSR2 → visible 만듦, SIGUSR1 → visible 제거)
              start/stop             starts.log / stops.log 에 기록
  pkill       …                      pkill.log 에 인자 기록
  posture     …                      FAKE_DIR/mode 의 내용을 그대로 출력(없으면 종료 코드 1)
  journalctl  …                      FAKE_DIR/journal.txt 를 그대로 출력
효과(effects) 형식: {"SIGUSR2": {"touch": "visible"}, "SIGUSR1": {"remove": "visible"}, "restart": {"remove": "visible"}}
"""
import json, os, sys

D = os.environ["FAKE_DIR"]
NAME = os.path.basename(sys.argv[0])
A = sys.argv[1:]


def p(*x):
    return os.path.join(D, *x)


def log(name, text):
    with open(p(name + ".log"), "a") as f:
        f.write(text + "\n")


def jload(name, default=None):
    try:
        return json.load(open(p(name)))
    except (OSError, ValueError):
        return default


def effect(key, defaults):
    eff = (jload("effects.json", {}) or {}).get(key, defaults.get(key))
    for kind, f in (eff or {}).items():
        if kind == "touch":
            open(p(f), "w").close()
        elif kind == "remove" and os.path.exists(p(f)):
            os.remove(p(f))


def hyprctl():
    a = list(A)
    if a[:1] == ["-i"]:
        if not os.path.isdir(p("hypr", a[1])):
            sys.exit(1)
        a = a[2:]
        if a[:1] == ["version"]:
            print("Hyprland fake"); return
    if not a:
        return
    cmd = a[0]
    if cmd == "dispatch":
        log("calls", a[1]); return
    if cmd == "eval":
        log("evals", a[1]); print("ok"); return
    if cmd == "layers":
        geo = jload("layer_geometry.json", {"x": 0, "y": 1240, "w": 2560, "h": 360})
        items = [dict(namespace="wvkbd", **geo)] if os.path.exists(p("visible")) else []
        print(json.dumps({"eDP-1": {"levels": {"3": items}}})); return
    try:
        print(open(p(cmd + ".json")).read())
    except OSError:
        print("[]")


def systemctl():
    a = list(A)
    if "show-environment" in a:
        try:
            print(open(p("environment.txt")).read(), end="")
        except OSError:
            pass
        return
    if "show" in a:
        try:
            print(open(p("mainpid")).read().strip())
        except OSError:
            print("4242")
        return
    if "is-active" in a:
        rc = (jload("rc.json", {}) or {}).get("is-active")
        if rc is not None:
            sys.exit(rc)
        units = [x for x in a if not x.startswith("-") and x not in ("is-active", "--user")]
        try:
            active = open(p("active_units.txt")).read().split()
            sys.exit(0 if any(u in active for u in units) else 3)
        except OSError:
            sys.exit(0)
    if "restart" in a:
        log("restarts", "restart"); effect("restart", {"restart": {"remove": "visible"}}); return
    if "kill" in a:
        sig = next(x for x in a if x.startswith("--signal=")).split("=", 1)[1]
        log("signals", sig); effect(sig, {"SIGUSR2": {"touch": "visible"}, "SIGUSR1": {"remove": "visible"}}); return
    if "start" in a:
        log("starts", " ".join(x for x in a if not x.startswith("-") and x != "start")); return
    if "stop" in a:
        log("stops", " ".join(x for x in a if not x.startswith("-") and x != "stop")); return


def main():
    if NAME == "hyprctl":
        hyprctl()
    elif NAME == "systemctl":
        systemctl()
    elif NAME == "pkill":
        log("pkill", " ".join(A))
    elif NAME == "posture":
        try:
            print(open(p("mode")).read().strip())
        except OSError:
            sys.exit(1)
    elif NAME == "journalctl":
        try:
            print(open(p("journal.txt")).read(), end="")
        except OSError:
            pass
    else:
        log("unknown", NAME + " " + " ".join(A))


main()
