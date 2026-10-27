"""observe_bpf — eBPF(bpftrace) 프리셋: 프로그램 문자열과 출력 파서(순수 계산, 시험 가능). 실행은 수집기(root)의 `bpf` 작업이 한다.
개인정보 원칙: 프로세스 이름(comm)·pid·실행 파일 이름·횟수/바이트 합계만 본다. 명령 인자·파일 내용·패킷 내용·URL 은 보지 않는다.
프리셋(모두 N초 동안만 붙었다가 떼어진다 — 상시 계측 아님):
  exec     프로세스 생성/종료 → 프로세스 구간(스팬: 부모-자식, CPU 시간). 누가 프로세스를 자주 만드나.
  wake     깨우는 쪽 → 깨어나는 쪽 comm 쌍의 횟수(sched_waking). 전력의 원인 추적.
  profile  약 99.6Hz(10,038µs, 1초 주기와 위상이 고정되지 않는 비조화 주기) CPU 샘플링: 프로세스별 CPU 비율 + 가장 많이 걸린 커널/사용자 맨 위 함수(JFR 의 가벼운 버전).
  psr      화면 갱신 원인: drm atomic 커밋을 일으킨 comm 별 횟수 + i915 PSR flush/invalidate/exit/activate 횟수(PSR 이 왜 풀리나).
  io       블록 입출력 comm 별 횟수·바이트.
  net      TCP/UDP 송수신 호출 comm 별 횟수."""
from __future__ import annotations

import json
import os
import re

PRESETS = ("exec", "wake", "profile", "psr", "io", "net")


def program(preset, sec, comm=None):
    """bpftrace 프로그램 문자열. comm 은 프로세스 이름 필터(영숫자·점·밑줄·하이픈만 허용 — 프로그램 문자열에 넣으므로 검증)."""
    if preset not in PRESETS:
        raise ValueError(f"알 수 없는 프리셋: {preset}")
    if comm is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,15}", comm):
        raise ValueError("comm 필터는 영숫자·._- 최대 15자")
    flt = f'/comm == "{comm}"/' if comm else ""
    end = f"interval:s:{int(sec)} {{ exit(); }}"
    if preset == "exec":
        return ("tracepoint:sched:sched_process_exec %s { printf(\"E %%d %%d %%s %%llu %%s\\n\", pid, curtask->real_parent->tgid, comm, nsecs, str(args->filename)); } "
                "tracepoint:sched:sched_process_exit /pid == tid/ %s { printf(\"X %%d %%s %%llu %%llu\\n\", pid, comm, nsecs, curtask->utime + curtask->stime); } %s") % (flt, flt, end)
    if preset == "wake":
        return f"tracepoint:sched:sched_waking {flt} {{ @w[comm, args->comm] = count(); }} {end}"
    if preset == "profile":
        return (f"profile:us:10038 {flt} {{ @cpu[comm] = count(); @kleaf[comm, kstack(1)] = count(); @uleaf[comm, ustack(1)] = count(); }} {end}")
    if preset == "psr":
        return ("kprobe:drm_mode_atomic_ioctl %s { @atomic[comm] = count(); } kprobe:i915:intel_psr_flush { @psr_flush = count(); } "
                "kprobe:i915:intel_psr_invalidate { @psr_invalidate = count(); } kprobe:i915:intel_psr_exit { @psr_exit = count(); } kprobe:i915:intel_psr_activate { @psr_activate = count(); } %s") % (flt, end)
    if preset == "io":
        return f"tracepoint:block:block_rq_issue {flt} {{ @n[comm] = count(); @bytes[comm] = sum(args->bytes); }} {end}"
    return (f"kprobe:tcp_sendmsg {flt} {{ @tcp_send[comm] = count(); }} kprobe:tcp_recvmsg {flt} {{ @tcp_recv[comm] = count(); }} "
            f"kprobe:udp_sendmsg {flt} {{ @udp_send[comm] = count(); }} kprobe:udp_recvmsg {flt} {{ @udp_recv[comm] = count(); }} {end}")


def parse_output(text):
    """bpftrace -f json 출력 → (printf 줄 목록, 맵 dict {이름: {키: 값}}). 깨진 줄은 건너뛴다. 맵 키가 여러 개면 키는 쉼표로 이어진 문자열."""
    lines, maps = [], {}
    for raw in text.splitlines():
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        if o.get("type") == "printf":
            lines.append(o.get("data", "").rstrip("\n"))
        elif o.get("type") == "map":
            for k, v in (o.get("data") or {}).items():
                maps.setdefault(k.lstrip("@"), {}).update(v if isinstance(v, dict) else {"": v})
    return lines, maps


def top(d, n=15):
    return sorted(d.items(), key=lambda kv: -kv[1])[:n]


def _split_last(key):
    a, _, b = key.rpartition(",")
    return (a, b) if a else (b, "")


def summarize(preset, lines, maps, sec, n=15):
    """파싱 결과 → 보여 줄 행 목록 dict. 모든 횟수는 초당(per_s)도 함께."""
    sec = max(sec, 0.001)
    if preset == "wake":
        rows = []
        for k, v in top(maps.get("w", {}), n):
            waker, wakee = _split_last(k)
            rows.append({"waker": waker, "wakee": wakee, "count": v, "per_s": round(v / sec, 1)})
        by_waker, by_wakee = {}, {}
        for k, v in maps.get("w", {}).items():
            waker, wakee = _split_last(k)
            by_waker[waker] = by_waker.get(waker, 0) + v
            by_wakee[wakee] = by_wakee.get(wakee, 0) + v
        return {"pairs": rows, "by_waker": [{"comm": a, "count": b, "per_s": round(b / sec, 1)} for a, b in top(by_waker, n)],
                "by_wakee": [{"comm": a, "count": b, "per_s": round(b / sec, 1)} for a, b in top(by_wakee, n)], "total": sum(maps.get("w", {}).values())}
    if preset == "profile":
        cpu = maps.get("cpu", {})
        tot = sum(cpu.values()) or 1

        def leaf(name):
            out = []
            for k, v in top(maps.get(name, {}), n):
                comm, _, stack = k.partition(",")
                frame = next((ln.strip() for ln in stack.splitlines() if ln.strip()), "?")
                out.append({"comm": comm, "frame": frame, "count": v, "pct": round(v * 100 / tot, 1)})
            return out
        return {"samples": sum(cpu.values()), "hz": round(1e6 / 10038, 1), "cpu": [{"comm": a, "count": b, "pct": round(b * 100 / tot, 1)} for a, b in top(cpu, n)],
                "kernel_leaf": leaf("kleaf"), "user_leaf": leaf("uleaf")}
    if preset == "psr":
        return {"atomic_ioctl": [{"comm": a, "count": b, "per_s": round(b / sec, 1)} for a, b in top(maps.get("atomic", {}), n)],
                "psr_flush": _scalar(maps, "psr_flush"), "psr_invalidate": _scalar(maps, "psr_invalidate"), "psr_exit": _scalar(maps, "psr_exit"), "psr_activate": _scalar(maps, "psr_activate"), "sec": sec}
    if preset == "io":
        io = maps.get("n", {})
        by = maps.get("bytes", {})
        return {"rows": [{"comm": a, "count": b, "per_s": round(b / sec, 1), "bytes": by.get(a, 0)} for a, b in top(io, n)]}
    if preset == "net":
        rows = {}
        for name in ("tcp_send", "tcp_recv", "udp_send", "udp_recv"):
            for comm, v in maps.get(name, {}).items():
                rows.setdefault(comm, {"comm": comm, "tcp_send": 0, "tcp_recv": 0, "udp_send": 0, "udp_recv": 0})[name] = v
        out = sorted(rows.values(), key=lambda r: -(r["tcp_send"] + r["tcp_recv"] + r["udp_send"] + r["udp_recv"]))[:n]
        for r in out:
            r["per_s"] = round((r["tcp_send"] + r["tcp_recv"] + r["udp_send"] + r["udp_recv"]) / sec, 1)
        return {"rows": out}
    if preset == "exec":
        return exec_summary(lines, sec, n)
    raise ValueError(preset)


def _scalar(maps, name):
    d = maps.get(name)
    if d is None:
        return 0
    return d.get("", 0) if isinstance(d, dict) else d


def parse_exec(lines):
    """E/X 줄 → {pid: {pid, ppid, comm, exe, t0_ns, t1_ns, cpu_ns}}. 같은 pid 가 exec 를 여러 번 하면(셸 → 프로그램) 마지막 comm/exe 와 첫 시작 시각을 쓴다."""
    procs = {}
    for ln in lines:
        p = ln.split(" ", 5)
        try:
            if p[0] == "E" and len(p) >= 5:
                pid = int(p[1])
                exe = os.path.basename(p[5]) if len(p) > 5 else ""
                cur = procs.setdefault(pid, {"pid": pid, "ppid": int(p[2]), "t0_ns": int(p[4]), "t1_ns": None, "cpu_ns": None})
                cur.update(comm=p[3], exe=exe)
            elif p[0] == "X" and len(p) >= 5:
                pid = int(p[1])
                cur = procs.setdefault(pid, {"pid": pid, "ppid": None, "t0_ns": None, "t1_ns": None, "cpu_ns": None, "comm": p[2], "exe": ""})
                cur["t1_ns"], cur["cpu_ns"] = int(p[3]), int(p[4])
                cur.setdefault("comm", p[2])
        except (ValueError, IndexError):
            continue
    return procs


def exec_summary(lines, sec, n=15):
    procs = parse_exec(lines)
    started = [p for p in procs.values() if p["t0_ns"] is not None]
    by = {}
    for p in started:
        g = by.setdefault(p["comm"], {"comm": p["comm"], "count": 0, "cpu_ms": 0.0, "wall_ms": 0.0})
        g["count"] += 1
        if p["cpu_ns"] is not None:
            g["cpu_ms"] += p["cpu_ns"] / 1e6
        if p["t1_ns"] is not None and p["t0_ns"] is not None:
            g["wall_ms"] += (p["t1_ns"] - p["t0_ns"]) / 1e6
    rows = sorted(by.values(), key=lambda g: (-g["count"], -g["cpu_ms"]))[:n]
    for g in rows:
        g["per_s"] = round(g["count"] / sec, 2)
        g["cpu_ms"], g["wall_ms"] = round(g["cpu_ms"], 1), round(g["wall_ms"], 1)
    parents = {}
    for p in started:
        if p["ppid"] is not None:
            parents[p["ppid"]] = parents.get(p["ppid"], 0) + 1
    return {"processes": len(started), "forks_per_s": round(len(started) / sec, 2), "by_comm": rows,
            "top_parents": [{"pid": a, "children": b, "comm": (procs.get(a) or {}).get("comm")} for a, b in top(parents, 5)]}


def exec_spans(lines, mono_to_epoch, comp="bpf"):
    """E/X 줄 → observectl trace 가 읽는 스팬 이벤트 목록(begin/end). 부모 pid 도 관측됐으면 부모-자식으로, 아니면 루트로 잇는다.
    mono_to_epoch(ns) → epoch 초. 반환: 이벤트 dict 목록(시각순)."""
    procs = {p["pid"]: p for p in parse_exec(lines).values() if p["t0_ns"] is not None}
    sid = {pid: f"p{pid:x}-{p['t0_ns'] & 0xffff:04x}" for pid, p in procs.items()}

    def root(pid, seen=()):
        p = procs[pid]
        if p["ppid"] in procs and p["ppid"] not in seen:
            return root(p["ppid"], seen + (pid,))
        return pid
    out = []
    for pid, p in procs.items():
        trace = sid[root(pid)]
        parent = sid.get(p["ppid"]) if p["ppid"] in procs else None
        common = {"pid": pid, "comp": comp, "span": sid[pid], "trace": trace, "parent": parent}
        out.append({"t": round(mono_to_epoch(p["t0_ns"]), 3), "lvl": "info", "ev": p["comm"] + ".begin", **common, "exe": p.get("exe", ""), "ppid": p["ppid"]})
        if p["t1_ns"] is not None:
            out.append({"t": round(mono_to_epoch(p["t1_ns"]), 3), "lvl": "info", "ev": p["comm"] + ".end", **common, "ms": round((p["t1_ns"] - p["t0_ns"]) / 1e6, 1),
                        "cpu_ms": round((p["cpu_ns"] or 0) / 1e6, 1)})
    return sorted(out, key=lambda e: e["t"])
