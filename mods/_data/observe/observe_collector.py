#!/usr/bin/env python3
"""observe_collector — **root** 수집기. systemd path 유닛이 제어 파일/요청 변경 때만 띄우고, 할 일이 없으면 스스로 종료한다(꺼져 있을 땐 프로세스 자체가 없어 오버헤드 0).

표본(제어 파일 enabled=true 일 때): L0 30초 / L1 5초 간격으로 /var/lib/observe/data/samples-YYYYMMDD.jsonl 에 한 줄씩.
  pw    전력: RAPL(패키지/psys/코어/언코어), 배터리 V×I·잔량·충전 상태, AC
  cs    패키지 C-state 잔여율(MSR PC2~PC10, TSC 기준 %), S0ix, cpuidle 상태별 %(전 CPU 평균), 평균 주파수
  irq   IRQ/소프트IRQ 초당 증가 상위, ACPI GPE(EC) 초당, ctxt/intr 초당, CPU 사용률
  proc  프로세스(comm+exe 이름별 합산) CPU%, 깨어남/s(자발적 컨텍스트 전환), RSS — CPU 상위 + 깨어남 상위
  L1:   thr 스레드별 상위, io 프로세스별 읽기/쓰기 B/s
  dev   VT, 덮개, 백라이트, GPU/오디오 런타임 PM, Wi-Fi(SSID·주파수·신호·절전; 30초마다), TLP 모드
  state 분류 휴리스틱: pc10 ≥ 5% 이면 "low"(깊은 절전: 패널 파이프 꺼짐 등), 아니면 "high" (powertop 측정에서 낮은 상태 pc10 17~24%, 높은 상태 0% 였음)
개인정보: 프로세스는 comm 과 exe 이름만(명령줄 인자는 읽지 않음).
요청 작업(requests/*.json → results/<id>.json): ping, wakers(ftrace 로 깨움 원인 프로파일), drmdebug(drm.debug 를 잠시 켬), display(debugfs 스냅샷 — 디스플레이를 깨워 상태를 바꿀 수 있음).
"""
import collections, glob, json, os, re, signal, struct, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe_core as core

PROC = os.environ.get("OBSERVE_PROC", "/proc")
SYS = os.environ.get("OBSERVE_SYS", "/sys")
IW = os.environ.get("OBSERVE_IW", "iw")
HZ = os.sysconf("SC_CLK_TCK")
NCPU = os.cpu_count() or 1
TRACEFS = os.environ.get("OBSERVE_TRACEFS", "/sys/kernel/tracing")
PC_REGS = {"pc2": 0x60D, "pc3": 0x3F8, "pc6": 0x3F9, "pc7": 0x3FA, "pc8": 0x630, "pc9": 0x631, "pc10": 0x632}
MSR_TSC = 0x10


def rd(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


# ---------------------------------------------------------------- 파서(순수 함수; 시험 대상)
def parse_stat(text):
    """/proc/stat → {busy, total, ctxt, intr}. busy = total − idle − iowait (jiffies)."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == "cpu":
            v = [int(x) for x in f[1:]]
            total = sum(v[:8])
            out["total"], out["busy"] = total, total - v[3] - (v[4] if len(v) > 4 else 0)
        elif f[0] in ("ctxt", "intr"):
            out[f[0]] = int(f[1])
    return out


def parse_interrupts(text):
    """/proc/interrupts → {이름: (합계, 설명)}. 숫자 IRQ 는 'IRQ9' 처럼, 이름 있는 줄(NMI, LOC …)은 그대로."""
    lines = text.splitlines()
    ncpu = len(lines[0].split()) if lines else 0
    out = {}
    for line in lines[1:]:
        f = line.split()
        if not f or not f[0].endswith(":"):
            continue
        name = f[0][:-1]
        nums = []
        for x in f[1:1 + ncpu]:
            if x.isdigit():
                nums.append(int(x))
            else:
                break
        desc = " ".join(f[1 + len(nums):])[:60]
        out[("IRQ" + name) if name.isdigit() else name] = (sum(nums), desc)
    return out


def parse_softirqs(text):
    out = {}
    for line in text.splitlines()[1:]:
        f = line.split()
        if f and f[0].endswith(":"):
            out[f[0][:-1]] = sum(int(x) for x in f[1:] if x.isdigit())
    return out


def parse_pid_stat(text):
    """/proc/<pid>/stat → (comm, utime+stime(jiffies), num_threads, rss_pages). comm 에 공백/괄호가 있어도 안전."""
    i, j = text.index("("), text.rindex(")")
    f = text[j + 2:].split()
    return text[i + 1:j], int(f[11]) + int(f[12]), int(f[17]), int(f[21])


def parse_ctxt(text):
    """/proc/<pid>/status 에서 (자발적, 비자발적) 컨텍스트 전환 수."""
    v = n = 0
    for line in text.splitlines():
        if line.startswith("voluntary_ctxt_switches:"):
            v = int(line.split()[1])
        elif line.startswith("nonvoluntary_ctxt_switches:"):
            n = int(line.split()[1])
    return v, n


def pkg_cstate_pct(prev, cur):
    """MSR 잔여 카운터 두 시점 → {pcN: %}. 카운터는 TSC 속도로 증가하므로 TSC 증가량으로 나눈다."""
    dt = cur["tsc"] - prev["tsc"]
    if dt <= 0:
        return {}
    return {k: max(0.0, min(100.0, round((cur[k] - prev[k]) / dt * 100, 2))) for k in PC_REGS if k in cur and k in prev}


def cpuidle_pct(prev, cur, wall_s, ncpu):
    """cpuidle 상태별 누적 시간(us, 전 CPU 합) → 상태별 % (CPU 시간 대비)."""
    cap = wall_s * 1e6 * ncpu
    return {k: round(max(0.0, (cur[k] - prev.get(k, cur[k])) / cap * 100), 2) for k in cur} if cap > 0 else {}


def quirks_tag(cmdline):
    """커널 인자에서 이 기기에서 의심 중인 3개(pcie_aspm=off, acpi_osi=Linux, irqpoll)를 태그로: 'quirks'(모두), 'no-quirks'(모두 없음), 아니면 'partial:…'. 부팅 간 비교용."""
    toks = cmdline.split()
    has = [t for t in ("pcie_aspm=off", "acpi_osi=Linux", "irqpoll") if t in toks]
    return "quirks" if len(has) == 3 else "no-quirks" if not has else "partial:" + "+".join(has)


def classify(cs):
    """깊은 절전 상태 분류. pc10 이 5% 이상이면 low. MSR 을 못 읽었으면 unknown."""
    if not cs or "pc10" not in cs:
        return "unknown"
    return "low" if cs["pc10"] >= 5 else "high"


def parse_trace(text):
    """ftrace 텍스트 → {'timer': Counter(함수), 'hrtimer': Counter(함수), 'irq': Counter('N name'), 'work': Counter(함수), 'waker': Counter(comm)}."""
    out = {k: collections.Counter() for k in ("timer", "hrtimer", "irq", "work", "waker")}
    for line in text.splitlines():
        if line.startswith("#") or ": " not in line:
            continue
        m = re.search(r"\s(timer_expire_entry|hrtimer_expire_entry|irq_handler_entry|workqueue_execute_start|sched_waking):\s*(.*)$", line)
        if not m:
            continue
        ev, rest = m[1], m[2]
        if ev == "timer_expire_entry":
            fn = re.search(r"function=(\S+)", rest)
            out["timer"][fn[1] if fn else "?"] += 1
        elif ev == "hrtimer_expire_entry":
            fn = re.search(r"function=(\S+)", rest)
            out["hrtimer"][fn[1] if fn else "?"] += 1
        elif ev == "irq_handler_entry":
            irq, name = re.search(r"irq=(\d+)", rest), re.search(r"name=(\S+)", rest)
            out["irq"][f"{irq[1] if irq else '?'} {name[1] if name else '?'}"] += 1
        elif ev == "workqueue_execute_start":
            fn = re.search(r"function (\S+)", rest) or re.search(r"function=(\S+)", rest)
            out["work"][fn[1] if fn else "?"] += 1
        else:
            c = re.search(r"comm=(.+?)\s+pid=", rest)
            out["waker"][c[1] if c else "?"] += 1
    return out


# ---------------------------------------------------------------- 표본 수집기
class Msr:
    def __init__(self):
        self.fd = None
        try:
            self.fd = os.open("/dev/cpu/0/msr", os.O_RDONLY)
        except OSError:
            try:
                subprocess.run(["/run/current-system/sw/bin/modprobe", "msr"], capture_output=True, timeout=10)   # NixOS 는 래퍼 modprobe 만 모듈 경로를 안다
                self.fd = os.open("/dev/cpu/0/msr", os.O_RDONLY)
            except Exception:
                self.fd = None

    def read(self, reg):
        return struct.unpack("Q", os.pread(self.fd, 8, reg))[0]

    def snap(self):
        if self.fd is None:
            return None
        try:
            d = {k: self.read(r) for k, r in PC_REGS.items()}
            d["tsc"] = self.read(MSR_TSC)
            return d
        except OSError:
            return None


def _energy(name):
    e, m = rd(f"{SYS}/class/powercap/{name}/energy_uj"), rd(f"{SYS}/class/powercap/{name}/max_energy_range_uj")
    return (int(e), int(m)) if e and m else None


def _watts(a, b, dt):
    if not a or not b or dt <= 0:
        return None
    d = b[0] - a[0]
    if d < 0:
        d += b[1]
    return round(d / dt / 1e6, 3)


def find_battery():
    for d in sorted(glob.glob(f"{SYS}/class/power_supply/*")):
        if rd(d + "/type") == "Battery":
            return d
    return None


def wifi_info():
    info = {}
    try:
        link = subprocess.run([IW, "dev", "wlan0", "link"], capture_output=True, text=True, timeout=5).stdout
        for key, pat in (("ssid", r"SSID:\s*(.+)"), ("freq", r"freq:\s*([\d.]+)"), ("signal", r"signal:\s*(-?\d+)")):
            m = re.search(pat, link)
            if m:
                info[key] = m[1].strip()
        ps = subprocess.run([IW, "dev", "wlan0", "get", "power_save"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"Power save:\s*(\w+)", ps)
        if m:
            info["ps"] = m[1]
    except Exception:
        pass
    return info


class Sampler:
    def __init__(self, level):
        self.level = level
        self.msr = Msr()
        self.bat = find_battery()
        self.prev = self._snapshot()
        self.warm = False                       # 첫 표본은 짧게(2초) 기다려 누적값 차이를 만든다
        self.wifi, self.wifi_t = {}, 0.0

    # 한 시점의 모든 누적값
    def _snapshot(self):
        s = {"t": time.time(), "mono": time.monotonic()}
        s["stat"] = parse_stat(rd(f"{PROC}/stat"))
        s["irq"] = parse_interrupts(rd(f"{PROC}/interrupts"))
        s["soft"] = parse_softirqs(rd(f"{PROC}/softirqs"))
        s["msr"] = self.msr.snap()
        s["rapl"] = {n: _energy(n) for n in ("intel-rapl:0", "intel-rapl:1", "intel-rapl:0:0", "intel-rapl:0:1")}
        s["gpe"] = {k: int((rd(f"{SYS}/firmware/acpi/interrupts/{k}") or "0").split()[0]) for k in ("gpe6E", "sci")}
        idle = collections.defaultdict(int)
        for st in glob.glob(f"{SYS}/devices/system/cpu/cpu0/cpuidle/state*"):
            name = rd(st + "/name")
            idle[name] = 0
        for st in glob.glob(f"{SYS}/devices/system/cpu/cpu[0-9]*/cpuidle/state*"):
            name = rd(os.path.join(os.path.dirname(st), os.path.basename(st), "name"))
            idle[name] += int(rd(st + "/time", "0") or 0)
        s["idle"] = dict(idle)
        s["s0ix"] = int(rd(f"{SYS}/devices/system/cpu/cpuidle/low_power_idle_system_residency_us", "0") or 0)
        s["procs"], s["threads"] = self._procs()
        return s

    def _procs(self):
        procs, threads = {}, {}
        for d in os.listdir(PROC):
            if not d.isdigit():
                continue
            try:
                comm, cpu, nthr, rss = parse_pid_stat(rd(f"{PROC}/{d}/stat"))
                vol, inv = parse_ctxt(rd(f"{PROC}/{d}/status"))
                try:
                    exe = os.path.basename(os.readlink(f"{PROC}/{d}/exe"))
                except OSError:
                    exe = ""
                io = (0, 0)
                if self.level == "L1":
                    t = rd(f"{PROC}/{d}/io")
                    mr, mw = re.search(r"read_bytes:\s*(\d+)", t), re.search(r"write_bytes:\s*(\d+)", t)
                    io = (int(mr[1]) if mr else 0, int(mw[1]) if mw else 0)
                procs[int(d)] = (comm, exe, cpu, vol, rss, io)
                if self.level == "L1":
                    for t in os.listdir(f"{PROC}/{d}/task"):
                        try:
                            tn, tcpu, _, _ = parse_pid_stat(rd(f"{PROC}/{d}/task/{t}/stat"))
                            tv, _ = parse_ctxt(rd(f"{PROC}/{d}/task/{t}/status"))
                            threads[(int(d), int(t))] = (comm, tn, tcpu, tv)
                        except (OSError, ValueError, IndexError):
                            pass
            except (OSError, ValueError, IndexError):
                continue
        return procs, threads

    def sample(self):
        cur = self._snapshot()
        p = self.prev
        dt = cur["mono"] - p["mono"]
        out = {"t": round(cur["t"], 3), "dt": round(dt, 2), "lvl": self.level}
        pw = {"pkg_w": _watts(p["rapl"]["intel-rapl:0"], cur["rapl"]["intel-rapl:0"], dt),
              "psys_w": _watts(p["rapl"]["intel-rapl:1"], cur["rapl"]["intel-rapl:1"], dt),
              "core_w": _watts(p["rapl"]["intel-rapl:0:0"], cur["rapl"]["intel-rapl:0:0"], dt),
              "uncore_w": _watts(p["rapl"]["intel-rapl:0:1"], cur["rapl"]["intel-rapl:0:1"], dt)}
        if self.bat:
            v, i = rd(self.bat + "/voltage_now"), rd(self.bat + "/current_now")
            pw["batt_w"] = round(int(v) * abs(int(i)) / 1e12, 3) if v and i else None
            pw["batt_pct"] = rd(self.bat + "/capacity")
            pw["q_uah"] = int(rd(self.bat + "/charge_now") or 0) or None        # 누적 계량값(1 mAh 단위, ≈15 mWh) — 10분 이상 평균에 쓰는 가장 믿을 만한 기준(observectl energy)
            pw["v_uv"] = int(v) if v else None
            pw["status"] = rd(self.bat + "/status")
        pw["ac"] = max([int(rd(d + "/online", "0") or 0) for d in glob.glob(f"{SYS}/class/power_supply/*") if rd(d + "/type") == "Mains"] or [0])
        out["pw"] = pw
        cs = pkg_cstate_pct(p["msr"], cur["msr"]) if p["msr"] and cur["msr"] else {}
        cs["s0ix_pct"] = round(max(0, cur["s0ix"] - p["s0ix"]) / (dt * 1e6) * 100, 2) if dt > 0 else None
        cs["idle"] = cpuidle_pct(p["idle"], cur["idle"], dt, NCPU)
        freqs = [int(rd(f, "0") or 0) for f in glob.glob(f"{SYS}/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")]
        cs["mhz"] = round(sum(freqs) / len(freqs) / 1000) if freqs else None
        out["cs"] = cs
        out["state"] = classify(cs)
        d_irq = sorted(((cur["irq"][k][0] - p["irq"].get(k, (cur["irq"][k][0], ""))[0], k, cur["irq"][k][1]) for k in cur["irq"]), reverse=True)[:8]
        d_soft = sorted(((cur["soft"][k] - p["soft"].get(k, cur["soft"][k]), k) for k in cur["soft"]), reverse=True)[:5]
        out["irq"] = {"top": [{"n": k, "per_s": round(v / dt, 1), "desc": desc} for v, k, desc in d_irq if v > 0],
                      "soft": [{"n": k, "per_s": round(v / dt, 1)} for v, k in d_soft if v > 0],
                      "gpe6e_s": round((cur["gpe"]["gpe6E"] - p["gpe"]["gpe6E"]) / dt, 1), "sci_s": round((cur["gpe"]["sci"] - p["gpe"]["sci"]) / dt, 1),
                      "ctxt_s": round((cur["stat"].get("ctxt", 0) - p["stat"].get("ctxt", 0)) / dt), "intr_s": round((cur["stat"].get("intr", 0) - p["stat"].get("intr", 0)) / dt),
                      "cpu_busy_pct": round((cur["stat"]["busy"] - p["stat"]["busy"]) / max(1, cur["stat"]["total"] - p["stat"]["total"]) * 100, 1),
                      "load1": rd(f"{PROC}/loadavg").split()[0] if rd(f"{PROC}/loadavg") else None}
        agg = {}
        for pid, (comm, exe, cpu, vol, rss, io) in cur["procs"].items():
            q = p["procs"].get(pid)
            if not q:
                continue
            a = agg.setdefault((comm, exe), {"n": 0, "cpu": 0.0, "wake": 0.0, "rss": 0, "rd": 0, "wr": 0})
            a["n"] += 1
            a["cpu"] += (cpu - q[2]) / HZ / dt * 100
            a["wake"] += (vol - q[3]) / dt
            a["rss"] += rss
            a["rd"] += max(0, io[0] - q[5][0]) / dt
            a["wr"] += max(0, io[1] - q[5][1]) / dt
        rows = [{"comm": k[0], "exe": k[1], "n": v["n"], "cpu": round(v["cpu"], 2), "wake": round(v["wake"], 1), "rss_mb": round(v["rss"] * 4096 / 1048576, 1)} for k, v in agg.items()]
        top = {r["comm"] + "|" + r["exe"]: r for r in sorted(rows, key=lambda r: -r["cpu"])[:8] + sorted(rows, key=lambda r: -r["wake"])[:8] if r["cpu"] > 0 or r["wake"] > 0}
        out["proc"] = list(top.values())
        if self.level == "L1":
            trows = []
            for key, (comm, tn, tcpu, tv) in cur["threads"].items():
                q = p["threads"].get(key)
                if q:
                    trows.append({"pid": key[0], "tid": key[1], "comm": comm, "thr": tn, "cpu": round((tcpu - q[2]) / HZ / dt * 100, 2), "wake": round((tv - q[3]) / dt, 1)})
            out["thr"] = sorted(trows, key=lambda r: -(r["wake"] + r["cpu"] * 10))[:15]
            ios = [{"comm": k[0], "rd_bps": round(v["rd"]), "wr_bps": round(v["wr"])} for k, v in agg.items() if v["rd"] + v["wr"] > 0]
            out["io"] = sorted(ios, key=lambda r: -(r["rd_bps"] + r["wr_bps"]))[:5]
        if time.monotonic() - self.wifi_t > 30:
            self.wifi, self.wifi_t = wifi_info(), time.monotonic()
        bl = glob.glob(f"{SYS}/class/backlight/*/brightness")
        out["dev"] = {"vt": rd(f"{SYS}/class/tty/tty0/active"), "lid": (rd(f"{PROC}/acpi/button/lid/LID0/state").split() or [None])[-1],
                      "bl": rd(bl[0]) if bl else None, "wifi": self.wifi, "tlp": (rd("/run/tlp/last_pwr").split() or [None])[0],
                      "boot": rd(f"{PROC}/sys/kernel/random/boot_id")[:8], "quirks": quirks_tag(rd(f"{PROC}/cmdline")),
                      "gpu_rpm": next((rd(f) for f in glob.glob(f"{SYS}/class/drm/card*/device/power/runtime_status")), None),
                      "audio_rpm": rd(f"{SYS}/bus/pci/devices/0000:00:1f.3/power/runtime_status") or None}
        self.prev = cur
        return out


# ---------------------------------------------------------------- 요청 작업
def job_ping(args):
    return {"pong": True, "msr": Msr().fd is not None, "tracefs": os.path.isdir(TRACEFS + "/events")}


def job_wakers(args):
    """ftrace 로 N초 동안 누가 CPU 를 깨우는지 센다(타이머/하이타이머 함수, IRQ 핸들러, workqueue 함수, [옵션] sched_waking 의 깨우는 쪽 comm)."""
    sec = max(1, min(int(args.get("sec", 10)), 60))
    events = ["timer:timer_expire_entry", "timer:hrtimer_expire_entry", "irq:irq_handler_entry", "workqueue:workqueue_execute_start"]
    if args.get("waking"):
        events.append("sched:sched_waking")
    T = TRACEFS
    saved = {k: rd(f"{T}/{k}") for k in ("tracing_on", "buffer_size_kb")}
    saved_ev = rd(f"{T}/set_event")
    try:
        open(f"{T}/tracing_on", "w").write("0")
        open(f"{T}/trace", "w").write("")
        open(f"{T}/buffer_size_kb", "w").write("8192")
        open(f"{T}/set_event", "w").write(" ".join(events))
        open(f"{T}/tracing_on", "w").write("1")
        t0 = time.time()
        time.sleep(sec)
        open(f"{T}/tracing_on", "w").write("0")
        text = rd(f"{T}/trace")
        dur = max(0.1, time.time() - t0)
    finally:
        try:
            open(f"{T}/tracing_on", "w").write("0")
            open(f"{T}/set_event", "w").write(" ".join(l for l in saved_ev.split() if not l.startswith("#")))
            m = re.search(r"expanded:\s*(\d+)", saved["buffer_size_kb"]) or re.search(r"\d+", saved["buffer_size_kb"] or "")
            open(f"{T}/buffer_size_kb", "w").write(m[1] if m and m.lastindex else (m[0] if m else "1408"))
            open(f"{T}/trace", "w").write("")
        except OSError:
            pass
    c = parse_trace(text)
    return {"sec": round(dur, 1), "total": sum(sum(v.values()) for v in c.values()),
            **{k: [{"key": a, "count": b, "per_s": round(b / dur, 1)} for a, b in v.most_common(15)] for k, v in c.items()}}


def job_drmdebug(args):
    """drm.debug 마스크를 N초 동안 켰다가 원래 값으로 되돌린다(로그는 커널 링 버퍼/저널로). 기본 마스크 = 전부에서 VBL(0x20, 스팸) 제외."""
    sec = max(1, min(int(args.get("sec", 15)), 120))
    mask = int(str(args.get("mask", "0x1df")), 0)
    p = f"{SYS}/module/drm/parameters/debug"
    old = rd(p)
    t0 = time.time()
    try:
        open(p, "w").write(str(mask))
        time.sleep(sec)
    finally:
        open(p, "w").write(old or "0")
    return {"from": round(t0, 1), "to": round(time.time(), 1), "mask": hex(mask), "restored": old}


def job_display(args):
    """디스플레이/PMC debugfs 스냅샷. **읽는 것이 디스플레이를 깨워 낮은 전력 상태를 깨뜨릴 수 있다**(측정 중 주의)."""
    out = {"perturbs": True, "t": round(time.time(), 1)}
    gpu = "/sys/kernel/debug/dri/0000:00:02.0"
    out["display_info"] = rd(f"{gpu}/i915_display_info")[:6000]
    out["power_domains"] = rd(f"{gpu}/i915_power_domain_info")[:4000]
    out["package_cstate"] = rd("/sys/kernel/debug/pmc_core/package_cstate_show")
    return out


JOBS = {"ping": job_ping, "wakers": job_wakers, "drmdebug": job_drmdebug, "display": job_display}


def process_requests():
    """requests/*.json 을 처리하고 results/<id>.json 을 쓴다. 처리한 개수를 돌려준다."""
    n = 0
    for f in sorted(glob.glob(os.path.join(core.REQ_DIR, "*.json"))):
        try:
            req = json.load(open(f))
        except (OSError, ValueError):
            req = {}
        try:
            os.unlink(f)
        except OSError:
            continue
        rid = re.sub(r"[^A-Za-z0-9_.-]", "", str(req.get("id") or os.path.basename(f)[:-5])).lstrip(".")[:64] or "req"
        res = {"id": rid, "type": req.get("type"), "t_start": round(time.time(), 1)}
        try:
            fn = JOBS.get(req.get("type"))
            if not fn:
                raise ValueError(f"알 수 없는 작업: {req.get('type')}")
            res["ok"], res["data"] = True, fn(req.get("args") or {})
        except Exception as e:
            res["ok"], res["error"] = False, f"{type(e).__name__}: {e}"
        res["t_end"] = round(time.time(), 1)
        os.makedirs(core.RES_DIR, exist_ok=True)
        tmp = os.path.join(core.RES_DIR, f".{rid}.tmp")
        json.dump(res, open(tmp, "w"), ensure_ascii=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(core.RES_DIR, rid + ".json"))
        n += 1
    return n


def main():
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    for d in (core.REQ_DIR, core.RES_DIR, core.SAMPLE_DIR):
        os.makedirs(d, exist_ok=True)
    sampler, idle_since, last_prune = None, time.monotonic(), 0.0
    while not stop:
        ctl = core.read_control()
        did = process_requests()
        if ctl["enabled"]:
            lvl = ctl["level"] if ctl["level"] in ("L0", "L1") else "L0"
            if sampler is None or sampler.level != lvl:
                sampler = Sampler(lvl)
            interval = max(1.0, float(ctl["interval_s"].get(lvl, 30)))
            end = time.monotonic() + (interval if sampler.warm else 2.0)
            sampler.warm = True
            while time.monotonic() < end and not stop:
                time.sleep(min(1.0, max(0.05, end - time.monotonic())))
                if os.path.exists(core.REQ_DIR) and os.listdir(core.REQ_DIR):
                    break
            s = sampler.sample()
            s["mark"] = core.read_control().get("mark")        # 표본 직전에 다시 읽는다(루프 시작에서 읽은 값을 쓰면 표지 변경이 한 표본 늦게 반영됨)
            core.append_jsonl(core.SAMPLE_DIR, "samples", s)
            if time.monotonic() - last_prune > 3600:
                core.prune(core.SAMPLE_DIR, "samples", ctl["retention_days"], ctl["max_total_mb"])
                last_prune = time.monotonic()
            idle_since = time.monotonic()
        else:
            sampler = None
            if did:
                idle_since = time.monotonic()
            if time.monotonic() - idle_since > 15:
                return 0
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
