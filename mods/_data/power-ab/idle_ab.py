#!/usr/bin/env python3
"""덮개를 닫은 채(화면 꺼짐) 방전 중인 노트북의 '쉬는 상태'에서 한 가지 설정을 켠/끈 구간을 번갈아 재서 비교한다. **root 로 실행**(sudo 인증 캐시가 긴 측정 중 만료되므로 systemd-run 으로 한 번에).

  sudo systemd-run --unit=idle-ab-test --collect <python3> idle_ab.py <powertop 경로> <모드>
  모드 netdata : Netdata 를 켠/끈 구간 비교(끝나면 원래 상태로)
  모드 usb-ts  : ELAN 터치스크린 USB 절전을 on/auto 로 번갈아(끝나면 on). 덮개가 닫혀 터치가 필요 없을 때만 의미가 있음

덮개가 닫히고 방전 중일 때만 시작한다(최대 1시간 대기). 일회성 실험용 스크립트라 시험은 없다(결과는 posture.md).
구간마다: 배터리 전력(전압×전류), RAPL(패키지/psys) 평균, powertop 의 패키지 C-state 비율과 초당 깨어남, EC GPE 비율을 기록한다.
끝나거나 죽을 때 Netdata 는 반드시 다시 켠다."""
import atexit, json, os, re, signal, statistics, subprocess, sys, time

PT = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 else "netdata"
LOG, OUT = f"/tmp/idle-ab-{MODE}.log", f"/tmp/idle-ab-{MODE}.json"
TS = "/sys/bus/usb/devices/3-8"          # ELAN 터치스크린(04f3:2ffa) — usb-ts 모드
BAT = "/sys/class/power_supply/BAT1"
WINDOW, SETTLE, ROUNDS = 90, 20, 2
state = {"netdata_was_active": None, "restored": False}


def ts_control(v):
    try:
        open(f"{TS}/power/control", "w").write(v)
    except OSError as e:
        log(f"터치스크린 control={v} 실패: {e}")


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def rd(p, d=""):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return d


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


def restore():
    if state["restored"]:
        return
    state["restored"] = True
    if MODE == "usb-ts":
        ts_control("on")                                   # 터치스크린 USB 절전은 원래대로(켜 둠=절전 안 함)
        time.sleep(3)
        log(f"복구: 터치스크린 control={rd(TS + '/power/control')} status={rd(TS + '/power/runtime_status')}")
    elif state["netdata_was_active"]:
        sh("systemctl", "start", "netdata")
        log("netdata 복구(start)")


def on_signal(sig, _):
    log(f"신호 {sig} 로 중단")
    restore()
    sys.exit(1)


atexit.register(restore)
for s in (signal.SIGTERM, signal.SIGINT):
    signal.signal(s, on_signal)


def watts():
    v, i = rd(f"{BAT}/voltage_now"), rd(f"{BAT}/current_now")
    return int(v) * abs(int(i)) / 1e12 if v and i else None


def rapl(name_dir):
    e = rd(f"/sys/class/powercap/{name_dir}/energy_uj")
    m = rd(f"/sys/class/powercap/{name_dir}/max_energy_range_uj")
    return (int(e), int(m)) if e and m else None


def rapl_w(a, b, sec):
    if not a or not b:
        return None
    d = b[0] - a[0]
    return (d + (a[1] if d < 0 else 0)) / 1e6 / sec


def gpe():
    return int(rd("/sys/firmware/acpi/interrupts/gpe6E", "0").split()[0] or 0)


def parse_powertop(path):
    t = open(path, errors="replace").read()
    out = {}
    m = re.search(r"System:\s*([\d.]+) wakeup/s;CPU:\s*([\d.]+)% usage", t)
    if m:
        out["wakeups"], out["cpu_usage"] = float(m[1]), float(m[2])
    sect = t.split("Package;0", 1)[1].split(";Core", 1)[0] if "Package;0" in t else ""
    for k, v in re.findall(r"\(pc(\d+)\);\s*([\d.]+)%", sect):
        out[f"pc{k}"] = float(v)
    return out


def window(label):
    csv = f"/tmp/idle-ab-{MODE}-{label}.csv"
    time.sleep(SETTLE)
    p = subprocess.Popen([PT, f"--time={WINDOW}", f"--csv={csv}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pk0, ps0, g0, t0 = rapl("intel-rapl:0"), rapl("intel-rapl:1"), gpe(), time.time()
    w = []
    while p.poll() is None and time.time() - t0 < WINDOW + 25:
        time.sleep(2)
        x = watts()
        if x is not None and rd(f"{BAT}/status") == "Discharging":
            w.append(x)
    p.wait(timeout=30)
    dt = time.time() - t0
    res = {"label": label, "battery_w": statistics.median(w) if w else None, "n": len(w), "pkg_w": rapl_w(pk0, rapl("intel-rapl:0"), dt),
           "psys_w": rapl_w(ps0, rapl("intel-rapl:1"), dt), "gpe_per_s": (gpe() - g0) / dt, "seconds": round(dt)}
    res.update(parse_powertop(csv))
    log(f"창 {label}: {json.dumps(res, ensure_ascii=False)}")
    return res


def main():
    log("시작: 덮개 닫힘 + 방전 대기")
    deadline = time.time() + 3600
    while time.time() < deadline:
        if "closed" in rd("/proc/acpi/button/lid/LID0/state") and rd(f"{BAT}/status") == "Discharging":
            break
        time.sleep(5)
    else:
        log("조건(덮개 닫힘+방전)이 1시간 안에 안 맞아 중단")
        return
    time.sleep(30)                                         # 덮개를 닫은 직후의 정리 작업(화면 끄기, TLP 전환 등)이 끝나도록
    state["netdata_was_active"] = sh("systemctl", "is-active", "netdata").stdout.strip() == "active"
    log(f"측정 시작(netdata 원래 상태: {'실행' if state['netdata_was_active'] else '정지'})")
    results = []
    for r in range(ROUNDS):
        for mode in ("run", "stop"):
            if rd("/proc/acpi/button/lid/LID0/state").find("closed") < 0 or rd(f"{BAT}/status") != "Discharging":
                log("조건이 바뀌어(덮개 열림/충전) 중단")
                restore()
                json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
                return
            if MODE == "usb-ts":
                ts_control("on" if mode == "run" else "auto")
            else:
                sh("systemctl", "start" if mode == "run" else "stop", "netdata")
            res = dict(window(f"{mode}{r + 1}"), mode=mode, round=r + 1)
            if MODE == "usb-ts":
                res.update(ts_status=rd(TS + "/power/runtime_status"), xhci_status=rd("/sys/bus/pci/devices/0000:00:14.0/power/runtime_status"))
            results.append(res)
    restore()
    json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
    os.chmod(OUT, 0o644)
    log("완료")


if __name__ == "__main__":
    main()
