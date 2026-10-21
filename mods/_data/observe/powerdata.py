"""powerui 의 데이터 계층: 수집기가 남긴 표본(JSONL)을 증분으로 읽어 가벼운 레코드로 줄이고, 그룹 비교·배터리 추정을 계산한다(터미널 없음).
표본 파일은 하루 수 MB 라 매번 다시 읽지 않고 파일별 오프셋부터 새로 붙은 줄만 읽는다."""
from __future__ import annotations

import glob
import json
import os
import re
import statistics
import time

import observe_core as core

BUSY = {"nix-daemon", "nix", "nixos-rebuild", "nixup", ".nixup-wrapped", "cc1", "ld", "rustc"}
GROUPS = {"state": "상태(low=깊은 절전 진입)", "psr": "PSR 켬/끔", "ac": "전원(AC/배터리)", "lid": "덮개", "vt": "화면(VT)", "boot": "부팅"}


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
        "ctxsw_top": sum(p.get("ctxsw_vol_s", 0) for p in procs), "ctxsw_all": (s.get("irq") or {}).get("ctxt_s"), "cpu_all": (s.get("irq") or {}).get("cpu_all_pct"),
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


class Store:
    """표본 디렉터리를 증분으로 읽는다. refresh() 는 새 레코드 수를 돌려준다. keep_s 보다 오래된 레코드는 버린다."""

    def __init__(self, directory=None, keep_s=3 * 86400):
        self.dir = directory or core.SAMPLE_DIR
        self.keep_s = keep_s
        self.recs: list[dict] = []
        self._off: dict[str, int] = {}

    def refresh(self, now=None):
        now = now if now is not None else time.time()
        horizon, cutoff = now + 300, now - self.keep_s          # 부팅 직후 RTC 가 +9h 앞선 표본은 가짜 미래 값(iter_jsonl 과 같은 처리)
        new = 0
        for f in sorted(glob.glob(os.path.join(self.dir, "samples-*.jsonl"))):
            m = re.search(r"-(\d{8})\.jsonl$", f)
            if not m:
                continue
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            off = self._off.get(f, 0)
            if size < off:
                off = 0
            if off == 0 and os.path.getmtime(f) < cutoff:
                continue
            if size == off:
                continue
            with open(f, "rb") as fh:
                fh.seek(off)
                data = fh.read(size - off)
            end = data.rfind(b"\n") + 1                          # 쓰는 중인 마지막 줄은 다음에
            self._off[f] = off + end
            for line in data[:end].splitlines():
                try:
                    o = json.loads(line)
                    t = o.get("t")
                except ValueError:
                    continue
                if t is None or t > horizon or t < cutoff:
                    continue
                self.recs.append(compact(core.normalize_sample(o)))   # 옛 형식(v1) 표본도 새 이름으로 읽는다
                new += 1
        if new:
            self.recs.sort(key=lambda r: r["t"])
        if self.recs and self.recs[0]["t"] < cutoff:
            self.recs = [r for r in self.recs if r["t"] >= cutoff]
        return new

    def since(self, t0, t1=None):
        return [r for r in self.recs if r["t"] >= t0 and (t1 is None or r["t"] <= t1)]


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


def group_key(r, by):
    if by == "ac":
        return "AC" if r["ac"] else "배터리"
    if by == "psr":
        return "PSR 켬" if r["psr"] else "PSR 끔"
    return r.get(by) or "?"


def group_table(recs, by, clean=False, max_gap=90):
    """그룹별 요약. 행: dict(group, n, hours, batt(방전 중 V×I 평균), coulomb(계량 평균, 10분 미만이면 None), psys, pkg, pc8, pc10, wake, cpu). 시간 많은 순."""
    rows = [r for r in recs if r["clean"]] if clean else list(recs)
    groups: dict[str, list] = {}
    pairs: dict[str, list] = {}
    for r in rows:
        groups.setdefault(group_key(r, by), []).append(r)
    for a, b in zip(rows, rows[1:]):
        if 0 < b["t"] - a["t"] <= max_gap:
            pairs.setdefault(group_key(b, by), []).append((a, b))
    out = []
    for k, g in groups.items():
        flat = [x for ab in pairs.get(k, []) for x in ab]
        cw, chrs = coulomb_pairs(pairs.get(k, []), max_gap)
        out.append({
            "group": k, "n": len(g), "hours": sum(min(b["t"] - a["t"], max_gap) for a, b in pairs.get(k, [])) / 3600,
            "batt_vi": _mean([r["batt_vi"] for r in g if r["status"] == "Discharging"]),
            "coulomb": cw if cw is not None and chrs >= 10 / 60 else None,
            "psys": _mean([r["psys"] for r in g]), "pkg": _mean([r["pkg"] for r in g]),
            "pc8": _mean([r["pc8"] for r in g]), "pc10": _mean([r["pc10"] for r in g]),
            "ctxsw_top": _mean([r["ctxsw_top"] for r in g]), "ctxsw_all": _mean([r["ctxsw_all"] for r in g]), "cpu_all": _mean([r["cpu_all"] for r in g]),
        })
    return sorted(out, key=lambda x: -x["hours"])


def coulomb_pairs(pairs, max_gap=90):
    dq = dt = wh = 0.0
    for a, b in pairs:
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


# ---------------------------------------------------------------- Netdata(REST API 만 있음: 웹 화면 없음)
NETDATA = os.environ.get("POWERUI_NETDATA", "http://127.0.0.1:19999")
NETDATA_CHARTS = [  # (차트, 제목, 단위, 합칠 차원 제외 목록, 부호 무시)
    ("system.cpu", "CPU 사용(idle 제외)", "%", ("idle",), False),
    ("system.net", "네트워크 합계(수신+송신)", "kbps", (), True),
    ("system.io", "디스크 입출력 합계", "KiB/s", (), True),
    ("system.ram", "메모리 사용(free·cached 제외)", "MiB", ("free", "cached"), False),
    ("sensors.temperature_nvme-pci-0200_temp1_Composite_input", "NVMe 온도", "°C", (), False),
]


def netdata_series(chart, seconds, points, exclude=(), absolute=False, timeout=2.0):
    """Netdata 의 한 차트를 [(t, 합계)] 로 읽는다(차원을 합산). 실패하면 None(netdata 가 꺼졌거나 차트 없음)."""
    import urllib.request
    url = f"{NETDATA}/api/v1/data?chart={chart}&after=-{int(seconds)}&points={int(points)}&group=average&format=json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    labels = d.get("labels") or []
    idx = [i for i, l in enumerate(labels) if i > 0 and l not in exclude]
    out = []
    for row in d.get("data") or []:
        vals = [row[i] for i in idx if isinstance(row[i], (int, float))]
        out.append((row[0], sum(abs(x) for x in vals) if absolute else sum(vals)) if vals else (row[0], None))
    return sorted(out)
