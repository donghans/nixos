"""usageui 의 데이터 계층(터미널 없음): 시간 범위 모델 + 한 번의 조회(load)로 모든 탭이 쓸 보기 모델을 만든다.
갱신은 수동 — load() 를 부를 때만 파일을 읽는다(타이머 없음). 계산은 observe_explain·observe_trace 의 검증된 함수를 재사용하고,
이 모듈은 범위·요약·배터리 추정·방전 곡선·하드웨어 정보를 계산한다. 값마다 '측정'인지 '추정'인지 라벨을 붙여 돌려준다."""
from __future__ import annotations

import collections
import glob
import json
import os
import statistics
import time
from datetime import datetime, timedelta

import observe_core as core
import observe_explain as ex
import observe_trace as tr
import usagespikes as sp

BUSY = {"nix-daemon", "nix", "nixos-rebuild", "nixup", ".nixup-wrapped", "cc1", "ld", "rustc"}   # 빌드 중인 표본은 '한가한 기준'에서 뺀다(clean=False)
MAX_GAP = 90                     # 표본 사이가 이보다 벌어지면 수집 공백(시간 합산에서 제외)
PRESETS = ["1시간", "6시간", "오늘", "어제", "3일", "7일"]
STALE_S = 300                    # 데이터 기준 시각이 이보다 오래되면 화면에 '오래됨' 표시


def host_profile():
    """센서 유무 판정은 observe_core.host_profile(CLI 와 공용)."""
    return core.host_profile()


def is_desktop(profile=None):
    return not (profile or host_profile())["battery"]


class Range:
    """[t0, t1] 조회 범위. follows_now=True 면 끝이 '지금'(새로고침 때마다 지금으로 이동)."""

    def __init__(self, t0, t1, label, follows_now=False):
        self.t0, self.t1, self.label, self.follows_now = t0, t1, label, follows_now

    def at(self, now):
        if not self.follows_now:
            return self
        span = self.t1 - self.t0
        return Range(now - span, now, self.label, True) if self.label != "오늘" else preset("오늘", now)

    @property
    def secs(self):
        return self.t1 - self.t0

    def text(self):
        a, b = datetime.fromtimestamp(self.t0), datetime.fromtimestamp(self.t1)
        f = "%H:%M" if a.date() == b.date() else "%m-%d %H:%M"
        return f"{a.strftime(f)} ~ {b.strftime(f)}"


def _midnight(t):
    return datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0)


def preset(name, now):
    if name == "1시간":
        return Range(now - 3600, now, name, True)
    if name == "6시간":
        return Range(now - 6 * 3600, now, name, True)
    if name == "3일":
        return Range(now - 3 * 86400, now, name, True)
    if name == "7일":
        return Range(now - 7 * 86400, now, name, True)
    if name == "오늘":
        return Range(_midnight(now).timestamp(), now, name, True)
    if name == "어제":
        m = _midnight(now)
        return Range((m - timedelta(days=1)).timestamp(), m.timestamp(), name, False)
    raise ValueError(f"알 수 없는 범위: {name}")


def parse_range(text, now=None):
    """프리셋 이름("1시간"…), "-30m"(지금까지 30분), "10:00..11:30", "2026-10-21 09:00..2026-10-21 12:00" 을 Range 로. 잘못되면 ValueError."""
    now = now if now is not None else time.time()
    s = str(text).strip()
    if s in PRESETS:
        return preset(s, now)
    if ".." in s:
        a, _, b = s.partition("..")
        t0, t1 = core.parse_when(a, now), core.parse_when(b, now)
        if t0 is None or t1 is None:
            raise ValueError(f"시각을 읽지 못함: {s}")
        if t1 <= t0:
            raise ValueError("끝이 시작보다 늦어야 합니다")
        return Range(t0, t1, "직접", False)
    t0 = core.parse_when(s, now)
    if t0 is None:
        raise ValueError(f"범위를 읽지 못함: {s} (예: 1시간 · -30m · 10:00..11:30)")
    if t0 >= now:
        raise ValueError("시작이 지금보다 앞이어야 합니다")
    return Range(t0, now, "직접", True)


def baseline_for(rng, kind="prev"):
    """비교 기준 구간 (t0, t1) 또는 None. prev=바로 앞의 같은 길이, yday=어제 같은 시간대, none."""
    if kind == "none":
        return None
    if kind == "yday":
        return (rng.t0 - 86400, rng.t1 - 86400)
    return (rng.t0 - rng.secs, rng.t0)


# ------------------------------------------------------------------ 표본 → 가벼운 레코드·배터리 추정
def compact(s):
    """수집기 표본 하나 → 그래프·집계에 필요한 필드만 남긴 dict. proc/irq/thr 같은 큰 필드는 버린다(깨끗한 표본 여부만 미리 계산)."""
    pw, cs, dev = s.get("pw") or {}, s.get("cs") or {}, s.get("dev") or {}
    psr = dev.get("psr") or {}
    procs = s.get("proc") or []
    kc = next((p.get("cpu_core_pct", 0) for p in procs if p.get("comm") == "kmscon"), 0)   # 코어 1개 = 100%
    mode = str(psr.get("mode") or "")
    return {
        "t": s["t"], "psys": pw.get("psys_w"), "batt_vi": pw.get("batt_vi_w"), "pkg": pw.get("pkg_w"), "core": pw.get("core_w"),
        "pct": _num(pw.get("batt_pct")), "q": pw.get("q_uah"), "v": pw.get("v_uv"), "full": pw.get("full_uah"),
        "status": pw.get("status"), "ac": bool(pw.get("ac")), "state": s.get("state") or "?",
        "psr": "enabled" in mode, "psr_sink": psr.get("sink"), "psr_mode": mode or None,
        "pc8": cs.get("pc8"), "pc10": cs.get("pc10"), "mhz": cs.get("mhz"),
        # 상위 프로세스(저장된 최대 16행)의 자발적 문맥 전환/s 합 — 시스템 전체 아님 / 시스템 전체 문맥 전환/s(비자발 포함) / 전체 CPU 대비 %
        # 옛 표본(메인 스레드만 센 proc 행)은 ctxsw_top 을 None 으로 둔다
        "ctxsw_top": None if any("ctxsw_vol_leader_s" in p for p in procs) else sum(p.get("ctxsw_vol_s", 0) for p in procs),
        "ctxsw_all": (s.get("irq") or {}).get("ctxt_s"), "cpu_all": (s.get("irq") or {}).get("cpu_all_pct"),
        "legacy": bool(s.get("legacy")),
        "clean": kc < 1.0 and not any(p.get("comm") in BUSY for p in procs),
        "lid": dev.get("lid"), "vt": dev.get("vt"), "bl": _num(dev.get("bl")), "boot": dev.get("boot"),
        "wifi_ps": (dev.get("wifi") or {}).get("ps"),
    }


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _mean(vals):
    v = [x for x in vals if isinstance(x, (int, float))]
    return statistics.mean(v) if v else None


def coulomb(recs, max_gap=90):
    """방전 중인 연속 쌍의 누적 계량값(q)으로 낸 평균 전력. 반환 (W 또는 None, 합산 시간(시간 단위)). 1 mAh 단위라 10분 이상에서만 믿을 만하다."""
    dq = dt = wh = 0.0
    for a, b in zip(recs, recs[1:]):
        if None in (a["q"], b["q"], a["v"], b["v"]) or a["status"] != "Discharging" or b["status"] != "Discharging":
            continue
        d = b["t"] - a["t"]
        if not 0 < d <= max_gap:
            continue
        x = a["q"] - b["q"]
        dq += x
        dt += d
        wh += x / 1e6 * ((a["v"] + b["v"]) / 2) / 1e6
    return (wh / (dt / 3600), dt / 3600) if dt > 0 else (None, 0.0)


def battery_estimate(recs, now=None):
    """현재 잔량·만충 용량(Wh)과 세 가지 기준 전력으로 본 남은 시간. 마지막 표본이 충전 중이면 charging=True 로만 알린다.
    기준: recent(최근 30분 계량 평균, 없으면 V×I 평균) / typical(최근 6시간 방전 중 '깨끗한' 표본의 계량 평균) / now(최근 3표본 V×I)."""
    if not recs:
        return None
    last = recs[-1]
    out = {"pct": last["pct"], "status": last["status"], "charging": last["status"] == "Charging", "ac": last["ac"], "t": last["t"]}
    # 충전 중 전압은 방전 때보다 높아 Wh 를 부풀리므로, 가장 최근 '방전 중' 전압을 기준으로 환산한다
    v = next((r["v"] for r in reversed(recs) if r["status"] == "Discharging" and r["v"]), last["v"])
    if v and last["q"]:
        out["remain_wh"] = last["q"] * v / 1e12
    full = last["full"] or _sysfs_int("charge_full")             # 오래된 표본에는 full_uah 가 없으므로 sysfs 로 보충
    if v and full:
        out["full_wh"] = full * v / 1e12
    if "remain_wh" not in out and out.get("full_wh") and last["pct"] is not None:
        out["remain_wh"] = out["full_wh"] * last["pct"] / 100
    t_end = last["t"]
    recent = [r for r in recs if r["t"] >= t_end - 1800]
    w, hrs = coulomb(recent)
    if w is None or hrs < 10 / 60:
        w = _mean([r["batt_vi"] for r in recent if r["status"] == "Discharging"])
    out["recent_w"] = w
    typ = [r for r in recs if r["t"] >= t_end - 6 * 3600 and r["status"] == "Discharging" and r["clean"]]
    tw, thrs = coulomb(typ)
    out["typical_w"] = tw if tw is not None and thrs >= 10 / 60 else _mean([r["batt_vi"] for r in typ])
    out["now_w"] = _mean([r["batt_vi"] for r in recs[-3:] if r["status"] == "Discharging"])
    rw = out.get("remain_wh")
    for key in ("recent", "typical", "now"):
        p = out.get(key + "_w")
        out[key + "_h"] = rw / p if rw and p and p > 0.5 else None
    for key in ("recent", "typical", "now"):                    # 만충 시간(참고): 만충 용량 / 전력
        p, fw = out.get(key + "_w"), out.get("full_wh")
        out[key + "_full_h"] = fw / p if fw and p and p > 0.5 else None
    return out


def _sysfs_int(name):
    for d in glob.glob("/sys/class/power_supply/BAT*"):
        try:
            return int(open(os.path.join(d, name)).read())
        except (OSError, ValueError):
            pass
    return None


# ------------------------------------------------------------------ 요약 계산
def _pairs(recs):
    """연속한 표본 쌍 중 간격이 MAX_GAP 이하인 것 → [(a, b, 초)]"""
    out = []
    for a, b in zip(recs, recs[1:]):
        d = b["t"] - a["t"]
        if 0 < d <= MAX_GAP:
            out.append((a, b, d))
    return out


def discharge_curve(recs):
    """방전 중 연속 쌍의 누적 계량으로 낸 사용 에너지. 반환 {"wh","hours","avg_w","err_w"} 또는 None.
    오차는 1 mAh(≈15 mWh) 양자화 ÷ 시간 — 짧은 범위는 믿기 어렵다는 걸 값과 함께 알린다."""
    wh = hrs = 0.0
    for a, b, d in _pairs(recs):
        if a["status"] == b["status"] == "Discharging" and None not in (a["q"], b["q"], a["v"], b["v"]):
            wh += (a["q"] - b["q"]) / 1e6 * ((a["v"] + b["v"]) / 2) / 1e6
            hrs += d / 3600
    if hrs <= 0:
        return None
    return {"wh": wh, "hours": hrs, "avg_w": wh / hrs, "err_w": 0.015 / hrs}


def charge_events(recs):
    """충전이 시작된 횟수(방전/완충 → Charging 전환)."""
    n, prev = 0, None
    for r in recs:
        if r["status"] == "Charging" and prev not in (None, "Charging"):
            n += 1
        prev = r["status"]
    return n


def time_shares(recs):
    """범위의 수집된 시간(시간 단위)과 항목별 비율. 반환 {"hours", "gap_s", "lid_open", "psr", "low", "ac", "discharging"}(비율 0~1)."""
    pr = _pairs(recs)
    tot = sum(d for _, _, d in pr)
    if tot <= 0:
        return {"hours": 0.0, "lid_open": None, "psr": None, "low": None, "ac": None, "discharging": None}
    frac = lambda f: sum(d for a, b, d in pr if f(b)) / tot
    return {"hours": tot / 3600, "lid_open": frac(lambda r: r["lid"] == "open"), "psr": frac(lambda r: r["psr"]),
            "low": frac(lambda r: r["state"] == "low"), "ac": frac(lambda r: r["ac"]), "discharging": frac(lambda r: r["status"] == "Discharging")}


def pkg_energy(rows, t0, t1):
    """구간 [t0, t1] 의 패키지(CPU+GPU) 전력량. 표본 하나는 (t-dt, t] 를 대표하므로 겹친 시간만큼 가중해 적분한다(observe_trace.energy 와 같은 방식).
    psys 가 없는 호스트(데스크톱)에서 앱별 에너지 추정의 기준으로 쓴다. 반환 (Wh, 평균 W) 또는 (None, None)."""
    wh = cover = 0.0
    for r in rows:
        w = (r.get("pw") or {}).get("pkg_w")
        t, dt = r.get("t"), r.get("dt") or 30.0
        if not isinstance(w, (int, float)) or t is None or t < t0 or t - dt > t1:
            continue
        ov = min(t, t1) - max(t - dt, t0)
        if ov > 0:
            wh += w * ov / 3600
            cover += ov
    return (wh, wh * 3600 / cover) if cover > 0 else (None, None)


def summarize(rows, recs, spans, rng, now=None):
    """요약 탭이 쓰는 값. 각 값은 (값, 라벨) 이 아니라 평평한 dict — 라벨은 LABELS 에 한 곳으로 모았다."""
    now = now if now is not None else time.time()
    en = tr.energy(rows, rng.t0, rng.t1) if rows else None
    sh = time_shares(recs)
    dc = discharge_curve(recs)
    first_pct = next((r["pct"] for r in recs if r["pct"] is not None), None)
    last_pct = next((r["pct"] for r in reversed(recs) if r["pct"] is not None), None)
    apps = ex.apps_table(rows)
    top_apps = []
    if apps:
        table, _n = apps
        tot = sum(v["cpu"] for v in table.values()) or 1.0
        top_apps = sorted(((k, v["cpu"], v["cpu"] * 100 / tot, v["ctxsw"]) for k, v in table.items()), key=lambda x: -x[1])[:5]
    est = battery_estimate(recs) if recs and now - recs[-1]["t"] <= 600 and rng.t1 >= now - 600 else None
    pkg_wh, avg_pkg_w = pkg_energy(rows, rng.t0, rng.t1)
    return {
        "pkg_wh": pkg_wh, "avg_pkg_w": avg_pkg_w, "avg_cpu_pct": _mean([r["cpu_all"] for r in recs]), "avg_ctxsw": _mean([r["ctxsw_all"] for r in recs]),
        "range": rng.text(), "n": len(rows), "hours": sh["hours"], "gap_s": max(0.0, rng.secs - sh["hours"] * 3600),
        "avg_psys_w": en["avg_psys_w"] if en else None, "psys_wh": en["psys_wh"] if en else None,
        "coulomb": dc, "pct_first": first_pct, "pct_last": last_pct, "charges": charge_events(recs),
        "shares": sh, "top_apps": top_apps, "focus": ex.focus_table(spans, rng.t0, rng.t1)[:5], "estimate": est,
    }


LABELS = {
    "avg_psys_w": "측정(RAPL psys, 플랫폼 전체보다 약 1 W 적게 보임)",
    "coulomb": "측정(누적 계량 — 배터리 안으로 들고 나간 전하량. 짧은 범위는 오차 큼)",
    "estimate": "추정(잔량 ÷ 최근 전력, 0% 까지 쓴다고 가정 — 실제로는 5~10% 남기고 끔)",
    "top_apps": "측정(CPU 시간 점유율 — 전력 점유율이 아님)",
    "shares": "측정(표본 30초 간격 기준 시간 비율)",
}


# ------------------------------------------------------------------ 하드웨어·배터리·수집 상태
def battery_health():
    """sysfs 의 배터리 정보: 만충/설계 용량(Wh 는 전압 곱), 건강 %, 사이클. 읽지 못한 값은 None."""
    out = {"full_wh": None, "design_wh": None, "health_pct": None, "cycles": None, "status": None}
    for d in glob.glob("/sys/class/power_supply/BAT*"):
        def rd(name):
            try:
                return int(open(os.path.join(d, name)).read())
            except (OSError, ValueError):
                return None
        full, design, vmin, cyc = rd("charge_full"), rd("charge_full_design"), rd("voltage_min_design"), rd("cycle_count")
        v = (vmin or 0) / 1e6 or None
        if full and design:
            out["health_pct"] = full * 100 / design
        if v and full:
            out["full_wh"] = full * v / 1e6
        if v and design:
            out["design_wh"] = design * v / 1e6
        out["cycles"] = cyc
        try:
            out["status"] = open(os.path.join(d, "status")).read().strip()
        except OSError:
            pass
        break
    return out


def collector_status(now=None):
    """수집기 상태: 마지막 표본 나이·수준·eBPF·표본 파일 크기. 파일이 없으면 None 값."""
    now = now if now is not None else time.time()
    files = sorted(glob.glob(os.path.join(core.SAMPLE_DIR, "samples-*.jsonl")))
    size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
    last = None
    if files:
        try:
            with open(files[-1], "rb") as fh:
                fh.seek(max(0, os.path.getsize(files[-1]) - 65536))
                lines = fh.read().splitlines()
            for line in reversed(lines):
                try:
                    last = json.loads(line)
                    break
                except ValueError:
                    continue
        except OSError:
            pass
    ctl = {}
    try:
        ctl = json.load(open(os.path.join(os.path.dirname(core.SAMPLE_DIR.rstrip("/")), "control.json")))
    except (OSError, ValueError):
        pass
    return {"files": len(files), "bytes": size, "last_t": last["t"] if last else None, "age_s": now - last["t"] if last else None,
            "control": ctl, "last": last}


# ------------------------------------------------------------------ 조회
def load(rng, baseline="prev", now=None):
    """범위를 읽어 보기 모델(dict)을 만든다. 표본이 없으면 rows=[] 로 돌려준다(오류 아님). 네트워크 조회는 하지 않는다(Netdata 는 탭에서 따로).
    rng.follows_now 이면 끝을 지금으로 옮긴 범위로 읽는다."""
    now = now if now is not None else time.time()
    rng = rng.at(now)
    base = baseline_for(rng, baseline)
    lo = min(rng.t0, base[0] if base else rng.t0) - 120
    all_rows = list(core.iter_jsonl(core.SAMPLE_DIR, "samples", lo, rng.t1 + 120))
    rows = [r for r in all_rows if rng.t0 <= r["t"] <= rng.t1]
    base_rows = [r for r in all_rows if base and base[0] <= r["t"] < base[1]]
    spans = tr.build_spans(list(core.iter_jsonl(core.state_dir(), "events", lo - 3600, rng.t1 + 120)))
    recs = [compact(r) for r in rows]
    prof = host_profile()
    prof = {"battery": prof["battery"] or any(r["pct"] is not None for r in recs), "psys": prof["psys"] or any(r["psys"] is not None for r in recs)}
    return {"profile": prof, "range": rng, "baseline": base, "baseline_kind": baseline, "loaded_at": now, "rows": rows, "base_rows": base_rows,
            "all_rows": all_rows, "recs": recs, "spans": spans, "summary": summarize(rows, recs, spans, rng, now),
            "apps": ex.apps_table(rows), "procs": ex.proc_table(rows), "ebpf": ex.ebpf_table(rows),
            "span_rows": ex.span_table(spans, rows, rng.t0, rng.t1),
            "spikes": sp.find_spikes(rows, spans, prof["psys"], all_rows=all_rows)}


def stale(view, now=None):
    """데이터 기준 시각이 지금보다 얼마나 오래됐나(초) — 화면의 '오래됨' 표시용. 끝이 과거인 범위는 해당 없음(None)."""
    now = now if now is not None else time.time()
    if not view["range"].follows_now:
        return None
    return now - view["loaded_at"]
