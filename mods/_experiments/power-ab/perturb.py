#!/usr/bin/env python3
"""perturb — **낮은 전력 상태에서** 되돌릴 수 있는 조작을 차례로 가하며 시각을 /tmp/perturb.log 에 남긴다.
전력은 boot_settle.py 의 /tmp/boot-settle.jsonl(30초 간격)이 따로 기록하므로, 조작 시각 뒤에 전력이 오르는지(상태 전환)를 거기서 읽는다. **root 로 실행**.
  sudo systemd-run --unit=perturb --collect --setenv=PATH=<iw>:/run/current-system/sw/bin <python3> perturb.py <hyprlock 경로> [관찰 초=90]
조작: load(CPU 4코어 20초) → netdata 재시작 → wifi 절전 끔(→복구) → vt tty1(→tty2) → hyprlock 잠금(→해제) → audio PCI on(→auto)."""
import os, pwd, signal, subprocess, sys, time

HYPRLOCK = sys.argv[1]
WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 90
LOG = "/tmp/perturb.log"


def log(m):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {m}\n")


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


def rd(p):
    try:
        return open(p).read().strip()
    except OSError:
        return ""


def lock_pids():
    return [int(x) for x in sh("pgrep", "-x", "hyprlock").stdout.split()]


def act_load():
    ps = [subprocess.Popen([sys.executable, "-c", "import time;t=time.time()\nwhile time.time()-t<20: pass"]) for _ in range(4)]
    [p.wait() for p in ps]


def act_netdata():
    sh("systemctl", "restart", "netdata")


def act_wifi(on):
    sh("iw", "dev", "wlan0", "set", "power_save", "on" if on else "off")


def act_vt(n):
    sh("chvt", str(n))


def act_lock(want):
    if want and not lock_pids():
        user = pwd.getpwuid(1000).pw_name
        sig = sh("ls", "/run/user/1000/hypr").stdout.split()[0]
        subprocess.Popen(["runuser", "-u", user, "--", "env", "XDG_RUNTIME_DIR=/run/user/1000", "WAYLAND_DISPLAY=wayland-1",
                          f"HYPRLAND_INSTANCE_SIGNATURE={sig}", HYPRLOCK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(8)
    elif not want:
        for _ in range(10):
            for p in lock_pids():
                os.kill(p, signal.SIGUSR1)
            if not lock_pids():
                break
            time.sleep(2)


def act_audio(on):
    open("/sys/bus/pci/devices/0000:00:1f.3/power/control", "w").write("on" if on else "auto")


STEPS = [("load 20s", act_load, None), ("netdata 재시작", act_netdata, None),
         ("wifi 절전 끔", lambda: act_wifi(False), lambda: act_wifi(True)),
         ("VT tty1", lambda: act_vt(1), lambda: act_vt(2)),
         ("hyprlock 잠금", lambda: act_lock(True), lambda: act_lock(False)),
         ("audio PCI on", lambda: act_audio(True), lambda: act_audio(False))]


def main():
    log(f"시작: 관찰 {WAIT}s, 조작 {len(STEPS)}개, 활성VT {rd('/sys/class/tty/tty0/active')}")
    time.sleep(WAIT)
    log("기준 관찰 끝(조작 없음)")
    try:
        for name, do, undo in STEPS:
            log(f"조작 시작: {name}")
            do()
            log(f"조작 적용됨: {name}")
            time.sleep(WAIT)
            if undo:
                undo()
                log(f"되돌림: {name}")
                time.sleep(WAIT)
    finally:
        for _, _, undo in STEPS:
            pass
        act_wifi(True), act_vt(2), act_lock(False), act_audio(False)
        log("완료(복구: wifi 절전 on, VT tty2, hyprlock 해제, audio auto)")


if __name__ == "__main__":
    main()
