"""observe_netdata — observectl 안의 Netdata 어댑터. **Netdata 가 켜져 있을 때만 쓰고, 꺼져 있으면 '관측 공백'으로 명시**한다(배터리에서 Netdata 를 끄는 정책과 양립).
무엇을 가져오나(정의는 SIGNALS 에 항목마다 적혀 있고 `observectl nd defs` 로 볼 수 있다): 1초 간격 RAPL(psys·패키지), 배터리 전압×전류, 전체 CPU, 시스템 전체 문맥 전환·인터럽트,
네트워크, 디스크, NVMe 온도, 그리고 앱 그룹별 CPU(88개 앱 그룹 전체 — observectl 이 저장하는 상위 16행보다 넓다).
**일부러 가져오지 않는 것**: 앱별 자발적 문맥 전환(`app.*_cpu_context_switches`). Netdata apps.plugin 이 `/proc/<pid>/status` 의 메인 스레드 값만 읽어 멀티스레드 앱을 크게 과소 집계한다
(2026-10-21 실측: electron 5.8/s 대 모든 스레드 합 약 92/s). 앱별 전환이 필요하면 `observectl bpf wake`·`thread_top.py`(스레드 단위)를 쓴다.
표준 라이브러리만."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("OBSERVE_NETDATA") or os.environ.get("POWERUI_NETDATA") or "http://127.0.0.1:19999"

# 이름 → (설명, 단위, 정의). 정의는 실제 API 메타데이터와 교차 검증한 것(2026-10-21).
SIGNALS = {
    "psys_w": ("RAPL psys", "W", "cpu.powercap_intel_rapl_zone_psys — 플랫폼 전체에 가깝지만 패널·SSD 등 일부(약 1 W)가 빠짐. observectl 의 psys_w 와 같은 종류이고 1초 간격 평균"),
    "pkg_w": ("RAPL 패키지", "W", "cpu.powercap_intel_rapl_zone_package-0 — CPU+GPU 패키지, 1초 간격 평균"),
    "batt_vi_w": ("배터리 V×I", "W", "sensors BAT1 전압×전류의 1초 간격 곱을 구간 평균(절댓값; 충전 중이면 충전 전력). observectl 의 30초 순간값보다 안정적"),
    "cpu_all_pct": ("전체 CPU", "%", "system.cpu 에서 idle·iowait 를 뺀 합 — **전체 CPU 대비**(100 = 모든 CPU 가 계속 일함, 코어 1개 기준 아님)"),
    "ctxsw_all_s": ("시스템 전체 문맥 전환", "/s", "system.ctxt — 자발+비자발 전체(`/proc/stat` ctxt)"),
    "intr_all_s": ("시스템 전체 인터럽트", "/s", "system.intr (`/proc/stat` intr)"),
    "net_rx_kbps": ("네트워크 수신", "kbit/s", "system.net 의 received(물리 인터페이스 합)"),
    "net_tx_kbps": ("네트워크 송신", "kbit/s", "system.net 의 sent 절댓값(물리 인터페이스 합)"),
    "disk_read_kibs": ("디스크 읽기", "KiB/s", "system.io 의 in"),
    "disk_write_kibs": ("디스크 쓰기", "KiB/s", "system.io 의 out 절댓값"),
    "nvme_temp_c": ("NVMe 온도", "°C", "sensors.temperature_nvme*_Composite_input"),
    "forks_s": ("프로세스 생성", "/s", "system.forks"),
}
APPS_NOTE = "앱 그룹별 CPU: app.<그룹>_cpu_utilization 의 user+system (제목 '100% = 1 core' — 코어 1개 = 100%, 프로세스 전체 스레드 합). 그룹 이름은 Netdata 가 정한 것(예: electron-39_8_10, kernel)"

_avail = [0.0, False]
_charts = [0.0, {}]


class NetdataError(Exception):
    pass


def _get(path, timeout=3.0):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as f:
            return json.load(f)
    except (OSError, ValueError, urllib.error.URLError) as e:
        raise NetdataError(str(e))


def available(timeout=0.7, ttl=10.0, now=None):
    """Netdata API 가 응답하는가(짧은 시간 캐시)."""
    t = now if now is not None else time.time()
    if t - _avail[0] < ttl:
        return _avail[1]
    try:
        _get("/api/v1/info", timeout)
        ok = True
    except NetdataError:
        ok = False
    _avail[0], _avail[1] = t, ok
    return ok


def reset_cache():
    _avail[0] = 0.0
    _charts[0] = 0.0


def charts(ttl=300.0):
    if time.time() - _charts[0] < ttl and _charts[1]:
        return _charts[1]
    _charts[1] = _get("/api/v1/charts", 5.0).get("charts", {})
    _charts[0] = time.time()
    return _charts[1]


def _window(t0, t1):
    t0, t1 = int(t0), int(t1)
    if t1 - t0 < 2:
        t1 = t0 + 2
    return t0, t1


def series(chart, t0, t1, points=60, group="average"):
    """한 차트의 [(epoch, {차원: 값 또는 None})] (시간순). 실패하면 NetdataError."""
    t0, t1 = _window(t0, t1)
    q = urllib.parse.urlencode({"chart": chart, "after": t0, "before": t1, "points": max(1, int(points)), "group": group, "format": "json"})
    d = _get("/api/v1/data?" + q)
    labels = d.get("labels", [])[1:]
    rows = [(r[0], dict(zip(labels, r[1:]))) for r in d.get("data", [])]
    return sorted(rows)


def window_avg(chart, t0, t1):
    """구간 평균 {차원: 값}. 데이터가 없으면 None(Netdata 가 그 시간에 꺼져 있었던 경우 등)."""
    rows = series(chart, t0, t1, points=1)
    if not rows:
        return None
    vals = rows[0][1]
    return None if all(v is None for v in vals.values()) else vals


def coverage(t0, t1):
    """구간에서 Netdata 데이터가 있는 비율(0~1). 꺼져 있던 시간이 있으면 1 미만 — 평균이 구간 일부만 대표한다는 뜻."""
    n = max(2, min(60, int((t1 - t0) // 5)))
    rows = series("system.ctxt", t0, t1, points=n)
    if not rows:
        return 0.0
    return sum(1 for _, v in rows if any(x is not None for x in v.values())) / len(rows)


def _find_chart(prefix):
    for k in charts():
        if k.startswith(prefix):
            return k
    return None


def _sum(vals, exclude=()):
    xs = [v for k, v in vals.items() if k not in exclude and v is not None]
    return sum(xs) if xs else None


def batt_vi_w(t0, t1):
    """1초 간격 전압×전류의 구간 평균(두 차트를 같은 점으로 맞춰 곱한다)."""
    n = max(2, min(300, int(t1 - t0)))
    v = series("sensors.voltage_BAT1-acpi-0_in0_input", t0, t1, points=n)
    c = series("sensors.curr_BAT1-acpi-0_curr1_input", t0, t1, points=n)
    prod = [abs(a[1].get("input")) * abs(b[1].get("input")) for a, b in zip(v, c) if a[1].get("input") is not None and b[1].get("input") is not None]
    return sum(prod) / len(prod) if prod else None


def signals(t0, t1):
    """구간 평균 신호 {이름: 값 또는 None}. 차트가 없거나 비어 있으면 그 항목만 None."""
    out = {}

    def one(name, fn):
        try:
            out[name] = fn()
        except NetdataError:
            out[name] = None
    one("psys_w", lambda: (window_avg("cpu.powercap_intel_rapl_zone_psys", t0, t1) or {}).get("power"))
    one("pkg_w", lambda: (window_avg("cpu.powercap_intel_rapl_zone_package-0", t0, t1) or {}).get("power"))
    one("batt_vi_w", lambda: batt_vi_w(t0, t1))
    one("cpu_all_pct", lambda: _sum(window_avg("system.cpu", t0, t1) or {}, exclude=("idle", "iowait")))
    one("ctxsw_all_s", lambda: (window_avg("system.ctxt", t0, t1) or {}).get("switches"))
    one("intr_all_s", lambda: (window_avg("system.intr", t0, t1) or {}).get("interrupts"))
    one("net_rx_kbps", lambda: abs((window_avg("system.net", t0, t1) or {}).get("received") or 0) if window_avg("system.net", t0, t1) else None)
    one("net_tx_kbps", lambda: abs((window_avg("system.net", t0, t1) or {}).get("sent") or 0) if window_avg("system.net", t0, t1) else None)
    one("disk_read_kibs", lambda: abs((window_avg("system.io", t0, t1) or {}).get("reads") or 0) if window_avg("system.io", t0, t1) else None)
    one("disk_write_kibs", lambda: abs((window_avg("system.io", t0, t1) or {}).get("writes") or 0) if window_avg("system.io", t0, t1) else None)
    one("nvme_temp_c", lambda: next(iter((window_avg(_find_chart("sensors.temperature_nvme") or "", t0, t1) or {}).values()), None))
    one("forks_s", lambda: (window_avg("system.forks", t0, t1) or {}).get("started"))
    return out


def app_name(label):
    m = re.match(r"app\.(.+?)_cpu_utilization(?:@.*)?$", label)
    return (m.group(1) if m else label).lstrip("_") or label


def top_apps(t0, t1, n=10):
    """앱 그룹별 CPU(코어 1개=100%) 상위 n. [(그룹, CPU%)] — user+system 합. 실패하면 NetdataError."""
    t0, t1 = _window(t0, t1)
    q = urllib.parse.urlencode({"contexts": "app.cpu_utilization", "after": t0, "before": t1, "points": 1, "group_by": "instance", "format": "json2"})
    d = _get("/api/v3/data?" + q, timeout=8.0)
    r = d.get("result") or {}
    labels, data = (r.get("labels") or [])[1:], (r.get("data") or [[None]])
    row = data[0][1:] if data else []
    out = []
    for lab, cell in zip(labels, row):
        v = cell[0] if isinstance(cell, list) else cell
        if isinstance(v, (int, float)) and v > 0:
            out.append((app_name(lab), float(v)))
    return sorted(out, key=lambda x: -x[1])[:n]


def sample_series(t0, t1, step=30):
    """표본(30초) 간격에 맞춘 Netdata 시계열 {신호: [(epoch, 값)]} — 한 번에 몇 개 차트만 읽어 `window --with-netdata` 가 그룹별로 평균을 낸다. 실패한 차트는 빠진다."""
    n = max(2, int((t1 - t0) // step))
    out = {}

    def put(name, chart, pick):
        try:
            rows = series(chart, t0, t1, points=n)
        except NetdataError:
            return
        out[name] = [(t, pick(v)) for t, v in rows if pick(v) is not None]
    put("psys_w", "cpu.powercap_intel_rapl_zone_psys", lambda v: next((x for x in v.values() if x is not None), None))
    put("cpu_all_pct", "system.cpu", lambda v: _sum(v, exclude=("idle", "iowait")) if any(x is not None for x in v.values()) else None)
    put("net_rx_kbps", "system.net", lambda v: abs(v["received"]) if v.get("received") is not None else None)
    put("net_tx_kbps", "system.net", lambda v: abs(v["sent"]) if v.get("sent") is not None else None)
    put("disk_read_kibs", "system.io", lambda v: abs(v["reads"]) if v.get("reads") is not None else None)
    put("disk_write_kibs", "system.io", lambda v: abs(v["writes"]) if v.get("writes") is not None else None)
    nv = _find_chart("sensors.temperature_nvme")
    if nv:
        put("nvme_temp_c", nv, lambda v: next((x for x in v.values() if x is not None), None))
    return out


def bucket_mean(points, t, half=15.0):
    """points=[(epoch, 값)] 에서 t 주변(±half 초) 값의 평균. 없으면 None."""
    xs = [v for tt, v in points if abs(tt - t) <= half and v is not None]
    return sum(xs) / len(xs) if xs else None


def chart_list(pattern=""):
    """차트 이름·단위·제목 목록(패턴이 있으면 부분 일치). [(이름, 단위, 제목)] 이름순."""
    p = pattern.lower()
    return sorted((k, v.get("units", ""), v.get("title", "")) for k, v in charts().items() if p in k.lower())


def snapshot(t0, t1, n_apps=8):
    """explain 이 쓰는 한 번의 묶음 조회. Netdata 가 응답하지 않으면 None. 반환 {coverage, signals, apps_cpu, notes}."""
    if not available():
        return None
    try:
        cov = coverage(t0, t1)
    except NetdataError:
        return None
    sig = signals(t0, t1) if cov > 0 else {k: None for k in SIGNALS}
    try:
        apps = top_apps(t0, t1, n_apps) if cov > 0 else []
    except NetdataError:
        apps = []
    return {"coverage": cov, "signals": sig, "apps_cpu": apps}
