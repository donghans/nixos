#!/usr/bin/env python3
"""호스트 가용 자원 스냅샷 — 노이즈(buff/cache·RSS 합계·누적 카운터)를 빼고 판정에 쓸 값만 낸다.

사용: hostres.py [--secs N] [--top N] [--hist 3h] [--json]
  --secs  PSI·vmstat·CPU 변화율을 재는 구간(기본 5초, 0 이면 구간 없이 순간값만)
  --hist  최근 이력 그래프 구간(기본 3h, 0 이면 생략). 호스트 PSI·가용메모리·스왑은 Netdata(127.0.0.1:19999)에서 읽는다.
          (observe 표본 안 쓴다 — 세션별 값은 아래 LLM 세션 표에서 본다)
표준 라이브러리만 쓴다. 읽기 전용(캐시 비우기·프로세스 종료 같은 변경 없음).
"""
import argparse, datetime, json, os, socket, subprocess, sys, time, urllib.request

# python3 -I(격리 모드)는 스크립트 폴더를 import 경로에 넣지 않으므로 명시한다
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostmetrics import *  # noqa: E402,F401,F403 — 측정·판정·세션 수집(출력 없음)
from hostmetrics import HELPERS  # noqa: E402 — sessions_end 가 제자리 갱신하는 리스트


def render(s, top):
    lv, why = verdict(s)
    ax = verdict_axes(s)
    m, sw, ps, r, c = s["mem"], s["swap"], s["psi"], s["rates"], s["cpu"]
    L = [f"## 호스트 자원 — 판정: {lv} (속도 {NAMES[ax['speed'][0]]} · 용량 {NAMES[ax['capacity'][0]]}, 구간 {s['window_s']}s)"]
    L += [f"- {w}" for w in why] or ["- 압박 징후 없음"]
    L.append(f"- **OOM 까지 여유 {g(headroom(s))}** = 커널 MemAvailable {g(m['available_raw'])} + 스왑 여유 {g(max(sw['total'] - sw['used'], 0))}"
             f" (주의 <{CALIB['headroom_warn'] // GIB}GiB · 압박 <{CALIB['headroom_press'] // GIB}GiB · 심각 <{CALIB['headroom_crit'] // GIB}GiB)")
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
    mp = ps["memory"]
    L.append(f"- 메모리 PSI: some {f(mp['some_pct'], '%')} / full {f(mp['full_pct'], '%')} (구간) · avg10 some {f(mp['some_avg10'], '%')} full {f(mp['full_avg10'], '%')}"
             f" · **avg60 some {f(mp['some_avg60'], '%')} full {f(mp['full_avg60'], '%')}**(지속 판정 기준)")
    if s.get("psi_cgroups"):
        L.append("- 메모리 대기를 만든 cgroup(가장 깊은 쪽, 구간 또는 avg10 stall %): " + " · ".join(
            f"{friendly(x['path'])} some {x['some_pct']:.1f}%/full {x['full_pct']:.1f}%" for x in s["psi_cgroups"]))
    L.append(f"- 변화율/s: pswpin {f(r['pswpin'])} · pswpout {f(r['pswpout'])} · majfault {f(r['pgmajfault'])} · refault {f(r['refault_file'])} · allocstall {f(r['allocstall'])}")
    L.append(f"- CPU {c['count']}코어: 사용 {f(c['busy_pct'], '%')} · load {c['load'][0]:.1f}/{c['load'][1]:.1f}/{c['load'][2]:.1f}"
             f" · PSI cpu some {f(ps['cpu']['some_pct'] if ps['cpu']['some_pct'] is not None else ps['cpu']['some_avg10'], '%')}"
             f" · IO some {f(ps['io']['some_pct'] if ps['io']['some_pct'] is not None else ps['io']['some_avg10'], '%')}")
    if s["tmpfs"]:
        L.append("- tmpfs 점유(≥100MiB, RAM/스왑을 차지 — 스왑에 나간 몫 포함이라 shmem 보다 클 수 있음): " + ", ".join(f"{p} {g(u)}/{g(t)}" for p, u, t in s["tmpfs"]))
    cons = cgroup_consumers(top)
    if cons:
        L.append(f"- 소비자 상위 {len(cons)} (cgroup 의 anon+shmem, 자기 몫):")
        L += [f"  - {g(b)}  {friendly(p)}  ({'/'.join(p.split('/')[-2:])[:70]})" for p, b in cons]
    L.append("- 참고(판정에 영향 없음):")
    L += [f"  - {x}" for x in info_lines(s)]
    L.append("- 새 작업이 쓸 메모리별 영향(스왑 여유의 절반만 쓴다고 본 값):")
    prev = 0.0
    for up, text in capacity_guide(s):
        L.append(f"  - {'~' + format(up, '.1f') + ' GiB' if up != float('inf') else '그 이상':<10} {text}")
    return "\n".join(L)


# ---------- 이력(최근 구간) ----------
BARS = "▁▂▃▄▅▆▇█"


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
    return "\n".join(L)


def render_sessions(rows):
    if not rows:
        return "## LLM 세션\n- 실행 중인 LLM CLI 세션 없음"
    tot = sum(r[0] for r in rows)
    busy = sum(1 for r in rows if r[7] and r[7]["status"] == "busy")
    L = [f"## LLM 세션 — {len(rows)}개(작동중 {busy} · 대기 {len(rows) - busy}), PSS 합 {tot / 1024:.1f}GiB (자식 프로세스 포함, 구간 CPU)"]
    for pss, pid, cwd, n, cpu, age, kind, m, kids in rows:
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
        # 명령줄은 개인정보 원칙상 읽지 않고 프로세스 이름만 쓴다. 도커·incus 가 띄운 것은 데몬 소속이라 여기 안 잡힌다.
        run = sorted(kids.items(), key=lambda kv: -kv[1][1])
        ks = ", ".join(f"{c}×{v[0]}({v[1]:.0f}MiB, 최장 {fmt_dur(v[2])})" for c, v in run[:6]) + (" …" if len(run) > 6 else "")
        L.append(f"    세션이 띄운 자식 프로세스: {ks or '없음'}")
        L.append(f"    {res}")
    if HELPERS:
        L.append(f"- (세션 아님) Claude-in-Chrome 네이티브 호스트 {len(HELPERS)}개 · PSS {sum(pss_kib(p) for p in HELPERS) / 1024:.0f}MiB — 브라우저가 띄운 보조 프로세스")
    return "\n".join(L)

# ---------- 호스트 맥락·요약·읽는 법 ----------
def sh(cmd, t=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def host_context(s):
    host = socket.gethostname()
    cpu = next((l.split(":", 1)[1].strip() for l in (read("/proc/cpuinfo") or "").splitlines() if l.startswith("model name")), "?")
    osr = dict(l.split("=", 1) for l in (read("/etc/os-release") or "").splitlines() if "=" in l)
    up = float((read("/proc/uptime") or "0").split()[0]) / 3600
    sw = ", ".join(f"{d['kind']} {g(d['size'])}" for d in s["swap"]["devices"]) or "없음"
    L = [f"- 호스트 **{host}**: {cpu} · {s['cpu']['count']}스레드 · RAM {g(s['mem']['total'])} · 스왑 {sw}(zram 이 우선순위 높음)",
         f"- OS {osr.get('PRETTY_NAME', '?').strip(chr(34))} · 커널 {os.uname().release} · 가동 {up / 24:.1f}일"
         f" · 하드웨어·설정 정본은 `~/nixos/hosts/{host}.nix|.toml` (추측 말고 거기서 읽을 것)"]
    vms = sh(["incus", "list", "-f", "csv", "-c", "nsm"])
    if vms is not None:
        run = [x.split(",") for x in vms.strip().splitlines() if ",RUNNING," in x]
        L.append("- 실행 중 incus VM: " + (", ".join(f"{c[0]}(게스트 메모리 {c[2] or '?'})" for c in run) or "없음")
                 + " — 이 VM 들의 RAM 이 호스트에서는 shmem/incus.service 로 보인다")
    else:
        L.append("- incus VM: 못 쟀음(조회 실패)")
    dk = sh(["docker", "ps", "--format", "{{.Names}}"])
    if dk is not None:
        names = dk.split()
        L.append(f"- 실행 중 Docker 컨테이너 {len(names)}개: " + ", ".join(names[:6]) + (" …" if len(names) > 6 else ""))
    else:
        L.append("- Docker: 못 쟀음(조회 실패)")
    return "\n".join(L)


def summary(s, sess, cons):
    lv, why = verdict(s)
    ax = verdict_axes(s)
    m = s["mem"]
    top = ", ".join(f"{friendly(p)} {g(b)}" for p, b in cons[:3])
    busy = sum(1 for r in sess if r[7] and r[7]["status"] == "busy")
    sub = sum(len(r[7]["sub"]["running"]) for r in sess if r[7])
    cg = s.get("psi_cgroups") or []
    guide = capacity_guide(s)
    return "\n".join([
        f"## 요약 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 측정, 이 호스트 한 대 기준)",
        f"- 판정 **{lv}** (속도 {NAMES[ax['speed'][0]]} · 용량 {NAMES[ax['capacity'][0]]})" + (f" — {why[0]}" if why else " — 압박 징후 없음"),
        f"- OOM 까지 여유 {g(headroom(s))}(MemAvailable {g(m['available_raw'])} + 스왑 여유); 새 작업은 약 {guide[0][0]:.1f} GiB 까지 바로, {guide[1][0]:.1f} GiB 까지 캐시를 밀어내며, "
        f"{guide[2][0]:.1f} GiB 까지 스왑 의존으로 띄울 수 있다(느려질 수 있음)",
        f"- 큰 메모리 소비자: {top or '없음'}" + (f" · 메모리 대기 주체: {friendly(cg[0]['path'])}(some {cg[0]['some_pct']:.1f}%)" if cg else ""),
        f"- LLM 세션 {len(sess)}개 중 작동중 {busy}개, 실행 중 서브에이전트 {sub}개 — 작동중인 만큼 지금 값은 평소보다 클 수 있다",
    ])


GUIDE = """## 읽는 법 (beelink-ser7-co 실측으로 보정한 기준 — 근거 `_plan/host-memory-verdict.md`)
1. 판정은 두 축이다. **속도**=메모리 PSI(작업이 기다린 시간 비율)의 지속(avg60)·순간(avg10), **용량**=OOM 까지 여유(MemAvailable + 스왑 여유). 남은 메모리 숫자나 스왑 사용량만으로 「압박」이라 하지 말 것.
2. 이 호스트는 ZRAM(우선순위 높음, 슬롯 15 GiB·압축 약 2.6배) 다음에 NVMe 스왑파일(24 GiB)이다(2026-10-26 실측, 아래 「스왑 기준점」 줄이 현재 보정값). ZRAM 슬롯이 차 있어도 정상이다 — 새 스왑은 디스크 스왑으로 가고 한 번 접근 p99 는 약 300µs 다(실측). 그래서 스왑 사용량·되읽기 숫자는 **정보**일 뿐 판정 근거가 아니다.
3. 시스템 전체 PSI 는 cgroup 하나가 혼자 스왑을 두드려도 오른다. 「메모리 대기를 만든 cgroup」 줄로 누구 때문인지 본 뒤, 그 주체가 사용자가 쓰는 앞 작업인지 판단한다(스왑 폭주 cgroup 이 있어도 무관한 프로세스의 지연은 거의 안 변했다 — 실측).
4. 「새 작업이 쓸 메모리별 영향」 표가 「더 띄워도 되나」의 답이다: 보수적 가용 이하면 바로, 낙관 가용까지는 캐시를 밀어내며, 그 위는 스왑 의존(느려질 수 있음), 그 이상은 OOM 위험. 활성 작업집합이 큰 작업(DB·빌드·VM)은 한 단계 낮춰 본다.
5. shmem·tmpfs(`/tmp`)·VM RAM 은 buff/cache 처럼 보여도 캐시가 아니다(비우면 되는 메모리로 세지 말 것). 세션 표의 「작동중」과 서브에이전트는 자원을 지금 쓰는 주체다. 못 쟀음 항목은 그대로 보고."""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secs", type=float, default=5)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--hist", default="3h")
    ap.add_argument("--no-sessions", action="store_true")
    ap.add_argument("--no-guide", action="store_true", help="읽는 법 블록 생략(반복 실행 시)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sb = None if a.no_sessions else sessions_begin()
    s = snapshot(a.secs)
    sess = [] if a.no_sessions else sessions_end(sb, a.secs > 0)
    if a.json:
        s["verdict"], s["reasons"] = verdict(s)
        ax = verdict_axes(s)
        s["axes"] = {k: dict(level=NAMES[v[0]], reasons=v[1]) for k, v in ax.items()}
        s["info"] = info_lines(s)
        s["headroom_gib"] = round(headroom(s) / GIB, 2)
        s["capacity"] = [dict(upto_gib=None if up == float("inf") else round(up, 2), meaning=t) for up, t in capacity_guide(s)]
        s["consumers"] = cgroup_consumers(a.top)
        s["sessions"] = [dict(pss_mib=r[0], pid=r[1], cwd=r[2], procs=r[3], age_h=r[5], kind=r[6], meta=r[7], children={c: dict(n=v[0], pss_mib=v[1], max_age_s=v[2]) for c, v in r[8].items()}) for r in sess]
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        cons = cgroup_consumers(a.top)
        out = [summary(s, sess, cons), "## 이 호스트\n" + host_context(s)]
        if not a.no_guide:
            out.append(GUIDE)
        out.append(render(s, a.top))
        h = parse_dur(a.hist)
        if h:
            out.append(history(h))
        if not a.no_sessions:
            out.append(render_sessions(sess))
        print("\n\n".join(out))


if __name__ == "__main__":
    main()
