#!/usr/bin/env python3
"""swapbench — 이 호스트의 **스왑 경로 기준점**을 재고 `hostmetrics.HOST_CALIBRATION` 에 붙일 항목을 낸다.

왜: 판정(hostmetrics)은 「스왑이 빠른 호스트(NVMe)」라는 전제로 스왑 사용·되읽기를 정보로 두고 OOM 까지 여유·PSI 만 판정에 쓴다.
다른 워크스테이션(NVMe 가 아니거나 스왑 구성이 다른 곳)은 이 전제가 맞는지 모르므로, 같은 시험을 돌려 숫자를 기록해 두면 그 숫자로 해석할 수 있다.

무엇을 재나(2026-10-26 beelink-ser7-co 에서 쓴 방식 그대로)
  - cgroup 메모리 제한(기본 300 MiB) 안에서 제한보다 큰 영역(기본 1536 MiB)을 쓰고 읽어 스왑 경로를 강제로 탄다.
    채우기·순차 읽기(스왑인+동시 스왑아웃) 처리량, 무작위 접근 한 번의 지연 분포(p50/p99), RAM 상주 기준선.
  - --bystander: 별도 scope 의 프로브가 스왑 폭주 중에도 영향을 받는지(sleep 1ms 초과 지연, 16 MiB 새 메모리 받기 시간) 스레셔 없음/있음으로 비교.
호스트 영향: 약 2 GiB 를 스왑에 쓰고(NVMe 마모는 무시할 수준으로 추정) 디스크를 수십 초 두드린다. 다른 세션이 큰 일을 하지 않을 때만 돌린다.
  호스트가 바쁘면(메모리 PSI full avg60 ≥1%) 또는 스왑 여유가 4 GiB 미만이면 거부한다(--force 로 무시).

사용: python3 -I swapbench.py [--mib 1536] [--limit 300M] [--bystander] [--entry] [--force]
  --entry 는 HOST_CALIBRATION 에 붙일 파이썬 항목을 출력한다(값은 이 실행의 측정치).
"""
import argparse, json, mmap, os, random, socket, subprocess, sys, time

PG = 4096


def pct(x, p):
    x = sorted(x)
    return x[min(int(len(x) * p), len(x) - 1)]


def vm():
    return {k: int(v) for k, v in (l.split() for l in open("/proc/vmstat"))}


def psi_total(kind="memory"):
    o = {}
    for l in open(f"/proc/pressure/{kind}"):
        p = l.split()
        o[p[0]] = int(dict(x.split("=") for x in p[1:])["total"])
    return o


def psi_avg60(kind="memory", level="full"):
    for l in open(f"/proc/pressure/{kind}"):
        p = l.split()
        if p[0] == level:
            return float(dict(x.split("=") for x in p[1:])["avg60"])
    return 0.0


def swaps():
    o = {}
    for l in open("/proc/swaps").read().splitlines()[1:]:
        f = l.split()
        o[f[0]] = (int(f[2]) * 1024, int(f[3]) * 1024)
    return o


def cg(name):
    path = "/sys/fs/cgroup" + open("/proc/self/cgroup").read().strip().split(":")[2]
    return int(open(f"{path}/{name}").read())


def bench(n_mb):
    """제한된 cgroup 안에서 실행. 결과 dict."""
    size, npg = n_mb << 20, (n_mb << 20) // PG
    res = {}
    buf = mmap.mmap(-1, size)
    v0, p0, s0, t0 = vm(), psi_total(), swaps(), time.monotonic()
    for off in range(0, size, 1 << 20):
        buf[off:off + (1 << 20)] = os.urandom(1 << 20)
    dt = time.monotonic() - t0
    v1, s1 = vm(), swaps()
    res["fill"] = dict(sec=round(dt, 2), mib_s=round(n_mb / dt), pswpout_pages=v1["pswpout"] - v0["pswpout"],
                       swap_used_delta_mib={k: round((s1[k][1] - s0.get(k, (0, 0))[1]) / (1 << 20)) for k in s1}, cg_swap_mib=cg("memory.swap.current") >> 20)
    time.sleep(1)
    x = 0
    for r in range(2):
        v0, t0 = vm(), time.monotonic()
        for off in range(0, size, PG):
            x += buf[off]
        dt = time.monotonic() - t0
        v1 = vm()
        res[f"seq{r}"] = dict(sec=round(dt, 2), mib_s=round(n_mb / dt), pswpin_pages=v1["pswpin"] - v0["pswpin"], pswpout_pages=v1["pswpout"] - v0["pswpout"])
    random.seed(1)
    idx = [random.randrange(npg) for _ in range(30000)]
    lat, t0 = [], time.monotonic()
    for i in idx:
        a = time.perf_counter_ns()
        x += buf[i * PG]
        lat.append(time.perf_counter_ns() - a)
    dt = time.monotonic() - t0
    us = [l / 1000 for l in lat]
    res["rand"] = dict(accesses=len(idx), sec=round(dt, 2), per_s=round(len(idx) / dt), lat_us={k: round(pct(us, p), 1) for k, p in (("p50", .5), ("p90", .9), ("p99", .99), ("p999", .999))}, max_us=round(max(us)))
    small = memoryview(buf)[:min(size, 64 << 20)]
    n_small = len(small) // PG
    for i in range(0, len(small), PG):
        x += small[i]
    lat = []
    for i in random.sample(range(n_small), min(10000, n_small)):
        a = time.perf_counter_ns()
        x += small[i * PG]
        lat.append(time.perf_counter_ns() - a)
    us = [l / 1000 for l in lat]
    res["resident_us"] = {k: round(pct(us, p), 2) for k, p in (("p50", .5), ("p99", .99))}
    return res


def probe(dur):
    """무관한 프로세스 역할: sleep(1ms) 초과 지연과 16 MiB 새 메모리 받아 건드리는 시간."""
    over, alloc, n, t_end = [], [], 0, time.monotonic() + dur
    while time.monotonic() < t_end:
        a = time.perf_counter_ns()
        time.sleep(0.001)
        over.append((time.perf_counter_ns() - a) / 1000 - 1000)
        n += 1
        if n % 50 == 0:
            a = time.perf_counter_ns()
            b = bytearray(16 << 20)
            for i in range(0, 16 << 20, PG):
                b[i] = 1
            alloc.append((time.perf_counter_ns() - a) / 1e6)
            del b
    return dict(sleep_over_us={k: round(pct(over, p), 1) for k, p in (("p50", .5), ("p99", .99))}, sleep_max_us=round(max(over)),
                alloc16_ms={k: round(pct(alloc, p), 2) for k, p in (("p50", .5), ("p99", .99))}, alloc_max_ms=round(max(alloc), 2))


def scope(limit, args):
    """제한 scope 안에서 이 스크립트를 다른 모드로 실행하는 명령."""
    base = ["systemd-run", "--user", "--scope", "-q"]
    if limit:
        base += ["-p", f"MemoryMax={limit}", "-p", "MemorySwapMax=3G"]
    return base + [sys.executable, "-I", os.path.abspath(__file__)] + args


def entry(res, by, mib):
    f = res["rand"]["lat_us"]
    seq = round((res["seq0"]["mib_s"] + res["seq1"]["mib_s"]) / 2)
    sw = swaps()
    devs = ", ".join(f"{os.path.basename(n)}({'zram' if 'zram' in n else '디스크'})" for n in sw)
    if by:
        b, t = by["baseline"], by["thrash"]
        bystander = (f"스왑 폭주 중 무관한 프로세스 지연(sleep 1ms 초과 p99 {b['sleep_over_us']['p99']}→{t['sleep_over_us']['p99']}µs, "
                     f"16MiB 할당 p99 {b['alloc16_ms']['p99']}→{t['alloc16_ms']['p99']}ms)")
    else:
        bystander = "무관한 프로세스 영향은 측정하지 않음(--bystander 로 측정)"
    zr = [(u / sz * 100) for n, (sz, u) in sw.items() if "zram" in n and sz]
    note = (f"측정 당시 ZRAM 슬롯 {zr[0]:.0f}% 사용 — 슬롯에 여유가 있으면 일부가 ZRAM 에 적중해 p50 이 크게 낮아진다(p99 는 디스크 경로). 같은 호스트에서도 ZRAM 상태에 따라 p50 이 달라지니 반복 측정 권장" if zr
            else "ZRAM 없음")
    return (f'    "{socket.gethostname()}": dict(\n        measured="{time.strftime("%Y-%m-%d")}", source="swapbench.py --mib {mib}",\n'
            f'        swap="{devs}", rotational=None,  # rotational 은 직접 확인해 True/False 로 고칠 것\n'
            f'        random_fault_us=dict(p50={f["p50"]}, p99={f["p99"]}, p999={f["p999"]}), seq_mib_s={seq}, fill_mib_s={res["fill"]["mib_s"]},\n'
            f'        bystander="{bystander}",\n        note="{note}",\n        thresholds={{}},\n    ),')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mib", type=int, default=1536)
    ap.add_argument("--limit", default="300M")
    ap.add_argument("--bystander", action="store_true")
    ap.add_argument("--entry", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--probe", type=float, default=0, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.probe:
        print(json.dumps(probe(a.probe)))
        return
    if a.inner:
        print(json.dumps(bench(a.mib)))
        return
    sw = swaps()
    free = sum(s - u for s, u in sw.values())
    if not a.force and (psi_avg60() >= 1.0 or free < (4 << 30)):
        sys.exit(f"거부: 호스트가 바쁘거나(메모리 PSI full avg60 {psi_avg60():.1f}%) 스왑 여유가 {free / (1 << 30):.1f} GiB 로 부족하다. 조용해진 뒤에 다시, 또는 --force")
    by = None
    if a.bystander:
        base = json.loads(subprocess.run(scope(None, ["--probe", "8"]), capture_output=True, text=True).stdout.splitlines()[-1])
    th = subprocess.Popen(scope(a.limit, ["--inner", "--mib", str(a.mib)]), stdout=subprocess.PIPE, text=True)
    if a.bystander:
        time.sleep(9)          # 채우기가 끝나고 순차 읽기(스왑 양방향)에 들어간 뒤
        thr = json.loads(subprocess.run(scope(None, ["--probe", "12"]), capture_output=True, text=True).stdout.splitlines()[-1])
        by = dict(baseline=base, thrash=thr)
    out = th.communicate()[0]
    res = json.loads(out.splitlines()[-1])
    print(json.dumps(dict(result=res, bystander=by), ensure_ascii=False, indent=1))
    if a.entry:
        print("\n# hostmetrics.HOST_CALIBRATION 에 붙일 항목:\n" + entry(res, by, a.mib))


if __name__ == "__main__":
    main()
