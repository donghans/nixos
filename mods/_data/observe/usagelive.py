"""usagelive — usageui 「실시간」 탭의 샘플링과 박스별 표시 조각. 시간축 그래프는 없고 **지금 값**(직전 표본과의 차이로 낸 변화율 포함)만 보인다.

- 측정·판정은 hostmetrics(호스트 측정 모듈, donghans-host-resources 스킬의 정본을 같은 디렉터리로 복사해 쓴다)를 그대로 쓴다.
- 읽기 전용. 이력은 저장하지 않는다. 샘플링을 언제 돌릴지(탭 활성·창 포커스 때만)는 호출부(usageui)가 정한다.
- 느린 항목(앱 CPU 상위·cgroup 소비자·LLM 세션 PSS)은 `slow_every` 초마다만 새로 잰다 — PSS 전체 순회와 /proc 전체 스캔이 1초 간격에는 비싸다.
  LLM 세션의 ctx 보충(donghans ctx sql subprocess)은 부르지 않는다.
- 개인정보: 프로세스는 이름만 쓴다. electron 앱 이름을 정하려 루트 프로세스의 명령줄을 읽지만(observe_apps) 저장·표시하지 않는다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

from rich.cells import cell_len
from rich.text import Text

try:
    import hostmetrics as hm
except ImportError:  # 소스에서 직접 실행할 때(설치본은 같은 디렉터리에 복사됨)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude-skills", "donghans-host-resources", "scripts"))
    import hostmetrics as hm
import diskbench as db
import observe_apps as ap
import usagegraph as pg

GIB = hm.GIB
MIB = hm.MIB
LEVEL_STYLE = {"여유": "bold green", "주의": "bold yellow", "압박": "bold dark_orange", "심각": "bold red"}


# ---------- 샘플링 ----------
def read_net():
    """{인터페이스: (수신 누적 B, 송신 누적 B)} — lo 제외."""
    out = {}
    for line in (hm.read("/proc/net/dev") or "").splitlines()[2:]:
        name, _, rest = line.partition(":")
        f = rest.split()
        name = name.strip()
        if name and name != "lo" and len(f) >= 9:
            out[name] = (int(f[0]), int(f[8]))
    return out


def read_disk():
    """{장치: (읽은 누적 B, 쓴 누적 B)} — 파티션·loop·zram·dm 제외(전체 장치만)."""
    try:
        whole = {d for d in os.listdir("/sys/block") if not d.startswith(("loop", "ram", "zram", "dm-"))}
    except OSError:
        return {}
    out = {}
    for line in (hm.read("/proc/diskstats") or "").splitlines():
        f = line.split()
        if len(f) >= 10 and f[2] in whole:
            out[f[2]] = (int(f[5]) * 512, int(f[9]) * 512)
    return out


def _num(path):
    try:
        return int((hm.read(path) or "").strip())
    except ValueError:
        return None


def read_power(base=None):
    """배터리·AC 어댑터 상태 dict(percent, status, now_wh, full_wh, watts, eta_h, ac) 또는 배터리가 없으면 None. watts 는 방전·충전 전력의 크기(부호 없음).
    sysfs 가 energy_* 를 주면 그대로, charge_*(µAh)만 주면 전압을 곱해 Wh 로 바꾼다. 여러 배터리는 합친다. eta_h 는 방전이면 남은 시간, 충전이면 만충까지(전력이 0.5 W 미만이면 None)."""
    base = base or os.environ.get("OBSERVE_POWER_SUPPLY_DIR", "/sys/class/power_supply")       # 환경 변수는 시험·화면 촬영용
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    bats, ac = [], None
    for n in names:
        d = f"{base}/{n}"
        typ = (hm.read(f"{d}/type") or "").strip()
        if typ == "Mains":
            ac = ((hm.read(f"{d}/online") or "0").strip() == "1") or bool(ac)
        elif typ == "Battery":
            v = _num(f"{d}/voltage_now")
            en, ef = _num(f"{d}/energy_now"), _num(f"{d}/energy_full")
            if en is None or ef is None:
                cn, cf = _num(f"{d}/charge_now"), _num(f"{d}/charge_full")
                vv = v or _num(f"{d}/voltage_min_design")
                en, ef = (cn * vv / 1e6, cf * vv / 1e6) if None not in (cn, cf, vv) else (None, None)
            pw = _num(f"{d}/power_now")
            if pw is None:
                cur = _num(f"{d}/current_now")
                pw = abs(cur) * v / 1e6 if cur is not None and v else None
            bats.append(dict(cap=_num(f"{d}/capacity"), status=(hm.read(f"{d}/status") or "").strip(), en=en, ef=ef, pw=abs(pw) if pw is not None else None))
    if not bats:
        return None
    en = sum(b["en"] for b in bats if b["en"] is not None) or None
    ef = sum(b["ef"] for b in bats if b["ef"] is not None) or None
    pw = sum(b["pw"] for b in bats if b["pw"] is not None) if any(b["pw"] is not None for b in bats) else None
    st = next((b["status"] for b in bats if b["status"] == "Discharging"), next((b["status"] for b in bats if b["status"] == "Charging"), bats[0]["status"]))
    pct = en / ef * 100 if en and ef else next((b["cap"] for b in bats if b["cap"] is not None), None)
    watts = pw / 1e6 if pw is not None else None
    eta = None
    if watts and watts >= 0.5 and en and ef:
        eta = en / 1e6 / watts if st == "Discharging" else ((ef - en) / 1e6 / watts if st == "Charging" else None)
    return dict(percent=pct, status=st, now_wh=en / 1e6 if en else None, full_wh=ef / 1e6 if ef else None, watts=watts, eta_h=eta, ac=ac)


RAPL = {"psys": "/sys/class/powercap/intel-rapl:1", "pkg": "/sys/class/powercap/intel-rapl:0"}


def read_rapl():
    """{이름: (누적 µJ, 감김 한계 µJ)} — RAPL 에너지 카운터(psys = 시스템 전체, pkg = CPU 패키지). 읽을 수 없는 것(권한·미지원)은 뺀다."""
    out = {}
    for k, d in RAPL.items():
        e, m = _num(f"{d}/energy_uj"), _num(f"{d}/max_energy_range_uj")
        if e is not None:
            out[k] = (e, m or 0)
    return out


def rapl_watts(cur, prev, dt):
    """RAPL 두 표본 → {이름: W}. 카운터가 감겼으면 한계를 더해 보정."""
    if not prev or dt <= 0:
        return {}
    out = {}
    for k, (e, m) in cur.items():
        if k in prev:
            d = e - prev[k][0]
            if d < 0 and m:
                d += m
            if d >= 0:
                out[k] = d / 1e6 / dt
    return out


def on_battery():
    """배터리로 방전 중이면 True(전원 연결·충전 중이거나 배터리가 없는 호스트는 False) — 보이지 않을 때 갱신을 멈출지 정하는 기준."""
    try:
        for d in os.listdir("/sys/class/power_supply"):
            base = f"/sys/class/power_supply/{d}"
            if (hm.read(f"{base}/type") or "").strip() == "Battery" and (hm.read(f"{base}/status") or "").strip() == "Discharging":
                return True
    except OSError:
        pass
    return False


def phys_links(wifi_rate=None):
    """{인터페이스: dict(kind, mbps, up)} — **물리 NIC 만**(브리지·tap·docker·tailscale 제외), 내려가 있는 것도 포함(행 수가 들쭉날쭉하지 않게). mbps 는 연결된 링크의 속도(모르면 None).
    유선은 sysfs speed(협상 속도), Wi-Fi 는 접속 AP 의 표기 속도(nmcli RATE — 신호에 따라 실제 링크는 이보다 낮다). wifi_rate 는 호출부가 (느리게) 구해 넘긴다 — 프로세스를 띄우는 일이라 매 표본마다 하지 않는다."""
    out = {}
    base = "/sys/class/net"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for n in names:
        d = os.path.join(base, n)
        if n == "lo" or not os.path.exists(os.path.join(d, "device")):
            continue
        up = (hm.read(f"{d}/operstate") or "").strip() == "up"
        if os.path.isdir(os.path.join(d, "wireless")):
            out[n] = dict(kind="Wi-Fi", mbps=wifi_rate if up else None, up=up)
            continue
        try:
            sp = int((hm.read(f"{d}/speed") or "-1").strip())
        except ValueError:
            sp = -1
        out[n] = dict(kind="유선", mbps=sp if up and sp > 0 else None, up=up)
    return out


def read_wifi_rate():
    """접속 중인 Wi-Fi AP 의 표기 속도(Mbit/s) 또는 None. nmcli 가 없거나 느리면 None."""
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "IN-USE,RATE", "dev", "wifi", "list", "--rescan", "no"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if line.startswith("*:"):
            m = re.match(r"\*:(\d+(?:\.\d+)?)\s*Mbit/s", line)
            return float(m.group(1)) if m else None
    return None


def nvme_link_bytes_s(dev):
    """NVMe 장치의 PCIe 링크 이론 상한(바이트/초) 또는 None — sysfs 의 현재 링크 속도(GT/s)×레인 수×인코딩 효율. 하드웨어가 직접 알려 주는 값이라 표기치 표가 없어도 쓴다."""
    if not dev.startswith("nvme"):
        return None
    try:
        ctrl = os.path.realpath(f"/sys/block/{dev}/device")          # /sys/devices/.../nvme/nvme0
        for base in (os.path.join(ctrl, "device"), os.path.join(os.path.dirname(ctrl), "device")):
            sp, wd = hm.read(f"{base}/current_link_speed"), hm.read(f"{base}/current_link_width")
            if sp and wd:
                gt = float(sp.split()[0])
                eff = 0.8 if gt <= 5.0 else 128 / 130            # PCIe 1·2 세대 8b/10b, 3 세대 이상 128b/130b
                return gt * 1e9 * int(wd) * eff / 8
    except (OSError, ValueError, IndexError):
        pass
    return None


def disk_info():
    """{장치: dict(model, read, write, name, link, bench)} — 모델명은 sysfs, 표기 성능은 hostmetrics.DISK_SPECS(없으면 read/write 가 None), link 는 NVMe PCIe 링크 상한(하드웨어에서 읽음, 없으면 None),
    bench 는 diskbench 의 실측 기록(dict(read, write, at, direct) 또는 None) — 있으면 % 의 분모로 가장 먼저 쓴다."""
    saved = db.load()
    out = {}
    try:
        devs = [d for d in os.listdir("/sys/block") if not d.startswith(("loop", "ram", "zram", "dm-"))]
    except OSError:
        return out
    for d in devs:
        model = " ".join((hm.read(f"/sys/block/{d}/device/model") or "").split())
        spec = next((v for k, v in getattr(hm, "DISK_SPECS", {}).items() if k in model), None)
        out[d] = dict(model=model or d, read=spec["read"] if spec else None, write=spec["write"] if spec else None, name=spec["name"] if spec else None, link=nvme_link_bytes_s(d), bench=saved.get(d))
    return out


def read_cores():
    """[(합계 틱, 유휴 틱)] 코어 순서 — /proc/stat 의 cpuN 줄."""
    out = []
    for line in (hm.read("/proc/stat") or "").splitlines():
        if line.startswith("cpu") and line[3:4].isdigit():
            v = list(map(int, line.split()[1:]))
            out.append((sum(v), v[3] + (v[4] if len(v) > 4 else 0)))
    return out


def rates(cur, prev, dt):
    """{키: (값0 변화율, 값1 변화율)} — 직전 표본이 없거나 누적값이 줄었으면(재설정) 그 키는 뺀다."""
    if prev is None or dt <= 0:
        return {}
    return {k: ((v[0] - prev[k][0]) / dt, (v[1] - prev[k][1]) / dt) for k, v in cur.items() if k in prev and v[0] >= prev[k][0] and v[1] >= prev[k][1]}


def proc_apps(resolver, prev, dt, hz):
    """(앱별 행 리스트 [{app, n, cpu, rss}], 이번 틱표). prev 가 있으면 CPU %(코어 1개=100%)를 낸다. 읽을 수 없는 프로세스는 건너뛴다."""
    page = os.sysconf("SC_PAGE_SIZE")
    info, ppid_of, exe_of = {}, {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = hm.read(f"/proc/{d}/stat")
        if not st:
            continue
        try:
            i, j = st.index("("), st.rindex(")")
            f = st[j + 2:].split()
            pid = int(d)
            info[pid] = (st[i + 1:j], int(f[1]), int(f[11]) + int(f[12]), int(f[21]) * page)
        except (ValueError, IndexError):
            continue
        ppid_of[pid] = info[pid][1]
        try:
            exe_of[pid] = os.path.basename(os.readlink(f"/proc/{d}/exe"))
        except OSError:
            exe_of[pid] = ""

    def cmdline(pid):
        return [a for a in (hm.read(f"/proc/{pid}/cmdline") or "").split("\0") if a]
    ticks, apps = {}, {}
    for pid, (comm, ppid, tk, rss) in info.items():
        ticks[pid] = tk
        name = resolver.resolve(pid, comm, exe_of.get(pid, ""), ppid, exe_of, ppid_of, cmdline)
        a = apps.setdefault(name, dict(app=name, n=0, cpu=0.0, rss=0))
        a["n"] += 1
        a["rss"] += rss
        if prev is not None and dt > 0 and pid in prev:
            a["cpu"] += max(tk - prev[pid], 0) / hz / dt * 100
    return sorted(apps.values(), key=lambda r: (-r["cpu"], -r["rss"])), ticks


def has_battery():
    base = "/sys/class/power_supply"
    try:
        return any((hm.read(f"{base}/{d}/type") or "").strip() == "Battery" for d in os.listdir(base))
    except OSError:
        return False


class LiveSampler:
    """`sample()` 를 부를 때마다 직전 호출과의 차이로 변화율을 계산한다(첫 호출은 구간 값이 None).
    이미 재는 중이면 기다리지 않고 None 을 돌려준다 — 느린 첫 표본 중에 타이머가 겹쳐 직전 표본·시각이 뒤섞이는 것을 막는다."""

    def __init__(self, slow_every=5.0, laptop=None):
        self.laptop = has_battery() if laptop is None else laptop         # 전력·배터리 표본은 배터리가 있는 호스트에서만
        self.slow_every = self.base_slow_every = slow_every
        self._slow_ms = 0.0
        self._b = None
        self._t = None
        self._net = self._disk = self._cores = None
        self._slow_t = None
        self._slow = {}
        self._sbegin = None
        self._ticks = None
        self._apps_t = None
        self._links = {}
        self._rapl = None
        self._disk_info = disk_info()
        self.resolver = ap.AppResolver()
        self.hz = os.sysconf("SC_CLK_TCK")
        self._lock = threading.Lock()

    def sample(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self._sample()
        finally:
            self._lock.release()

    def _sample(self):
        t0 = time.monotonic()
        measured = self._b is not None
        s = hm.end(self._b or hm.begin(), measured)
        self._b = hm.begin()
        dt = (t0 - self._t) if self._t else 0
        net, disk = read_net(), read_disk()
        s["net"], s["disk"] = rates(net, self._net, dt), rates(disk, self._disk, dt)
        s["disk_info"] = self._disk_info
        s["power"] = read_power() if self.laptop else None
        rp = read_rapl() if self.laptop else {}
        s["rapl_w"] = rapl_watts(rp, self._rapl, dt)
        self._rapl = rp
        self._net, self._disk = net, disk
        cores = read_cores()
        s["cores"] = [None if not self._cores or i >= len(self._cores) or c[0] == self._cores[i][0] else (1 - (c[1] - self._cores[i][1]) / (c[0] - self._cores[i][0])) * 100
                      for i, c in enumerate(cores)]
        self._cores = cores
        s["meminfo"] = hm.meminfo()
        refreshed = self._slow_t is None or t0 - self._slow_t >= self.slow_every
        if refreshed:
            self._refresh_slow(t0)
        s.update(self._slow)
        s["measured"] = measured
        self._t = t0
        s["t"] = time.time()                                    # 표본 시각 — 화면에 보여 낡은 값을 알아보게 한다
        s["cost_ms"] = (time.monotonic() - t0) * 1000
        s["slow_ms"] = self._slow_ms
        s["fast_ms"] = max(s["cost_ms"] - (self._slow_ms if refreshed else 0), 0)   # 느린 항목을 새로 잰 표본이면 그 몫을 뺀 값 — 갱신 간격 조절은 이 값으로 한다
        return s

    def _refresh_slow(self, t0):
        ts = time.monotonic()
        adt = (t0 - self._apps_t) if self._apps_t else 0
        apps, self._ticks = proc_apps(self.resolver, self._ticks, adt, self.hz)
        self._apps_t = t0
        first = self._sbegin is None
        sess = hm.sessions_end(self._sbegin or hm.sessions_begin(), not first, False)
        self._sbegin = hm.sessions_begin()
        self._links = phys_links(read_wifi_rate())               # nmcli 호출이 있어 느린 항목과 같은 주기로
        self._slow = dict(links=self._links, apps=apps[:12], cons=hm.cgroup_consumers(8), sessions=sess, apps_measured=adt > 0)
        self._slow_t = t0
        self._slow_ms = (time.monotonic() - ts) * 1000
        self.slow_every = max(self.base_slow_every, self._slow_ms / 1000 * 10)    # 느린 항목이 느려질수록(바쁜 호스트) 드물게 잰다(CPU 약 10% 이하)
        if adt == 0:                                  # 첫 스캔은 앱 CPU 를 잴 직전 표본이 없다 — 주기를 기다리지 않고 2초 뒤 한 번 더 재서 앱 CPU 표를 바로 채운다
            self._slow_t = t0 - self.slow_every + 2.0


# ---------- 표시 조각(Text) ----------
def fit(s, n):
    """칸 폭(한글 2칸) 기준으로 n 칸에 맞춘다 — 길면 자르고(…) 짧으면 공백으로 채움. f-string 의 :<n 은 글자 수라 한글 표가 어긋난다."""
    s = str(s)
    if cell_len(s) > n:
        while s and cell_len(s) > n - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (n - cell_len(s))


def human_bytes(x, per_s=False):
    if x is None:
        return "-"
    for u, d in (("GiB", GIB), ("MiB", MIB), ("KiB", 1024)):
        if abs(x) >= d:
            return f"{x / d:.1f} {u}" + ("/s" if per_s else "")
    return f"{x:.0f} B" + ("/s" if per_s else "")


def pct_style(v, warn, bad):
    return "red" if v >= bad else "yellow" if v >= warn else "green"


TRACK_BG = "grey23"         # 안 찬 막대 구간(트랙)의 배경색 — 짙은 회색
TRACK_STYLE = f"on {TRACK_BG}"


def track_bar(frac, width, style):
    """채운 부분(style)과 **안 찬 부분을 짙은 회색 배경(트랙)** 으로 이은 막대. 길이는 항상 width 칸.
    1/8 칸 단위의 걸친 칸(▏~▉)은 글자 색 = style, **배경 = 트랙색** 이라 그 칸의 빈 쪽도 검정이 아니라 회색으로 이어진다."""
    frac = 0.0 if frac != frac else max(0.0, min(1.0, frac))
    eighths = round(frac * width * 8)
    full, part = divmod(eighths, 8)
    t = Text()
    if full:
        t.append("█" * full, style=style)
    if part and full < width:
        t.append(pg.BLOCKS[part], style=f"{style} on {TRACK_BG}")
        full += 1
    t.append(" " * (width - full), style=f"on {TRACK_BG}")
    return t


def render_verdict(s):
    lv, why = hm.verdict(s)
    ax = hm.verdict_axes(s)
    t = Text(" ")
    t.append(f" {lv} ", style=LEVEL_STYLE.get(lv, "bold") + " reverse")
    t.append(f"  속도 {hm.NAMES[ax['speed'][0]]} · 용량 {hm.NAMES[ax['capacity'][0]]}", style="grey70")
    t.append(f"  구간 {s['window_s']}s" + ("" if s["measured"] else " (첫 표본)") + (f" · 표본 {time.strftime('%H:%M:%S', time.localtime(s['t']))}" if s.get("t") else ""), style="grey50")
    for w in why[:3] or ["압박 징후 없음"]:
        t.append("\n  " + w, style="grey70")
    g = hm.capacity_guide(s)
    t.append(f"\n  OOM 까지 여유 {hm.headroom(s) / GIB:.1f} GiB(MemAvailable + 스왑 여유)", style="bold")
    t.append(f"\n  새 작업: ~{g[0][0]:.1f} GiB 바로 · ~{g[1][0]:.1f} 캐시 밀어냄 · ~{g[2][0]:.1f} 스왑 의존 · 그 이상 OOM 위험", style="grey62")
    return t


def mem_segments(s):
    """메모리 구성 [(이름, 바이트, 스타일)] — 합이 총량을 넘지 않게 하고 나머지는 '기타(커널 등)'."""
    m, mi = s["mem"], s["meminfo"]
    total = m["total"]
    parts = [("실제 사용(anon)", m["anon"], "red"), ("tmpfs·공유(Shmem)", m["shmem"], "dark_orange"),
             ("활성 캐시", m["active_file"], "yellow"), ("식은 캐시", mi.get("Inactive(file)", 0), "cyan"),
             ("빈 메모리", mi.get("MemFree", 0), "green")]
    # ZRAM 은 압축한 데이터를 RAM 에 두므로 MemFree 에서 빠져 있다 — 따로 보여야 '기타'가 영문 모를 덩어리로 남지 않는다
    zram = sum(d.get("compressed", 0) for d in s["swap"]["devices"] if d["kind"] == "zram")
    parts.append(("ZRAM 압축 점유", zram, "magenta"))
    parts.append(("커널 slab", mi.get("Slab", 0), "dark_cyan"))
    rest = max(total - sum(b for _, b, _ in parts), 0)
    return parts + [("그 밖(페이지테이블·드라이버 등)", rest, "grey50")]


def seg_bar(parts, width):
    """segments 를 폭 width 칸으로 — 비율이 큰 순서로 나머지 칸을 배분(합이 정확히 width)."""
    tot = sum(b for _, b, _ in parts) or 1
    raw = [b / tot * width for _, b, _ in parts]
    cells = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: -(raw[i] - cells[i]))[:width - sum(cells)]:
        cells[i] += 1
    t = Text()
    for (_, _, st), n in zip(parts, cells):
        t.append("█" * n, style=st)
    return t


def render_mem(s, w):
    m, sw = s["mem"], s["swap"]
    parts = mem_segments(s)
    t = Text(" ")
    t.append_text(seg_bar(parts, max(10, w - 3)))
    lw = max(cell_len(n) for n, _, _ in parts) + 2      # 범례 이름 칸 = 가장 긴 이름(한글 2칸) + 2
    for name, b, st in parts:
        t.append("\n  ")
        t.append("■", style=st)
        t.append(f" {fit(name, lw)}{b / GIB:6.1f} GiB  {b / m['total'] * 100:4.0f}%")
    t.append(f"\n\n  바로 쓸 수 있음(보수적) {m['reclaimable_floor'] / GIB:.1f} GiB = 빈 메모리 + 식은 캐시", style="bold")
    t.append(f"\n  커널 MemAvailable {m['available_raw'] / GIB:.1f} GiB — 활성 캐시·회수 가능 slab({m['sreclaimable'] / GIB:.1f} GiB)을 더한 낙관값", style="grey62")
    dev = ", ".join(f"{d['kind']} {d['used'] / GIB:.1f}/{d['size'] / GIB:.1f}" + (f"(RAM 점유 {d['compressed'] / GIB:.1f})" if "compressed" in d else "") for d in sw["devices"]) or "없음"
    t.append(f"\n  스왑 사용 {sw['used'] / GIB:.1f}/{sw['total'] / GIB:.1f} GiB — {dev}", style="grey70")
    if s["tmpfs"]:
        t.append("\n  tmpfs: " + ", ".join(f"{p} {u / GIB:.1f} GiB" for p, u, _ in s["tmpfs"][:3]) + " (스왑 몫 포함, Shmem=RAM분)", style="grey62")
    return t


def render_pressure(s):
    ps, r = s["psi"], s["rates"]
    t = Text()

    def fv(x):
        return "-" if x is None else f"{x:.1f}%"
    for k, name in (("memory", "메모리"), ("cpu", "CPU"), ("io", "IO")):
        p = ps[k]
        some = p["some_pct"] if p["some_pct"] is not None else p["some_avg10"]
        full = p["full_pct"] if p["full_pct"] is not None else p["full_avg10"]
        t.append(f" {fit(name, 7)}some ")
        t.append(f"{fv(some):>6}", style=pct_style(some or 0, 3, 10))
        if k != "cpu":
            t.append("  full ")
            t.append(f"{fv(full):>6}", style=pct_style(full or 0, 0.5, 1))
        t.append(f"   avg60 some {fv(p.get('some_avg60')):>5}" + (f" full {fv(p.get('full_avg60')):>5}" if k != "cpu" else ""), style="grey62")
        t.append("\n")
    cg = s.get("psi_cgroups") or []
    t.append("\n 메모리 대기 주체: ", style="grey70")
    t.append(" · ".join(f"{hm.friendly(c['path'])[:26]} {c['some_pct']:.1f}%" for c in cg[:3]) if cg else "없음", style="default" if cg else "grey50")
    t.append("\n 스왑 되읽기 pswpin ")
    t.append("-" if r["pswpin"] is None else f"{r['pswpin']:.0f}/s", style="default")
    t.append("  pswpout " + ("-" if r["pswpout"] is None else f"{r['pswpout']:.0f}/s") + "  (정보 — 판정은 PSI·OOM 여유)", style="grey62")
    t.append("\n PSI = 기다린 시간 비율(some 일부·full 전부). 판정은 avg60", style="grey50")
    return t


def render_io(s, w):
    t = Text()
    cores = s["cores"]
    t.append(f" CPU {s['cpu']['count']}스레드 — 평균 " + ("-" if s["cpu"]["busy_pct"] is None else f"{s['cpu']['busy_pct']:.0f}%") + f" · load {s['cpu']['load'][0]:.1f}\n", style="bold")
    per_row = 2 if len(cores) <= 4 else 4                  # 듀얼·쿼드 같은 적은 코어는 2열, 그 이상은 4열
    while per_row > 1 and (w - 2) // per_row - 9 < 4:     # 칸 하나 = 번호 4 + 막대 + 값 4 + 공백 — 막대가 4칸도 못 나오면 열을 줄인다
        per_row //= 2
    bw = max(4, min(12, (w - 2) // per_row - 9))
    for i, v in enumerate(cores):
        t.append(f" {i:>2} ", style="grey62")
        t.append_text(track_bar((v or 0) / 100, bw, pct_style(v or 0, 50, 85) if v is not None else TRACK_STYLE))
        t.append(f"{'-' if v is None else format(v, '.0f') + '%':>4} ")
        if (i + 1) % per_row == 0 or i == len(cores) - 1:
            t.append("\n")
    t.append("\n 네트워크 — 링크 속도 대비(수신↓ 송신↑)")
    links = s.get("links", {})
    net = s["net"]
    for k in sorted(links, key=lambda k: (links[k]["kind"] != "유선", k)):          # 물리 NIC 는 늘 같은 순서·같은 행 수(내려가 있으면 한 줄)
        ln = links[k]
        if not ln.get("up", True):
            t.append(f"\n  {k}  {ln['kind']} — 연결 안 됨", style="grey50")
            continue
        rx, tx = net.get(k, (0.0, 0.0))
        mb = ln.get("mbps")
        t.append(f"\n  {k}  {ln['kind']} " + (f"링크 {mb:g} Mbit/s" + ("*" if ln["kind"] == "Wi-Fi" else "") if mb else "링크 속도 알 수 없음(% 없음)"), style="bold")
        t.append("\n")
        cap = mb * 125000 if mb else None            # Mbit/s → 바이트/초
        t.append_text(_rate_pair(("↓", rx, cap), ("↑", tx, cap), w))
    virt = [v for k, v in net.items() if k not in links]    # 브리지·tap·VPN 등은 한 줄 합계로(생겼다 없어져도 행 수가 안 변함)
    t.append("\n  가상 인터페이스 합계(브리지·tap·VPN 등)", style="grey62")
    t.append("\n")
    t.append_text(_rate_pair(("↓", sum(v[0] for v in virt), None), ("↑", sum(v[1] for v in virt), None), w))
    if any(ln.get("kind") == "Wi-Fi" and ln.get("up", True) and ln.get("mbps") for ln in links.values()):
        t.append("\n  * Wi-Fi: AP 표기 최대 속도(실제 링크는 신호에 따라 낮음)", style="grey50")
    t.append("\n 디스크 — 실측(없으면 표기·PCIe 링크 상한) 대비(읽기/쓰기)")
    info = s.get("disk_info", {})
    if s["disk"]:
        for k, (rd, wr) in sorted(s["disk"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:3]:
            di = info.get(k, {})
            sp_r, sp_w, link, bn = di.get("read"), di.get("write"), di.get("link"), di.get("bench")
            if bn:
                cap_r, cap_w, basis = bn["read"], bn["write"], f"실측 R {bn['read'] / 1e6:,.0f}/W {bn['write'] / 1e6:,.0f} MB/s({time.strftime('%m-%d', time.localtime(bn['at']))})"
            elif sp_r:
                cap_r, cap_w, basis = sp_r, sp_w, f"표기 R {sp_r / 1e6:g}/W {sp_w / 1e6:g} MB/s"
            elif link:
                cap_r = cap_w = link
                basis = f"PCIe 링크 상한 {link / 1e6:,.0f} MB/s(표기치 미등록)"
            else:
                cap_r = cap_w = None
                basis = "(표기·링크 정보 없음 — % 없음)"
            t.append(f"\n  {k}  {di.get('name') or di.get('model') or ''}  {basis}", style="bold" if cap_r else "grey62")
            t.append("\n")
            t.append_text(_rate_pair(("읽기", rd, cap_r), ("쓰기", wr, cap_w), w))
        if not any(v.get("bench") for v in info.values()):
            t.append("\n  d: 짧은 디스크 벤치마크로 이 시스템의 실측 속도를 기준으로 쓰기", style="grey50")
    else:
        t.append("\n  -", style="grey50")
    return t


def _rate_pair(a, b, w):
    """두 방향(↓↑ · 읽기/쓰기)을 한 쌍으로: 윗줄 `라벨 속도 %`, 아랫줄은 칸 폭 전체를 쓰는 **그래프 막대**(분모 cap 이 있을 때만). a·b = (라벨, 바이트/초, cap)."""
    half = max(24, (w - 2) // 2)
    cells = []
    for label, rate, cap in (a, b):
        num = Text(f"    {label} {human_bytes(rate, True):>11}")
        bar = Text()
        if cap:
            frac = rate / cap
            num.append(f"  {frac * 100:4.1f}%" if frac >= 0.001 else "  <.1% ")
            bar = Text("    ")
            bar.append_text(track_bar(min(frac, 1.0), half - 6, pct_style(frac * 100, 50, 85)))
        cells.append((num, bar))
    out = Text()
    for num, _ in cells:
        out.append_text(num)
        out.append(" " * max(half - cell_len(num.plain), 0))
    if any(bar.plain for _, bar in cells):
        out.append("\n")
        for _, bar in cells:
            out.append_text(bar)
            out.append(" " * max(half - cell_len(bar.plain), 0))
    return out


def _hm(h):
    """시간(float) → `3시간 22분` / `45분`."""
    if h is None:
        return "-"
    m = round(h * 60)
    return f"{m // 60}시간 {m % 60:02d}분" if m >= 60 else f"{m}분"


def render_power(s, w):
    """노트북 전용 「전력·배터리」 — 배터리 잔량 막대, 방전·충전 전력과 남은 시간, AC, RAPL(psys 시스템 전체·pkg CPU 패키지, 읽을 수 있을 때만). 지금 값만(이력은 usageui 기록 탭)."""
    pw = s.get("power")
    t = Text()
    if not pw:
        t.append(" 배터리 정보를 읽지 못함", style="grey50")
        return t
    pct = pw["percent"]
    st = {"Discharging": "방전 중", "Charging": "충전 중", "Full": "완충", "Not charging": "충전 안 함(보호 설정 등)"}.get(pw["status"], pw["status"] or "상태 모름")
    ac = {True: "AC 연결", False: "AC 없음(배터리 구동)", None: "AC 정보 없음"}[pw["ac"]]
    t.append(" 배터리 ", style="bold")
    t.append("-" if pct is None else f"{pct:.0f}%", style=pct_style(100 - (pct or 0), 50, 80) if pct is not None else "grey50")
    wh = f" ({pw['now_wh']:.1f}/{pw['full_wh']:.1f} Wh)" if pw["now_wh"] and pw["full_wh"] else ""
    t.append(f"{wh} · {st} · {ac}\n")
    bw = max(10, w - 6)
    t.append("  ")
    t.append_text(track_bar((pct or 0) / 100, bw, "green" if (pct or 0) >= 30 else ("yellow" if (pct or 0) >= 15 else "red")))
    t.append("\n")
    if pw["watts"] is not None:
        if pw["status"] == "Discharging":
            t.append(f" 방전 {pw['watts']:.1f} W", style="bold")
            t.append(f" · 이 속도면 약 {_hm(pw['eta_h'])} 남음" if pw["eta_h"] else " · 남은 시간 계산 불가(전력 0.5 W 미만)")
        elif pw["status"] == "Charging":
            t.append(f" 충전 +{pw['watts']:.1f} W", style="bold")
            t.append(f" · 만충까지 약 {_hm(pw['eta_h'])}" if pw["eta_h"] else "")
        else:
            t.append(f" 배터리 전력 {pw['watts']:.1f} W")
    else:
        t.append(" 배터리 전력을 읽지 못함", style="grey50")
    rw = s.get("rapl_w") or {}
    bits = [f"{lab} {rw[k]:.1f} W" for k, lab in (("psys", "시스템 전체(psys)"), ("pkg", "CPU 패키지")) if k in rw]
    t.append("\n " + (" · ".join(bits) if bits else "RAPL(psys·패키지 전력) 못 읽음 — 권한 또는 미지원") + (" — 최근 표본 간격 평균" if bits else ""), style="grey62")
    return t


def render_top(s, w):
    t = Text(" 메모리 — cgroup 의 anon+shmem 자기 몫 상위\n", style="bold")
    for p, b in s.get("cons", [])[:6]:
        t.append(f"  {b / GIB:5.1f} GiB  {hm.friendly(p)[:max(10, w - 18)]}\n")
    t.append("\n CPU — 앱 단위(코어 1개=100%)" + ("" if s.get("apps_measured") else " · 첫 표본 후 표시") + "\n", style="bold")
    nw = max(8, w - 36)       # 이름 칸: 줄이 박스 폭을 넘어 줄바꿈되지 않게 꼬리(프로세스 수·RSS)를 뺀 나머지
    for a in s.get("apps", [])[:6]:
        if s.get("apps_measured"):
            t.append(f"  {a['cpu']:6.1f}%  {fit(a['app'], nw)} {a['n']:>4}개 {a['rss'] / MIB:7.0f} MiB\n")
    return t


def render_sessions(s):
    rows = s.get("sessions", [])
    if not rows:
        return Text(" 실행 중인 LLM CLI 세션 없음", style="grey50")
    busy = sum(1 for r in rows if r[7] and r[7]["status"] == "busy")
    t = Text(f" {len(rows)}개 — 작동중 {busy} · 대기 {len(rows) - busy} · PSS 합 {sum(r[0] for r in rows) / 1024:.1f} GiB\n", style="bold")
    for pss, pid, cwd, n, cpu, age, kind, m, kids in rows[:8]:
        st = {"busy": "작동중", "idle": "대기"}.get(m["status"], m["status"]) if m else "상태 기록 없음"
        run = len(m["sub"]["running"]) if m else 0
        t.append("  ")
        t.append(fit(st, 8), style="green" if st == "작동중" else "grey62")
        t.append(f" {fit(m['name'] if m else kind, 15)}{fit(cwd, 13)}PSS {pss:5.0f} MiB · 프로세스 {n}" + (f" · 서브에이전트 {run}" if run else "") + "\n")
    return t
