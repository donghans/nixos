#!/usr/bin/env python3
"""boot_settle — 부팅 직후부터 일정 간격으로 전력(RAPL 패키지/psys, 배터리)과 프로세스별 CPU·깨어남(자발적 컨텍스트 스위치)을 기록해,
"부팅 후 몇십 분이 지나야 쉬는 전력이 안정된다"는 현상의 원인(어느 프로세스가 얼마나 오래 일하는지)을 시간 순으로 본다. **root 로 실행**(RAPL energy_uj).

  sudo systemd-run --unit=boot-settle --collect <python3> boot_settle.py [총 초=3600] [간격 초=30]
결과: /tmp/boot-settle.jsonl (한 줄 = 한 시점). 같은 이름의 프로세스는 합산한다(예: node, claude).
"""
import json, os, sys, time

TOTAL = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
STEP = int(sys.argv[2]) if len(sys.argv) > 2 else 30
OUT = "/tmp/boot-settle.jsonl"
HZ = os.sysconf("SC_CLK_TCK")
BAT = "/sys/class/power_supply/BAT1"


def rd(p, d=""):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return d


def wifi_chan():
    """연결된 Wi-Fi 의 주파수(MHz). /sys/class/net/wlan0 에는 없어 iw 를 쓰되, 없으면 빈 값."""
    import subprocess
    try:
        o = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True, text=True, timeout=5).stdout
        return next((l.split()[1] for l in o.splitlines() if l.strip().startswith("freq:")), "")
    except Exception:
        return ""


def rapl(n):
    e, m = rd(f"/sys/class/powercap/{n}/energy_uj"), rd(f"/sys/class/powercap/{n}/max_energy_range_uj")
    return (int(e), int(m)) if e and m else None


def watts(a, b, dt):
    if not a or not b or dt <= 0:
        return None
    d = b[0] - a[0]
    return (d + (a[1] if d < 0 else 0)) / 1e6 / dt


def procs():
    """{pid: (이름, CPU 틱, 자발적 컨텍스트 스위치 합)}"""
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            stat = open(f"/proc/{pid}/stat").read()
            comm = stat[stat.index("(") + 1:stat.rindex(")")]
            f = stat[stat.rindex(")") + 2:].split()
            ticks = int(f[11]) + int(f[12])                      # utime + stime
            vol = 0
            for t in os.listdir(f"/proc/{pid}/task"):
                for line in open(f"/proc/{pid}/task/{t}/status"):
                    if line.startswith("voluntary_ctxt_switches"):
                        vol += int(line.split()[1])
                        break
            out[int(pid)] = (comm, ticks, vol)
        except (OSError, ValueError, IndexError):
            continue
    return out


def aggregate(prev, cur, dt):
    cpu, wake = {}, {}
    for pid, (comm, ticks, vol) in cur.items():
        if pid in prev:
            cpu[comm] = cpu.get(comm, 0) + (ticks - prev[pid][1]) / HZ / dt * 100
            wake[comm] = wake.get(comm, 0) + (vol - prev[pid][2]) / dt
    top = lambda d, n: [[k, round(v, 1)] for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n] if v > 0.05]
    return top(cpu, 8), top(wake, 8)


def main():
    t0 = time.time()
    prev, pk, ps, tp = procs(), rapl("intel-rapl:0"), rapl("intel-rapl:1"), time.time()
    while time.time() - t0 < TOTAL:
        time.sleep(STEP)
        now = time.time()
        cur, pk2, ps2 = procs(), rapl("intel-rapl:0"), rapl("intel-rapl:1")
        dt = now - tp
        v, i = rd(f"{BAT}/voltage_now"), rd(f"{BAT}/current_now")
        cpu, wake = aggregate(prev, cur, dt)
        lid = rd("/proc/acpi/button/lid/LID0/state").split()
        rec = {"uptime": float(rd("/proc/uptime").split()[0]), "pkg_w": watts(pk, pk2, dt), "psys_w": watts(ps, ps2, dt),
               "batt_w": int(v) * abs(int(i)) / 1e12 if v and i else None, "ac": rd("/sys/class/power_supply/ADP1/online"),
               "status": rd(f"{BAT}/status"), "lid": lid[-1] if lid else "?",
               "load1": rd("/proc/loadavg").split()[0], "vt": rd("/sys/class/tty/tty0/active"),
               "audio_pci": rd("/sys/bus/pci/devices/0000:00:1f.3/power/runtime_status"), "wifi_chan": wifi_chan(),
               "hyprlock": os.path.exists("/proc") and any(rd(f"/proc/{d}/comm") == "hyprlock" for d in os.listdir("/proc") if d.isdigit()),
               "top_cpu": cpu, "top_wake": wake}
        with open(OUT, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.chmod(OUT, 0o644)
        prev, pk, ps, tp = cur, pk2, ps2, now


if __name__ == "__main__":
    main()
