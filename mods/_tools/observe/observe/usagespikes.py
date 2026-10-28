"""튀었던 순간 순위 — 긴 범위(예: 7일)의 평균에 묻히는 순간 부하를 찾아 순위를 매기고, 이웃·평균과 비교할 값을 함께 만든다.

방식: 범위를 5분 창으로 나눠 평균 전력을 구하고, 전원 상태(노트북은 AC/방전)별 **중앙값**보다 충분히 높은 창이 이어진 것을 한 사건으로 묶는다.
순위 기준은 최고값이 아니라 **평소(중앙값)보다 더 쓴 에너지(Wh)** — 1~2점짜리 스파이크보다 오래 높았던 구간이 위로 온다.
신호: psys 가 있으면 psys(플랫폼 전체), 없으면 패키지 전력(CPU+GPU, 전체 소비 아님). 순수 계산이라 화면·CLI 가 같이 쓴다. 상관일 뿐 원인 단정이 아니다."""
from __future__ import annotations

import bisect
import statistics

import observe_explain as ex

BUCKET_S = 300            # 창 길이(초)
MIN_SAMPLES = 3           # 창에 표본이 이보다 적으면 건너뜀(수집 공백)
MIN_ABOVE_W = 1.0         # 중앙값보다 최소 이만큼(W) 높아야 '높은 창'
MIN_ABOVE_FRAC = 0.2      # 그리고 중앙값의 이 비율 이상 높아야
MIN_WH = 0.05             # 초과 에너지가 이보다 작은 사건은 버림
CONTEXT_S = 1800          # 앞·뒤 이웃 구간 길이(초)
DAYS_BACK = 7             # '다른 날 같은 시각' 비교에 쓰는 일수


def power_of(row, psys):
    """표본의 전력(W). psys 가 있는 호스트는 psys 만(없는 표본은 건너뜀 — 단위 섞임 방지), 없으면 패키지."""
    pw = row.get("pw") or {}
    return pw.get("psys_w") if psys else pw.get("pkg_w")


def _cpu(row):
    return (row.get("irq") or {}).get("cpu_all_pct")


def _mean(vals):
    v = [x for x in vals if isinstance(x, (int, float))]
    return sum(v) / len(v) if v else None


def _window_mean(ts, p, lo, hi):
    """[lo, hi) 안 표본의 평균 전력. 표본이 MIN_SAMPLES 보다 적으면 None."""
    i, j = bisect.bisect_left(ts, lo), bisect.bisect_left(ts, hi)
    vals = [x for x in p[i:j] if x is not None]
    return sum(vals) / len(vals) if len(vals) >= MIN_SAMPLES else None


def _bucket_means(rows, psys):
    """(그룹, 5분 창 번호) → 평균 전력. 표본이 MIN_SAMPLES 보다 적은 창은 뺀다. 그룹은 노트북에서 AC 여부."""
    acc = {}
    for r in rows:
        v = power_of(r, psys)
        if v is None:
            continue
        g = bool((r.get("pw") or {}).get("ac")) if psys else 0
        acc.setdefault((g, int(r["t"] // BUCKET_S)), []).append(v)
    return {k: sum(v) / len(v) for k, v in acc.items() if len(v) >= MIN_SAMPLES}


def find_spikes(rows, spans, psys, n=8, all_rows=None, usual_rows=None):
    """rows(범위 안 표본)에서 가장 많이 튄 사건 n 개. all_rows(범위 밖 기준 구간까지 읽은 표본)가 있으면 앞뒤 이웃·다른 날 비교에 쓴다.
    usual_rows 가 있으면 「평소(중앙값)·p90」을 그 표본으로 구한다 — 튄 순간 근처로 범위를 좁혀 봐도 같은 사건이 같은 기준으로 보이게(없으면 rows 자체). 각 항목:
    {rank, t0, t1, dur_s, power, peak, median, p90, excess_wh, before, after, other_days, other_n, cpu, apps[(앱, CPU%)], focus, ac}
    표본이 부족하거나 튄 곳이 없으면 []."""
    rows = sorted(rows, key=lambda r: r["t"])
    ts = [r["t"] for r in rows]
    p = [power_of(r, psys) for r in rows]
    ctx = sorted(all_rows, key=lambda r: r["t"]) if all_rows else rows
    cts = [r["t"] for r in ctx]
    cp = [power_of(r, psys) for r in ctx]
    buckets = {}                                           # (그룹, 창 번호) → [인덱스]
    for i, r in enumerate(rows):
        if p[i] is None:
            continue
        g = bool((r.get("pw") or {}).get("ac")) if psys else 0     # 노트북은 AC/방전을 따로 본다(전력 기준이 다름)
        buckets.setdefault((g, int(r["t"] // BUCKET_S)), []).append(i)
    means = {k: sum(p[i] for i in v) / len(v) for k, v in buckets.items() if len(v) >= MIN_SAMPLES}
    smeans = _bucket_means(usual_rows, psys) if usual_rows else means
    stat = {}
    for g in {k[0] for k in smeans}:
        vals = sorted(m for k, m in smeans.items() if k[0] == g)
        stat[g] = (statistics.median(vals), vals[min(len(vals) - 1, int(len(vals) * 0.9))])
    hot = {}
    for k, m in means.items():
        if k[0] not in stat:
            continue
        med = stat[k[0]][0]
        if m > med + max(MIN_ABOVE_W, MIN_ABOVE_FRAC * med):
            hot[k] = (m - med) * BUCKET_S / 3600
    events, seen = [], set()
    for k in sorted(hot, key=lambda k: (k[0], k[1])):
        if k in seen:
            continue
        run = [k]
        seen.add(k)
        while (k[0], run[-1][1] + 1) in hot:
            nxt = (k[0], run[-1][1] + 1)
            run.append(nxt)
            seen.add(nxt)
        events.append((k[0], run))
    out = []
    for g, run in events:
        idx = [i for kk in run for i in buckets[kk]]
        wh = sum(hot[kk] for kk in run)
        if wh < MIN_WH:
            continue
        t0, t1 = ts[min(idx)], ts[max(idx)]
        ev_rows = [rows[i] for i in idx]
        others = [x for x in (_window_mean(cts, cp, t0 - d * 86400, t1 + 1 - d * 86400) for d in range(1, DAYS_BACK + 1)) if x is not None]
        apps = []
        got = ex.apps_table(ev_rows)
        if got:
            apps = sorted(((a, v["cpu"]) for a, v in got[0].items()), key=lambda kv: -kv[1])[:3]
        foc = ex.focus_table(spans, t0, t1 + BUCKET_S)
        out.append({"t0": t0, "t1": t1, "dur_s": len(run) * BUCKET_S, "power": sum(means[kk] for kk in run) / len(run), "peak": max(means[kk] for kk in run),
                    "median": stat[g][0], "p90": stat[g][1], "excess_wh": wh,
                    "before": _window_mean(cts, cp, t0 - CONTEXT_S, t0), "after": _window_mean(cts, cp, t1 + 1, t1 + 1 + CONTEXT_S),
                    "other_days": _mean(others), "other_n": len(others), "cpu": _mean([_cpu(r) for r in ev_rows]), "apps": apps,
                    "focus": foc[0][0] if foc else None, "ac": g if psys else None})
    out.sort(key=lambda s: -s["excess_wh"])
    for i, s in enumerate(out[:n], 1):
        s["rank"] = i
    return out[:n]
