#!/usr/bin/env python3
"""호스트 가용 자원 스냅샷 — 노이즈(buff/cache·RSS 합계·누적 카운터)를 빼고 판정에 쓸 값만 낸다.

사용: hostres.py [--secs N] [--top N] [--hist 3h] [--json]
  --secs  PSI·vmstat·CPU 변화율을 재는 구간(기본 5초, 0 이면 구간 없이 순간값만)
  --hist  최근 이력 그래프 구간(기본 3h, 0 이면 생략). 호스트 PSI·가용메모리·스왑은 Netdata(127.0.0.1:19999),
          LLM CLI 앱(claude 등)의 RSS·CPU 는 observe 표본(/var/lib/observe/data)에서 읽는다 — 없으면 그 줄만 생략.
표준 라이브러리만 쓴다. 읽기 전용(캐시 비우기·프로세스 종료 같은 변경 없음).
"""
import argparse, datetime, glob, json, os, socket, subprocess, time, urllib.request

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
    """{'some': (avg10, total_us), 'full': (...)}"""
    out = {}
    for line in (read(f"/proc/pressure/{kind}") or "").splitlines():
        p = line.split()
        kv = dict(x.split("=") for x in p[1:])
        out[p[0]] = (float(kv["avg10"]), int(kv["total"]))
    return out


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


def snapshot(secs):
    m0, v0 = meminfo(), vmstat()
    p0 = {k: psi(k) for k in ("memory", "cpu", "io")}
    c0 = cpu_times()
    t0 = time.monotonic()
    if secs > 0:
        time.sleep(secs)
    m1, v1 = meminfo(), vmstat()
    p1 = {k: psi(k) for k in ("memory", "cpu", "io")}
    c1 = cpu_times()
    dt = max(time.monotonic() - t0, 1e-6)

    def pct(kind, level):
        a, b = p0[kind].get(level), p1[kind].get(level)
        if not a or not b or secs <= 0:
            return None
        return (b[1] - a[1]) / (dt * 1e6) * 100

    rate = lambda k: (v1.get(k, 0) - v0.get(k, 0)) / dt if secs > 0 else None
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
                     some_pct=pct(k, "some"), full_pct=pct(k, "full")) for k in p1},
        rates=dict(pswpin=rate("pswpin"), pswpout=rate("pswpout"), pgmajfault=rate("pgmajfault"),
                   refault_file=rate("workingset_refault_file"),
                   allocstall=None if secs <= 0 else sum(
                       (v1[k] - v0[k]) for k in v1 if k.startswith("allocstall_")) / dt),
        cpu=dict(count=os.cpu_count(), busy_pct=None if c1[0] == c0[0] else (1 - (c1[1] - c0[1]) / (c1[0] - c0[0])) * 100,
                 load=os.getloadavg()),
        tmpfs=tmpfs_use(),
    )
    return s


def verdict(s):
    """(수준, 이유 목록). 기준은 경험칙 — 이 호스트의 실측으로 보정되지 않았다."""
    why, level = [], 0
    mp = s["psi"]["memory"]
    full = mp["full_pct"] if mp["full_pct"] is not None else mp["full_avg10"]
    some = mp["some_pct"] if mp["some_pct"] is not None else mp["some_avg10"]
    if full is not None:
        if full >= 5: level = max(level, 3); why.append(f"메모리 PSI full {full:.1f}% (≥5%: 심각)")
        elif full >= 1: level = max(level, 2); why.append(f"메모리 PSI full {full:.1f}% (≥1%: 압박)")
    if some is not None and some >= 10:
        level = max(level, 1); why.append(f"메모리 PSI some {some:.1f}% (경합)")
    r = s["rates"]
    if r["pswpin"] is not None and r["pswpin"] >= 1000:  # 4KiB 페이지 → 약 4MiB/s 이상 되읽음
        level = max(level, 2); why.append(f"스왑 되읽기 {r['pswpin']:.0f} pages/s (스래싱 징후)")
    floor = s["mem"]["reclaimable_floor"]
    if floor < 2 * GIB:
        level = max(level, 1); why.append(f"보수적 가용 {floor / GIB:.1f}GiB (<2GiB)")
    sw = s["swap"]
    if sw["total"] and (sw["total"] - sw["used"]) / sw["total"] < 0.10:
        level = max(level, 1); why.append("스왑 여유 10% 미만 — 갑자기 부족해질 수 있음")
    for d in sw["devices"]:
        if d["kind"] == "zram" and d["size"] and d["used"] / d["size"] > 0.95:
            why.append("ZRAM 거의 가득 — 추가 스왑아웃은 디스크 스왑으로 감")
    if s["psi"]["io"]["full_avg10"] and s["psi"]["io"]["full_avg10"] >= 5:
        level = max(level, 1); why.append(f"IO PSI full {s['psi']['io']['full_avg10']:.1f}%")
    names = ["여유", "주의", "압박", "심각"]
    return names[level], why


def g(b):
    return f"{b / GIB:.1f}GiB"


def render(s, top):
    lv, why = verdict(s)
    m, sw, ps, r, c = s["mem"], s["swap"], s["psi"], s["rates"], s["cpu"]
    L = [f"## 호스트 자원 — 판정: {lv}  (구간 {s['window_s']}s)"]
    L += [f"- {w}" for w in why] or ["- 압박 징후 없음"]
    L.append(f"- **새로 쓸 수 있는 메모리(보수적)**: {g(m['reclaimable_floor'])} = 빈 메모리 + 식은 파일 캐시"
             f" (총 {g(m['total'])})")
    L.append(f"- 커널 MemAvailable {g(m['available_raw'])} — 위 값에 활성 파일 캐시 {g(m['active_file'])}"
             f"·회수 가능 slab {g(m['sreclaimable'])} 가 더해진 낙관값(회수하면 재폴트·지연 발생)")
    L.append(f"- 캐시가 아닌데 buff/cache 로 보이는 것: shmem {g(m['shmem'])}(tmpfs·VM 공유메모리) | anon {g(m['anon'])}"
             f" | 커널 slab 회수불가 {g(m['sunreclaim'])}")
    dev = ", ".join(
        f"{d['kind']} {g(d['used'])}/{g(d['size'])}" + (f"(압축 후 RAM {g(d['compressed'])})" if "compressed" in d else "")
        for d in sw["devices"]) or "없음"
    L.append(f"- 스왑 사용 {g(sw['used'])}/{g(sw['total'])} — {dev}")

    def f(x, u=""):
        return "-" if x is None else f"{x:.1f}{u}"
    L.append(f"- 메모리 PSI: some {f(ps['memory']['some_pct'], '%')} / full {f(ps['memory']['full_pct'], '%')} (구간) · avg10 some {f(ps['memory']['some_avg10'], '%')} full {f(ps['memory']['full_avg10'], '%')}")
    L.append(f"- 변화율/s: pswpin {f(r['pswpin'])} · pswpout {f(r['pswpout'])} · majfault {f(r['pgmajfault'])} · refault {f(r['refault_file'])} · allocstall {f(r['allocstall'])}")
    L.append(f"- CPU {c['count']}코어: 사용 {f(c['busy_pct'], '%')} · load {c['load'][0]:.1f}/{c['load'][1]:.1f}/{c['load'][2]:.1f}"
             f" · PSI cpu some {f(ps['cpu']['some_pct'] if ps['cpu']['some_pct'] is not None else ps['cpu']['some_avg10'], '%')}"
             f" · IO some {f(ps['io']['some_pct'] if ps['io']['some_pct'] is not None else ps['io']['some_avg10'], '%')}")
    if s["tmpfs"]:
        L.append("- tmpfs 점유(≥100MiB, RAM/스왑을 차지): " + ", ".join(f"{p} {g(u)}/{g(t)}" for p, u, t in s["tmpfs"]))
    cons = cgroup_consumers(top)
    if cons:
        L.append(f"- 소비자 상위 {len(cons)} (cgroup 의 anon+shmem, 자기 몫):")
        L += [f"  - {g(b)}  {p}" for p, b in cons]
    return "\n".join(L)


# ---------- 이력(최근 구간) ----------
BARS = "▁▂▃▄▅▆▇█"
LLM_APPS = ("claude", "codex", "gemini", "opencode")  # observe 의 앱 이름(= 정리한 프로세스 이름)


def parse_dur(t):
    t = str(t).strip()
    if t in ("0", ""):
        return 0
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(float(t[:-1]) * mult[t[-1]]) if t[-1] in mult else int(float(t))


def spark(vals, hi=None, lo=0.0):
    """스파크라인(기본 0 기준, lo 를 주면 lo~hi 구간). 값이 없는 칸은 공백."""
    nums = [v for v in vals if v is not None]
    if not nums:
        return ""
    top = hi if hi is not None else max(nums)
    span = (top - lo) if top > lo else 1
    return "".join(" " if v is None else BARS[max(0, min(int((v - lo) / span * 7.999), 7))] for v in vals)


def netdata(chart, secs, points, group, col=1):
    """오래된→최신 순 값 리스트(칸당 group 집계). 실패하면 None."""
    url = (f"http://127.0.0.1:19999/api/v1/data?chart={chart}&after=-{secs}&points={points}"
           f"&group={group}&format=json&options=nonzero%7Cnull2zero")
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            rows = json.load(r)["data"]
    except Exception:
        return None
    return [row[col] for row in reversed(rows)]


def observe_apps(secs, points):
    """observe 표본에서 LLM CLI 앱별 {app: ([rss_mb max/칸], [cpu_core_pct mean/칸], [프로세스 수 max/칸])}."""
    now = time.time()
    t_from = now - secs
    files = sorted(glob.glob("/var/lib/observe/data/samples-*.jsonl"))[-2:]
    width = secs / points
    acc = {}
    for fp in files:
        try:
            if os.path.getmtime(fp) < t_from:
                continue
            fh = open(fp)
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"apps"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("t", 0)
                if t < t_from:
                    continue
                b = min(int((t - t_from) / width), points - 1)
                for a in d.get("apps") or []:
                    if a["app"] in LLM_APPS:
                        r = acc.setdefault(a["app"], [dict(), dict(), dict()])
                        r[0][b] = max(r[0].get(b, 0), a["rss_mb"])
                        r[1].setdefault(b, []).append(a["cpu_core_pct"])
                        r[2][b] = max(r[2].get(b, 0), a["n"])
    out = {}
    for app, (rss, cpu, n) in acc.items():
        out[app] = ([rss.get(i) for i in range(points)],
                    [sum(cpu[i]) / len(cpu[i]) if i in cpu else None for i in range(points)],
                    [n.get(i) for i in range(points)])
    return out


def history(hist_s, points=36):
    L = []
    step = hist_s / points
    L.append(f"## 최근 {hist_s // 60}분 이력 (칸당 {step / 60:.0f}분 · 왼쪽=과거 → 오른쪽=지금 · PSI·CPU·RSS 는 0 기준, 가용·스왑은 구간 최소~최대 기준)")
    series = [
        ("메모리 PSI full(칸 최대 %)", "system.memory_full_pressure", "max", 1.0, "%"),
        ("메모리 PSI some(칸 최대 %)", "system.memory_some_pressure", "max", 10.0, "%"),
        ("CPU PSI some(칸 최대 %)", "system.cpu_some_pressure", "max", 10.0, "%"),
        ("IO PSI full(칸 최대 %)", "system.io_full_pressure", "max", 1.0, "%"),
    ]
    got = False
    for name, chart, grp, floor, unit in series:
        v = netdata(chart, hist_s, points, grp)
        if v is None:
            continue
        got = True
        L.append(f"- {name:<22} {spark(v, hi=max(max(v), floor))}  최대 {max(v):.1f}{unit} · 지금 {v[-1]:.1f}{unit}")
    avail = netdata("mem.available", hist_s, points, "min")
    if avail is not None:
        got = True
        L.append(f"- {'가용 메모리(칸 최소)':<20} {spark(avail, lo=min(avail))}  최소 {min(avail) / 1024:.1f}GiB · 지금 {avail[-1] / 1024:.1f}GiB"
                 "  (커널 MemAvailable 낙관값)")
    swap = netdata("mem.swap", hist_s, points, "max", col=2)  # 열 순서: free, used
    if swap is not None:
        got = True
        L.append(f"- {'스왑 사용(칸 최대)':<20} {spark(swap, lo=min(swap))}  최대 {max(swap) / 1024:.1f}GiB · 지금 {swap[-1] / 1024:.1f}GiB")
    if not got:
        L.append("- Netdata 이력을 못 읽음(127.0.0.1:19999) — 호스트 PSI·가용 이력 생략")
    llm = observe_apps(hist_s, points)
    if llm:
        L.append("- LLM CLI 앱 전체 합계(observe 표본 30초 간격; 세션별 이력은 기록되지 않음):")
        for app, (rss, cpu, n) in sorted(llm.items()):
            r = [x for x in rss if x is not None]
            c = [x for x in cpu if x is not None]
            L.append(f"  - {app} RSS   {spark(rss)}  최대 {max(r) / 1024:.1f}GiB · 지금 {r[-1] / 1024:.1f}GiB · 프로세스 최대 {max(x for x in n if x)}개")
            L.append(f"  - {app} CPU   {spark(cpu)}  최대 {max(c):.0f}% · 평균 {sum(c) / len(c):.0f}% (코어 1개=100%)")
    else:
        L.append("- observe 표본에서 LLM CLI 앱 기록을 못 찾음(수집이 꺼졌거나 구간 밖)")
    return "\n".join(L)


# ---------- LLM 세션별 현재 사용량 ----------
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


def session_meta():
    """pid → ~/.claude/sessions/<pid>.json 의 상태 + 대화·서브에이전트 요약(살아 있는 세션만 의미 있음)."""
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
    if need:
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


def sessions_begin():
    ppid, comm, t0 = proc_table()
    return ppid, comm, t0, time.monotonic()


def sessions_end(begin, measured):
    """LLM CLI 세션(프로세스 + 자식 트리)별 PSS·CPU(begin 이후 구간). PSS 는 공유 페이지를 나눠 계산해 합계가 겹치지 않는다."""
    ppid, comm, t0, t_start = begin
    roots = [p for p, c in comm.items() if c in SESSION_COMMS]
    _, _, t1 = proc_table()
    dt = max(time.monotonic() - t_start, 1e-6)
    secs = 1 if measured else 0
    hz = os.sysconf("SC_CLK_TCK")
    boot = float((read("/proc/uptime") or "0").split()[0])
    meta = session_meta()
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
        rows.append((pss, r, cwd, len(tree), cpu, age, comm[r].lstrip(".").replace("-wrapped", ""), meta.get(r)))
    return sorted(rows, reverse=True)


def render_sessions(rows):
    if not rows:
        return "## LLM 세션\n- 실행 중인 LLM CLI 세션 없음"
    tot = sum(r[0] for r in rows)
    busy = sum(1 for r in rows if r[7] and r[7]["status"] == "busy")
    L = [f"## LLM 세션 — {len(rows)}개(작동중 {busy} · 대기 {len(rows) - busy}), PSS 합 {tot / 1024:.1f}GiB (자식 프로세스 포함, 구간 CPU)"]
    for pss, pid, cwd, n, cpu, age, kind, m in rows:
        head = f"- {m['name'] if m else kind} [{m['sid'] if m else '?'}] pid {pid} · {cwd}"
        res = f"PSS {pss:.0f}MiB · 프로세스 {n}개 · CPU {'-' if cpu is None else f'{cpu:.0f}%'} · 가동 {'-' if age is None else f'{age:.0f}h'}"
        if not m:
            L.append(f"{head} · 상태 기록 없음 · {res}")
            continue
        st = {"busy": "작동중", "idle": "대기"}.get(m["status"], m["status"])
        sa = m["sub"]
        if sa["running"]:
            subs = f"실행 {len(sa['running'])}개({', '.join(d for d, _ in sa['running'][:3])}; 마지막 활동 {ago(max(t for _, t in sa['running']))})"
        else:
            subs = "실행 중 없음"
        subs += f" · 완료 {sa['done']}개" + (f"(마지막 종료 {ago(sa['last_end'])})" if sa["last_end"] else "")
        L.append(f"{head} · **{st}** {ago(m['since'])}부터")
        note = " [ctx 보충]" if m.get("src") == "transcript+ctx" else (f" [못 쟀음: ctx 접속 실패 — {m['ctx_err']}]" if m.get("ctx_err") else "")
        L.append(f"    마지막 사용자 입력 {ago(m['last_user'])} · 마지막 응답 {ago(m['last_asst'])}{note} · 서브에이전트 {subs}")
        L.append(f"    {res}")
    return "\n".join(L)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secs", type=float, default=5)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--hist", default="3h")
    ap.add_argument("--no-sessions", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sb = None if a.no_sessions else sessions_begin()
    s = snapshot(a.secs)
    sess = [] if a.no_sessions else sessions_end(sb, a.secs > 0)
    if a.json:
        s["verdict"], s["reasons"] = verdict(s)
        s["consumers"] = cgroup_consumers(a.top)
        s["sessions"] = [dict(pss_mib=r[0], pid=r[1], cwd=r[2], procs=r[3], age_h=r[5], kind=r[6], meta=r[7]) for r in sess]
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        out = [render(s, a.top)]
        h = parse_dur(a.hist)
        if h:
            out.append(history(h))
        if not a.no_sessions:
            out.append(render_sessions(sess))
        print("\n\n".join(out))


if __name__ == "__main__":
    main()
