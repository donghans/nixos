"""procscan — /proc 에서 프로세스 목록 스냅샷을 만든다(읽기 전용). procui 의 그룹·보호·종료가 모두 이 스냅샷을 기준으로 한다.

개인정보: 프로세스 이름(comm·exe 기본 이름)·숫자만 읽는다. 명령 인자는 읽지 않는다
(단 observe_apps.AppResolver 가 electron 앱 이름을 정하려고 루트 프로세스의 명령줄을 읽을 수 있다 — 저장·표시하지 않는다).
프로세스 한 건 = dict: pid, ppid, comm, exe, uid, start(부팅 후 틱 — PID 재사용 판별용), ticks(utime+stime), rss(바이트),
threads, state, cgroup(경로), kernel(커널 스레드 여부). `annotate` 가 app 을, `with_cpu` 가 cpu(코어 1개=100%)를 더한다.
"""
from __future__ import annotations

import os
import time

HZ = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
KIB = 1024
MIB = 1 << 20
GIB = 1 << 30


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def parse_stat(text):
    """/proc/<pid>/stat 한 줄 → (comm, 필드 리스트 f) — comm 에 공백·괄호가 있어도 마지막 ')' 기준. 실패하면 None."""
    try:
        i, j = text.index("("), text.rindex(")")
        return text[i + 1:j], text[j + 2:].split()
    except ValueError:
        return None


def scan():
    procs = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = read(f"/proc/{d}/stat")
        parsed = parse_stat(st) if st else None
        if not parsed:
            continue
        comm, f = parsed
        try:
            pid = int(d)
            ppid, threads, start = int(f[1]), int(f[17]), int(f[19])
            ticks, rss = int(f[11]) + int(f[12]), int(f[21]) * PAGE
            uid = os.stat(f"/proc/{d}").st_uid
        except (ValueError, IndexError, OSError):
            continue
        try:
            exe = os.path.basename(os.readlink(f"/proc/{d}/exe")).removesuffix(" (deleted)")
        except OSError:
            exe = ""
        cg = ""
        for line in (read(f"/proc/{d}/cgroup") or "").splitlines():
            if line.startswith("0::"):
                cg = line[3:]
        procs.append(dict(pid=pid, ppid=ppid, comm=comm, exe=exe, uid=uid, start=start, ticks=ticks, rss=rss, threads=threads,
                          state=f[0], cgroup=cg, kernel=(not exe and (ppid == 2 or pid == 2)), cpu=0.0, app=comm))
    return procs


def annotate(procs, resolver=None):
    """각 프로세스에 app(observe 앱 이름)을 단다. resolver 가 없으면 comm 을 그대로 쓴다(시험·observe 모듈이 없을 때)."""
    if resolver is None:
        return procs
    exe_of = {p["pid"]: p["exe"] for p in procs}
    ppid_of = {p["pid"]: p["ppid"] for p in procs}

    def cmdline(pid):
        return [a for a in (read(f"/proc/{pid}/cmdline") or "").split("\0") if a]
    for p in procs:
        p["app"] = resolver.resolve(p["pid"], p["comm"], p["exe"], p["ppid"], exe_of, ppid_of, cmdline)
    return procs


def with_cpu(procs, prev, dt):
    """prev = {(pid, start): ticks}(직전 스냅샷), dt 초. 첫 스냅샷이면 cpu 는 0. 새로 계산한 {(pid,start): ticks} 를 돌려준다."""
    cur = {}
    for p in procs:
        k = (p["pid"], p["start"])
        cur[k] = p["ticks"]
        if prev and dt > 0 and k in prev:
            p["cpu"] = max(p["ticks"] - prev[k], 0) / HZ / dt * 100
    return cur


def by_pid(procs):
    return {p["pid"]: p for p in procs}


def ancestors(pid, bp):
    """pid 자신과 모든 조상(PID 1 까지)의 pid 집합. 순환·끊김에도 멈춘다."""
    out, x = set(), pid
    while x and x not in out:
        out.add(x)
        p = bp.get(x)
        if not p:
            break
        x = p["ppid"]
    return out


def descendants(pid, procs):
    kids = {}
    for p in procs:
        kids.setdefault(p["ppid"], []).append(p["pid"])
    out, stack = set(), list(kids.get(pid, []))
    while stack:
        x = stack.pop()
        if x not in out:
            out.add(x)
            stack += kids.get(x, [])
    return out


def unit_of(cgroup):
    """cgroup 경로 → 사람이 읽는 유닛 이름(마지막 구성요소, `\\x2d` 복원). 루트면 '/'."""
    last = (cgroup or "").rstrip("/").rsplit("/", 1)[-1].replace("\\x2d", "-")
    return last or "/"


def age_s(p, boot_uptime):
    return max(boot_uptime - p["start"] / HZ, 0)


def uptime():
    return float((read("/proc/uptime") or "0").split()[0])


def fmt_dur(sec):
    return f"{sec:.0f}초" if sec < 90 else f"{sec / 60:.0f}분" if sec < 5400 else f"{sec / 3600:.1f}시간" if sec < 172800 else f"{sec / 86400:.1f}일"


def pss_kib(pid):
    for line in (read(f"/proc/{pid}/smaps_rollup") or "").splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1])
    return None


def detail(p, procs, view_labels=None):
    """프로세스 한 건의 세부 사용량(문자열 리스트). 권한이 없어 못 읽은 항목은 「못 쟀음」. view_labels = {뷰 이름: 그룹}."""
    pid = p["pid"]
    bp = by_pid(procs)
    L = [f"{p['comm']}  (pid {pid}, 앱 {p['app']})", ""]
    pss = pss_kib(pid)
    L.append(f"CPU(최근 구간)  {p['cpu']:.1f}% (코어 1개=100%)")
    L.append(f"메모리  RSS {p['rss'] / MIB:.0f} MiB · PSS " + ("못 쟀음(권한)" if pss is None else f"{pss / KIB:.0f} MiB"))
    L.append(f"스레드 {p['threads']} · 상태 {p['state']} · 시작 후 {fmt_dur(age_s(p, uptime()))}")
    try:
        fds = len(os.listdir(f"/proc/{pid}/fd"))
    except OSError:
        fds = None
    L.append("열린 FD  " + ("못 쟀음(권한)" if fds is None else str(fds)))
    io = read(f"/proc/{pid}/io")
    if io:
        d = dict(line.split(": ") for line in io.strip().splitlines() if ": " in line)
        L.append(f"I/O 누적  읽기 {int(d.get('read_bytes', 0)) / MIB:.1f} MiB · 쓰기 {int(d.get('write_bytes', 0)) / MIB:.1f} MiB")
    else:
        L.append("I/O 누적  못 쟀음(권한)")
    L.append(f"cgroup  {p['cgroup'] or '?'}")
    chain, x = [], p["ppid"]
    while x and x in bp and len(chain) < 8:
        chain.append(f"{bp[x]['comm']}({x})")
        x = bp[x]["ppid"]
    L.append("부모 사슬  " + (" → ".join(chain) or "-"))
    kids = [c for c in procs if c["ppid"] == pid]
    L.append(f"자식 {len(kids)}개  " + ", ".join(f"{c['comm']}({c['pid']})" for c in kids[:6]) + (" …" if len(kids) > 6 else ""))
    if view_labels:
        L.append("그룹  " + " · ".join(f"{k}: {v}" for k, v in view_labels.items()))
    return L
