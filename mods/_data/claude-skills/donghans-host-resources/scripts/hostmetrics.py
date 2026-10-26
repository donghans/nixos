#!/usr/bin/env python3
"""hostmetrics — 호스트 자원·LLM 세션 **측정과 판정**(출력 없음). hostres.py(CLI)·usageui 실시간 탭·procui 가 함께 쓴다.

정본은 이 스킬 폴더다(observe.nix 가 같은 파일을 usageui·procui 디렉터리로 복사한다 — 복제본을 따로 고치지 않는다).
표준 라이브러리만 쓰고 읽기 전용이다. print 는 없다.
증분 측정: `begin()` → (시간 경과) → `end(b)` 로 변화율을 낸다. 실시간 갱신은 end 의 결과를 다음 begin 대신 쓸 수 없으므로
호출부가 `b = begin()` 을 매 주기 새로 만든다(snapshot(secs) 은 begin·sleep·end 의 얇은 묶음).
폴링에 쓰지 말 것: ctx_last_chat(donghans ctx sql subprocess)·session_meta 의 ctx 보충(10초 timeout) — 실시간 호출부는 session_meta(use_ctx=False).
"""
import datetime, glob, json, os, socket, subprocess, time

GIB = 1 << 30
MIB = 1 << 20


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def meminfo():
    d = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.split()[0]) * 1024
    return d


def vmstat():
    d = {}
    for line in (read("/proc/vmstat") or "").splitlines():
        k, v = line.split()
        d[k] = int(v)
    return d


def psi(kind):
    """{'some': (avg10, total_us, avg60), 'full': (...)}"""
    out = {}
    for line in (read(f"/proc/pressure/{kind}") or "").splitlines():
        p = line.split()
        kv = dict(x.split("=") for x in p[1:])
        out[p[0]] = (float(kv["avg10"]), int(kv["total"]), float(kv.get("avg60", 0)))
    return out


def cgroup_psi():
    """{cgroup 상대 경로: (some 누적 µs, full 누적 µs, some avg10, full avg10)} — memory.pressure 가 있는 cgroup 전부.
    PSI 는 계층 합산이라 상위 cgroup 값에는 하위 몫이 들어 있다(누가 만들었는지는 pressure_culprits 가 가장 깊은 쪽으로 좁힌다)."""
    root, out = "/sys/fs/cgroup", {}
    for dp, dn, fn in os.walk(root):
        if "memory.pressure" not in fn:
            continue
        v = {}
        for line in (read(os.path.join(dp, "memory.pressure")) or "").splitlines():
            p = line.split()
            try:
                kv = dict(x.split("=") for x in p[1:])
                v[p[0]] = (float(kv["avg10"]), int(kv["total"]))
            except (ValueError, KeyError, IndexError):
                continue
        if "some" in v:
            out[os.path.relpath(dp, root) if dp != root else "/"] = (v["some"][1], v.get("full", (0, 0))[1], v["some"][0], v.get("full", (0, 0))[0])
    return out


def pressure_culprits(c0, c1, dt, measured, top=4, min_pct=0.5):
    """메모리 대기를 만든 cgroup 상위. 구간(c0→c1)이 있으면 구간 stall %, 없으면 avg10. 하위가 값의 80% 이상을 차지하면 상위는 빼고 하위를 낸다."""
    rows = []
    for path, (st, ft, s10, f10) in c1.items():
        if path == "/":
            continue
        if measured and path in c0:
            some = (st - c0[path][0]) / (dt * 1e6) * 100
            full = (ft - c0[path][1]) / (dt * 1e6) * 100
        else:
            some, full = s10, f10
        if some >= min_pct:
            rows.append(dict(path=path, some_pct=round(some, 2), full_pct=round(full, 2), some_avg10=s10, full_avg10=f10))
    rows.sort(key=lambda r: -r["some_pct"])
    keep = []
    for r in rows:
        if any(o is not r and o["path"].startswith(r["path"] + "/") and o["some_pct"] >= 0.8 * r["some_pct"] for o in rows):
            continue
        keep.append(r)
    return keep[:top]


def cpu_times():
    f = (read("/proc/stat") or "cpu 0 0 0 0 0 0 0 0").splitlines()[0].split()[1:]
    v = list(map(int, f))
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v), idle


def swaps():
    """스왑 장치별 종류·크기·사용 + ZRAM 압축 실측"""
    res = []
    for line in (read("/proc/swaps") or "").splitlines()[1:]:
        name, typ, size, used, prio = line.split()[:5]
        kind = "zram" if "zram" in name else "disk"
        item = dict(name=name, kind=kind, size=int(size) * 1024, used=int(used) * 1024)
        if kind == "zram":
            mm = (read(f"/sys/block/{os.path.basename(name)}/mm_stat") or "").split()
            if len(mm) >= 3:
                item["orig"], item["compressed"] = int(mm[0]), int(mm[1])  # 압축 전 데이터·실제 RAM 점유
        res.append(item)
    return res


def tmpfs_use(min_bytes=100 * MIB):
    out = []
    for line in (read("/proc/mounts") or "").splitlines():
        p = line.split()
        if p[2] != "tmpfs":
            continue
        try:
            s = os.statvfs(p[1])
        except OSError:
            continue
        used = (s.f_blocks - s.f_bfree) * s.f_frsize
        if used >= min_bytes:
            out.append((p[1], used, s.f_blocks * s.f_frsize))
    return sorted(out, key=lambda x: -x[1])


def cgroup_consumers(top, min_bytes=100 * MIB):
    """cgroup 별 anon+shmem(회수 어려운 메모리)의 「자기 몫」(하위 cgroup 몫을 뺀 값) 상위 N."""
    root = "/sys/fs/cgroup"
    val, kids = {}, {}
    for dp, dn, fn in os.walk(root):
        if "memory.stat" not in fn:
            continue
        st = {}
        for line in (read(os.path.join(dp, "memory.stat")) or "").splitlines():
            k, v = line.split()
            st[k] = int(v)
        val[dp] = st.get("anon", 0) + st.get("shmem", 0)
        par = os.path.dirname(dp)
        kids.setdefault(par, []).append(dp)
    rows = []
    for dp, v in val.items():
        own = v - sum(val.get(c, 0) for c in kids.get(dp, []))
        if own >= min_bytes:
            rows.append((os.path.relpath(dp, root) if dp != root else "/", own))
    return sorted(rows, key=lambda x: -x[1])[:top]



def begin():
    """증분 측정의 0 시점 표본."""
    return dict(m0=meminfo(), v0=vmstat(), p0={k: psi(k) for k in ("memory", "cpu", "io")}, c0=cpu_times(), cg0=cgroup_psi(), t0=time.monotonic())


def end(b, measured=True):
    """1 시점 표본을 재고 b(begin 결과) 이후 변화율을 낸다. measured=False 면 구간 값(PSI·변화율·CPU 사용률)은 None."""
    m0, v0, p0, c0, t0 = b["m0"], b["v0"], b["p0"], b["c0"], b["t0"]
    cg1 = cgroup_psi()
    m1, v1 = meminfo(), vmstat()
    p1 = {k: psi(k) for k in ("memory", "cpu", "io")}
    c1 = cpu_times()
    dt = max(time.monotonic() - t0, 1e-6)

    def pct(kind, level):
        a, bb = p0[kind].get(level), p1[kind].get(level)
        if not a or not bb or not measured:
            return None
        return (bb[1] - a[1]) / (dt * 1e6) * 100

    rate = lambda k: (v1.get(k, 0) - v0.get(k, 0)) / dt if measured else None
    sw = swaps()
    avail, shmem = m1["MemAvailable"], m1.get("Shmem", 0)
    swap_total, swap_free = m1.get("SwapTotal", 0), m1.get("SwapFree", 0)
    s = dict(
        window_s=round(dt, 1),
        mem=dict(
            total=m1["MemTotal"], available_raw=avail, shmem=shmem,
            # 보수적 하한 = 비어 있는 메모리 + 식은(비활성) 파일 캐시. 커널 MemAvailable 에는 더해져 있는
            # 활성 파일 캐시(비우면 곧 재폴트)와 slab(회수가 느리고 불확실)을 뺀다. Shmem 은 MemAvailable 에 원래 안 들어간다.
            reclaimable_floor=m1.get("MemFree", 0) + m1.get("Inactive(file)", 0),
            active_file=m1.get("Active(file)", 0),
            anon=m1.get("AnonPages", 0), sreclaimable=m1.get("SReclaimable", 0),
            sunreclaim=m1.get("SUnreclaim", 0),
        ),
        swap=dict(total=swap_total, used=swap_total - swap_free, devices=sw),
        psi={k: dict(some_avg10=p1[k].get("some", (None,))[0], full_avg10=p1[k].get("full", (None,))[0],
                     some_avg60=p1[k].get("some", (None, None, None))[2], full_avg60=p1[k].get("full", (None, None, None))[2],
                     some_pct=pct(k, "some"), full_pct=pct(k, "full")) for k in p1},
        psi_cgroups=pressure_culprits(b["cg0"], cg1, dt, measured),
        rates=dict(pswpin=rate("pswpin"), pswpout=rate("pswpout"), pgmajfault=rate("pgmajfault"),
                   refault_file=rate("workingset_refault_file"),
                   allocstall=None if not measured else sum(
                       (v1[k] - v0[k]) for k in v1 if k.startswith("allocstall_")) / dt),
        cpu=dict(count=os.cpu_count(), busy_pct=None if c1[0] == c0[0] else (1 - (c1[1] - c0[1]) / (c1[0] - c0[0])) * 100,
                 load=os.getloadavg()),
        tmpfs=tmpfs_use(),
    )
    return s


def snapshot(secs):
    b = begin()
    if secs > 0:
        time.sleep(secs)
    return end(b, secs > 0)



# ---------- 판정(이 호스트용으로 보정) ----------
# 근거: _plan/host-memory-verdict.md — 2026-10-26 실측(NVMe 스왑 한 번 접근 p50 약 48µs·순차 약 120 MiB/s, 스왑 폭주 cgroup 이 있어도 무관한 프로세스 지연은 거의 불변,
# Netdata 유효 4일 이력의 PSI 분포). 시스템 전체 PSI 는 한 cgroup 이 혼자 스왑을 두드려도 오르므로 「순간 튐」(avg10)과 「지속」(avg60)을 나누고,
# 되돌릴 수 없는 한계인 「OOM 까지 여유(MemAvailable + 스왑 여유)」를 용량 축으로 따로 본다. 사용자 체감으로 임계값을 교정할 때는 CALIB 만 고친다.
HOST = socket.gethostname()
# 호스트별 스왑 기준점(벤치마크 실측) — 새 호스트(특히 NVMe 가 아닌 워크스테이션)는 `swapbench.py --entry` 결과를 여기에 항목으로 추가한다.
# 항목이 있으면 thresholds 로 아래 CALIB 기본값을 덮어쓰고, info_lines 가 실측값을 인사이트에 쓴다. 없으면 「보정 안 됨」을 표시한다.
HOST_CALIBRATION = {
    "beelink-ser7-co": dict(
        measured="2026-10-26", source="_plan/host-memory-verdict.md §2-3·2-4",
        swap="ZRAM(zstd·우선순위 100) + NVMe 스왑파일(SAMSUNG MZVL21T0HCLR·우선순위 10)", rotational=False,
        random_fault_us=dict(p50=48, p99=345, p999=2553), seq_mib_s=122, fill_mib_s=315,
        bystander="스왑 약 100 MiB/s 폭주 중에도 무관한 프로세스 지연 거의 불변(sleep 1ms 초과 p99 58→69µs, 16MiB 할당 p99 5.9→5.5ms)",
        note="2회 측정: ZRAM 슬롯이 98.7% 찼을 때 p50 48µs·p99 345µs·순차 122 MiB/s, 슬롯 약 96%(일부 여유로 ZRAM 적중)일 때 p50 7.6µs·p99 273µs·순차 166 MiB/s — p99(디스크 경로)가 안정적, p50 은 ZRAM 상태에 따라 달라짐. 타 프로세스 p99 38.0→39.5µs·16MiB 할당 p99 6.2→3.0ms(2차)",
        thresholds={},
    ),
}
CALIBRATED_HOSTS = set(HOST_CALIBRATION)
CALIB = dict(
    full60_warn=1.0, full60_press=3.0, full60_crit=10.0,   # 메모리 PSI full avg60 % — 이력 분위: ≥1% 2.2%, ≥3% 0.1%
    some60_press=20.0,                                      # 메모리 PSI some avg60 %
    spike=5.0,                                              # full avg10(또는 5초 구간) % — 이력 1.0% 구간. 순간 튐
    io_full60_warn=5.0,
    headroom_warn=8 * GIB, headroom_press=3 * GIB, headroom_crit=1 * GIB,   # MemAvailable + 스왑 여유
)
CALIB.update(HOST_CALIBRATION.get(HOST, {}).get("thresholds", {}))
NAMES = ["여유", "주의", "압박", "심각"]


def mount_source(path):
    """path 가 속한 마운트의 장치(예: /dev/nvme0n1p2). /proc/self/mountinfo 의 가장 긴 마운트 지점 일치. 못 찾으면 None."""
    best, src = "", None
    for line in (read("/proc/self/mountinfo") or "").splitlines():
        a, _, b = line.partition(" - ")
        f, g = a.split(), b.split()
        if len(f) > 4 and len(g) > 1 and (path == f[4] or path.startswith(f[4].rstrip("/") + "/")) and len(f[4]) > len(best):
            best, src = f[4], g[1]
    return src


def swap_rotational(devices):
    """디스크 스왑 장치별 회전 여부 {경로: True|False|None(모름)}. 스왑파일은 마운트 장치로 거슬러 올라간다(btrfs 의 가상 st_dev 는 쓰지 않는다)."""
    out = {}
    for d in devices:
        if d["kind"] != "disk":
            continue
        dev = d["name"] if d["name"].startswith("/dev/") else mount_source(d["name"])
        rot = None
        if dev and dev.startswith("/dev/"):
            base = os.path.basename(os.path.realpath(dev))
            for cand in (f"/sys/block/{base}/queue/rotational", *glob.glob(f"/sys/block/*/{base}/../queue/rotational")):
                v = read(cand)
                if v is not None:
                    rot = v.strip() == "1"
                    break
        out[d["name"]] = rot
    return out


def headroom(s):
    """OOM 까지 여유 바이트 = 커널 MemAvailable + 스왑 여유(ZRAM 슬롯 여유 포함)."""
    return s["mem"]["available_raw"] + max(s["swap"]["total"] - s["swap"]["used"], 0)


def verdict_axes(s):
    """{'speed': (수준 0~3, 이유), 'capacity': (수준, 이유)} — 속도 축은 PSI, 용량 축은 OOM 까지 여유."""
    c = CALIB
    sp, sw = [], []
    lv = 0
    mp = s["psi"]["memory"]
    f60, s60 = mp.get("full_avg60"), mp.get("some_avg60")
    spike = max(x for x in (mp.get("full_pct"), mp.get("full_avg10"), 0) if x is not None)
    if f60 is not None and f60 >= c["full60_crit"]:
        lv = 3; sp.append(f"메모리 PSI full avg60 {f60:.1f}% (≥{c['full60_crit']:.0f}%: 지속적으로 거의 멈춤)")
    elif (f60 is not None and f60 >= c["full60_press"]) or (s60 is not None and s60 >= c["some60_press"]):
        lv = 2; sp.append(f"메모리 PSI 지속 대기 — full avg60 {f60 or 0:.1f}% · some avg60 {s60 or 0:.1f}%")
    elif f60 is not None and f60 >= c["full60_warn"]:
        lv = 1; sp.append(f"메모리 PSI full avg60 {f60:.1f}% (≥{c['full60_warn']:.0f}%: 지속 대기가 생기는 중)")
    if spike >= c["spike"] and lv < 1:
        lv = 1; sp.append(f"메모리 PSI full 순간 {spike:.1f}% (≥{c['spike']:.0f}%: 순간 튐 — avg60 이 낮으면 곧 지나감)")
    io = s["psi"]["io"].get("full_avg60")
    if io is not None and io >= c["io_full60_warn"] and lv < 1:
        lv = 1; sp.append(f"IO PSI full avg60 {io:.1f}%")
    cap, clv = [], 0
    h = headroom(s)
    if h < c["headroom_crit"]:
        clv = 3; cap.append(f"OOM 까지 여유 {h / GIB:.1f} GiB(<{c['headroom_crit'] / GIB:.0f} GiB: OOM 임박)")
    elif h < c["headroom_press"]:
        clv = 2; cap.append(f"OOM 까지 여유 {h / GIB:.1f} GiB(<{c['headroom_press'] / GIB:.0f} GiB)")
    elif h < c["headroom_warn"]:
        clv = 1; cap.append(f"OOM 까지 여유 {h / GIB:.1f} GiB(<{c['headroom_warn'] / GIB:.0f} GiB) — 새 큰 작업은 스왑에 의존")
    return dict(speed=(lv, sp), capacity=(clv, cap))


def info_lines(s):
    """판정에 영향을 주지 않는 참고 정보(이 호스트를 해석하는 데 필요한 것)."""
    out = []
    for d in s["swap"]["devices"]:
        if d["kind"] == "zram" and d["size"]:
            slots = d["used"] / d["size"] * 100
            ratio = f", 압축률 {d['orig'] / d['compressed']:.1f}" if d.get("compressed") and d.get("orig") else ""
            comp = f"RAM 점유 {d['compressed'] / GIB:.1f} GiB" if d.get("compressed") else "RAM 점유 ?"
            out.append(f"ZRAM 슬롯 {slots:.0f}% 사용({comp}{ratio}) — 슬롯(압축 전 기준)이 차도 위험 신호가 아니다: 새로 밀려나는 페이지는 우선순위가 낮은 디스크 스왑으로 가고, ZRAM 안의 페이지는 그대로 남는다")
        elif d["kind"] == "disk" and d["size"]:
            out.append(f"디스크 스왑 {d['used'] / GIB:.1f}/{d['size'] / GIB:.1f} GiB 사용 — 대체로 식은 페이지(추정). 접근 비용은 아래 「스왑 기준점」 줄")
    r = s["rates"]
    if r["pswpin"] is not None and r["pswpin"] >= 1000:
        out.append(f"스왑 되읽기 {r['pswpin']:.0f} pages/s — 정보일 뿐: 이 호스트에서는 PSI 가 낮으면 영향이 작다(4일 이력의 58% 구간이 4 MiB/s 이상)")
    out.append(f"보수적 가용 {s['mem']['reclaimable_floor'] / GIB:.1f} GiB(빈 메모리 + 식은 캐시) · 커널 MemAvailable {s['mem']['available_raw'] / GIB:.1f} GiB · 예약분(워터마크 약 0.3 GiB·HugePages·CMA·cgroup memory.min/low)은 2026-10-26 실측에서 사실상 없음")
    cal = HOST_CALIBRATION.get(HOST)
    if cal:
        f = cal["random_fault_us"]
        out.append(f"스왑 기준점(실측 {cal['measured']}, {cal['swap']}): 한 번 접근 p50 {f['p50']}µs·p99 {f['p99']}µs(RAM 상주 0.3µs), 순차 약 {cal['seq_mib_s']} MiB/s, {cal['bystander']} — 근거 {cal['source']}")
        if cal.get("note"):
            out.append(f"  기준점 메모: {cal['note']}")
    else:
        out.append(f"스왑 기준점 없음: {HOST} 는 스왑 벤치마크를 한 적이 없어 판정 임계값이 beelink-ser7-co 기본값 그대로다. "
                   "`python3 -I scripts/swapbench.py --entry`(cgroup 제한 안에서 스왑 경로를 재고 HOST_CALIBRATION 에 붙일 항목을 출력)로 측정해 기록할 것")
    rot = [n for n, v in swap_rotational(s["swap"]["devices"]).items() if v]
    if rot:
        out.append(f"경고: 회전 디스크 스왑({', '.join(rot)}) — 이 호스트의 NVMe 기준(한 번 접근 약 50µs)이 맞지 않는다. 스왑 되읽기가 곧 체감 지연이므로 스왑 사용·되읽기를 정보로 두지 말고 속도 축 근거로 볼 것")
    return out


def capacity_guide(s):
    """새 작업이 쓸 메모리 크기별 영향 [(상한 GiB, 설명)] — 「더 띄워도 되나」 질문용. 스왑 여유의 절반만 안전하게 쓸 수 있다고 본다."""
    m = s["mem"]
    swap_free = max(s["swap"]["total"] - s["swap"]["used"], 0)
    a, b = m["reclaimable_floor"], m["available_raw"]
    c = b + swap_free * 0.5
    return [(a / GIB, "바로 쓸 수 있음(재폴트 거의 없음)"), (b / GIB, "식은·활성 캐시를 밀어내며 쓰는 구간(약간 느려짐)"),
            (c / GIB, "스왑에 의존(식은 페이지는 디스크 스왑으로 — 작업집합이 크면 느려짐)"), (float("inf"), "그 이상은 OOM 위험")]


def verdict(s):
    """(수준 이름, 이유 목록) — 속도·용량 두 축 중 높은 쪽. 이유는 [속도]/[용량] 로 표시. 참고 정보는 info_lines()."""
    ax = verdict_axes(s)
    level = max(ax["speed"][0], ax["capacity"][0])
    why = [f"[속도] {x}" for x in ax["speed"][1]] + [f"[용량] {x}" for x in ax["capacity"][1]]
    return NAMES[level], why


def g(b):
    return f"{b / GIB:.1f}GiB"


# ---------- LLM 세션별 현재 사용량 ----------
HELPERS = []  # 세션이 아닌 claude 프로세스(Vivaldi 의 Claude-in-Chrome 네이티브 호스트 등)
SESSION_COMMS = {".claude-wrapped", "claude", "codex", "gemini", "opencode"}


def proc_table():
    ppid, comm, ticks = {}, {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = read(f"/proc/{d}/stat")
        if not st:
            continue
        try:
            i, j = st.index("("), st.rindex(")")
            f = st[j + 2:].split()
            pid = int(d)
            comm[pid] = st[i + 1:j]
            ppid[pid] = int(f[1])
            ticks[pid] = int(f[11]) + int(f[12])
        except (ValueError, IndexError):
            continue
    return ppid, comm, ticks


def subtree(root, ppid):
    kids = {}
    for p, pp in ppid.items():
        kids.setdefault(pp, []).append(p)
    out, stack = [], [root]
    while stack:
        x = stack.pop()
        out.append(x)
        stack += kids.get(x, [])
    return out


def pss_kib(pid):
    for line in (read(f"/proc/{pid}/smaps_rollup") or "").splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1])
    return 0


# ---------- LLM 세션 상태(작동중/대기, 마지막 대화, 서브에이전트) ----------
CLAUDE_DIR = os.path.expanduser("~/.claude")


def ago(ts):
    """epoch 초 → 'N분 전 (HH:MM)'"""
    if ts is None:
        return "-"
    d = max(time.time() - ts, 0)
    n = f"{d:.0f}초" if d < 90 else f"{d / 60:.0f}분" if d < 5400 else f"{d / 3600:.1f}시간" if d < 172800 else f"{d / 86400:.1f}일"
    return f"{n} 전({datetime.datetime.fromtimestamp(ts).strftime('%H:%M')})"


def iso_ts(x):
    try:
        return datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def last_chat(path):
    """transcript 끝부분에서 (마지막 사용자 입력 시각, 마지막 어시스턴트 응답 시각). 도구 결과·시스템 주입은 제외."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 3 * MIB, 0))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return None, None
    user = asst = None
    for line in reversed(lines):
        if user and asst:
            break
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t, m = d.get("type"), d.get("message") or {}
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        c = m.get("content")
        if t == "assistant" and not asst:
            if isinstance(c, list) and any(b.get("type") == "text" and b.get("text", "").strip() for b in c):
                asst = iso_ts(d.get("timestamp"))
        elif t == "user" and not user:
            txt = c if isinstance(c, str) else "".join(b.get("text", "") for b in c if b.get("type") == "text") if isinstance(c, list) else ""
            if txt.strip() and not txt.lstrip().startswith(("<system-reminder", "<command-", "<local-command", "[Request interrupted")):
                user = iso_ts(d.get("timestamp"))
    return user, asst


def subagents(sdir):
    """{'running': [(설명, 마지막 활동 epoch)], 'done': 개수, 'last_end': epoch}"""
    run, done, last_end = [], 0, None
    for meta in glob.glob(os.path.join(sdir, "agent-*.meta.json")):
        try:
            m = json.load(open(meta))
            mt = os.path.getmtime(meta[:-len(".meta.json")] + ".jsonl")
        except (OSError, ValueError):
            continue
        if m.get("finished"):
            done += 1
            last_end = max(last_end or 0, mt)
        else:
            run.append((str(m.get("description", ""))[:40], mt))
    return dict(running=run, done=done, last_end=last_end)


def ctx_last_chat(sids):
    """로컬 transcript 에서 못 찾은 세션의 마지막 대화 시각을 공유 ctx 저장소에서 보충(`donghans ctx sql`, 읽기 전용, 이 호스트의 기록만).
    {세션ID 앞 8자: (사용자 입력 epoch, 어시스턴트 응답 epoch)}. 접속 실패·명령 없음이면 빈 dict(조용히 생략하지 않고 호출부가 표시)."""
    if not sids:
        return {}
    arr = ",".join(f"'{x}%'" for x in sids)
    q = ("select substr(session_id,1,8), "
         "extract(epoch from max(ts) filter (where role='user' and text not like '[tool_%' and text not like '<system-reminder%')), "
         "extract(epoch from max(ts) filter (where role='assistant' and text not like '[tool_%' and length(text)>0)) "
         f"from messages where host = '{socket.gethostname()}' and session_id like any (array[{arr}]) group by 1")
    r = subprocess.run(["donghans", "ctx", "sql", q], capture_output=True, text=True, timeout=10)
    out = {}
    for line in r.stdout.splitlines()[1:]:
        c = line.split("\t")
        if len(c) == 3:
            f = lambda x: float(x) if x not in ("", "None", "NULL") else None
            out[c[0]] = (f(c[1]), f(c[2]))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:120])
    return out


def session_meta(use_ctx=True):
    """pid → ~/.claude/sessions/<pid>.json 의 상태 + 대화·서브에이전트 요약(살아 있는 세션만 의미 있음).
    use_ctx=False 면 transcript 에서 못 찾은 항목을 ctx 저장소(subprocess·최대 10초)로 보충하지 않는다(실시간 폴링용)."""
    out = {}
    for f in glob.glob(os.path.join(CLAUDE_DIR, "sessions", "*.json")):
        try:
            d = json.load(open(f))
            pid = int(d["pid"])
        except (OSError, ValueError, KeyError):
            continue
        sid = d.get("sessionId", "")
        tr = next(iter(glob.glob(os.path.join(CLAUDE_DIR, "projects", "*", f"{sid}.jsonl"))), None)
        u, a = last_chat(tr) if tr else (None, None)
        sa = subagents(os.path.join(os.path.dirname(tr), sid, "subagents")) if tr else dict(running=[], done=0, last_end=None)
        out[pid] = dict(name=d.get("name", "?"), sid=sid[:8], status=d.get("status", "?"),
                        since=float(d.get("statusUpdatedAt", 0)) / 1000 or None,
                        last_user=u, last_asst=a, sub=sa, src="transcript")
    need = [m["sid"] for m in out.values() if m["last_user"] is None or m["last_asst"] is None]
    if need and use_ctx:
        try:
            got = ctx_last_chat(need)
            for m in out.values():
                if m["sid"] in got:
                    cu, ca = got[m["sid"]]
                    if m["last_user"] is None and cu:
                        m["last_user"], m["src"] = cu, "transcript+ctx"
                    if m["last_asst"] is None and ca:
                        m["last_asst"], m["src"] = ca, "transcript+ctx"
        except Exception as e:  # ctx 서버 꺼짐 등 — 조용히 넘어가지 않고 표에 남긴다
            for m in out.values():
                if m["sid"] in need:
                    m["ctx_err"] = str(e) or type(e).__name__
    return out


def proc_age_s(pid, hz, boot):
    st = read(f"/proc/{pid}/stat") or ""
    try:
        return boot - int(st[st.rindex(")") + 2:].split()[19]) / hz
    except (ValueError, IndexError):
        return None


def fmt_dur(sec):
    return f"{sec:.0f}초" if sec < 90 else f"{sec / 60:.0f}분" if sec < 5400 else f"{sec / 3600:.1f}시간"


def sessions_begin():
    ppid, comm, t0 = proc_table()
    return ppid, comm, t0, time.monotonic()


def sessions_end(begin, measured, use_ctx=True):
    """LLM CLI 세션(프로세스 + 자식 트리)별 PSS·CPU(begin 이후 구간). PSS 는 공유 페이지를 나눠 계산해 합계가 겹치지 않는다."""
    ppid, comm, t0, t_start = begin
    roots, HELPERS[:] = [], []
    for p, c in comm.items():
        if c in SESSION_COMMS:
            (HELPERS if "--chrome-native-host" in (read(f"/proc/{p}/cmdline") or "") else roots).append(p)
    _, _, t1 = proc_table()
    dt = max(time.monotonic() - t_start, 1e-6)
    secs = 1 if measured else 0
    hz = os.sysconf("SC_CLK_TCK")
    boot = float((read("/proc/uptime") or "0").split()[0])
    meta = session_meta(use_ctx)
    rows = []
    for r in roots:
        tree = subtree(r, ppid)
        pss = sum(pss_kib(p) for p in tree) / 1024
        cpu = (sum(t1.get(p, 0) for p in tree if p in t0) - sum(t0.get(p, 0) for p in tree if p in t1)) / hz / dt * 100 if secs > 0 else None
        try:
            cwd = os.path.basename(os.readlink(f"/proc/{r}/cwd")) or "/"
        except OSError:
            cwd = "?"
        st = read(f"/proc/{r}/stat") or ""
        try:
            age = (boot - int(st[st.rindex(")") + 2:].split()[19]) / hz) / 3600
        except (ValueError, IndexError):
            age = None
        kids = {}
        for p in tree:
            if p == r:
                continue
            c = comm.get(p, "?")
            e = proc_age_s(p, hz, boot)
            k = kids.setdefault(c, [0, 0.0, 0.0])  # 개수, PSS(MiB), 최장 가동(초)
            k[0] += 1; k[1] += pss_kib(p) / 1024; k[2] = max(k[2], e or 0)
        rows.append((pss, r, cwd, len(tree), cpu, age, comm[r].lstrip(".").replace("-wrapped", ""), meta.get(r), kids))
    return sorted(rows, reverse=True)


def friendly(path):
    last = path.rsplit("/", 1)[-1].replace("\\x2d", "-")
    if last == "incus.service":
        return "incus VM 들"
    if last == "docker.service":
        return "Docker 컨테이너(rootless)"
    if last.startswith("tmux-spawn"):
        return "tmux 창 하나(안의 claude 세션·셸 포함)"
    for pre in ("app-Hyprland-", "app-", ):
        if last.startswith(pre):
            last = last[len(pre):]
    return last.rsplit(".", 1)[0].rsplit("-", 1)[0] if last.endswith(".scope") else last
