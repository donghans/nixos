#!/usr/bin/env python3
"""power-ab — 배터리로 방전 중일 때 설정(화면 주사율)별 소비 전력을 번갈아 재서 비교한다.

  power-ab [--seconds 90] [--settle 15] [--rounds 2] [--scenarios 165,60,48] [--mouse] [--containers]

- **전원 어댑터를 뽑은 상태(방전 중)에서만** 잴 수 있다(어댑터가 연결돼 있으면 배터리 전류가 0 이라 잴 게 없다).
- 소비 전력 = 배터리 전압 × 전류(sysfs). 시나리오를 번갈아(165 → 60 → 48 → 165 → …) 여러 바퀴 재서 배터리 온도/잔량에 따른 느린 변화가 한 설정에 몰리지 않게 한다.
- 재는 동안 CPU 가 바쁘면(평균 사용률 10% 초과) 결과에 표시한다 — 그 값은 화면 설정 차이가 아니라 작업 때문일 수 있다.
- `--containers`: 시나리오를 `c-run`(전부 실행) → `c-genple`(genple 컨테이너만 일시정지) → `c-all`(전부 일시정지) 로. `docker pause`(프로세스를 얼려 둠, 상태 유지)를 쓰고 끝나거나 중단되면 **반드시 unpause** 한다. 화면 설정은 그대로 둔다.
- 배터리 전압×전류와 **함께 Netdata 에 기록된 RAPL 전력(CPU 패키지, 플랫폼 전체 psys)** 을 같은 구간 평균으로 기록해 교차 확인한다(sudo 불필요: 처음에는 `sudo -n` 으로 energy_uj 를 읽으려 했으나 비밀번호가 필요한 sudo 라 긴 측정 중 인증 캐시가 만료돼 실패했다). psys 가 배터리 소비와 비슷하면 측정을 믿을 수 있다.
- `--mouse`: 재는 동안 포인터를 화면 가운데 원 둘레로 부드럽게(60회/초) 움직여 화면이 계속 바뀌는 상태로 잰다(정지 화면과 비교용). 끝나면 포인터를 원래 자리로 돌린다. 클릭/키 입력은 하지 않는다.
- 끝나면(중간에 Ctrl+C 해도) `displayctl restore` 로 저장된 화면 설정으로 되돌린다. 밝기는 건드리지 않는다.
- 시나리오: 주사율(Hz) 숫자. `165`/`60` 은 표준 모드, 그 외(`48` 등)는 같은 해상도의 사용자 지정 주사율. 전환은 런타임만(저장 안 함)이고 끝나면 저장된 구성으로 복원한다.
"""
import argparse
import json
import math
import os
import socket
import statistics
import subprocess
import sys
import threading
import time

SYSFS = os.environ.get("POWER_AB_SYSFS", "/sys/class/power_supply")
PROC_STAT = os.environ.get("POWER_AB_PROC_STAT", "/proc/stat")
NOMINAL_V = 15.2          # 이 배터리의 설계 전압(voltage_min_design)로 Wh 를 환산


def read(path: str, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def battery(root: str = SYSFS):
    """첫 배터리(BAT*) 디렉터리."""
    for name in sorted(os.listdir(root)):
        if name.startswith("BAT"):
            return os.path.join(root, name)
    return None


def watts(bat: str):
    """(와트, 상태). 전압(µV) × 전류(µA)."""
    v, i = read(f"{bat}/voltage_now"), read(f"{bat}/current_now")
    status = read(f"{bat}/status", "?")
    if v is None or i is None:
        return None, status
    return int(v) * abs(int(i)) / 1e12, status


def cpu_times(path: str = PROC_STAT):
    parts = read(path, "cpu 0 0 0 0").splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def cpu_busy(a, b) -> float:
    total, idle = b[0] - a[0], b[1] - a[1]
    return 0.0 if total <= 0 else 100.0 * (total - idle) / total


def summarize(samples: list) -> dict:
    w = [s["w"] for s in samples]
    return {"n": len(w), "median": statistics.median(w), "mean": statistics.fmean(w), "min": min(w), "max": max(w),
            "cpu": statistics.fmean(s["cpu"] for s in samples)}


def with_rapl(summary: dict, power: dict) -> dict:
    return dict(summary, pkg=power.get("pkg"), psys=power.get("psys"))


def battery_wh(bat: str) -> float:
    full = read(f"{bat}/charge_full")
    return int(full) / 1e6 * NOMINAL_V if full else 0.0


def hours(wh: float, w: float) -> float:
    return wh / w if w > 0 else 0.0


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def render(results: dict, wh: float) -> str:
    """results: {시나리오: [summarize 결과 (바퀴마다)]}. 결과에 pkg/psys(Netdata RAPL)가 있으면 열을 추가한다."""
    has = any(r.get("pkg") is not None or r.get("psys") is not None for runs in results.values() for r in runs)
    rows, base = [], None
    for name, runs in results.items():
        med = statistics.fmean(r["median"] for r in runs)
        cpu = statistics.fmean(r["cpu"] for r in runs)
        cur = {"med": med, "pkg": _mean(r.get("pkg") for r in runs), "psys": _mean(r.get("psys") for r in runs)}
        base = base or cur
        spread = max(r["median"] for r in runs) - min(r["median"] for r in runs)
        rows.append((name, cur, base, spread, cpu))

    def fmt(v):
        return "-" if v is None else f"{v:.2f}"

    def diff(a, b):
        return "-" if a is None or b is None else f"{a - b:+.2f}"

    head = f"{'설정':<10} {'소비전력':>9} {'기준 대비':>9} {'바퀴 간 차이':>12} {'CPU':>6} {'예상 사용시간':>13}"
    out = [head + (f" | {'psys(플랫폼)':>12} {'기준 대비':>9} | {'CPU 패키지':>10} {'기준 대비':>9}" if has else "")]
    for name, c, b, spread, cpu in rows:
        line = f"{name:<10} {c['med']:>7.2f} W {c['med'] - b['med']:>+7.2f} W {spread:>10.2f} W {cpu:>5.1f}% {hours(wh, c['med']):>9.1f} 시간"
        if has:
            line += f" | {fmt(c['psys']):>10} W {diff(c['psys'], b['psys']):>7} W | {fmt(c['pkg']):>8} W {diff(c['pkg'], b['pkg']):>7} W"
        out.append(line + ("  (CPU 바쁨: 작업 영향 가능)" if cpu > 10 and not has else ""))
    out.append(f"\n예상 사용시간은 지금 배터리 용량({wh:.1f} Wh = 만충 {battery_note(wh)})을 그 전력으로 쓴다고 가정한 값이다.")
    out.append("'바퀴 간 차이'가 '기준 대비'보다 크면 그 차이는 설정 때문이 아니라 측정 잡음일 수 있다.")
    if has:
        out.append("psys(플랫폼 전체)의 변화가 소비전력(배터리 전압×전류)의 변화와 비슷하면 측정을 믿을 수 있다. CPU 패키지는 CPU(+내장 GPU)만의 전력이라 더 작다.")
    return "\n".join(out)


def battery_note(wh: float) -> str:
    return "설계 용량의 약 {:.0f}%".format(wh / (5.28 * NOMINAL_V) * 100)


NETDATA = os.environ.get("NETDATA_URL", "http://127.0.0.1:19999")
CHARTS = {"pkg": "cpu.powercap_intel_rapl_zone_package-0", "psys": "cpu.powercap_intel_rapl_zone_psys"}


def netdata_avg(chart: str, t0: float, t1: float, opener=None):
    """Netdata 에 기록된 chart 의 [t0, t1](epoch 초) 평균. root 로 도는 Netdata 가 RAPL 을 이미 기록하므로 sudo 가 필요 없다. 못 읽으면 None."""
    import urllib.parse
    import urllib.request
    q = urllib.parse.urlencode({"chart": chart, "after": int(t0), "before": int(t1), "points": 1, "group": "average", "format": "json"})
    try:
        with (opener or urllib.request.urlopen)(f"{NETDATA}/api/v1/data?{q}", timeout=10) as r:
            rows = json.load(r)["data"]
    except (OSError, ValueError, KeyError):
        return None
    vals = [x for x in (rows[0][1:] if rows else []) if x is not None]
    return sum(vals) if vals else None


def netdata_power(t0: float, t1: float) -> dict:
    """구간 평균 {"pkg": CPU 패키지 W, "psys": 플랫폼 전체 W}(못 읽은 것은 None)."""
    return {k: netdata_avg(c, t0, t1) for k, c in CHARTS.items()}


CONTAINER_FOCUS = os.environ.get("POWER_AB_FOCUS", "genple")     # c-genple 에서 멈출 컨테이너 이름
paused: set = set()                                               # 우리가 멈춘 컨테이너(끝에 반드시 복구)


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def running_containers() -> list:
    return [n for n in docker("ps", "--format", "{{.Names}}").stdout.split() if n]


def set_containers(mode: str) -> bool:
    """mode: run(전부 실행) / genple(focus 컨테이너만 정지) / all(전부 정지). 우리가 멈춘 것만 다시 켠다."""
    want = {"run": set(), "genple": {CONTAINER_FOCUS}, "all": set(running_containers()) | set(paused)}.get(mode)
    if want is None:
        return False
    ok = True
    for n in sorted(paused - want):
        ok = docker("unpause", n).returncode == 0 and ok
        paused.discard(n)
    for n in sorted(want - paused):
        if docker("pause", n).returncode == 0:
            paused.add(n)
        else:
            ok = False
    return ok


def circle_point(cx: float, cy: float, r: float, period: float, t: float) -> tuple:
    """원 둘레 위의 점: 중심 (cx, cy), 반지름 r, 한 바퀴 period 초, 시각 t."""
    a = 2 * math.pi * (t % period) / period
    return round(cx + r * math.cos(a)), round(cy + r * math.sin(a))


def cursor_cmd(x: int, y: int) -> str:
    return f"dispatch hl.dsp.cursor.move({{ x = {x}, y = {y} }})"


def hypr_socket() -> str:
    return f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket.sock"


def hypr_send(cmd: str) -> bytes:
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(hypr_socket())
        s.sendall(cmd.encode())
        return s.recv(256)
    finally:
        s.close()


def mouse_circles(stop: threading.Event, fps: int = 60, period: float = 6.0) -> None:
    """stop 이 켜질 때까지 포인터를 내장 화면 가운데 원 둘레로 움직인다(Hyprland 소켓으로 직접 보내 CPU 를 거의 안 씀)."""
    mon = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True).stdout)[0]
    cx, cy, r = mon["width"] / 2, mon["height"] / 2, min(mon["width"], mon["height"]) * 0.3
    t0 = time.monotonic()
    while not stop.wait(1 / fps):
        x, y = circle_point(cx, cy, r, period, time.monotonic() - t0)
        try:
            hypr_send(cursor_cmd(x, y))
        except OSError:
            return


def cursor_pos():
    out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True, text=True).stdout.strip()
    try:
        x, y = out.split(",")
        return int(x), int(y)
    except ValueError:
        return None


def apply(name: str) -> bool:
    """시나리오: 주사율(Hz) 숫자(런타임만 바꿈, 끝나면 displayctl restore) 또는 c-run/c-genple/c-all(컨테이너 일시정지 상태)."""
    if name.startswith("c-"):
        return set_containers(name[2:])
    if not name.isdigit():
        return False
    r = subprocess.run(["hyprctl", "eval", f'hl.monitor({{ output = "eDP-1", mode = "2560x1600@{name}", position = "0x0", scale = 1 }})'], capture_output=True, text=True)
    return r.returncode == 0


def measure(bat: str, seconds: int, settle: int, sleep=time.sleep):
    """(샘플 목록, {"pkg","psys"} 구간 평균 W). 안정화 뒤 샘플링 구간의 Netdata RAPL 평균을 함께 구한다."""
    sleep(settle)
    out, prev = [], cpu_times()
    t0 = time.time()
    end = t0 + seconds
    while time.time() < end:
        sleep(2)
        w, status = watts(bat)
        cur = cpu_times()
        if status != "Discharging" or w is None:
            raise RuntimeError(f"측정 중 방전이 아니게 됨(상태 {status}) — 어댑터가 다시 연결됐나요?")
        out.append({"w": w, "cpu": cpu_busy(prev, cur)})
        prev = cur
    sleep(2)                                              # Netdata 가 마지막 초를 기록할 시간
    return out, netdata_power(t0, t0 + seconds)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="power-ab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--settle", type=int, default=15)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--scenarios", default="165,60,48")
    ap.add_argument("--mouse", action="store_true", help="재는 동안 포인터를 원 둘레로 움직임")
    ap.add_argument("--containers", action="store_true", help="컨테이너 일시정지 상태별(c-run,c-genple,c-all)로 비교")
    a = ap.parse_args(argv)
    bat = battery()
    if not bat:
        print("배터리를 찾지 못했습니다.", file=sys.stderr)
        return 2
    w, status = watts(bat)
    if status != "Discharging":
        print(f"배터리 상태가 '{status}' 입니다. 전원 어댑터를 **뽑고** 다시 실행하세요(방전 중에만 잴 수 있습니다).", file=sys.stderr)
        return 2
    names = ["c-run", "c-genple", "c-all"] if a.containers else [s.strip() for s in a.scenarios.split(",") if s.strip()]
    total = len(names) * a.rounds * (a.seconds + a.settle)
    print(f"{names} 를 {a.rounds}바퀴, 각 {a.seconds}초(+안정화 {a.settle}초) — 약 {total // 60}분. 재는 동안 컴퓨터를 쓰지 마세요.", flush=True)
    results = {n: [] for n in names}
    stop, saved = threading.Event(), cursor_pos()
    if a.mouse:
        threading.Thread(target=mouse_circles, args=(stop,), daemon=True).start()
    try:
        for r in range(a.rounds):
            for n in names:
                if not apply(n):
                    print(f"{n} 적용 실패", file=sys.stderr)
                    return 1
                samples, power = measure(bat, a.seconds, a.settle)
                s = with_rapl(summarize(samples), power)
                results[n].append(s)
                extra = "".join(f", {lab} {s[k]:.2f} W" for k, lab in (("psys", "psys"), ("pkg", "패키지")) if s.get(k) is not None)
                print(f"  바퀴 {r + 1} · {n:>8}: {s['median']:.2f} W (CPU {s['cpu']:.1f}%{extra})", flush=True)
    except (RuntimeError, KeyboardInterrupt) as e:
        print(f"중단: {e}", file=sys.stderr)
        return 1
    finally:
        stop.set()
        for n in sorted(paused):                         # 우리가 멈춘 컨테이너는 반드시 복구
            docker("unpause", n)
        paused.clear()
        if a.mouse and saved:
            time.sleep(0.1)
            try:
                hypr_send(cursor_cmd(*saved))
            except OSError:
                pass
        subprocess.run(["displayctl", "restore"], capture_output=True)
    print("\n" + render(results, battery_wh(bat)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
