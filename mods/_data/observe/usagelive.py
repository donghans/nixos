"""usagelive — usageui 「실시간」 탭의 샘플링과 박스별 표시 조각. 시간축 그래프는 없고 **지금 값**(직전 표본과의 차이로 낸 변화율 포함)만 보인다.

- 측정·판정은 hostmetrics(호스트 측정 모듈, donghans-host-resources 스킬의 정본을 같은 디렉터리로 복사해 쓴다)를 그대로 쓴다.
- 읽기 전용. 이력은 저장하지 않는다. 샘플링을 언제 돌릴지(탭 활성·창 포커스 때만)는 호출부(usageui)가 정한다.
- 느린 항목(앱 CPU 상위·cgroup 소비자·LLM 세션 PSS)은 `slow_every` 초마다만 새로 잰다 — PSS 전체 순회와 /proc 전체 스캔이 1초 간격에는 비싸다.
  LLM 세션의 ctx 보충(donghans ctx sql subprocess)은 부르지 않는다.
- 개인정보: 프로세스는 이름만 쓴다. electron 앱 이름을 정하려 루트 프로세스의 명령줄을 읽지만(observe_apps) 저장·표시하지 않는다.
"""
from __future__ import annotations

import os
import sys
import threading
import time

from rich.text import Text

try:
    import hostmetrics as hm
except ImportError:  # 소스에서 직접 실행할 때(설치본은 같은 디렉터리에 복사됨)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude-skills", "donghans-host-resources", "scripts"))
    import hostmetrics as hm
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


class LiveSampler:
    """`sample()` 를 부를 때마다 직전 호출과의 차이로 변화율을 계산한다(첫 호출은 구간 값이 None).
    이미 재는 중이면 기다리지 않고 None 을 돌려준다 — 느린 첫 표본 중에 타이머가 겹쳐 직전 표본·시각이 뒤섞이는 것을 막는다."""

    def __init__(self, slow_every=5.0):
        self.slow_every = slow_every
        self._b = None
        self._t = None
        self._net = self._disk = self._cores = None
        self._slow_t = None
        self._slow = {}
        self._sbegin = None
        self._ticks = None
        self._apps_t = None
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
        self._net, self._disk = net, disk
        cores = read_cores()
        s["cores"] = [None if not self._cores or i >= len(self._cores) or c[0] == self._cores[i][0] else (1 - (c[1] - self._cores[i][1]) / (c[0] - self._cores[i][0])) * 100
                      for i, c in enumerate(cores)]
        self._cores = cores
        s["meminfo"] = hm.meminfo()
        if self._slow_t is None or t0 - self._slow_t >= self.slow_every:
            self._refresh_slow(t0)
        s.update(self._slow)
        s["measured"] = measured
        self._t = t0
        s["cost_ms"] = (time.monotonic() - t0) * 1000
        return s

    def _refresh_slow(self, t0):
        adt = (t0 - self._apps_t) if self._apps_t else 0
        apps, self._ticks = proc_apps(self.resolver, self._ticks, adt, self.hz)
        self._apps_t = t0
        first = self._sbegin is None
        sess = hm.sessions_end(self._sbegin or hm.sessions_begin(), not first, False)
        self._sbegin = hm.sessions_begin()
        self._slow = dict(apps=apps[:12], cons=hm.cgroup_consumers(8), sessions=sess, apps_measured=adt > 0)
        self._slow_t = t0


# ---------- 표시 조각(Text) ----------
def human_bytes(x, per_s=False):
    if x is None:
        return "-"
    for u, d in (("GiB", GIB), ("MiB", MIB), ("KiB", 1024)):
        if abs(x) >= d:
            return f"{x / d:.1f} {u}" + ("/s" if per_s else "")
    return f"{x:.0f} B" + ("/s" if per_s else "")


def pct_style(v, warn, bad):
    return "red" if v >= bad else "yellow" if v >= warn else "green"


def render_verdict(s):
    lv, why = hm.verdict(s)
    ax = hm.verdict_axes(s)
    t = Text(" ")
    t.append(f" {lv} ", style=LEVEL_STYLE.get(lv, "bold") + " reverse")
    t.append(f"  속도 {hm.NAMES[ax['speed'][0]]} · 용량 {hm.NAMES[ax['capacity'][0]]}", style="grey70")
    t.append(f"  구간 {s['window_s']}s" + ("" if s["measured"] else " (첫 표본)"), style="grey50")
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
    for name, b, st in parts:
        t.append("\n  ")
        t.append("■", style=st)
        t.append(f" {name:<22}{b / GIB:6.1f} GiB  {b / m['total'] * 100:4.0f}%")
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
        t.append(f" {name:<4} some ")
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
    t.append("\n PSI = 사용량이 아니라 '기다렸는가': some=일부 작업 대기, full=전부 대기. 판정은 지속(avg60) 기준", style="grey50")
    return t


def render_io(s, w):
    t = Text()
    cores = s["cores"]
    t.append(f" CPU {s['cpu']['count']}스레드 — 평균 " + ("-" if s["cpu"]["busy_pct"] is None else f"{s['cpu']['busy_pct']:.0f}%") + f" · load {s['cpu']['load'][0]:.1f}\n", style="bold")
    bw = 8
    per_row = max(1, (w - 2) // (bw + 11))
    for i, v in enumerate(cores):
        t.append(f" {i:>2} ", style="grey62")
        t.append(pg.hbar((v or 0) / 100, bw), style=pct_style(v or 0, 50, 85) if v is not None else "grey35")
        t.append(f"{'-' if v is None else format(v, '.0f') + '%':>4} ")
        if (i + 1) % per_row == 0 or i == len(cores) - 1:
            t.append("\n")
    t.append("\n 네트워크(수신/송신)")
    if s["net"]:
        for k, (rx, tx) in sorted(s["net"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:4]:
            t.append(f"\n  {k:<12}{human_bytes(rx, True):>12} / {human_bytes(tx, True):<12}")
    else:
        t.append("\n  -", style="grey50")
    t.append("\n 디스크(읽기/쓰기)")
    if s["disk"]:
        for k, (rd, wr) in sorted(s["disk"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:3]:
            t.append(f"\n  {k:<12}{human_bytes(rd, True):>12} / {human_bytes(wr, True):<12}")
    else:
        t.append("\n  -", style="grey50")
    return t


def render_top(s, w):
    t = Text(" 메모리 — cgroup 의 anon+shmem 자기 몫 상위\n", style="bold")
    for p, b in s.get("cons", [])[:6]:
        t.append(f"  {b / GIB:5.1f} GiB  {hm.friendly(p)[:max(10, w - 18)]}\n")
    t.append("\n CPU — 앱 단위(코어 1개=100%)" + ("" if s.get("apps_measured") else " · 첫 표본 후 표시") + "\n", style="bold")
    nw = max(8, w - 36)       # 이름 칸: 줄이 박스 폭을 넘어 줄바꿈되지 않게 꼬리(프로세스 수·RSS)를 뺀 나머지
    for a in s.get("apps", [])[:6]:
        if s.get("apps_measured"):
            t.append(f"  {a['cpu']:6.1f}%  {a['app'][:nw]:<{nw}} {a['n']:>4}개 {a['rss'] / MIB:7.0f} MiB\n")
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
        t.append(f"{st:<6}", style="green" if st == "작동중" else "grey62")
        t.append(f" {(m['name'] if m else kind)[:14]:<14} {cwd[:12]:<12} PSS {pss:5.0f} MiB · 프로세스 {n}" + (f" · 서브에이전트 {run}" if run else "") + "\n")
    return t
