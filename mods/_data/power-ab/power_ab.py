#!/usr/bin/env python3
"""power-ab — 배터리로 방전 중일 때 설정(화면 주사율)별 소비 전력을 번갈아 재서 비교한다.

  power-ab [--seconds 90] [--settle 15] [--rounds 2] [--scenarios 165,60,48]

- **전원 어댑터를 뽑은 상태(방전 중)에서만** 잴 수 있다(어댑터가 연결돼 있으면 배터리 전류가 0 이라 잴 게 없다).
- 소비 전력 = 배터리 전압 × 전류(sysfs). 시나리오를 번갈아(165 → 60 → 48 → 165 → …) 여러 바퀴 재서 배터리 온도/잔량에 따른 느린 변화가 한 설정에 몰리지 않게 한다.
- 재는 동안 CPU 가 바쁘면(평균 사용률 10% 초과) 결과에 표시한다 — 그 값은 화면 설정 차이가 아니라 작업 때문일 수 있다.
- 끝나면(중간에 Ctrl+C 해도) `displayctl restore` 로 저장된 화면 설정으로 되돌린다. 밝기는 건드리지 않는다.
- 시나리오: `165`/`60` 은 표준 모드로 전환, `48` 은 저장된 구성(`displayctl restore`, 지금은 사용자 지정 48Hz).
"""
import argparse
import os
import statistics
import subprocess
import sys
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


def battery_wh(bat: str) -> float:
    full = read(f"{bat}/charge_full")
    return int(full) / 1e6 * NOMINAL_V if full else 0.0


def hours(wh: float, w: float) -> float:
    return wh / w if w > 0 else 0.0


def render(results: dict, wh: float) -> str:
    """results: {시나리오: [summarize 결과 (바퀴마다)]}"""
    rows, base = [], None
    for name, runs in results.items():
        med = statistics.fmean(r["median"] for r in runs)
        cpu = statistics.fmean(r["cpu"] for r in runs)
        base = med if base is None else base
        spread = max(r["median"] for r in runs) - min(r["median"] for r in runs)
        rows.append((name, med, med - base, spread, cpu, hours(wh, med)))
    out = [f"{'설정':<10} {'소비전력':>9} {'기준 대비':>10} {'바퀴 간 차이':>12} {'CPU':>6} {'예상 사용시간':>13}"]
    for name, med, d, spread, cpu, h in rows:
        out.append(f"{name:<10} {med:>7.2f} W {d:>+8.2f} W {spread:>10.2f} W {cpu:>5.1f}% {h:>9.1f} 시간" + ("  (CPU 바쁨: 작업 영향 가능)" if cpu > 10 else ""))
    out.append(f"\n예상 사용시간은 지금 배터리 용량({wh:.1f} Wh = 만충 {battery_note(wh)})을 그 전력으로 쓴다고 가정한 값이다.")
    out.append("'바퀴 간 차이'가 '기준 대비'보다 크면 그 차이는 설정 때문이 아니라 측정 잡음일 수 있다.")
    return "\n".join(out)


def battery_note(wh: float) -> str:
    return "설계 용량의 약 {:.0f}%".format(wh / (5.28 * NOMINAL_V) * 100)


def apply(name: str) -> bool:
    if name in ("165", "60"):
        mode = "2560x1600@165" if name == "165" else "2560x1600@60"
        r = subprocess.run(["hyprctl", "eval", f'hl.monitor({{ output = "eDP-1", mode = "{mode}", position = "0x0", scale = 1 }})'], capture_output=True, text=True)
    else:
        r = subprocess.run(["displayctl", "restore"], capture_output=True, text=True)
    return r.returncode == 0


def measure(bat: str, seconds: int, settle: int, sleep=time.sleep) -> list:
    sleep(settle)
    out, prev = [], cpu_times()
    end = time.time() + seconds
    while time.time() < end:
        sleep(2)
        w, status = watts(bat)
        cur = cpu_times()
        if status != "Discharging" or w is None:
            raise RuntimeError(f"측정 중 방전이 아니게 됨(상태 {status}) — 어댑터가 다시 연결됐나요?")
        out.append({"w": w, "cpu": cpu_busy(prev, cur)})
        prev = cur
    return out


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="power-ab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--settle", type=int, default=15)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--scenarios", default="165,60,48")
    a = ap.parse_args(argv)
    bat = battery()
    if not bat:
        print("배터리를 찾지 못했습니다.", file=sys.stderr)
        return 2
    w, status = watts(bat)
    if status != "Discharging":
        print(f"배터리 상태가 '{status}' 입니다. 전원 어댑터를 **뽑고** 다시 실행하세요(방전 중에만 잴 수 있습니다).", file=sys.stderr)
        return 2
    names = [s.strip() for s in a.scenarios.split(",") if s.strip()]
    total = len(names) * a.rounds * (a.seconds + a.settle)
    print(f"{names} 를 {a.rounds}바퀴, 각 {a.seconds}초(+안정화 {a.settle}초) — 약 {total // 60}분. 재는 동안 컴퓨터를 쓰지 마세요.", flush=True)
    results = {n: [] for n in names}
    try:
        for r in range(a.rounds):
            for n in names:
                if not apply(n):
                    print(f"{n} 적용 실패", file=sys.stderr)
                    return 1
                s = summarize(measure(bat, a.seconds, a.settle))
                results[n].append(s)
                print(f"  바퀴 {r + 1} · {n:>4}: {s['median']:.2f} W (CPU {s['cpu']:.1f}%)", flush=True)
    except (RuntimeError, KeyboardInterrupt) as e:
        print(f"중단: {e}", file=sys.stderr)
        return 1
    finally:
        subprocess.run(["displayctl", "restore"], capture_output=True)
    print("\n" + render(results, battery_wh(bat)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
