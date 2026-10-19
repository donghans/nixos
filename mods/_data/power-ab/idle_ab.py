#!/usr/bin/env python3
"""덮개를 닫은 채(화면 꺼짐) 방전 중인 노트북의 '쉬는 상태'에서 한 가지 설정을 켠/끈 구간을 번갈아 재서 비교한다. **root 로 실행**(sudo 인증 캐시가 긴 측정 중 만료되므로 systemd-run 으로 한 번에).

  sudo systemd-run --unit=idle-ab-test --collect <python3> idle_ab.py <powertop 경로> <모드>
  모드 netdata : Netdata 를 켠/끈 구간 비교(끝나면 원래 상태로)
  모드 usb-ts  : ELAN 터치스크린 USB 절전을 on/auto 로 번갈아(끝나면 on). 덮개가 닫혀 터치가 필요 없을 때만 의미가 있음
  모드 bisect  : 덮개 닫힘+방전에서 **한 가지씩 누적해서 끄며**(EDAC → Thunderbolt → 프로세서 열관리 → Wi-Fi 절전 켬 → tailscaled → 컨테이너 pause → Netdata → LPSS/ISH 런타임 PM) 구간마다 패키지 C-state/깨어남/전력을 재서
               패키지가 C2 에서 못 내려가는 원인을 찾는다. 끝에 모두 되돌리고 기준 구간을 한 번 더 재 흔들림을 본다. 터치패드/힌지가 잠깐 안 될 수 있음(LPSS/ISH 단계, 맨 마지막)
  모드 ab2     : bisect 의 후속. 시간이 지나며 쉬는 전력이 저절로 줄어드는 영향(부팅 직후 백그라운드 작업이 잦아듦)을 빼려고 후보마다 **기준-변경-기준-변경(ABAB)** 으로 번갈아 잰다(Wi-Fi 절전, Netdata, LPSS/ISH).
               덮개 닫힘+방전 조건이 되면 2분 더 기다린 뒤 시작. 끝에 모두 원래대로.
  모드 session : **tty2(kmscon)의 Claude 처럼 그래픽 세션에 안 묶인 세션에서만.** 그래픽 세션 켜짐 2구간 → Hyprland 세션 종료(`wayland-wm@hyprland\\x2duwsm.desktop.service` 정지) → 꺼짐 2구간 → Netdata 정지 2구간.
               한 방향(그래픽 세션은 복구하지 않음: 사용자가 다시 로그인/재부팅). Netdata 는 끝에 다시 켠다

덮개가 닫히고 방전 중일 때만 시작한다(최대 1시간 대기). 일회성 실험용 스크립트라 시험은 없다(결과는 posture.md).
구간마다: 배터리 전력(전압×전류), RAPL(패키지/psys) 평균, powertop 의 패키지 C-state 비율과 초당 깨어남, EC GPE 비율을 기록한다.
끝나거나 죽을 때 Netdata 는 반드시 다시 켠다."""
import atexit, json, os, re, signal, statistics, subprocess, sys, time

os.environ["PATH"] = (os.environ.get("IDLE_AB_EXTRA_PATH", "") + ":" if os.environ.get("IDLE_AB_EXTRA_PATH") else "") + "/run/current-system/sw/bin:/run/wrappers/bin:" + os.environ.get("PATH", "")   # systemd-run 서비스의 PATH 는 거의 비어 있음(pgrep/runuser 등이 필요)
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


def window(label, seconds=None, settle=None):
    csv = f"/tmp/idle-ab-{MODE}-{label}.csv"
    seconds = seconds or WINDOW
    time.sleep(SETTLE if settle is None else settle)
    p = subprocess.Popen([PT, f"--time={seconds}", f"--csv={csv}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pk0, ps0, g0, t0 = rapl("intel-rapl:0"), rapl("intel-rapl:1"), gpe(), time.time()
    w = []
    while p.poll() is None and time.time() - t0 < seconds + 25:
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


def stop_graphical():
    """Hyprland(uwsm) 세션을 정상 종료한다. root 에서 사용자 systemd 를 호출."""
    uid = sh("id", "-u", "donghans").stdout.strip() or "1000"
    r = sh("runuser", "-u", "donghans", "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
           "systemctl", "--user", "stop", "wayland-wm@hyprland\\x2duwsm.desktop.service")
    log(f"그래픽 세션 정지 rc={r.returncode} {r.stderr.strip()[:120]}")
    for _ in range(30):
        if sh("pgrep", "Hyprland").returncode != 0:         # (프로세스 이름이 .Hyprland-wrapped 라 -x 로는 안 잡힘)
            break
        time.sleep(1)
    log(f"Hyprland 프로세스: {sh('pgrep', '-c', 'Hyprland').stdout.strip() or 0}")


def run_session():
    log("session 모드 시작: 방전 대기(덮개 상태는 기록만)")
    deadline = time.time() + 3600
    while time.time() < deadline:
        if rd(f"{BAT}/status") == "Discharging":
            break
        time.sleep(5)
    else:
        log("1시간 안에 방전 상태가 안 돼 중단")
        return
    time.sleep(10)
    state["netdata_was_active"] = sh("systemctl", "is-active", "netdata").stdout.strip() == "active"
    log(f"측정 시작 덮개={rd('/proc/acpi/button/lid/LID0/state')} netdata={'실행' if state['netdata_was_active'] else '정지'}")
    results = []

    def run_window(label, phase):
        if rd(f"{BAT}/status") != "Discharging":
            raise RuntimeError("충전 상태가 됨")
        res = dict(window(label), phase=phase, hyprland=sh("pgrep", "-c", "Hyprland").stdout.strip() or "0")
        results.append(res)
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)

    try:
        run_window("gfx-on-1", "gfx-on"); run_window("gfx-on-2", "gfx-on")
        stop_graphical()
        run_window("gfx-off-1", "gfx-off"); run_window("gfx-off-2", "gfx-off")
        sh("systemctl", "stop", "netdata"); log("netdata 정지")
        run_window("gfx-off-nd-off-1", "gfx-off+netdata-off"); run_window("gfx-off-nd-off-2", "gfx-off+netdata-off")
    except Exception as e:                      # 충전 상태 변화 등
        log(f"중단: {e}")
    finally:
        restore()
        os.chmod(OUT, 0o644) if os.path.exists(OUT) else None
        log("완료")


# ───────── bisect 모드: 한 가지씩 누적해서 끄고(되돌릴 수 있게) 구간마다 재기 ─────────
def pci_unbind(drv, addr):
    try:
        open(f"/sys/bus/pci/drivers/{drv}/unbind", "w").write(addr)
        return True
    except OSError as e:
        log(f"  unbind {drv} {addr} 실패: {e}")
        return False


def pci_bind(drv, addr):
    try:
        open(f"/sys/bus/pci/drivers/{drv}/bind", "w").write(addr)
    except OSError as e:
        log(f"  bind {drv} {addr} 실패: {e}")


def as_user(*cmd):
    uid = sh("id", "-u", "donghans").stdout.strip() or "1000"
    return sh("runuser", "-u", "donghans", "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DOCKER_HOST=unix:///run/user/{uid}/docker.sock", *cmd)


def wifi_iface():
    out = sh("iw", "dev").stdout
    m = re.search(r"Interface\s+(\S+)", out)
    return m[1] if m else None


def run_bisect():
    log("bisect 모드 시작: 덮개 닫힘 + 방전 대기")
    deadline = time.time() + 3600
    while time.time() < deadline:
        if "closed" in rd("/proc/acpi/button/lid/LID0/state") and rd(f"{BAT}/status") == "Discharging":
            break
        time.sleep(5)
    else:
        log("조건(덮개 닫힘+방전)이 1시간 안에 안 맞아 중단")
        return
    time.sleep(40)                                           # 덮개를 닫은 직후의 정리(화면 끄기, TLP 전환 등)가 끝나도록
    iface = wifi_iface()
    wifi_orig = (re.search(r"Power save:\s*(\w+)", sh("iw", "dev", iface, "get", "power_save").stdout or "") or [None, "off"])[1] if iface else None
    containers = [c for c in as_user("docker", "ps", "-q").stdout.split() if c]
    nd_active = sh("systemctl", "is-active", "netdata").stdout.strip() == "active"
    ts_active = sh("systemctl", "is-active", "tailscaled").stdout.strip() == "active"
    log(f"측정 시작 wifi={iface}({wifi_orig}) 컨테이너 {len(containers)}개 netdata={nd_active} tailscaled={ts_active}")
    undo = []                                                # 되돌릴 일(역순 실행)
    results = []

    def step(label, desc, do):
        if rd(f"{BAT}/status") != "Discharging" or "closed" not in rd("/proc/acpi/button/lid/LID0/state"):
            raise RuntimeError("조건이 바뀜(충전/덮개 열림)")
        log(f"단계 {label}: {desc}")
        do()
        res = dict(window(label, seconds=45, settle=12), step=label, desc=desc)
        results.append(res)
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)

    def revert_all():
        for f in reversed(undo):
            try:
                f()
            except Exception as e:
                log(f"  되돌리기 오류: {e}")
        undo.clear()

    def edac():
        if pci_unbind("igen6_edac", "0000:00:00.0"):
            undo.append(lambda: pci_bind("igen6_edac", "0000:00:00.0"))

    def tb():
        if pci_unbind("thunderbolt", "0000:00:0d.2"):
            undo.append(lambda: pci_bind("thunderbolt", "0000:00:0d.2"))

    def thermal():
        if pci_unbind("proc_thermal_pci", "0000:00:04.0"):
            undo.append(lambda: pci_bind("proc_thermal_pci", "0000:00:04.0"))

    def wifi():
        if iface:
            sh("iw", "dev", iface, "set", "power_save", "on")
            undo.append(lambda: sh("iw", "dev", iface, "set", "power_save", wifi_orig or "off"))

    def tailscale():
        if ts_active:
            sh("systemctl", "stop", "tailscaled")
            undo.append(lambda: sh("systemctl", "start", "tailscaled"))

    def docker_pause():
        if containers:
            as_user("docker", "pause", *containers)
            undo.append(lambda: as_user("docker", "unpause", *containers))

    def netdata():
        if nd_active:
            sh("systemctl", "stop", "netdata")
            undo.append(lambda: sh("systemctl", "start", "netdata"))

    def lpss_ish():
        for dev in ("0000:00:15.0", "0000:00:12.0"):
            path = f"/sys/bus/pci/devices/{dev}/power/control"
            old = rd(path)
            try:
                open(path, "w").write("auto")
                undo.append(lambda path=path, old=old: open(path, "w").write(old or "on"))
            except OSError as e:
                log(f"  {dev} control=auto 실패: {e}")

    try:
        step("s0-base", "기준(아무것도 안 끔)", lambda: None)
        step("s1-edac", "+ igen6_edac(메모리 EDAC) 해제", edac)
        step("s2-thunderbolt", "+ Thunderbolt NHI(00:0d.2) 해제", tb)
        step("s3-thermal", "+ proc_thermal_pci(00:04.0) 해제", thermal)
        step("s4-wifi", "+ Wi-Fi 절전 켬", wifi)
        step("s5-tailscale", "+ tailscaled 정지", tailscale)
        step("s6-docker", "+ 컨테이너 pause", docker_pause)
        step("s7-netdata", "+ Netdata 정지", netdata)
        step("s8-lpss-ish", "+ LPSS(00:15.0)/ISH(00:12.0) 런타임 PM auto(터치패드/힌지 영향 가능)", lpss_ish)
        revert_all()
        time.sleep(5)
        res = dict(window("s9-reverted", seconds=45, settle=12), step="s9-reverted", desc="모두 되돌린 뒤 기준(흔들림 확인)")
        results.append(res)
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
    except Exception as e:
        log(f"중단: {e}")
    finally:
        revert_all()
        sh("systemctl", "restart", "posture-daemon.service")   # ISH 를 건드렸다면 힌지 센서 설정을 다시 잡게
        log("모두 되돌림, posture-daemon 재시작")
        if os.path.exists(OUT):
            os.chmod(OUT, 0o644)
        log("완료")


def run_ab2():
    log("ab2 모드 시작: 덮개 닫힘 + 방전 대기")
    deadline = time.time() + 3600
    while time.time() < deadline:
        if "closed" in rd("/proc/acpi/button/lid/LID0/state") and rd(f"{BAT}/status") == "Discharging":
            break
        time.sleep(5)
    else:
        log("조건이 1시간 안에 안 맞아 중단")
        return
    time.sleep(int(os.environ.get("IDLE_AB_SETTLE", "120")))
    iface = wifi_iface()
    wifi_orig = (re.search(r"Power save:\s*(\w+)", sh("iw", "dev", iface, "get", "power_save").stdout or "") or [None, "off"])[1] if iface else None
    nd_active = sh("systemctl", "is-active", "netdata").stdout.strip() == "active"
    log(f"측정 시작 wifi={iface}({wifi_orig}) netdata={nd_active}")
    results = []
    ctl = {d: f"/sys/bus/pci/devices/{d}/power/control" for d in ("0000:00:15.0", "0000:00:12.0")}
    orig_ctl = {d: rd(p) or "on" for d, p in ctl.items()}

    def wifi_set(on):
        if iface:
            sh("iw", "dev", iface, "set", "power_save", "on" if on else (wifi_orig or "off"))

    def nd_set(on):
        if nd_active:
            sh("systemctl", "stop" if on else "start", "netdata")

    def ish_set(on):
        for d, p in ctl.items():
            try:
                open(p, "w").write("auto" if on else orig_ctl[d])
            except OSError as e:
                log(f"  {d} 실패: {e}")

    def win(label, cand, state):
        if rd(f"{BAT}/status") != "Discharging" or "closed" not in rd("/proc/acpi/button/lid/LID0/state"):
            raise RuntimeError("조건이 바뀜(충전/덮개 열림)")
        res = dict(window(label, seconds=45, settle=15), step=label, cand=cand, state=state, bl=rd("/sys/class/backlight/intel_backlight/brightness"))
        results.append(res)
        log(f"  {label}: batt={res.get('battery_w') and round(res['battery_w'], 2)} psys={res.get('psys_w') and round(res['psys_w'], 2)} pkg={res.get('pkg_w') and round(res['pkg_w'], 2)}")
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)

    try:
        only = [c for c in os.environ.get("IDLE_AB_CANDS", "").split(",") if c]   # 일부 후보만(예: netdata-off)
        for cand, setter in (("wifi-ps", wifi_set), ("netdata-off", nd_set), ("lpss-ish-auto", ish_set)):
            if only and cand not in only:
                continue
            log(f"후보 {cand}: A(기준) B(변경) A B")
            for i, state in enumerate(("A", "B", "A", "B")):
                setter(state == "B")
                win(f"{cand}-{i + 1}{state}", cand, state)
            setter(False)
    except Exception as e:
        log(f"중단: {e}")
    finally:
        wifi_set(False); nd_set(False); ish_set(False)
        sh("systemctl", "restart", "posture-daemon.service")
        log("모두 원래대로, posture-daemon 재시작")
        if os.path.exists(OUT):
            os.chmod(OUT, 0o644)
        log("완료")


def main():
    if MODE == "ab2":
        return run_ab2()
    if MODE == "bisect":
        return run_bisect()
    if MODE == "session":
        return run_session()
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
