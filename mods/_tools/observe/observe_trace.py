"""observe_trace — 스팬(구간) 이벤트를 트리로 묶고, 구간별 에너지·요약을 계산한다(표준 라이브러리만, 순수 계산).
스팬 이벤트: `<이름>.begin` / `<이름>.end` / `<이름>.fail`, 필드 span(id)·trace·parent·ms (observe_events._Span, observe-emit span-*).
끝 이벤트가 없는 스팬은 '진행 중 또는 비정상 종료'(t1=None)로 남는다."""
from __future__ import annotations

import statistics

STD = {"t", "mono", "pid", "comp", "lvl", "ev", "span", "trace", "parent", "ms", "exc"}


def build_spans(events):
    """이벤트 목록(시간순) → 스팬 dict 목록(시작 시각순). 키: id trace parent comp name t0 t1 ms status attrs pid."""
    spans = {}
    for e in events:
        sid = e.get("span")
        ev = e.get("ev", "")
        if not sid:
            continue
        if ev.endswith(".begin"):
            spans[sid] = {"id": sid, "trace": e.get("trace"), "parent": e.get("parent"), "comp": e.get("comp"), "name": ev[:-6],
                          "t0": e["t"], "t1": None, "ms": None, "status": "running", "attrs": {k: v for k, v in e.items() if k not in STD}, "pid": e.get("pid")}
        elif ev.endswith((".end", ".fail")):
            sp = spans.get(sid)
            if not sp:                                         # 시작 이벤트가 기록 수준/보관 기간 때문에 없음 → 끝만으로 복원
                ms = e.get("ms") or 0
                sp = spans[sid] = {"id": sid, "trace": e.get("trace"), "parent": e.get("parent"), "comp": e.get("comp"), "name": ev.rsplit(".", 1)[0],
                                   "t0": e["t"] - ms / 1000, "t1": None, "ms": None, "status": "running", "attrs": {}, "pid": e.get("pid")}
            sp["t1"] = e["t"]
            sp["ms"] = e.get("ms") if e.get("ms") is not None else round((e["t"] - sp["t0"]) * 1000, 1)
            sp["status"] = "fail" if ev.endswith(".fail") else "ok"
            sp["attrs"].update({k: v for k, v in e.items() if k not in STD})
            if e.get("exc"):
                sp["attrs"]["exc"] = e["exc"]
    return sorted(spans.values(), key=lambda s: s["t0"])


def traces(spans):
    """{trace_id: [스팬…]} (각 목록은 시작 순). trace 가 없는 스팬은 자기 id 를 trace 로 본다."""
    out = {}
    for s in spans:
        out.setdefault(s["trace"] or s["id"], []).append(s)
    return out


def depth_of(span, by_id):
    d, seen = 0, set()
    while span["parent"] and span["parent"] in by_id and span["parent"] not in seen:
        seen.add(span["parent"])
        span = by_id[span["parent"]]
        d += 1
    return d


def order_tree(spans):
    """한 트레이스의 스팬을 깊이우선(부모 다음에 자식, 형제는 시작 순)으로 [(깊이, 스팬)] 로 줄 세운다. 부모가 목록에 없으면 루트로 본다."""
    by_id = {s["id"]: s for s in spans}
    kids = {}
    roots = []
    for s in spans:
        if s["parent"] and s["parent"] in by_id:
            kids.setdefault(s["parent"], []).append(s)
        else:
            roots.append(s)
    out = []

    def walk(s, d):
        out.append((d, s))
        for c in kids.get(s["id"], []):
            walk(c, d + 1)
    for r in roots:
        walk(r, 0)
    return out


def energy(samples, t0, t1, now=None):
    """구간 [t0, t1] 의 에너지. 표본 하나는 (t-dt, t] 를 대표하므로 겹친 시간만큼 가중해 적분한다(t1 이 None 이면 now 까지).
    반환 dict: psys_wh, batt_wh(방전 중 V×I), avg_psys_w, cover_s(표본이 덮은 시간), n(겹친 표본 수), coulomb_wh(구간 앞뒤 표본의 누적 계량 차이, 10분 이상일 때만).
    표본이 하나도 겹치지 않으면 None. 구간이 표본 간격(30초)보다 짧으면 추정치일 뿐이다(cover_s·n 으로 판단)."""
    if t1 is None:
        t1 = now if now is not None else t0
    if t1 <= t0:
        return None
    psys = batt = cover = 0.0
    n = 0
    for s in samples:
        t, dt = s.get("t"), s.get("dt") or 30.0
        if t is None or t < t0 or t - dt > t1:
            continue
        ov = min(t, t1) - max(t - dt, t0)
        if ov <= 0:
            continue
        pw = s.get("pw") or {}
        n += 1
        cover += ov
        if isinstance(pw.get("psys_w"), (int, float)):
            psys += pw["psys_w"] * ov
        if pw.get("status") == "Discharging" and isinstance(pw.get("batt_vi_w"), (int, float)):
            batt += pw["batt_vi_w"] * ov
    if n == 0:
        return None
    out = {"psys_wh": psys / 3600, "batt_wh": batt / 3600, "avg_psys_w": psys / cover if cover else None, "cover_s": cover, "n": n, "coulomb_wh": None}
    if t1 - t0 >= 600:
        a = max((s for s in samples if s["t"] <= t0), key=lambda s: s["t"], default=None)
        b = min((s for s in samples if s["t"] >= t1), key=lambda s: s["t"], default=None)
        if a and b:
            pa, pb = a.get("pw") or {}, b.get("pw") or {}
            if pa.get("status") == "Discharging" and pb.get("status") == "Discharging" and None not in (pa.get("q_uah"), pb.get("q_uah"), pa.get("v_uv"), pb.get("v_uv")):
                out["coulomb_wh"] = (pa["q_uah"] - pb["q_uah"]) / 1e6 * ((pa["v_uv"] + pb["v_uv"]) / 2) / 1e6
    return out


def summarize(spans, samples):
    """(comp, name) 별 요약: 횟수, 실패 수, 소요 중앙값/95%/최대(초), 에너지(psys Wh) 평균·합. 끝나지 않은 스팬은 횟수에만 센다."""
    groups = {}
    for s in spans:
        groups.setdefault((s["comp"], s["name"]), []).append(s)
    rows = []
    for (comp, name), g in groups.items():
        done = [s for s in g if s["t1"] is not None]
        durs = sorted(s["ms"] / 1000 for s in done if s["ms"] is not None)
        wh = [e["psys_wh"] for s in done if (e := energy(samples, s["t0"], s["t1"]))]
        rows.append({"comp": comp, "name": name, "n": len(g), "fail": sum(1 for s in g if s["status"] == "fail"), "running": sum(1 for s in g if s["t1"] is None),
                     "p50": statistics.median(durs) if durs else None, "p95": durs[min(len(durs) - 1, int(len(durs) * 0.95))] if durs else None, "max": durs[-1] if durs else None,
                     "wh_mean": statistics.mean(wh) if wh else None, "wh_sum": sum(wh) if wh else None, "wh_n": len(wh)})
    return sorted(rows, key=lambda r: -(r["wh_sum"] or 0) - r["n"] * 1e-6)


def fmt_dur(sec):
    if sec is None:
        return "…"
    if sec < 1:
        return f"{sec * 1000:.0f}ms"
    if sec < 90:
        return f"{sec:.1f}s"
    if sec < 5400:
        return f"{sec / 60:.1f}분"
    return f"{sec / 3600:.1f}시간"


def fmt_energy(e):
    """에너지 dict → '0.12Wh(4.1W)' / 표본이 적으면 '~' 를 붙인다 / 없으면 '-'."""
    if not e:
        return "-"
    mark = "~" if e["n"] < 3 or e["cover_s"] < 20 else ""
    wh = e["coulomb_wh"] if e["coulomb_wh"] is not None else e["psys_wh"]
    w = f"({e['avg_psys_w']:.1f}W)" if e["avg_psys_w"] is not None else ""
    return f"{mark}{wh:.3f}Wh{w}"


def render_trace(spans, samples, width=100, now=None):
    """한 트레이스를 폭포(waterfall) 줄 목록으로. 각 줄: 들여쓴 이름 · 소요 · 에너지 · 막대(트레이스 전체 시간 대비 위치/길이)."""
    order = order_tree(spans)
    if not order:
        return []
    t0 = min(s["t0"] for _, s in order)
    t1 = max((s["t1"] if s["t1"] is not None else (now or s["t0"])) for _, s in order)
    total = max(t1 - t0, 1e-6)
    bar_w = max(10, width - 62)
    lines = []
    for d, s in order:
        end = s["t1"] if s["t1"] is not None else (now or t1)
        a = int((s["t0"] - t0) / total * bar_w)
        b = max(a + 1, min(bar_w, int((end - t0) / total * bar_w + 0.999)))
        bar = " " * a + ("█" if s["status"] != "fail" else "▒") * (b - a) + (" …" if s["t1"] is None else "")
        label = "  " * d + f"{s['comp']}:{s['name']}"
        mark = {"fail": " ✗", "running": " …"}.get(s["status"], "")
        lines.append(f"{label[:34]:<34}{mark:<2} {fmt_dur(s['ms'] / 1000 if s['ms'] is not None else None):>7} {fmt_energy(energy(samples, s['t0'], s['t1'], now)):>18}  {bar}")
    return lines
