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



def begin():
    """증분 측정의 0 시점 표본."""
    return dict(m0=meminfo(), v0=vmstat(), p0={k: psi(k) for k in ("memory", "cpu", "io")}, c0=cpu_times(), t0=time.monotonic())


def end(b, measured=True):
    """1 시점 표본을 재고 b(begin 결과) 이후 변화율을 낸다. measured=False 면 구간 값(PSI·변화율·CPU 사용률)은 None."""
    m0, v0, p0, c0, t0 = b["m0"], b["v0"], b["p0"], b["c0"], b["t0"]
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
                     some_pct=pct(k, "some"), full_pct=pct(k, "full")) for k in p1},
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
        if (full or 0) >= 0.5 or (some or 0) >= 3:  # 대기 시간(PSI)이 실제로 늘 때만 압박으로 본다
            level = max(level, 2); why.append(f"스왑 되읽기 {r['pswpin']:.0f} pages/s + PSI 상승 (스래싱)")
        else:
            level = max(level, 1); why.append(f"스왑 되읽기 {r['pswpin']:.0f} pages/s 이나 PSI 는 낮음(대기 영향 아직 작음)")
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
