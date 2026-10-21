"""observe_explain — 한 구간을 **여러 출처를 교차해서** 설명한다(순수 계산, 표준 라이브러리만): "이 시간에 전력이 왜 이랬나"를 한 화면으로.
묶는 것: 전력 4지표(psys·패키지·순간 V×I·누적 계량) + 상태(low/high·PSR·덮개·AC) + 시스템 활동(전체 CPU·문맥 전환·인터럽트, Netdata 가 있으면 네트워크·디스크·온도)
        + 프로세스(observectl 저장분과 Netdata 앱 그룹) + 포커스한 앱·열린 구간(스팬)과 그 에너지 + **기준 구간 대비 달라진 것의 순위**.
원칙: ① 출처를 항상 밝힌다(observectl 30초 / Netdata 1초). ② Netdata 가 꺼져 있거나 일부만 있으면 그 항목을 '관측 공백'으로 적는다(없는 값을 0 으로 두지 않음).
③ 순위는 **상관일 뿐 인과가 아니다**라고 명시한다. ④ 믿을 수 없는 값(짧은 구간의 순간 V×I·누적 계량, 메인 스레드만 센 옛 전환 값)은 표시하고 제외한다. ⑤ 한계를 마지막에 적는다."""
from __future__ import annotations

import collections
import statistics

import observe_tiers as tiers
import observe_trace as tr

POWER = [("psys_w", "psys(RAPL, 약 1 W 누락)", "W"), ("pkg_w", "패키지(RAPL)", "W"), ("batt_vi_w", "순간 V×I(방전 중)", "W"), ("coulomb_w", "누적 계량", "W")]
# 시스템 활동: (이름, 라벨, 단위, observectl 쪽 경로, 변화로 칠 최소 절댓값)
SYSTEM = [("cpu_all_pct", "전체 CPU(전체 대비)", "%", ("irq", "cpu_all_pct"), 1.0), ("ctxsw_all_s", "시스템 전체 문맥 전환", "/s", ("irq", "ctxt_s"), 200.0),
          ("intr_all_s", "시스템 전체 인터럽트", "/s", ("irq", "intr_s"), 100.0), ("net_rx_kbps", "네트워크 수신", "kbit/s", None, 100.0), ("net_tx_kbps", "네트워크 송신", "kbit/s", None, 100.0),
          ("disk_read_kibs", "디스크 읽기", "KiB/s", None, 500.0), ("disk_write_kibs", "디스크 쓰기", "KiB/s", None, 500.0), ("nvme_temp_c", "NVMe 온도", "°C", None, 3.0), ("forks_s", "프로세스 생성", "/s", None, 5.0)]
MIN_ABS = {"psys_w": 0.3, "pkg_w": 0.2, "batt_vi_w": 0.3, "coulomb_w": 0.3}


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(xs) if xs else None


def _get(r, path):
    for k in path:
        r = r.get(k) if isinstance(r, dict) else None
    return r


def coulomb_w(g):
    """구간의 누적 계량 평균 전력(W)과 양자화 오차 범위(W). 방전 중 표본 2개 미만이면 (None, None). 오차 ≈ 1 mAh(≈15 mWh) ÷ 구간 시간."""
    pts = [r for r in g if _get(r, ("pw", "q_uah")) is not None and _get(r, ("pw", "v_uv")) and _get(r, ("pw", "status")) == "Discharging"]
    if len(pts) < 2 or pts[-1]["t"] <= pts[0]["t"]:
        return None, None
    dt = pts[-1]["t"] - pts[0]["t"]
    v = sum(p["pw"]["v_uv"] for p in pts) / len(pts) / 1e6
    return (pts[0]["pw"]["q_uah"] - pts[-1]["pw"]["q_uah"]) / 1e6 * v / (dt / 3600), (1e-3 * v) / (dt / 3600)


def power_rows(g, threshold=0.3):
    """구간의 전력 4지표. {지표: {"value", "note", "reliable"}}. 신뢰 기준은 observectl ab 와 같다(순간 V×I 는 표본 8개 이상, 계량은 오차가 임계의 절반 이하)."""
    out = {}
    out["psys_w"] = {"value": _mean([_get(r, ("pw", "psys_w")) for r in g]), "note": "", "reliable": True}
    out["pkg_w"] = {"value": _mean([_get(r, ("pw", "pkg_w")) for r in g]), "note": "", "reliable": True}
    dis = [r for r in g if _get(r, ("pw", "status")) == "Discharging"]
    vi = _mean([_get(r, ("pw", "batt_vi_w")) for r in dis])
    out["batt_vi_w"] = {"value": vi, "note": f"표본 {len(dis)}개" + ("" if len(dis) >= 8 else " — 적어서 신뢰 낮음"), "reliable": len(dis) >= 8}
    w, err = coulomb_w(g)
    out["coulomb_w"] = {"value": w, "note": "" if w is None else f"오차 ±{err:.2f} W" + ("" if err <= threshold / 2 else " — 구간이 짧아 신뢰 낮음"), "reliable": w is not None and err <= threshold / 2}
    return out


def state_summary(g):
    n = len(g)
    if not n:
        return {}
    pct = lambda f: round(sum(1 for r in g if f(r)) * 100 / n)
    return {"n": n, "low_pct": pct(lambda r: r.get("state") == "low"), "psr_pct": pct(lambda r: "enabled" in str((_get(r, ("dev", "psr")) or {}).get("mode") or "")),
            "lid": dict(collections.Counter(str(_get(r, ("dev", "lid"))) for r in g)), "ac": dict(collections.Counter("AC" if _get(r, ("pw", "ac")) else "배터리" for r in g)),
            "vt": dict(collections.Counter(str(_get(r, ("dev", "vt"))) for r in g))}


def proc_table(g):
    """observectl 이 저장한 프로세스 행을 구간 평균으로. {comm: {"cpu": 코어1개=100% 평균, "ctxsw": 모든 스레드 자발 전환/s 평균(v3 표본만, 없으면 None)}}.
    저장은 표본마다 상위 16행뿐이라 등장하지 않은 표본은 0 으로 센다(긴 꼬리는 빠짐 — coverage 로 비율을 알린다)."""
    n = len(g)
    cpu, ctx, nctx = collections.defaultdict(float), collections.defaultdict(float), 0
    for r in g:
        v3 = not any("ctxsw_vol_leader_s" in p for p in r.get("proc", []))
        nctx += v3
        for p in r.get("proc", []):
            cpu[p["comm"]] += p.get("cpu_core_pct", p.get("cpu", 0))
            if v3:
                ctx[p["comm"]] += p.get("ctxsw_vol_s", 0)
    return {c: {"cpu": cpu[c] / n, "ctxsw": (ctx[c] / nctx) if nctx else None} for c in cpu} if n else {}, nctx


def ctxsw_coverage(g):
    """저장된 상위 프로세스 행의 자발 전환 합이 시스템 전체 문맥 전환(자발+비자발)의 몇 %인가(v3 표본만; 하한값 — 분모에 비자발이 들어 있음)."""
    a = b = 0.0
    for r in g:
        if any("ctxsw_vol_leader_s" in p for p in r.get("proc", [])):
            continue
        c = _get(r, ("irq", "ctxt_s"))
        if c:
            a += sum(p.get("ctxsw_vol_s", 0) for p in r.get("proc", []))
            b += c
    return a / b if b else None


def ebpf_table(g):
    """구간 표본에 붙은 정밀(eBPF) 집계 `ebpf` 를 프로세스별 평균으로. 없으면 None. {"tiers": {단계}, "records": 개수, "procs": [{"comm","pid","cpu","vol","sw"}…]}."""
    recs = [r["ebpf"] for r in g if r.get("ebpf")]
    if not recs:
        return None
    acc = collections.defaultdict(lambda: collections.defaultdict(float))
    for rec in recs:
        for p in rec["procs"]:
            key = (p["comm"], p["pid"])
            for src, dst in (("cpu_core_pct", "cpu"), ("vol_s", "vol"), ("invol_s", "invol"), ("sw_s", "sw")):
                if src in p:
                    acc[key][dst] += p[src]
    n = len(recs)
    rows = [{"comm": c, "pid": pid, **{k: v / n for k, v in d.items()}} for (c, pid), d in acc.items()]
    rows.sort(key=lambda r: -(r.get("cpu", 0) + r.get("vol", 0) / 100 + r.get("sw", 0) / 100))
    return {"tiers": sorted({r["tier"] for r in recs}), "records": n, "procs": rows[:8]}


def apps_table(g):
    """구간 표본의 `apps`(앱 단위 합계, 전체 프로세스 포함, v4)를 앱별 평균으로. 표본에 apps 가 없으면(v3 이하) None. {앱: {"cpu","ctxsw","rss","n"}}(없는 표본은 0 으로 센다)."""
    have = [r for r in g if r.get("apps")]
    if not have:
        return None
    cpu, ctx, rss, n = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float)
    for r in have:
        for a in r["apps"]:
            cpu[a["app"]] += a["cpu_core_pct"]; ctx[a["app"]] += a["ctxsw_vol_s"]; rss[a["app"]] += a.get("rss_mb", 0.0); n[a["app"]] = max(n[a["app"]], a.get("n", 0))
    m = len(have)
    return {k: {"cpu": cpu[k] / m, "ctxsw": ctx[k] / m, "rss": rss[k] / m, "n": n[k]} for k in cpu}, m


def focus_table(spans, t0, t1):
    """포커스 스팬(`windows` 의 `focus:<앱>`)을 구간에 잘라 앱별 시간(초)으로. [(앱, 초, 구간 대비 %)] 큰 순."""
    acc = collections.defaultdict(float)
    for s in spans:
        if s["comp"] != "windows" or not s["name"].startswith("focus:"):
            continue
        a, b = max(s["t0"], t0), min(s["t1"] if s["t1"] is not None else t1, t1)
        if b > a:
            acc[s["name"][6:]] += b - a
    tot = max(t1 - t0, 1e-9)
    return sorted(((k, v, v * 100 / tot) for k, v in acc.items()), key=lambda x: -x[1])


def span_table(spans, rows, t0, t1, n=8):
    """창·포커스가 아닌 구간(nixup, 덮개 정책, eBPF 프로세스 등)을 구간에 잘라 [(이름, 초, 에너지 dict 또는 None)] 긴 순."""
    out = []
    for s in spans:
        if s["comp"] == "windows":
            continue
        a, b = max(s["t0"], t0), min(s["t1"] if s["t1"] is not None else t1, t1)
        if b - a >= 1:
            out.append((f"{s['comp']}:{s['name']}", b - a, tr.energy(rows, a, b)))
    return sorted(out, key=lambda x: -x[1])[:n]


def _rel(cur, base):
    if cur is None or base is None:
        return None
    return (cur - base) / base if base else (None if cur == 0 else float("inf"))


def build(rows, spans, t0, t1, base=None, nd=None, threshold=0.3):
    """한 구간 설명 dict. rows=구간·기준 구간을 모두 덮는 observectl 표본(정규화됨), spans=build_spans 결과, base=(b0,b1) 또는 None,
    nd=callable(t0,t1)→Netdata snapshot dict 또는 None(꺼짐). 구조는 render() 가 읽는다."""
    sel = lambda a, b: [r for r in rows if a <= r["t"] < b]       # 반열린 구간 — 경계의 표본이 두 구간에 겹쳐 들어가지 않게
    cur, ref = sel(t0, t1), (sel(*base) if base else [])
    res = {"window": (t0, t1), "baseline": base, "n": len(cur), "n_base": len(ref), "notes": []}
    res["state"], res["state_base"] = state_summary(cur), state_summary(ref)
    pw, pwb = power_rows(cur, threshold), (power_rows(ref, threshold) if ref else {})
    res["power"] = {k: {**v, "base": (pwb.get(k) or {}).get("value")} for k, v in pw.items()}
    legacy = sum(1 for r in cur if r.get("legacy"))
    # Netdata
    snap = nd(t0, t1) if nd else None
    snap_b = nd(*base) if (nd and base) else None
    res["netdata"] = {"available": snap is not None, "coverage": snap["coverage"] if snap else None, "base_coverage": snap_b["coverage"] if snap_b else None}
    if nd is not None and snap is None:
        res["notes"].append("Netdata 가 응답하지 않음 — Netdata 에서 오는 항목(네트워크·디스크·온도·앱 그룹별 CPU·1초 전력)은 '관측 공백'(0 이 아님)")
    elif snap and snap["coverage"] < 0.9:
        res["notes"].append(f"Netdata 데이터가 이 구간의 {snap['coverage'] * 100:.0f}% 만 있음(그 외 시간은 꺼져 있었음) — Netdata 값은 있는 부분의 평균")
    if snap:
        for key, lab in (("psys_w", "psys"), ("pkg_w", "pkg"), ("batt_vi_w", "batt_vi_w")):
            res["power"].setdefault(key, {})["netdata"] = snap["signals"].get(key)
            if snap_b:
                res["power"][key]["netdata_base"] = snap_b["signals"].get(key)
    # 시스템 활동
    sysrows = []
    for name, label, unit, path, min_abs in SYSTEM:
        o = _mean([_get(r, path) for r in cur]) if path else None
        ob = _mean([_get(r, path) for r in ref]) if (path and ref) else None
        n = snap["signals"].get(name) if snap else None
        nb = snap_b["signals"].get(name) if snap_b else None
        sysrows.append({"name": name, "label": label, "unit": unit, "obs": o, "obs_base": ob, "nd": n, "nd_base": nb, "min_abs": min_abs})
    res["system"] = sysrows
    # 프로세스
    pt, nctx = proc_table(cur)
    ptb, _ = proc_table(ref) if ref else ({}, 0)
    res["procs"] = {"cur": pt, "base": ptb, "ctx_samples": nctx, "ctx_coverage": ctxsw_coverage(cur), "legacy_samples": legacy}
    res["ebpf"] = ebpf_table(cur)
    at, atb = apps_table(cur), apps_table(ref)
    res["apps"] = {"cur": at[0] if at else None, "base": atb[0] if atb else None, "samples": at[1] if at else 0}
    res["apps_nd"] = {"cur": dict(snap["apps_cpu"]) if snap else None, "base": dict(snap_b["apps_cpu"]) if snap_b else None}
    # 포커스·구간
    res["focus"] = focus_table(spans, t0, t1)
    res["focus_base"] = focus_table(spans, *base) if base else []
    res["spans"] = span_table(spans, rows, t0, t1)
    res["changes"] = rank_changes(res)
    # 한계
    dur = t1 - t0
    if dur < 300:
        res["notes"].append(f"구간이 {dur:.0f}초라 표본이 {len(cur)}개뿐 — 순간 V×I·누적 계량은 신뢰 낮음(5분 이상 권장)")
    if not ref and base:
        res["notes"].append("기준 구간에 표본이 없어 비교 불가")
    if legacy:
        res["notes"].append(f"옛 형식 표본 {legacy}개: 프로세스별 자발 전환은 메인 스레드만 센 값이라 전환 표에서 제외(CPU 는 유효)")
    cov = res["procs"]["ctx_coverage"]
    if res["apps"]["cur"] is None and cov is not None and cov < 0.5:
        res["notes"].append(f"저장된 상위 프로세스(최대 16행)의 자발 전환 합은 시스템 전체 문맥 전환의 {cov * 100:.0f}% 이하 — 나머지(긴 꼬리)는 프로세스 표에 없음")
    res["notes"].append("psys 는 총 소비보다 약 1 W 적게 보임(차이는 유효, 절대값 비교는 배터리 계량으로). 표본은 30초 간격(Netdata 는 1초)")
    return res


def rank_changes(res):
    """기준 대비 달라진 것의 순위(상대 변화 큰 순). 항목: 전력(신뢰 가능한 것만), 시스템 활동, 프로세스 CPU. **상관일 뿐 인과가 아니다.**"""
    out = []
    for key, label, unit in POWER:
        p = res["power"].get(key) or {}
        if p.get("reliable") is False:
            continue
        v, b = p.get("value"), p.get("base")
        if v is not None and b is not None and abs(v - b) >= MIN_ABS[key]:
            out.append({"kind": "전력", "name": label, "cur": v, "base": b, "unit": unit, "rel": _rel(v, b)})
    for s in res["system"]:
        v = s["nd"] if s["nd"] is not None else s["obs"]
        b = s["nd_base"] if s["nd"] is not None else s["obs_base"]
        if v is not None and b is not None and abs(v - b) >= s["min_abs"]:
            out.append({"kind": "시스템", "name": s["label"], "cur": v, "base": b, "unit": s["unit"], "rel": _rel(v, b)})
    if res["apps"]["cur"] is not None and res["apps"]["base"] is not None:        # 앱 단위(전체 프로세스)가 있으면 그것으로 비교 — 프로세스 행과 이중으로 세지 않는다
        ca, ba = res["apps"]["cur"], res["apps"]["base"]
        for app in set(ca) | set(ba):
            v, b = ca.get(app, {}).get("cpu", 0.0), ba.get(app, {}).get("cpu", 0.0)
            if abs(v - b) >= 1.0:
                out.append({"kind": "앱 CPU", "name": app, "cur": v, "base": b, "unit": "코어%", "rel": _rel(v, b)})
        cur, base = {}, {}
    else:
        cur, base = res["procs"]["cur"], res["procs"]["base"]
    for c in (set(cur) | set(base)) if res["n_base"] else ():       # 기준 표본이 없으면 프로세스 비교를 하지 않는다(전부 '신규'로 보이는 오류 방지)
        v, b = cur.get(c, {}).get("cpu", 0.0), base.get(c, {}).get("cpu", 0.0)
        if abs(v - b) >= 1.0:
            out.append({"kind": "프로세스 CPU", "name": c, "cur": v, "base": b, "unit": "코어%", "rel": _rel(v, b)})
    return sorted(out, key=lambda x: -(abs(x["cur"] - x["base"]) / (abs(x["base"]) + 1e-9) if x["rel"] is not None else 0))[:12]


def _f(x, p=2):
    return "-" if x is None else f"{x:.{p}f}"


SECTION_TITLES = ["요약", "전력", "시스템 활동", "프로세스·앱", "포커스·열린 구간", "기준 대비 달라진 것 — 상관일 뿐 인과가 아님", "한계와 주의"]


def sections(res, hms):
    """render 와 같은 내용을 SECTION_TITLES 순서의 [(제목, 줄 목록)] 로 — powerui 가 섹션마다 박스를 만든다."""
    t0, t1 = res["window"]
    S = []
    head = [f"{hms(t0)} ~ {hms(t1)} ({(t1 - t0) / 60:.1f}분, 표본 {res['n']}개)" + (f"   기준 {hms(res['baseline'][0])} ~ {hms(res['baseline'][1])} (표본 {res['n_base']}개)" if res["baseline"] else "")]
    nd = res["netdata"]
    head.append("출처: observectl(30초 표본)" + (f" + Netdata(1초, 이 구간 {nd['coverage'] * 100:.0f}% 있음)" if nd["available"] else " — Netdata 응답 없음(해당 항목은 관측 공백)"))
    st, sb = res["state"], res["state_base"]
    if st:
        fmt = lambda d: " ".join(f"{k} {v}개" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))
        head.append(f"상태: low {st['low_pct']}%(깊은 절전 진입) · PSR 켬 {st['psr_pct']}% · 덮개 [{fmt(st['lid'])}] · 전원 [{fmt(st['ac'])}] · 화면 [{fmt(st['vt'])}]" + (f"   | 기준: low {sb['low_pct']}% · PSR {sb['psr_pct']}%" if sb else ""))
    S.append(("요약", head))
    P = ["                         이 구간   기준     변화      Netdata(1초)   신뢰"]
    for key, label, unit in POWER:
        p = res["power"].get(key) or {}
        v, b = p.get("value"), p.get("base")
        d = f"{v - b:+.2f}" if v is not None and b is not None else "-"
        ndv = p.get("netdata")
        note = p.get("note", "")
        if key == "batt_vi_w" and v is None and ndv is not None:
            note = "방전 표본 없음(충전 중) — Netdata 값은 충전 전력"
        P.append(f"{label:<24}{_f(v):>7}{_f(b):>8}{d:>9}{_f(ndv):>14}   {note}" + ("" if p.get("reliable", True) else "  ← 순위에서 제외"))
    S.append(("전력", P))
    Y = ["                         이 구간   기준     변화      출처"]
    for s in res["system"]:
        if s["nd"] is None and s["obs"] is None:
            Y.append(f"{s['label']:<22}{'관측 공백':>8}   (Netdata 필요)")
            continue
        v, b, src = (s["nd"], s["nd_base"], "Netdata 1초") if s["nd"] is not None else (s["obs"], s["obs_base"], "observectl 30초")
        d = f"{v - b:+.1f}" if v is not None and b is not None else "-"
        Y.append(f"{s['label']:<22}{_f(v, 1):>8}{_f(b, 1):>8}{d:>9}   {src} · {s['unit']}")
    S.append(("시스템 활동", Y))
    pr = res["procs"]
    Q = []
    ap = res["apps"]
    if ap["cur"] is not None:
        apb = ap["base"] or {}
        Q.append(f"앱 단위(전체 프로세스를 앱으로 묶은 합 — 커버리지 100%, 표본 {ap['samples']}개) CPU 는 코어 1개=100%      이 구간 CPU   기준   | 자발 전환/s(모든 스레드)  프로세스 수")
        for k, v in sorted(ap["cur"].items(), key=lambda kv: -(kv[1]["cpu"] + kv[1]["ctxsw"] / 100))[:10]:
            Q.append(f"{k[:26]:<26}{v['cpu']:>8.1f}{apb.get(k, {}).get('cpu', 0.0):>8.1f}   | {v['ctxsw']:>8.0f}{v['n']:>12.0f}")
        Q.append("")
    Q.append("observectl 저장분(상위 16행, 이름별) — CPU 는 코어 1개=100%      이 구간 CPU   기준   | 자발 전환/s(모든 스레드)" + ("   (앱 단위 표가 있으면 그쪽이 전체)" if ap["cur"] is not None else ""))
    cur, base = pr["cur"], pr["base"]
    for c, v in sorted(cur.items(), key=lambda kv: -kv[1]["cpu"])[:8]:
        ctx = "-" if v["ctxsw"] is None else f"{v['ctxsw']:.0f}"
        Q.append(f"{c:<26}{v['cpu']:>8.1f}{base.get(c, {}).get('cpu', 0.0):>8.1f}   | {ctx:>6}")
    ctxrank = sorted(((c, v["ctxsw"]) for c, v in cur.items() if v["ctxsw"] is not None), key=lambda x: -x[1])[:5]
    if ctxrank:
        Q.append("자발 전환 상위: " + ", ".join(f"{c} {v:.0f}/s" for c, v in ctxrank))
    eb = res.get("ebpf")
    if eb:
        Q.append("")
        info = ", ".join(f"{tiers.TIERS[t]['label']} — 정확성 {tiers.TIERS[t]['accuracy']}" for t in eb["tiers"] if t in tiers.TIERS)
        Q.append(f"정밀(eBPF, 이 구간 간격 {eb['records']}개 평균; {info})      CPU(코어1=100%)  자발 전환/s  비자발/s  총 전환/s")
        for p in eb["procs"]:
            f = lambda k, w=7: "-" if k not in p else f"{p[k]:.1f}"
            Q.append(f"{p['comm'][:24]:<26}{f('cpu'):>8}{f('vol'):>12}{f('invol'):>10}{f('sw'):>10}")
    if res["apps_nd"]["cur"] is not None:
        Q.append("")
        Q.append("앱 그룹 CPU — Netdata(전체 프로세스, 코어 1개=100%)      이 구간   기준")
        a, ab = res["apps_nd"]["cur"], res["apps_nd"]["base"] or {}
        for k, v in sorted(a.items(), key=lambda kv: -kv[1])[:8]:
            Q.append(f"{k:<26}{v:>8.1f}{ab.get(k, 0.0):>8.1f}")
    S.append(("프로세스·앱", Q))
    F = []
    if res["focus"]:
        F.append("포커스한 앱: " + " · ".join(f"{a} {s / 60:.1f}분({p:.0f}%)" for a, s, p in res["focus"][:6]))
    if res["spans"]:
        F.append("열린 구간(스팬): " + " · ".join(f"{n} {tr.fmt_dur(s)} {tr.fmt_energy(e)}" for n, s, e in res["spans"][:6]))
    S.append(("포커스·열린 구간", F or ["(이 구간에 기록된 포커스·스팬 없음)"]))
    C = []
    if not res["changes"]:
        C.append("(기준과 의미 있게 다른 항목 없음)" if res["baseline"] else "(기준 구간이 없어 비교하지 않음)")
    for c in res["changes"]:
        rel = "신규" if c["rel"] == float("inf") else ("-" if c["rel"] is None else f"{c['rel'] * 100:+.0f}%")
        C.append(f"{c['kind']:<10}{c['name']:<28}{c['base']:>9.2f} → {c['cur']:<9.2f}{c['unit']:<8}{rel:>7}")
    S.append((SECTION_TITLES[5], C))
    S.append(("한계와 주의", [f"※ {n}" for n in res["notes"]]))
    return S


def render(res, hms):
    """사람이 읽는 텍스트(줄 목록). hms(epoch)→'HH:MM:SS' 형식 함수를 받는다."""
    L = []
    for i, (title, lines) in enumerate(sections(res, hms)):
        L.append(("== explain " + lines[0]) if i == 0 else f"[{title}]")
        L.extend(lines[1:] if i == 0 else lines)
        L.append("")
    return L
