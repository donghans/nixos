#!/usr/bin/env python3
"""power-report — Netdata 에 기록된 지표로 "전력 / 배터리 / CPU" 를 같은 시간축 그래프(PNG)와 요약 표로 보여준다.

사용:  power-report [--hours 6] [--from "2026-10-17 10:00" --to "2026-10-17 11:00"] [-o 파일.png]

그래프(위→아래, 시간축 공유):
  1. 배터리 잔량(%)
  2. 전력(W): 배터리 전력(전압×전류, 방향 구분 없는 크기), RAPL 패키지, RAPL psys(플랫폼 전체)
  3. CPU 사용률(%)과 평균 주파수(GHz)
  4. 패키지 온도(°C)
  5. AC 연결 여부와 TLP 적용 모드(전원 상태 기록기 netdata-power-state 가 남긴 값)
충전/방전 구분은 기록(`power.battery_state`)이 있는 구간은 실제 값, 기록이 없는 이전 구간은 잔량 변화로 추정(그래프 제목에 표시).
요약: 구간 평균/최대 전력, 방전 구간의 추정 남은 시간.
주의: 배터리 전류는 충전/방전 부호가 없는 크기다. 데이터는 Netdata 가 켜져 있던 시간에만 있다.
"""
import argparse, json, math, os, sys, time, urllib.parse, urllib.request
from datetime import datetime

API = os.environ.get("NETDATA_URL", "http://127.0.0.1:19999")
BAT = "/sys/class/power_supply/BAT1"
CHARTS = {
    "cap": "powersupply_capacity.BAT1",
    "volt": "sensors.voltage_BAT1-acpi-0_in0_input",
    "curr": "sensors.curr_BAT1-acpi-0_curr1_input",
    "pkg": "cpu.powercap_intel_rapl_zone_package-0",
    "psys": "cpu.powercap_intel_rapl_zone_psys",
    "cpu": "system.cpu",
    "freq": "cpu.cpufreq",
    "temp": "sensors.temperature_coretemp-isa-0000_temp1_Package_id_0_input",
    # 전원 상태 기록기(mods/sys/services/netdata.nix 의 netdata-power-state)가 statsd 로 보낸 게이지
    "acon": "statsd_power.ac_online_gauge",
    "bstate": "statsd_power.battery_state_gauge",
    "tlp": "statsd_power.tlp_profile_gauge",
}


def get(chart, t0, t1, points):
    q = urllib.parse.urlencode({"chart": chart, "after": int(t0), "before": int(t1), "points": points, "group": "average", "format": "json"})
    try:
        with urllib.request.urlopen(f"{API}/api/v1/data?{q}", timeout=20) as r:
            d = json.load(r)
    except Exception as e:
        print(f"경고: {chart} 를 읽지 못함 ({e})", file=sys.stderr)
        return [], []
    rows = sorted(d["data"], key=lambda r: r[0])
    return d["labels"][1:], rows


def series(chart, t0, t1, points, reduce="sum", skip=()):
    labels, rows = get(chart, t0, t1, points)
    ts, vs = [], []
    for r in rows:
        vals = [v for l, v in zip(labels, r[1:]) if v is not None and l not in skip]
        ts.append(r[0])
        vs.append(None if not vals else (sum(vals) if reduce == "sum" else sum(vals) / len(vals) if reduce == "mean" else vals[0]))
    return ts, vs


def sysfs(name):
    try:
        return int(open(f"{BAT}/{name}").read().strip())
    except Exception:
        return None


def mean(xs):
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser(description="Netdata 전력/배터리/CPU 그래프")
    ap.add_argument("--hours", type=float, default=6, help="최근 몇 시간 (기본 6)")
    ap.add_argument("--from", dest="t_from", help='시작 "YYYY-MM-DD HH:MM"')
    ap.add_argument("--to", dest="t_to", help='끝 "YYYY-MM-DD HH:MM" (기본 지금)')
    ap.add_argument("-o", "--out", help="저장할 PNG 경로 (기본 ~/Pictures/power-report/<시각>.png)")
    ap.add_argument("--no-plot", action="store_true", help="그래프 없이 요약만")
    a = ap.parse_args()
    parse = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()
    t1 = parse(a.t_to) if a.t_to else time.time()
    t0 = parse(a.t_from) if a.t_from else t1 - a.hours * 3600
    # 해상도: 점 사이 간격을 최소 20초로(배터리에서는 수집 간격이 10초라 더 촘촘하면 빈 점이 생겨 선이 끊김), 최대 900점
    points = int(min(900, max(30, (t1 - t0) / 20)))

    data = {}
    for k, c in CHARTS.items():
        red = "mean" if k in ("freq",) else "sum"
        skip = ("idle",) if k == "cpu" else ()
        data[k] = series(c, t0, t1, points, reduce=red, skip=skip)
    ts = [t for t, v in zip(*data["cap"]) if v is not None]
    if not ts:
        print("이 구간에 기록이 없습니다 (Netdata 가 꺼져 있었거나 보존 기간 밖).")
        return 1

    # 배터리 전력 = 전압 × 전류 (시간축을 맞추려고 공통 ts 의 같은 인덱스를 씀 — 같은 points/구간으로 질의했으므로 정렬됨)
    def aligned(k):
        t, v = data[k]
        m = dict(zip(t, v))
        return [m.get(x) for x in ts]
    volt, curr = aligned("volt"), aligned("curr")
    batw = [(v * i if v is not None and i is not None else None) for v, i in zip(volt, curr)]
    pkg, psys = aligned("pkg"), aligned("psys")
    cpu, freq, temp, cap = aligned("cpu"), aligned("freq"), aligned("temp"), aligned("cap")
    freq_ghz = [None if f is None else f / 1000 for f in freq]

    acon, bstate, tlp = aligned("acon"), aligned("bstate"), aligned("tlp")
    # 충전/방전: 기록(power.battery_state)이 있으면 그 값, 없으면 구간 안 잔량 변화로 추정(10분 이동 창)
    win = max(1, int(600 / max(1, (ts[-1] - ts[0]) / max(1, len(ts) - 1))))
    CODE = {0: "방전", 1: "충전", 2: "만충", 3: "만충"}
    state, recorded = [], 0
    for i in range(len(ts)):
        if bstate[i] is not None and round(bstate[i]) in CODE:
            state.append(CODE[round(bstate[i])]); recorded += 1
            continue
        j = max(0, i - win)
        d = (cap[i] - cap[j]) if cap[i] is not None and cap[j] is not None else 0
        state.append("충전" if d > 0.5 else "방전" if d < -0.5 else "-")
    rec_note = "기록" if recorded == len(ts) else f"기록 {recorded}/{len(ts)}점, 나머지는 잔량 변화로 추정" if recorded else "잔량 변화로 추정(기록 없음)"

    # 요약
    fmt = lambda x: "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.1f}"
    dt = (ts[-1] - ts[0]) / 3600
    print(f"구간 {datetime.fromtimestamp(ts[0]):%m-%d %H:%M} ~ {datetime.fromtimestamp(ts[-1]):%m-%d %H:%M} ({dt:.1f}시간, {len(ts)}점)")
    print(f"  배터리 전력(전압×전류) 평균 {fmt(mean(batw))} W / 최대 {fmt(max([x for x in batw if x is not None], default=None))} W")
    print(f"  RAPL 패키지 평균 {fmt(mean(pkg))} W | psys(플랫폼) 평균 {fmt(mean(psys))} W | CPU 사용률 평균 {fmt(mean(cpu))}% | 평균 주파수 {fmt(mean(freq_ghz))} GHz")
    dis = [w for w, s in zip(batw, state) if s == "방전" and w is not None]
    full = sysfs("charge_full")
    vnow = mean(volt)
    last_cap = next((c for c in reversed(cap) if c is not None), None)
    if dis and full and not math.isnan(vnow) and last_cap is not None and state[-1] == "방전":
        e_full = full / 1e6 * vnow   # Wh (충전량 Ah × 평균 전압)
        w_recent = mean(dis[-max(3, win):])
        print(f"  방전 중: 최근 평균 {w_recent:.1f} W, 잔량 {last_cap:.0f}% → 이 속도라면 약 {last_cap/100*e_full/w_recent:.1f}시간 남음 (전체 약 {e_full:.0f} Wh 기준, 추정)")
    elif state and state[-1] != "방전":
        print(f"  지금은 {state[-1] if state[-1] != '-' else '충전/방전 변화 없음'} 상태 — 남은 시간 계산 생략")
    if dis:
        print(f"  방전 구간 평균 {mean(dis):.1f} W (샘플 {len(dis)}개)")
    # 상태별 평균 전력 (psys, 패키지) — AC/배터리·TLP 모드 비교용
    for name in ("방전", "충전", "만충"):
        idx = [i for i, st in enumerate(state) if st == name]
        if idx:
            print(f"  [{name}] {len(idx)}점: psys {fmt(mean([psys[i] for i in idx]))} W, 패키지 {fmt(mean([pkg[i] for i in idx]))} W, CPU {fmt(mean([cpu[i] for i in idx]))}%, 주파수 {fmt(mean([freq_ghz[i] for i in idx]))} GHz")
    for tv, tn in ((0, "TLP=AC 모드"), (1, "TLP=배터리 모드")):
        idx = [i for i, v in enumerate(tlp) if v is not None and round(v) == tv]
        if idx:
            print(f"  [{tn}] {len(idx)}점: psys {fmt(mean([psys[i] for i in idx]))} W, 패키지 {fmt(mean([pkg[i] for i in idx]))} W, CPU {fmt(mean([cpu[i] for i in idx]))}%")
    if a.no_plot:
        return 0

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    X = [datetime.fromtimestamp(t) for t in ts]
    BG, GRID, FG, MUTED = "#000000", "#262626", "#cfcfcf", "#9a9a9a"
    CY, BL, AM, GR, RD = "#33ccff", "#268bd2", "#ebcb8b", "#8fbf7f", "#e06c75"
    from matplotlib import font_manager as fm
    have = {f.name for f in fm.fontManager.ttflist}
    ko = [n for n in ("NanumGothic", "NanumBarunGothic", "Malgun Gothic", "Pretendard") if n in have]
    plt.rcParams.update({"font.family": ko + ["DejaVu Sans"], "axes.unicode_minus": False})
    fig, ax = plt.subplots(5, 1, figsize=(13, 10.2), sharex=True, gridspec_kw={"height_ratios": [1.1, 1.6, 1.2, 0.8, 0.55], "hspace": 0.12})
    fig.patch.set_facecolor(BG)
    for x in ax:
        x.set_facecolor(BG)
        x.grid(True, color=GRID, lw=0.7)
        for s in x.spines.values():
            s.set_color("#595959")
        x.tick_params(colors=MUTED, labelsize=9)
    nn = lambda v: [float("nan") if y is None else y for y in v]
    # 충전/방전 배경
    i = 0
    while i < len(X) - 1:
        j = i
        while j + 1 < len(X) - 1 and state[j + 1] == state[i]:
            j += 1
        if state[i] in ("충전", "방전"):
            for x in ax:
                x.axvspan(X[i], X[j + 1], color=(GR if state[i] == "충전" else AM), alpha=0.10, lw=0)
        elif state[i] == "만충":
            for x in ax:
                x.axvspan(X[i], X[j + 1], color=BL, alpha=0.08, lw=0)
        i = j + 1
    ax[0].plot(X, nn(cap), color=CY, lw=1.8); ax[0].set_ylabel("배터리 잔량 (%)", color=FG); ax[0].set_ylim(0, 105)
    ax[1].plot(X, nn(psys), color=AM, lw=1.2, label="RAPL psys (플랫폼 전체)")
    ax[1].plot(X, nn(batw), color=CY, lw=1.4, label="배터리 전력 (전압×전류)")
    ax[1].plot(X, nn(pkg), color=BL, lw=1.2, label="RAPL 패키지 (CPU)")
    ax[1].set_ylabel("전력 (W)", color=FG); ax[1].set_ylim(bottom=0)
    leg = ax[1].legend(loc="upper left", fontsize=9, facecolor=BG, edgecolor="#595959", labelcolor=FG, ncol=3)
    ax[2].plot(X, nn(cpu), color=BL, lw=1.2); ax[2].set_ylabel("CPU 사용률 (%)", color=BL); ax[2].set_ylim(0, 100)
    f2 = ax[2].twinx(); f2.plot(X, nn(freq_ghz), color=AM, lw=1.0); f2.set_ylabel("평균 주파수 (GHz)", color=AM); f2.tick_params(colors=MUTED, labelsize=9); f2.set_ylim(bottom=0)
    for s in f2.spines.values():
        s.set_color("#595959")
    ax[3].plot(X, nn(temp), color=RD, lw=1.2); ax[3].set_ylabel("패키지 온도 (°C)", color=FG)
    # 전원 상태 기록: AC 연결(1/0)과 TLP 적용 모드(0=AC, 1=배터리)를 단계선으로
    if any(v is not None for v in acon + tlp):
        ax[4].step(X, nn([None if v is None else round(v) for v in acon]), where="post", color=CY, lw=1.4, label="AC 연결 (1=연결)")
        ax[4].step(X, nn([None if v is None else round(v) + 0.0 for v in tlp]), where="post", color=AM, lw=1.2, ls="--", label="TLP 모드 (0=AC, 1=배터리)")
        ax[4].set_yticks([0, 1]); ax[4].set_ylim(-0.3, 1.3)
        ax[4].legend(loc="center left", fontsize=8, facecolor=BG, edgecolor="#595959", labelcolor=FG, ncol=2)
    else:
        ax[4].text(0.5, 0.5, "전원 상태 기록 없음 (netdata-power-state 가 켜진 뒤부터 기록됨)", transform=ax[4].transAxes, ha="center", va="center", color=MUTED, fontsize=9)
    ax[4].set_ylabel("전원 상태", color=FG)
    ax[4].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); ax[3].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=12))
    for x in ax:
        x.set_xlim(X[0], X[-1])
    fig.suptitle(f"전력 / 배터리 / CPU   {X[0]:%m-%d %H:%M} ~ {X[-1]:%m-%d %H:%M}   (노란 배경=방전, 초록=충전, 파랑=만충 · 상태: {rec_note})", color=FG, fontsize=11, y=0.94)
    out = a.out or os.path.expanduser(f"~/Pictures/power-report/{datetime.now():%Y%m%d-%H%M%S}.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=BG, bbox_inches="tight")
    print("그래프:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
