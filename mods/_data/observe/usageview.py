"""usageui 의 화면 조각(rich Text·표 행만 만든다 — Textual 앱 없이 시험 가능). 이름·단위·'측정/추정' 라벨은 여기서 한 곳에 정한다."""
from __future__ import annotations

import time

from rich.cells import cell_len
from rich.text import Text

import observe_explain as ex
import usagechart as uc
import usagegraph as pg
import usagedata as ud

LOW_GLOSS = "low = 깊은 절전 상태에 들어간 시간(패키지 pc10 ≥ 5%) — 전력이 낮다는 뜻이 아님"


def pad(s, n):
    """한글(2칸 폭)을 칸 수로 세어 오른쪽을 공백으로 채운다(f-string 의 :<n 은 글자 수라 한글 표가 어긋남)."""
    return s + " " * max(0, n - cell_len(s))


def _f(x, p=2, unit=""):
    try:
        x = float(x)   # /proc 에서 읽은 값(load1 등)은 문자열로 들어올 수 있다
    except (TypeError, ValueError):
        return "-"
    return "-" if x != x else f"{x:.{p}f}{unit}"


def _line(t, label, value, note="", vstyle="bold", lw=16, vw=22):
    t.append(" " + pad(label, lw), style="grey70")
    t.append(pad(value, vw), style=vstyle)
    if note:
        t.append(note, style="grey50")
    t.append("\n")


def freshness(view, now=None):
    """상단 한 줄: 데이터 기준 시각과 새로고침 안내. 지금까지 범위가 오래됐으면 경고."""
    now = now if now is not None else time.time()
    rng = view["range"]
    at = time.strftime("%H:%M:%S", time.localtime(view["loaded_at"]))
    age = ud.stale(view, now)
    head = f"데이터 기준 {at}" + ("(지금까지)" if rng.follows_now else "(고정 범위)")
    if age is not None and age > ud.STALE_S:
        head += f" · ⚠ {int(age // 60)}분 전 데이터 — r 로 새로고침"
    else:
        head += " · r 새로고침"
    return head


def summary_range(view):
    s, rng = view["summary"], view["range"]
    t = Text()
    _line(t, "범위", f"{s['range']}", f"{rng.label}" + (" · 지금까지" if rng.follows_now else ""), lw=14, vw=14)
    _line(t, "수집", f"표본 {s['n']}개", f"{pg.fmt_dur(s['hours'])}" + (f" · 공백 {int(s['gap_s'])}초" if s["gap_s"] >= 60 else ""), lw=14, vw=14)
    b = view["baseline"]
    if b:
        f = lambda x: time.strftime("%H:%M", time.localtime(x))
        _line(t, "비교 기준", f"{f(b[0])} ~ {f(b[1])}", "원인 탭", lw=14, vw=14)
    return t


def summary_power(view):
    s = view["summary"]
    t = Text()
    if not s["n"]:
        t.append(" 이 범위에는 표본이 없습니다 — `observectl on` 으로 수집을 켜고 시간이 지나야 합니다.\n", style="grey70")
        return t
    if not view["profile"]["battery"]:
        # 데스크톱형: 배터리·psys 가 없으니 패키지 전력과 CPU·문맥 전환으로 요약한다
        _line(t, "평균 패키지 전력", _f(s["avg_pkg_w"], 1, " W"), "측정 · RAPL, CPU+GPU 만(전체 소비 아님)", lw=18, vw=10)
        _line(t, "패키지 전력량", _f(s["pkg_wh"], 2, " Wh"), "측정 · 적분", lw=18, vw=10)
        _line(t, "평균 CPU", _f(s["avg_cpu_pct"], 1, "%"), "측정 · 전체 CPU 대비", lw=18, vw=10)
        _line(t, "평균 문맥 전환", _f(s["avg_ctxsw"], 0, "/s"), "측정 · 시스템 전체", lw=18, vw=10)
        return t
    _line(t, "평균 전력", _f(s["avg_psys_w"], 2, " W"), "측정 · psys", lw=14, vw=14)
    _line(t, "쓴 전력량", _f(s["psys_wh"], 2, " Wh"), "측정 · 적분", lw=14, vw=14)
    c = s["coulomb"]
    if c:
        short = c["hours"] < 10 / 60
        _line(t, "배터리에서 쓴", f"{c['wh']:.2f} Wh · {pg.fmt_dur(c['hours'])}", f"측정 · ±{c['err_w']:.2f} W" + (" 오차 큼" if short else ""),
              vstyle="bold" if not short else "grey70", lw=14, vw=14)
    else:
        _line(t, "배터리에서 쓴", "-", "방전 구간 없음", vstyle="grey50", lw=14, vw=14)
    _line(t, "배터리 잔량", f"{_f(s['pct_first'], 0, '%')} → {_f(s['pct_last'], 0, '%')}", f"충전 {s['charges']}회", lw=14, vw=14)
    return t


def bar_line(label, frac, width, style="cyan"):
    t = Text()
    t.append(" " + pad(label, 22), style="grey70")
    t.append(pg.hbar(frac or 0, width), style=style if frac is not None else "grey35")
    t.append(f" {'-' if frac is None else format(frac * 100, '.0f') + '%':>5}")
    return t


def summary_habit(view, w):
    sh = view["summary"]["shares"]
    bw = max(10, min(40, w - 36))
    t = Text()
    items = [("덮개 열림", sh.get("lid_open"), "cyan"), ("배터리로 사용(방전)", sh.get("discharging"), "dark_orange"), ("AC 전원 연결", sh.get("ac"), "dodger_blue1"),
             ("PSR 켬(화면 절전)", sh.get("psr"), "cyan"), ("low (깊은 절전 진입)", sh.get("low"), "green")]
    for i, (lab, frac, st) in enumerate(items):
        t.append_text(bar_line(lab, frac, bw, st))
        t.append("\n")
    t.append(" " + LOW_GLOSS, style="grey50")
    return t


def summary_apps(view, w):
    s = view["summary"]
    t = Text()
    bw = max(4, min(24, w - 40))
    if s["top_apps"]:
        t.append(" CPU 점유가 큰 앱 (코어 1개=100%)\n", style="bold")
        for name, cpu, share, ctx in s["top_apps"]:
            t.append(" " + pad(name[:16], 17) + f"{cpu:>6.1f}%  ", style="white")
            t.append(pg.hbar(share / 100, bw), style="magenta")
            t.append(f" {share:>3.0f}%\n", style="grey50")
    else:
        t.append(" 앱 단위 표본(v4)이 아직 없습니다.\n", style="grey50")
    t.append("\n")
    if s["focus"]:
        t.append(" 가장 오래 본 앱(창 포커스 시간)\n", style="bold")
        for name, sec, pct in s["focus"]:
            t.append(" " + pad(name[:16], 17) + pad(pg.fmt_dur(sec / 3600), 9) + "  ", style="white")
            t.append(pg.hbar(pct / 100, bw), style="cyan")
            t.append(f" {pct:>3.0f}%\n", style="grey50")
    else:
        t.append(" 창 포커스 기록이 없습니다.\n", style="grey50")
    return t


def summary_estimate(view):
    s = view["summary"]
    e = s["estimate"]
    t = Text()
    if e is None:
        t.append(" 범위의 끝이 '지금'이 아니거나 최근 표본이 없어 계산하지 않습니다(예상 사용 시간은 지금 기준).\n", style="grey50")
        return t
    if e.get("charging"):
        t.append(" 충전 중이라 계산하지 않습니다 — 충전기를 뽑으면 방전 기준으로 계산합니다.\n", style="grey70")
        return t
    t.append(f" 잔량 {_f(e.get('remain_wh'), 1, ' Wh')} / 만충 {_f(e.get('full_wh'), 1, ' Wh')} ({_f(e.get('pct'), 0, '%')})\n", style="white")
    for key, lab in (("now", "지금 전력 기준"), ("recent", "최근 30분 기준"), ("typical", "최근 6시간 평소 기준")):
        w, h = e.get(key + "_w"), e.get(key + "_h")
        t.append(" " + pad(lab, 14), style="grey70")
        t.append(pad(pg.fmt_dur(h), 10), style="bold")
        t.append(f"{_f(w, 1, ' W')}\n", style="grey50")
    t.append(" 추정: 잔량 ÷ 전력, 0% 까지 쓴다고 가정(실제로는 5~10% 남기고 끔). 검증은 하드웨어·배터리 탭의 방전 곡선(하루 이상 쌓인 뒤).", style="grey50")
    return t


# ------------------------------------------------------------------ 표 행
def apps_rows(view):
    got = view["apps"]
    if not got:
        return []
    table, _ = got
    tot_cpu = sum(v["cpu"] for v in table.values()) or 1.0
    # 앱별 전력량 추정의 기준: psys 가 있으면 psys, 없으면(데스크톱) 패키지(CPU+GPU) 전력량
    psys_wh = view["summary"]["psys_wh"] if view["profile"]["psys"] else view["summary"]["pkg_wh"]
    rows = []
    for k, v in sorted(table.items(), key=lambda kv: -kv[1]["cpu"])[:20]:
        share = v["cpu"] / tot_cpu
        rows.append((k, f"{v['cpu']:.1f}", f"{share * 100:.0f}%", f"{v['ctxsw']:.0f}", f"{v['rss']:.0f}", f"{v['n']:.0f}",
                     "-" if psys_wh is None else f"{psys_wh * share:.2f}"))
    return rows


def focus_rows(view):
    return [(n, pg.fmt_dur(s / 3600), f"{p:.0f}%") for n, s, p in ex.focus_table(view["spans"], view["range"].t0, view["range"].t1)[:15]]


def proc_rows(view):
    table, nctx = view["procs"]
    rows = []
    for c, v in sorted(table.items(), key=lambda kv: -kv[1]["cpu"])[:20]:
        rows.append((c, f"{v['cpu']:.1f}", "-" if v["ctxsw"] is None else f"{v['ctxsw']:.0f}"))
    return rows


def ebpf_rows(view):
    e = view["ebpf"]
    if not e:
        return None
    return [(p["comm"], str(p["pid"]), f"{p.get('cpu', 0):.1f}", f"{p.get('vol', 0):.0f}", f"{p.get('invol', 0):.0f}", f"{p.get('sw', 0):.0f}") for p in e["procs"]], e


def span_rows(view):
    out = []
    for name, sec, en in view["span_rows"]:
        row = (name, tr_dur(sec))
        out.append(row + (("-" if not en else f"{en['psys_wh']:.2f} Wh"),) if view["profile"]["psys"] else row)   # psys 가 없으면 전력량 열이 없다
    return out


def tr_dur(sec):
    import observe_trace as tr
    return tr.fmt_dur(sec)


# ------------------------------------------------------------------ 전력 탭 그래프
POWER_SERIES = [  # (제목, 필드, 단위, 색, 하한, 상한, 형식, 그라데이션)
    ("psys — RAPL 플랫폼 전력(측정, 총 소비보다 약 1 W 적게 보임)", "psys", "W", "cyan", 0.0, None, "{:.1f}", True),
    ("패키지 — CPU+GPU 전력(측정)", "pkg", "W", "magenta", 0.0, None, "{:.1f}", False),
    ("배터리 소비 — 순간 V×I, 방전 중에만(측정, 노이즈 큼)", "batt_vi", "W", "dark_orange", 0.0, None, "{:.1f}", True),
    ("배터리 잔량", "pct", "%", "green", 0.0, 100.0, "{:.0f}", False),
    ("전체 CPU(전체 대비 %, 측정)", "cpu_all", "%", "green", 0.0, 100.0, "{:.0f}", False),
    ("시스템 전체 문맥 전환(측정)", "ctxsw_all", "/s", "cyan", 0.0, None, "{:.0f}", False),
]


def power_chart(view, i, w, h):
    title, key, unit, style, lo, hi, fmt, grad = POWER_SERIES[i]
    rng = view["range"]
    text, st = uc.chart(uc.series_points(view["recs"], key), rng.t0, rng.t1, w, h, unit, style, lo, hi, fmt, gradient=grad, axis=False)
    return text, uc.stats_str(st, unit, fmt)


def power_bands(view, w):
    rng = view["range"]
    return uc.bands_text(view["recs"], rng.t0, rng.t1, w), f"{view['summary']['range']} · 표본 {len(view['recs'])}개"


# ------------------------------------------------------------------ 시스템(Netdata)·하드웨어
ND_CHARTS = [("psys_w", "Netdata · psys 1초 평균", "W", "cyan"), ("cpu_all_pct", "Netdata · 전체 CPU(전체 대비 %)", "%", "green"),
             ("net_rx_kbps", "Netdata · 네트워크 수신", "kbit/s", "dodger_blue1"), ("disk_write_kibs", "Netdata · 디스크 쓰기", "KiB/s", "magenta"),
             ("nvme_temp_c", "Netdata · NVMe 온도", "°C", "dark_orange")]


def nd_charts(profile):
    """이 호스트에 있는 센서의 Netdata 차트만(psys 가 없으면 psys 차트 제외)."""
    return [c for c in ND_CHARTS if profile["psys"] or c[0] != "psys_w"]


def nd_chart(sysdata, key, rng, w, h):
    pts = (sysdata or {}).get("series", {}).get(key)
    if not pts:
        return Text(" 이 범위에 Netdata 값이 없습니다(Netdata 가 꺼져 있었거나 응답 없음 → '관측 공백')", style="grey50"), ""
    unit = next(u for k, _, u, _ in ND_CHARTS if k == key)
    style = next(s for k, _, _, s in ND_CHARTS if k == key)
    text, st = uc.chart(pts, rng.t0, rng.t1, w, h, unit, style, fmt=None, gradient=False)
    return text, uc.stats_str(st, unit)


def nd_signal_rows(sysdata, view=None):
    """Netdata 신호 표 행. V×I 는 구간 전체의 |전압×전류| 평균이라 충전·AC 시간이 섞이면 방전 전력이 아니므로 값을 가리고 이유를 적는다."""
    if not sysdata or not sysdata.get("snap"):
        return []
    import observe_netdata as nd
    sig = sysdata["snap"]["signals"]
    mixed = bool(view) and any(r["status"] != "Discharging" for r in view["recs"])
    prof = (view or {}).get("profile") or {"battery": True, "psys": True}
    rows = []
    for k, v in sig.items():
        if (k == "psys_w" and not prof["psys"]) or (k == "batt_vi_w" and not prof["battery"]):
            continue                         # 이 호스트에 없는 센서의 신호는 보이지 않는다(항상 '관측 공백'이라 혼란만 줌)
        if k == "batt_vi_w" and mixed:
            rows.append((nd.SIGNALS[k][0], "비교 불가", "구간에 충전·AC 시간이 섞여 방전 전력이 아님"))
        else:
            rows.append((nd.SIGNALS[k][0], "관측 공백" if v is None else f"{v:.2f}", nd.SIGNALS[k][1]))
    return rows


def summary_battery(view, health):
    """대시보드 '배터리' 칸: 건강 + 예상 사용 시간(추정)을 한 칸에."""
    t = Text()
    if health["health_pct"] is not None:
        _line(t, "배터리 건강", f"{health['health_pct']:.0f}%", f"만충 {_f(health['full_wh'], 1, ' Wh')} / 설계 {_f(health['design_wh'], 1, ' Wh')}")
    t.append("\n")
    t.append_text(summary_estimate(view))
    return t


def battery_text(h):
    t = Text()
    if h["full_wh"] is None and h["health_pct"] is None:
        t.append(" 배터리 정보를 읽지 못했습니다.\n", style="grey50")
        return t
    _line(t, "만충 용량", _f(h["full_wh"], 1, " Wh"), f"설계 {_f(h['design_wh'], 1, ' Wh')}")
    _line(t, "배터리 건강", _f(h["health_pct"], 0, "%"), "= 만충 ÷ 설계 용량(펌웨어가 보고하는 값)")
    _line(t, "충전 횟수", "-" if h["cycles"] is None else str(h["cycles"]), "펌웨어 사이클 카운트(0 이면 보고하지 않을 수 있음)")
    _line(t, "상태", h["status"] or "-")
    return t


def device_text(view):
    r = (view["rows"] or [None])[-1]
    t = Text()
    if not r:
        t.append(" 이 범위에 표본이 없습니다.\n", style="grey50")
        return t
    dev, cs, pw = r.get("dev") or {}, r.get("cs") or {}, r.get("pw") or {}
    psr = dev.get("psr") or {}
    wifi = dev.get("wifi") or {}
    _line(t, "마지막 표본", time.strftime("%H:%M:%S", time.localtime(r["t"])))
    if not view["profile"]["battery"]:
        # 데스크톱형: 덮개·PSR·밝기·패키지 C-state 는 해당 없음 — 프로세스 관리에 쓸 값만
        irq = r.get("irq") or {}
        _line(t, "CPU 주파수", _f(cs.get("mhz"), 0, " MHz"))
        _line(t, "부하(load1)", _f(irq.get("load1"), 2), f"전체 CPU {_f(irq.get('cpu_all_pct'), 0, '%')}")
        _line(t, "문맥 전환·인터럽트", f"{_f(irq.get('ctxt_s'), 0, '/s')} · {_f(irq.get('intr_s'), 0, '/s')}")
        _line(t, "부팅", str(dev.get("boot", "-")))
        return t
    _line(t, "덮개·화면", f"덮개 {dev.get('lid', '-')} · 화면 {dev.get('vt', '-')}", f"밝기 {dev.get('bl', '-')}")
    _line(t, "PSR(화면 절전)", str(psr.get("mode") or "-"), f"싱크 {psr.get('sink', '-')}")
    _line(t, "CPU 주파수", _f(cs.get("mhz"), 0, " MHz"), f"pc8 {_f(cs.get('pc8'), 0, '%')} · pc10 {_f(cs.get('pc10'), 0, '%')}")
    _line(t, "Wi-Fi 절전", str(wifi.get("ps", "-")))
    _line(t, "부팅", str(dev.get("boot", "-")))
    return t


def collector_text(c):
    t = Text()
    ctl = c["control"] or {}
    if c["last_t"] is None:
        t.append(" 표본 파일이 없습니다 — `observectl on` 으로 수집을 켜세요.\n", style="grey70")
        return t
    on = ctl.get("enabled")
    _line(t, "수집", "켜짐" if on else "꺼짐", f"수준 {ctl.get('level', '-')} · 간격 {(ctl.get('interval_s') or {}).get(ctl.get('level', 'L0'), '-')}초")
    age = c["age_s"]
    _line(t, "마지막 표본", f"{int(age)}초 전", "⚠ 수집이 멈췄을 수 있음" if age > 120 and on else "", vstyle="bold" if age <= 120 else "dark_orange")
    _line(t, "표본 파일", f"{c['files']}개 · {c['bytes'] / 1e6:.1f} MB", "/var/lib/observe/data")
    eb = ctl.get("ebpf")
    live = eb and eb.get("until", 0) > time.time()
    _line(t, "정밀 eBPF", f"{eb['tier']} (켜짐)" if live else "꺼짐", "observectl ebpf on sample --for 10m 로 켬")
    return t


GLOSSARY = [
    ("측정 / 추정", "측정 = 장치가 보고한 값을 그대로 쓴 것, 추정 = 가정을 거쳐 계산한 것. 화면의 모든 값에 라벨을 붙였습니다."),
    ("psys", "RAPL 이 보고하는 플랫폼 전력. 패널·SSD 등 일부(약 1 W)가 빠져 총 소비보다 적게 보입니다."),
    ("패키지", "CPU+GPU 가 들어 있는 칩의 전력."),
    ("순간 V×I", "배터리 전압×전류를 한 순간 곱한 값. 노이즈가 커서 표본이 적으면 믿기 어렵습니다."),
    ("누적 계량", "배터리를 드나든 전하량(coulomb counter)의 변화로 낸 평균 전력. 1 mAh(≈15 mWh) 단위라 5분 미만은 오차가 큽니다."),
    ("low / high", "전력 높낮이가 아니라 '깊은 절전 상태(pc10)에 들어갔나'(≥ 5%)입니다."),
    ("PSR", "Panel Self Refresh — 화면이 안 바뀔 때 패널이 스스로 화면을 유지해 GPU·메모리 접근을 줄이는 기능."),
    ("앱 CPU %", "코어 1개를 100% 로 본 CPU 시간. 앱 단위는 프로세스를 앱으로 묶은 합입니다(커버리지 100%)."),
    ("전환/s", "자발적 문맥 전환 — 프로세스가 스스로 잠들었다 깨는 횟수. 모든 스레드의 합이며, 많을수록 잦게 깨어난다는 뜻입니다."),
    ("가장 오래 본 앱", "창 포커스 기록(observe-focus)에서 가져온 시간. 창 제목·내용은 기록하지 않습니다."),
    ("관측 공백", "그 시간에 수집이 없었다는 뜻이며 0 이 아닙니다(예: Netdata 가 꺼져 있던 시간)."),
]


# ------------------------------------------------------------------ 원인 탭
def _share(counter, keys):
    tot = sum(counter.values()) or 1
    return sum(v for k, v in counter.items() if k in keys) * 100 / tot


def condition_diffs(res):
    """이 구간과 기준 구간의 '조건' 차이(전원·덮개·PSR·low 비율). 전력 차이를 읽기 전에 조건이 같았는지 먼저 알린다. [문장]"""
    st, sb = res.get("state"), res.get("state_base")
    if not st or not sb:
        return []
    out = []
    a, b = _share(st["ac"], {"AC"}), _share(sb["ac"], {"AC"})
    if abs(a - b) >= 30:
        out.append(f"전원이 다름 — AC 연결 비율 이 구간 {a:.0f}% / 기준 {b:.0f}% (충전·AC 는 전력을 크게 바꿈)")
    a, b = _share(st["lid"], {"open"}), _share(sb["lid"], {"open"})
    if abs(a - b) >= 30:
        out.append(f"덮개 상태가 다름 — 열림 비율 이 구간 {a:.0f}% / 기준 {b:.0f}% (덮개 닫힘은 화면이 꺼져 전력이 크게 낮음)")
    if abs(st["psr_pct"] - sb["psr_pct"]) >= 30:
        out.append(f"PSR(화면 절전) 상태가 다름 — 이 구간 {st['psr_pct']}% / 기준 {sb['psr_pct']}%")
    if abs(st["low_pct"] - sb["low_pct"]) >= 30:
        out.append(f"깊은 절전 진입 비율이 다름 — 이 구간 {st['low_pct']}% / 기준 {sb['low_pct']}%")
    return out


def cause_headline(res):
    """원인 탭 맨 위: 결론 한두 문장(+조건 경고). res 는 ex.build 결과, False/None 이면 안내."""
    t = Text()
    if res is None:
        t.append(" 이 탭을 열면 계산합니다(Netdata 조회가 있어 몇 초 걸릴 수 있음).\n", style="grey50")
        return t
    if res is False:
        t.append(" 이 범위에는 표본이 없어 비교할 수 없습니다.\n", style="grey70")
        return t
    p = (res["power"].get("psys_w") or {})
    v, b = p.get("value"), p.get("base")
    if v is None:
        t.append(" 전력 값이 없습니다.\n", style="grey70")
        return t
    if not res["baseline"] or b is None:
        t.append(f" 평균 전력(psys) {v:.1f} W. 비교 기준이 없어 무엇이 달라졌는지는 말할 수 없습니다(v 로 기준을 고르세요).\n")
        return t
    d = v - b
    if abs(d) < 0.3:
        t.append(f" 평균 전력(psys)이 기준과 거의 같습니다: {b:.1f} W → {v:.1f} W ({d:+.1f} W, 0.3 W 미만은 차이로 보지 않음).\n", style="bold")
    else:
        word, st = ("올랐습니다", "bold red") if d > 0 else ("내렸습니다", "bold green")
        t.append(f" 평균 전력(psys)이 기준보다 ", style="bold")
        t.append(f"{b:.1f} W → {v:.1f} W ({d:+.1f} W, {d / b * 100:+.0f}%) {word}.\n", style=st)
    for c in condition_diffs(res):
        t.append(f" ⚠ {c}\n", style="dark_orange")
    top = [c for c in res["changes"] if c["kind"] in ("앱 CPU", "프로세스 CPU")][:3]
    if top and abs(d) >= 0.3:
        t.append(" 같이 달라진 것(상관일 뿐): ", style="grey70")
        t.append(" · ".join(f"{c['name']} {_change_word(c)}" for c in top) + "\n")
    elif abs(d) >= 0.3:
        t.append(" 눈에 띄게 달라진 앱은 없습니다 — 전력 차이는 조건(위 경고)이나 화면·무선 같은 앱 밖 요인일 수 있습니다.\n", style="grey70")
    return t


def _change_word(c):
    if c["rel"] == float("inf"):
        return f"신규(+{c['cur']:.1f})"
    return f"{c['base']:.1f}→{c['cur']:.1f} ({c['rel'] * 100:+.0f}%)" if c["rel"] is not None else f"{c['base']:.1f}→{c['cur']:.1f}"


def cause_changes(res):
    """'달라진 것 순위' 박스 본문: 늘어남 ▲ 빨강 / 줄어듦 ▼ 초록. 읽는 법을 맨 아래에 적는다."""
    t = Text()
    if not res:
        return t
    if not res["changes"]:
        t.append(" (기준과 의미 있게 다른 항목 없음)" if res["baseline"] else " (기준 구간이 없어 비교하지 않음)", style="grey50")
        return t
    t.append(" " + pad("종류", 14) + pad("항목", 30) + pad("기준 → 이 구간", 24) + "변화\n", style="grey50")
    for c in res["changes"]:
        up = c["cur"] >= c["base"]
        st = "red" if up else "green"
        rel = "신규" if c["rel"] == float("inf") else ("" if c["rel"] is None else f"{c['rel'] * 100:+.0f}%")
        t.append(f" {pad(c['kind'], 14)}{pad(c['name'][:28], 30)}", style="white")
        t.append(("▲ " if up else "▼ ") + pad(f"{c['base']:.2f} → {c['cur']:.2f} {c['unit']}", 22), style=st)
        t.append(f"{rel}\n", style=st)
    t.append("\n ▲ 늘어남(빨강) ▼ 줄어듦(초록). 코어% = 코어 1개를 100% 로 본 CPU 시간. 순서는 상대 변화가 큰 순.", style="grey50")
    t.append("\n 이 표는 '같이 달라진 것'이지 원인이 아닙니다 — 원인을 확인하려면 의심 가는 것 하나만 바꿔 번갈아 재는 ABAB 측정(observectl ab)이 필요합니다.", style="grey50")
    return t


# ------------------------------------------------------------------ 데스크톱형 '원인' 탭: 전력 대신 CPU·앱 변화로 구간 비교
def _avg(rows, f):
    v = [f(r) for r in rows]
    v = [x for x in v if isinstance(x, (int, float))]
    return sum(v) / len(v) if v else None


def desktop_compare(view):
    """이 구간과 기준 구간의 전체 CPU·문맥 전환·패키지 전력 평균과, 앱별 CPU 변화(큰 순). 기준 구간이 없거나 표본이 없으면 None.
    반환 {"metrics": [(이름, 지금, 기준, 단위)], "apps": [(앱, 지금 CPU, 기준 CPU, 차이)]}. CPU 는 앱 표는 코어 1개=100%, 전체 CPU 는 전체 대비 %."""
    rows, base = view["rows"], view["base_rows"]
    if not rows or not base:
        return None
    pk = lambda r: (r.get("pw") or {}).get("pkg_w")
    irq = lambda k: (lambda r: (r.get("irq") or {}).get(k))
    metrics = [("전체 CPU", _avg(rows, irq("cpu_all_pct")), _avg(base, irq("cpu_all_pct")), "%"),
               ("문맥 전환", _avg(rows, irq("ctxt_s")), _avg(base, irq("ctxt_s")), "/s"),
               ("패키지 전력", _avg(rows, pk), _avg(base, pk), "W")]
    cur, old = ex.apps_table(rows), ex.apps_table(base)
    apps = []
    if cur:
        c, o = cur[0], (old[0] if old else {})
        for k in set(c) | set(o):
            a, b = c.get(k, {"cpu": 0.0})["cpu"], o.get(k, {"cpu": 0.0})["cpu"]
            apps.append((k, a, b, a - b))
        apps.sort(key=lambda x: -abs(x[3]))
    return {"metrics": metrics, "apps": apps[:12]}


def desktop_cause_head(view):
    cmp = desktop_compare(view)
    t = Text()
    if cmp is None:
        t.append(" 비교할 표본이 부족합니다 — 이 구간과 기준 구간(v 로 바꿈) 모두에 수집된 표본이 있어야 합니다.", style="grey50")
        return t
    for name, a, b, unit in cmp["metrics"]:
        d = None if a is None or b is None else a - b
        _line(t, name, _f(a, 1, unit), f"기준 {_f(b, 1, unit)}" + ("" if d is None else f" · 차이 {d:+.1f}{unit}"), lw=14, vw=12)
    return t


def desktop_cause_changes(view):
    cmp = desktop_compare(view)
    t = Text()
    if not cmp or not cmp["apps"]:
        return t
    t.append(" 앱별 CPU 변화(코어 1개=100%, 차이가 큰 순) — 상관일 뿐 원인이라는 뜻은 아님\n", style="grey50")
    for name, a, b, d in cmp["apps"]:
        t.append(" " + pad(name[:20], 21), style="white")
        t.append(f"{a:>6.1f}% ← {b:>6.1f}%  ", style="grey70")
        t.append(f"{d:+.1f}\n", style="dark_orange" if d > 0 else "green")
    return t
