"""범용 조회(observectl query): 신호(표본 경로·별칭·앱별 값·Netdata) × 시간 범위 × 묶기(시간 간격 또는 상태 등) × 집계.
window·top·explain 이 각자 하던 "구간 평균" 계산을 한 곳에서 일반화한 것 — 순수 함수라 시험하기 쉽다."""
import re

import observe_stats as stats

# 별칭 → (표본 경로, 방전 중 표본만 쓰는지). 경로는 표본(정규화된 v4) 기준
ALIASES = {
    "psys": ("pw.psys_w", False), "pkg": ("pw.pkg_w", False), "core": ("pw.core_w", False), "uncore": ("pw.uncore_w", False),
    "vi": ("pw.batt_vi_w", True),            # 충전 중의 전류는 방전 전력이 아니므로 방전 중 표본만
    "pc8": ("cs.pc8", False), "pc10": ("cs.pc10", False), "cpu_all": ("irq.cpu_all_pct", False),
}
AGGS = ("mean", "min", "max", "p50", "p95", "sum", "count")
ND_PREFIX = "nd:"


def parse_step(s):
    """'30s' '5m' '1h' → 초. 숫자만이면 초."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", str(s).strip())
    if not m:
        raise ValueError(f"간격 형식이 아님: {s!r} (예: 30s, 5m, 1h)")
    return float(m[1]) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m[2]]


def _get(s, path):
    for k in path.split("."):
        s = s.get(k) if isinstance(s, dict) else None
    return s


def extract(row, sig):
    """표본 하나에서 신호 값(숫자) 또는 None.
    신호 형식: 별칭(psys…) · 점 경로(pw.psys_w) · app:<앱>.cpu|ctxsw · proc:<comm>.cpu|ctxsw"""
    if sig in ALIASES:
        path, dis = ALIASES[sig]
        if dis and _get(row, "pw.status") != "Discharging":
            return None
        v = _get(row, path)
    elif sig.startswith(("app:", "proc:")):
        kind, _, rest = sig.partition(":")
        name, _, field = rest.rpartition(".")
        key = {"cpu": "cpu_core_pct", "ctxsw": "ctxsw_vol_s"}.get(field)
        if not name or key is None:
            raise ValueError(f"{sig!r}: 형식은 {kind}:<이름>.cpu 또는 {kind}:<이름>.ctxsw")
        table = row.get("apps" if kind == "app" else "proc")
        if table is None:
            return None
        if kind == "proc" and any("ctxsw_vol_leader_s" in p for p in table) and key == "ctxsw_vol_s":
            return None                       # 옛 표본의 메인 스레드만 센 값은 쓰지 않는다(L9)
        hit = [p.get(key) for p in table if p.get("app" if kind == "app" else "comm") == name]
        return float(sum(h for h in hit if isinstance(h, (int, float)))) if hit else 0.0
    else:
        v = _get(row, sig)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def aggregate(vals, agg):
    xs = sorted(v for v in vals if isinstance(v, (int, float)) and v == v)
    if agg == "count":
        return float(len(xs))
    if not xs:
        return None
    if agg == "mean":
        return stats.mean(xs)
    if agg == "min":
        return xs[0]
    if agg == "max":
        return xs[-1]
    if agg == "sum":
        return sum(xs)
    q = 0.5 if agg == "p50" else 0.95
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def run(rows, signals, agg="mean", step=None, key=None, nd_series=None, nd_half=15.0):
    """묶는 기준은 step(초 단위 시간 구간) 또는 key(행 → 그룹 이름). 둘 다 없으면 전체 한 줄.
    nd:<이름> 신호는 nd_series[이름]=[(epoch, 값)] 에서 표본 시각 ±nd_half 초를 평균해 쓴다.
    반환 [(그룹 이름, n, [신호별 값 또는 None])] — 그룹은 시간순/이름순."""
    if agg not in AGGS:
        raise ValueError(f"집계는 {', '.join(AGGS)} 중 하나")
    t0 = rows[0]["t"] if rows else 0
    groups = {}
    for r in rows:
        if step:
            g = t0 + int((r["t"] - t0) // step) * step
        elif key:
            g = key(r)
        else:
            g = "전체"
        groups.setdefault(g, []).append(r)
    out = []
    for g in sorted(groups, key=lambda x: (isinstance(x, str), x)):
        rs, vals = groups[g], []
        for sig in signals:
            if sig.startswith(ND_PREFIX):
                pts = (nd_series or {}).get(sig[len(ND_PREFIX):], [])
                xs = []
                for r in rs:
                    near = [v for tt, v in pts if abs(tt - r["t"]) <= nd_half and v is not None]
                    xs.append(sum(near) / len(near) if near else None)
                vals.append(aggregate(xs, agg))
            else:
                vals.append(aggregate([extract(r, sig) for r in rs], agg))
        out.append((g, len(rs), vals))
    return out
