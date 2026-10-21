#!/usr/bin/env python3
"""observectl — 관측 시스템 CLI (사용자 권한). 켜고 끄기, 구간 요약, 타임라인, 깨움 원인 프로파일, A/B 통계.

  observectl status                         상태(수집기 켜짐 여부, 데이터 양, 마지막 표본)
  observectl on [L0|L1] / observectl off           수집 켜기(L0 30초, L1 5초+스레드/IO) / 끄기  (path 유닛이 수집기를 띄우고 내림 — sudo 불필요)
  observectl level <컴포넌트|*> <수준>        이벤트 로그 수준(trace|debug|info|warn|error)을 즉시 변경
  observectl mark <조건> [메모] / --clear     실험 조건 표지(A/B …). 이후 표본이 이 조건으로 묶임
  observectl window [--since 11:00 --until 11:30 --by state|vt|ssid|mark|lid|ac]   그룹별 전력/C-state 요약
  observectl energy [--since 1h --by state|quirks]   누적 계량(charge_now) 기준 평균 전력을 psys·V×I 와 나란히 비교(측정 검증용)
  observectl states [--since 2h]           low/high(깊은 절전 여부) 전환 시각과 지속 시간
  observectl top [--since 30m] [--by cpu|ctxsw|thr|io]   프로세스/스레드 상위(cpu=코어 1개 기준 %, ctxsw=자발적 문맥 전환/s; wake 는 ctxsw 의 옛 이름)
  observectl events [--since 1h --comp displayui --level debug --grep 키워드]   우리 유틸리티 이벤트 로그
  observectl timeline --at 12:09:37 [--span 60]   그 순간 전후의 표본·이벤트·journal·커널 로그를 시간순으로 합침
  observectl wakers [초=10] [--waking]      ftrace 로 CPU 를 깨우는 원인(타이머/하이타이머 함수, IRQ, workqueue)을 센다 (root 작업은 수집기가 대행)
  observectl drmdebug [초=15]               drm.debug 를 잠시 켬(로그는 timeline 으로)
  observectl display                        디스플레이/PMC debugfs 스냅샷(주의: 읽는 것이 디스플레이를 깨워 상태를 바꿀 수 있음)
  observectl ab [--metric psys_w] [--threshold 0.3] [--settle 20]   observectl mark 로 나눈 A/B 구간을 통계로 판정(임계 이상 + 모든 쌍 같은 부호일 때만 '확인')
  observectl hyprtrace on|off               다음 로그인부터 Hyprland TRACE 로그(HYPRLAND_TRACE=1). 켜면 로그/전력에 영향이 있으니 필요할 때만
"""
import argparse, collections, json, os, re, subprocess, sys, time, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe_core as core
import observe_stats as stats
import observe_explain as ex
import observe_netdata as nd
import observe_query as qy
import observe_tiers as tiers

METRICS = {"psys_w": ("pw", "psys_w"), "pkg_w": ("pw", "pkg_w"), "batt_vi_w": ("pw", "batt_vi_w"), "core_w": ("pw", "core_w"), "uncore_w": ("pw", "uncore_w")}


def samples(since=None, until=None):
    return list(core.iter_jsonl(core.SAMPLE_DIR, "samples", since, until))


def get(s, path):
    for k in path.split("."):
        s = s.get(k) if isinstance(s, dict) else None
    return s


def mean_of(rows, f):
    v = [x for x in (f(r) for r in rows) if isinstance(x, (int, float))]
    return stats.mean(v) if v else float("nan")


def fmt(x, w=6, p=2):
    return f"{x:>{w}.{p}f}" if isinstance(x, (int, float)) and x == x else " " * (w - 1) + "-"


BUSY_COMMS = {"nix-daemon", "nix", "nixos-rebuild", "nixup", ".nixup-wrapped", "cc1", "ld", "rustc"}


def is_clean(r):
    """측정 위생: 내 세션이 화면을 갱신 중(kmscon CPU ≥ 1%)이거나 빌드(nix 등)가 도는 표본은 '한가한 상태' 비교에서 뺀다."""
    kc = next((p["cpu_core_pct"] for p in r.get("proc", []) if p["comm"] == "kmscon"), 0)   # 코어 1개 = 100%
    return kc < 1.0 and not any(p["comm"] in BUSY_COMMS for p in r.get("proc", []))


def group_key(s, by):
    if by == "state":
        return s.get("state", "?")
    if by == "vt":
        return get(s, "dev.vt") or "?"
    if by == "ssid":
        return (get(s, "dev.wifi.ssid") or "?")
    if by == "lid":
        return get(s, "dev.lid") or "?"
    if by == "ac":
        return "AC" if get(s, "pw.ac") else "배터리"
    if by == "mark":
        return (s.get("mark") or {}).get("cond") or "-"
    if by == "flag":
        return s.get("flag") or "-"
    if by == "boot":
        return get(s, "dev.boot") or "?"
    if by == "quirks":
        return get(s, "dev.quirks") or "?"
    if by == "psr":
        return "PSR 켬" if "enabled" in str((get(s, "dev.psr") or {}).get("mode") or "") else "PSR 끔"
    if by == "wifips":
        return get(s, "dev.wifi.ps") or "?"
    return "전체"


def cmd_status(a):
    ctl = core.read_control()
    active = subprocess.run(["systemctl", "is-active", "observe-collector"], capture_output=True, text=True).stdout.strip()
    rows = samples(time.time() - 86400)
    print(f"수집 {'켜짐' if ctl['enabled'] else '꺼짐'} · 수준 {ctl['level']}({ctl['interval_s'].get(ctl['level'])}초) · 수집기 프로세스 {active} · 표지 {ctl.get('mark')}")
    print(f"이벤트 수준: {ctl['components']}")
    n = len(rows)
    last = rows[-1] if rows else None
    print(f"최근 24시간 표본 {n}개" + (f" · 마지막 {core.hms(last['t'])} ({time.time() - last['t']:.0f}초 전) 상태={last.get('state')} psys={get(last, 'pw.psys_w')}W" if last else ""))
    size = sum(os.path.getsize(os.path.join(core.SAMPLE_DIR, f)) for f in os.listdir(core.SAMPLE_DIR)) if os.path.isdir(core.SAMPLE_DIR) else 0
    ev = sum(1 for _ in core.iter_jsonl(core.state_dir(), "events", time.time() - 86400))
    print(f"표본 파일 {size / 1048576:.1f} MiB · 최근 24시간 이벤트 {ev}개 ({core.state_dir()})")


def cmd_on(a):
    ctl = core.write_control({"enabled": True, "level": a.level})
    print(f"수집 켬: {ctl['level']} {ctl['interval_s'][ctl['level']]}초 (수집기는 path 유닛이 몇 초 안에 띄움)")


def cmd_off(a):
    core.write_control({"enabled": False})
    print("수집 끔 (수집기는 15초 뒤 스스로 종료)")


def cmd_level(a):
    if a.level not in core.LEVELS:
        sys.exit(f"수준은 {list(core.LEVELS)} 중 하나")
    core.write_control({"components": {a.component: a.level}})
    print(f"{a.component} → {a.level}")


def cmd_mark(a):
    if a.clear:
        core.write_control({"mark": None})
        print("표지 해제")
        return
    core.write_control({"mark": {"cond": a.cond, "t": round(time.time(), 1), "note": " ".join(a.note)}})
    core.append_jsonl(core.state_dir(), "events", {"t": round(time.time(), 3), "pid": os.getpid(), "comp": "observectl", "lvl": "info", "ev": "mark", "cond": a.cond, "note": " ".join(a.note)})
    print(f"표지: {a.cond} ({core.hms(time.time())})")


def energy_by_group(rows, by, max_gap=90):
    """연속한 표본 쌍(a→b)마다 b 의 그룹에 (방전량 ΔQ, 시간 dt, psys·V×I 평균)을 누적한다. 누적 계량값(q_uah)은 1 mAh 단위라
    짧은 쌍으로는 양자화가 크므로 **그룹 전체를 합산**해서 평균 전력을 낸다. 반환: {그룹: dict(n, hours, coulomb_w, psys_w, vi_w)} (방전 중인 쌍만)."""
    acc = collections.defaultdict(lambda: {"dq": 0.0, "dt": 0.0, "wh": 0.0, "n": 0, "psys": [], "vi": []})
    for a, b in zip(rows, rows[1:]):
        qa, qb = get(a, "pw.q_uah"), get(b, "pw.q_uah")
        va, vb = get(a, "pw.v_uv"), get(b, "pw.v_uv")
        dt = b["t"] - a["t"]
        if None in (qa, qb, va, vb) or not (0 < dt <= max_gap) or get(b, "pw.status") != "Discharging" or get(a, "pw.status") != "Discharging":
            continue
        g = acc[group_key(b, by)]
        dq = qa - qb                                   # µAh (방전이면 양수)
        g["dq"] += dq; g["dt"] += dt; g["n"] += 1
        g["wh"] += dq / 1e6 * ((va + vb) / 2) / 1e6    # Wh
        for lst, key in ((g["psys"], "pw.psys_w"), (g["vi"], "pw.batt_vi_w")):
            x = get(b, key)
            if isinstance(x, (int, float)):
                lst.append(x)
    return {k: {"n": g["n"], "hours": g["dt"] / 3600, "coulomb_w": g["wh"] / (g["dt"] / 3600) if g["dt"] else float("nan"),
                "psys_w": stats.mean(g["psys"]), "vi_w": stats.mean(g["vi"])} for k, g in acc.items() if g["dt"] > 0}


def cmd_energy(a):
    rows = samples(core.parse_when(a.since), core.parse_when(a.until) if a.until else None)
    if a.clean:
        rows = [r for r in rows if is_clean(r)]
    res = energy_by_group(rows, a.by)
    if not res:
        sys.exit("누적 계량값(q_uah)이 있는 방전 표본이 없습니다(수집기를 새 버전으로 재시작한 뒤 쌓인 표본만 가능)")
    print(f"누적 계량 기준 평균 전력 vs psys vs 순간 V×I — 그룹 기준 {a.by} (쌍을 합산하므로 짧은 그룹은 부정확)")
    print(f"{'그룹':<18}{'n':>4}{'시간(분)':>9}{'계량 W':>8}{'psys W':>8}{'V×I W':>8}{'계량−psys':>10}{'V×I−계량':>10}")
    for k, g in sorted(res.items(), key=lambda kv: -kv[1]["hours"]):
        print(f"{str(k)[:17]:<18}{g['n']:>4}{g['hours'] * 60:>9.1f}{fmt(g['coulomb_w'], 8)}{fmt(g['psys_w'], 8)}{fmt(g['vi_w'], 8)}{fmt(g['coulomb_w'] - g['psys_w'], 10)}{fmt(g['vi_w'] - g['coulomb_w'], 10)}")


def cmd_window(a):
    since, until = core.parse_when(a.since), core.parse_when(a.until) if a.until else None
    rows = samples(since, until)
    if a.clean:
        n0 = len(rows)
        rows = [r for r in rows if is_clean(r)]
        print(f"(--clean: 내 세션 활동·빌드 표본 {n0 - len(rows)}개 제외, {len(rows)}개 사용)")
    if not rows:
        sys.exit("표본이 없습니다(observectl on 으로 켠 뒤 시간이 지나야 함)")
    groups = collections.defaultdict(list)
    for r in rows:
        groups[group_key(r, a.by)].append(r)
    print(f"{core.hms(rows[0]['t'])} ~ {core.hms(rows[-1]['t'])} · 표본 {len(rows)}개 · 그룹 기준 {a.by}")
    legacy = sum(1 for r in rows if r.get("legacy"))
    if legacy:
        print(f"(옛 형식 표본 {legacy}개 포함 — 이름만 바뀐 값은 같게 읽음. 단 옛 표본의 프로세스별 자발적 전환은 메인 스레드만이라 멀티스레드 프로세스를 크게 과소 집계해서 '상위전환/s' 열에서 제외함. 용어는 power-evidence.md 정정표)")
    print("(V×I 열은 방전 중인 표본만 평균: 충전 중의 전류는 방전 전력이 아님 · 상위전환/s 는 저장된 상위 프로세스(최대 16행)의 모든 스레드 자발적 문맥 전환 합으로 시스템 전체가 아님 · 전체CPU% 는 전체 CPU 대비(코어 1개=100% 가 아님))")
    print(f"{'그룹':<18}{'n':>4}{'V×I':>7}{'psys':>7}{'pkg':>6}{'core':>6}{'pc8%':>6}{'pc10%':>6}{'상위전환/s':>11}{'전체CPU%':>9}")
    for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        ctxsw_top = mean_of(g, lambda r: None if r.get("legacy") and any("ctxsw_vol_leader_s" in p for p in r.get("proc", [])) else sum(p.get("ctxsw_vol_s", 0) for p in r.get("proc", [])))
        print(f"{str(k)[:17]:<18}{len(g):>4}{fmt(mean_of(g, lambda r: get(r, 'pw.batt_vi_w') if get(r, 'pw.status') == 'Discharging' else None), 7)}{fmt(mean_of(g, lambda r: get(r, 'pw.psys_w')), 7)}{fmt(mean_of(g, lambda r: get(r, 'pw.pkg_w')))}"
              f"{fmt(mean_of(g, lambda r: get(r, 'pw.core_w')))}{fmt(mean_of(g, lambda r: get(r, 'cs.pc8')), 6, 1)}{fmt(mean_of(g, lambda r: get(r, 'cs.pc10')), 6, 1)}{fmt(ctxsw_top, 11, 0)}{fmt(mean_of(g, lambda r: get(r, 'irq.cpu_all_pct')), 9, 1)}")
    if not a.no_netdata and nd.available():
        got = window_netdata_table(groups, rows[0]["t"], rows[-1]["t"] + 30)
        if got:
            keys, res = got
            print("\nNetdata 병기(1초 수집값을 같은 표본 시각에 맞춰 그룹 평균 · 없으면 '-' = 관측 공백)")
            print(f"{'그룹':<18}" + "".join(f"{nd.SIGNALS[k][0] + ' ' + nd.SIGNALS[k][1]:>20}" for k in keys))
            for k in groups:
                print(f"{str(k)[:17]:<18}" + "".join(f"{fmt(v, 20, 1)}" for v in res[k]))


def window_netdata_table(groups, t0, t1, provider=None):
    """window 그룹마다 Netdata 신호의 평균(표본 시각 ±15초 값만 사용). 반환 (헤더 목록, {그룹: [값 또는 None]}) 또는 None(Netdata 없음)."""
    sample = provider or nd.sample_series
    try:
        ser = sample(t0, t1)
    except nd.NetdataError:
        return None
    keys = [k for k in ("net_rx_kbps", "net_tx_kbps", "disk_read_kibs", "disk_write_kibs", "nvme_temp_c") if k in ser]
    if not keys:
        return None
    res = {}
    for k, g in groups.items():
        res[k] = []
        for key in keys:
            xs = [nd.bucket_mean(ser[key], r["t"]) for r in g]
            xs = [x for x in xs if x is not None]
            res[k].append(sum(xs) / len(xs) if xs else None)
    return keys, res


def cmd_query(a):
    t0, t1 = core.parse_when(a.since), core.parse_when(a.until) if a.until else None
    rows = samples(t0, t1)
    if not rows:
        sys.exit("표본이 없습니다(observectl on 으로 켠 뒤 시간이 지나야 함)")
    sigs = a.signal
    nd_series = None
    if any(s.startswith(qy.ND_PREFIX) for s in sigs):
        if not nd.available():
            sys.exit(f"nd: 신호는 Netdata 가 켜져 있어야 합니다({nd.BASE}). 켜져 있는 구간만 값이 있고 나머지는 '-'(관측 공백)입니다.")
        nd_series = nd.sample_series(rows[0]["t"], rows[-1]["t"] + 30)
        bad = [s for s in sigs if s.startswith(qy.ND_PREFIX) and s[len(qy.ND_PREFIX):] not in nd_series]
        if bad:
            sys.exit(f"알 수 없거나 비어 있는 Netdata 신호 {bad} — 가능한 이름: {', '.join(sorted(nd_series))}")
    key = None if a.step or a.by == "none" else (lambda r: group_key(r, a.by))
    try:
        step = qy.parse_step(a.step) if a.step else None
        res = qy.run(rows, sigs, a.agg, step, key, nd_series)
    except ValueError as e:
        sys.exit(str(e))
    legacy = sum(1 for r in rows if r.get("legacy"))
    print(f"{core.hms(rows[0]['t'])} ~ {core.hms(rows[-1]['t'])} · 표본 {len(rows)}개 · 집계 {a.agg} · " + (f"{a.step} 간격" if a.step else f"그룹 {a.by}"))
    if legacy and any(s.startswith(("app:", "proc:")) for s in sigs):
        print(f"(옛 형식 표본 {legacy}개는 앱·프로세스 값이 없거나 메인 스레드만 센 값이라 그 신호에서는 빠짐)")
    print(f"{'구간' if a.step else '그룹':<18}{'n':>5}" + "".join(f"{s[:22]:>24}" for s in sigs))
    for g, n, vals in res:
        label = core.hms(g) if a.step else str(g)[:17]
        print(f"{label:<18}{n:>5}" + "".join(fmt(v, 24, a.digits) for v in vals))


def cmd_states(a):
    rows = samples(core.parse_when(a.since))
    if not rows:
        sys.exit("표본이 없습니다")
    start, cur = rows[0], rows[0].get("state")
    segs = []
    for r in rows[1:]:
        if r.get("state") != cur:
            segs.append((cur, start["t"], r["t"]))
            start, cur = r, r.get("state")
    segs.append((cur, start["t"], rows[-1]["t"]))
    for st, t0, t1 in segs:
        g = [r for r in rows if t0 <= r["t"] <= t1]
        print(f"{core.hms(t0)}~{core.hms(t1)} ({(t1 - t0) / 60:5.1f}분) {st:<7} psys {fmt(mean_of(g, lambda r: get(r, 'pw.psys_w')))} W · VT {get(g[0], 'dev.vt')} · lid {get(g[0], 'dev.lid')} · {get(g[0], 'dev.wifi.ssid') or '-'}")


def cmd_top(a):
    if a.by == "wake":
        print("(--by wake 는 --by ctxsw 의 옛 이름입니다 — 프로세스의 자발적 문맥 전환/s. 시스템 전체 깨움은 `observectl bpf wake`)")
        a.by = "ctxsw"
    rows = samples(core.parse_when(a.since))
    if not rows:
        sys.exit("표본이 없습니다")
    if a.by == "ctxsw":                      # 옛 표본(v1·v2)의 프로세스 전환은 메인 스레드만이라 순위가 왜곡됨 → 제외
        skipped = sum(1 for r in rows if any("ctxsw_vol_leader_s" in p for p in r.get("proc", [])))
        rows = [r for r in rows if not any("ctxsw_vol_leader_s" in p for p in r.get("proc", []))]
        if skipped:
            print(f"(옛 형식 표본 {skipped}개 제외: 프로세스별 자발적 전환이 메인 스레드만이라 멀티스레드 프로세스를 크게 과소 집계했음)")
        if not rows:
            sys.exit("새 형식(모든 스레드 합) 표본이 아직 없습니다 — 수집기가 새 버전으로 쌓은 뒤에 보세요")
    acc = collections.defaultdict(lambda: [0.0, 0.0, 0])
    if a.by == "app":                        # 앱 단위 합계(v4, 전체 프로세스 포함)
        have = [r for r in rows if r.get("apps")]
        if not have:
            sys.exit("앱 단위(v4) 표본이 아직 없습니다 — 수집기가 새 버전으로 쌓은 뒤에 보세요")
        if len(have) < len(rows):
            print(f"(앱 단위 표본 {len(have)}개만 사용, 그 이전 {len(rows) - len(have)}개는 제외)")
        rows = have
        for r in rows:
            for p_ in r["apps"]:
                acc[p_["app"]][0] += p_["cpu_core_pct"]; acc[p_["app"]][1] += p_["ctxsw_vol_s"]; acc[p_["app"]][2] += 1
    elif a.by == "thr":
        for r in rows:
            for t in r.get("thr", []):
                k = f"{t['comm']}/{t['thr']}"
                acc[k][0] += t["cpu_core_pct"]; acc[k][1] += t["ctxsw_vol_s"]; acc[k][2] += 1
    elif a.by == "io":
        for r in rows:
            for t in r.get("io", []):
                acc[t["comm"]][0] += t["rd_bps"]; acc[t["comm"]][1] += t["wr_bps"]; acc[t["comm"]][2] += 1
    else:
        for r in rows:
            for p in r.get("proc", []):
                k = p["comm"] if not p["exe"] or p["exe"].startswith(p["comm"][:6]) else f"{p['comm']}({p['exe']})"
                acc[k][0] += p["cpu_core_pct"]; acc[k][1] += p.get("ctxsw_vol_s", p.get("ctxsw_vol_leader_s", 0)); acc[k][2] += 1
    n = len(rows)
    key = (lambda kv: -kv[1][1]) if a.by in ("ctxsw", "io") else (lambda kv: -kv[1][0])
    head = "이름              읽기B/s  쓰기B/s" if a.by == "io" else ("앱(전체 프로세스 합)          CPU(코어1개=100%)  자발전환/s  (등장)" if a.by == "app" else "이름                      CPU(코어1개=100%)  자발전환/s  (등장)")
    print(f"표본 {n}개 평균 기준(등장하지 않은 표본은 0 으로 계산) · 정렬 {a.by}\n{head}")
    for k, (c, w, m) in sorted(acc.items(), key=key)[:a.n]:
        print(f"{k[:28]:<28}{c / n:>8.2f}{w / n:>16.1f}   ({m}/{n})")


def read_events(a, since, until):
    for e in core.iter_jsonl(core.state_dir(), "events", since, until):
        if a.comp and e.get("comp") != a.comp:
            continue
        if core.LEVELS.get(e.get("lvl"), 2) < core.LEVELS[a.level]:
            continue
        if a.grep and a.grep not in json.dumps(e, ensure_ascii=False):
            continue
        yield e


def fmt_event(e):
    kv = {k: v for k, v in e.items() if k not in ("t", "mono", "pid", "comp", "lvl", "ev")}
    return f"{core.hms(e['t'])}.{int(e['t'] * 1000) % 1000:03d} {e.get('lvl', '?'):<5} {e.get('comp', '?')}: {e.get('ev')} {json.dumps(kv, ensure_ascii=False) if kv else ''}"


def cmd_events(a):
    for e in read_events(a, core.parse_when(a.since), core.parse_when(a.until) if a.until else None):
        print(fmt_event(e))


def cmd_trace(a):
    import observe_trace as tr
    since, until = core.parse_when(a.since), core.parse_when(a.until) if a.until else None
    now = time.time()
    ev = list(read_events(argparse.Namespace(comp=None, level="trace", grep=None), since - 3600, until))   # 시작이 구간 밖인 스팬의 끝을 놓치지 않게 앞쪽을 넉넉히
    spans = [s for s in tr.build_spans(ev) if (s["t1"] or now) >= since and s["t0"] <= (until or now)]
    if a.comp:
        spans = [s for s in spans if s["comp"] == a.comp]
    if a.name:
        spans = [s for s in spans if a.name in s["name"]]
    if a.min_ms:
        spans = [s for s in spans if s["ms"] is None or s["ms"] >= a.min_ms]
    if not spans:
        sys.exit("스팬이 없습니다. 도구에 `observe-emit span-run …` 또는 Events.span() 이 있어야 합니다(observectl events 로 원본 확인)")
    samples = samples_between(since - 60, (until or now) + 60)
    if a.by:
        print(f"{'컴포넌트:이름':<34}{'횟수':>5}{'실패':>5}{'중앙값':>9}{'95%':>9}{'최대':>9}{'평균 Wh':>10}{'합 Wh':>9}{'에너지 n':>9}")
        for r in tr.summarize(spans, samples):
            print(f"{(r['comp'] + ':' + r['name'])[:33]:<34}{r['n']:>5}{r['fail']:>5}{tr.fmt_dur(r['p50']):>9}{tr.fmt_dur(r['p95']):>9}{tr.fmt_dur(r['max']):>9}{fmt(r['wh_mean'], 10, 3)}{fmt(r['wh_sum'], 9, 3)}{r['wh_n']:>9}")
        print("(에너지 = psys W 를 구간에 걸쳐 적분. 표본 간격(30초)보다 짧은 구간은 추정치 — `observectl on L1` 로 5초 간격이면 더 낫다)")
        return
    groups = tr.traces(spans)
    pick = sorted(groups.items(), key=lambda kv: kv[1][0]["t0"])
    if a.trace:
        pick = [(k, v) for k, v in pick if k.startswith(a.trace)]
    pick = pick[-a.n:]
    for tid, sp in pick:
        root = sp[0]
        print(f"== trace {tid}  {core.hms(root['t0'])}  스팬 {len(sp)}개")
        for line in tr.render_trace(sp, samples, a.width, now):
            print(line)
        print()


def samples_between(t0, t1):
    return list(core.iter_jsonl(core.SAMPLE_DIR, "samples", t0, t1))


def _span_events(since, until):
    ev = list(read_events(argparse.Namespace(comp=None, level="trace", grep=None), since - 3600, until))
    import observe_trace as tr
    return tr.build_spans(ev)


def cmd_explain(a):
    now = time.time()
    if a.at:
        center = core.parse_when(a.at)
        t0, t1 = center - a.span / 2, center + a.span / 2
    else:
        t0, t1 = core.parse_when(a.since), core.parse_when(a.until) if a.until else now
    if t1 <= t0:
        sys.exit("구간이 비었습니다(--since/--until 확인)")
    if a.baseline == "none":
        base = None
    elif a.baseline == "prev":
        base = (t0 - (t1 - t0), t0)
    else:
        x, _, y = a.baseline.partition("..")
        if not y:
            sys.exit("--baseline 은 none | prev | 시작..끝 (예: 10:00..10:30)")
        base = (core.parse_when(x), core.parse_when(y))
    lo = min(t0, base[0] if base else t0)
    rows = samples(lo - 60, t1 + 60)
    if not rows:
        sys.exit("표본이 없습니다(observectl on 으로 켠 뒤 시간이 지나야 함)")
    provider = None if a.no_netdata else (lambda x, y: nd.snapshot(x, y))
    res = ex.build(rows, _span_events(lo, t1), t0, t1, base, provider)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, default=str, indent=1))
        return
    print("\n".join(ex.render(res, core.hms)))


def _dur_seconds(text):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", str(text).strip())
    if not m:
        sys.exit("--for 는 10m, 90s, 1h 같은 형식(최대 60분)")
    return float(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2]]


def cmd_ebpf(a):
    if a.action == "tiers":
        print("시간 제한형 eBPF 정밀 모드의 단계(2026-10-21 실측, 코어 1개 기준 — 장부 #61). 기본 수집(L0, 30초, 스레드 정확)은 약 0.5% 이고 이 모드는 그 위에 얹힌다.")
        for k, t in tiers.TIERS.items():
            print(f"  {k:<7}{t['label']:<12}비용 {t['cost']}\n          정확성 {t['accuracy']} · 얻는 것: {t['gives']}")
        print(f"안전장치: --for 로 제한 시간(최대 {tiers.MAX_MINUTES}분) 뒤 자동 종료, counts·full 은 시스템 전환이 초당 {tiers.GUARD_SW_PER_S} 를 넘으면 스스로 멈춤.")
        return
    ctl = core.read_control()
    if a.action == "off":
        core.write_control({"ebpf": None})
        print("정밀 모드를 껐습니다(수집기가 다음 반복에서 bpftrace 를 끝냅니다).")
        return
    if a.action == "on":
        if a.tier not in tiers.TIERS:
            sys.exit(f"단계는 {'|'.join(tiers.TIERS)} 중 하나")
        if not ctl.get("enabled"):
            sys.exit("수집이 꺼져 있습니다 — 먼저 `observectl on` 으로 켜세요(정밀 모드는 수집 표본에 합쳐집니다)")
        secs = min(_dur_seconds(a.for_), tiers.MAX_MINUTES * 60)
        until = time.time() + secs
        core.write_control({"ebpf": {"tier": a.tier, "until": until}})
        t = tiers.TIERS[a.tier]
        print(f"정밀 모드 {a.tier}({t['label']}) 를 {secs / 60:.0f}분 동안 켭니다 — 비용 {t['cost']}, 정확성 {t['accuracy']}. {core.hms(until)} 에 자동으로 꺼집니다.")
        return
    e = ctl.get("ebpf")
    now = time.time()
    if e and float(e.get("until", 0)) > now:
        print(f"켜짐: {e['tier']} — {(float(e['until']) - now) / 60:.1f}분 남음 ({core.hms(float(e['until']))} 까지)")
    else:
        print("꺼짐")
    last = [r for r in samples(now - 600) if r.get("ebpf")]
    if last:
        r = last[-1]["ebpf"]
        print(f"최근 집계 {core.hms(last[-1]['t'])} ({r['tier']}, {r['dt']}초):")
        for p in r["procs"][:5]:
            print("   " + " · ".join(f"{k}={v}" for k, v in p.items()))
    stopped = [r for r in samples(now - 3600) if r.get("ebpf_stopped")]
    if stopped:
        print(f"⚠ 스스로 멈춤({core.hms(stopped[-1]['t'])}): {stopped[-1]['ebpf_stopped']}")


def cmd_nd(a):
    if a.what == "charts":
        if not nd.available(ttl=0):
            sys.exit(f"Netdata 가 응답하지 않습니다({nd.BASE})")
        lst = nd.chart_list(a.chart or "")
        print(f"차트 {len(lst)}개" + (f" (이름에 '{a.chart}' 포함)" if a.chart else "") + " — 이름 · 단위 · 제목")
        for name, unit, title in lst[:a.n if a.chart else a.n]:
            print(f"  {name:<52}{unit:<14}{title[:60]}")
        if len(lst) > a.n:
            print(f"  … {len(lst) - a.n}개 더 (-n 으로 늘리거나 이름 조각으로 좁히세요)")
        return
    if a.what == "get":
        if not a.chart:
            sys.exit("차트 이름이 필요합니다: observectl nd get <차트> [--since 30m] (이름은 `nd charts <조각>`)")
        if not nd.available(ttl=0):
            sys.exit(f"Netdata 가 응답하지 않습니다({nd.BASE})")
        t0, t1 = core.parse_when(a.since), core.parse_when(a.until) if a.until else time.time()
        info = nd.charts().get(a.chart)
        if not info:
            sys.exit(f"차트 '{a.chart}' 없음 — `observectl nd charts {a.chart.split('.')[0]}` 로 찾아보세요")
        rows = nd.series(a.chart, t0, t1, points=a.n)
        print(f"{a.chart} [{info.get('units', '')}] {info.get('title', '')}\n{core.hms(t0)} ~ {core.hms(t1)} · {len(rows)}점(구간 평균) · None='관측 공백'")
        dims = list(rows[0][1]) if rows else []
        print(f"{'시각':<10}" + "".join(f"{d[:16]:>18}" for d in dims))
        for t, v in rows:
            print(f"{core.hms(t):<10}" + "".join(f"{'공백' if v[d] is None else format(v[d], '.2f'):>18}" for d in dims))
        return
    if a.what == "defs":
        print(f"Netdata 어댑터가 가져오는 신호(정의는 실제 API 메타데이터로 교차 검증) — 주소 {nd.BASE}")
        for k, (label, unit, d) in nd.SIGNALS.items():
            print(f"  {k:<16}{label} [{unit}]\n      {d}")
        print(f"  (앱 그룹) {nd.APPS_NOTE}")
        print("\n일부러 가져오지 않는 것: 앱별 자발적 문맥 전환(app.*_cpu_context_switches) — Netdata 가 /proc/<pid>/status 의 메인 스레드 값만 읽어 멀티스레드 앱을 크게 과소 집계함.")
        print("앱별 전환이 필요하면 `observectl bpf wake`(시스템 전체 sched_waking)나 thread_top.py(스레드 단위)를 쓴다.")
        return
    if not nd.available(ttl=0):
        sys.exit(f"Netdata 가 응답하지 않습니다({nd.BASE}) — 켜져 있어야 이 명령이 동작합니다. observectl 의 나머지 분석은 Netdata 없이도 됩니다.")
    t0, t1 = core.parse_when(a.since), core.parse_when(a.until) if a.until else time.time()
    if a.what == "stats":
        snap = nd.snapshot(t0, t1, 0)
        print(f"Netdata {core.hms(t0)} ~ {core.hms(t1)} · 이 구간 데이터 {snap['coverage'] * 100:.0f}%")
        for k, v in snap["signals"].items():
            label, unit, _ = nd.SIGNALS[k]
            print(f"  {label:<20}{'관측 공백' if v is None else f'{v:.2f}':>12} {unit}")
    else:
        print(f"Netdata 앱 그룹 CPU(코어 1개=100%) {core.hms(t0)} ~ {core.hms(t1)}")
        for name, v in nd.top_apps(t0, t1, a.n):
            print(f"  {name:<30}{v:>8.2f}")


def journal(since, until, mode):
    if mode == "none":
        return []
    cmd = ["journalctl", "--no-pager", "-o", "json", "-q", "--since", f"@{since}", "--until", f"@{until}"]
    if mode == "warn":
        cmd += ["-p", "warning"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        ident = j.get("SYSLOG_IDENTIFIER", "?")
        msg = j.get("MESSAGE", "")
        if isinstance(msg, list):
            msg = "(바이너리)"
        if mode == "all" and ident in ("tailscaled", "netdata", "redsocks", "otel-plugin.org", "sudo", "systemd-resolved") and j.get("PRIORITY", "6") > "4":
            continue
        res.append((int(j["__REALTIME_TIMESTAMP"]) / 1e6, f"journal {ident}: {str(msg)[:170]}"))
    return res


def cmd_timeline(a):
    at = core.parse_when(a.at)
    t0, t1 = at - a.span, at + a.span
    items = []
    for s in samples(t0, t1):
        items.append((s["t"], f"표본  {s.get('state')} psys {get(s, 'pw.psys_w')} pkg {get(s, 'pw.pkg_w')} pc10 {get(s, 'cs.pc10')} VT {get(s, 'dev.vt')} lid {get(s, 'dev.lid')} wifi {get(s, 'dev.wifi.ssid')}"))
    ns = argparse.Namespace(comp=None, level="trace", grep=None)
    for e in read_events(ns, t0, t1):
        items.append((e["t"], "이벤트 " + fmt_event(e)[13:]))
    items += journal(t0, t1, a.journal)
    for t, line in sorted(items):
        print(f"{core.hms(t)}{'  <<<' if abs(t - at) < 1 else ''} {line}")
    if not items:
        print("해당 구간에 기록이 없습니다")


def request(typ, args, wait):
    rid = f"{typ}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    os.makedirs(core.REQ_DIR, exist_ok=True)
    with open(os.path.join(core.REQ_DIR, rid + ".json"), "w") as f:
        json.dump({"id": rid, "type": typ, "args": args}, f)
    path = os.path.join(core.RES_DIR, rid + ".json")
    end = time.time() + wait
    while time.time() < end:
        if os.path.exists(path):
            return json.load(open(path))
        time.sleep(0.5)
    sys.exit("수집기가 응답하지 않음(observe-collector.path 유닛이 켜져 있는지, `systemctl status observe-collector` 확인)")


def _tbl(rows, cols):
    """rows(dict 목록)를 (제목, 키, 너비, 정렬) 열로 출력."""
    print("  ".join(f"{t:<{w}}" if al == "<" else f"{t:>{w}}" for t, _k, w, al in cols))
    for r in rows:
        print("  ".join((f"{str(r.get(k, ''))[:w]:<{w}}" if al == "<" else f"{str(r.get(k, ''))[:w]:>{w}}") for _t, k, w, al in cols))


def cmd_bpf(a):
    r = request("bpf", {"preset": a.preset, "sec": a.sec, "comm": a.comm, "n": a.n}, a.sec + 40)
    if not r.get("ok"):
        sys.exit(f"오류: {r.get('error')}")
    res = r["data"]                                  # 수집기가 {id, type, ok, data|error, t_start, t_end} 로 감싸 돌려준다
    if res.get("error"):
        sys.exit(f"오류: {res['error']}")
    if res.get("rc"):
        print(f"(bpftrace 종료 코드 {res['rc']}: {res.get('stderr', '').strip()[-200:]})")
    s = res["summary"]
    print(f"== bpf {a.preset} {res['sec']}초" + (f" (comm={a.comm})" if a.comm else ""))
    if a.preset == "wake":
        print(f"깨움 합계 {s['total']}회 ({s['total'] / res['sec']:.0f}/s)\n[깨우는 쪽]")
        _tbl(s["by_waker"], [("comm", "comm", 22, "<"), ("횟수", "count", 8, ">"), ("/s", "per_s", 8, ">")])
        print("[깨어나는 쪽]")
        _tbl(s["by_wakee"], [("comm", "comm", 22, "<"), ("횟수", "count", 8, ">"), ("/s", "per_s", 8, ">")])
        print("[쌍]")
        _tbl(s["pairs"], [("깨우는 쪽", "waker", 22, "<"), ("깨어나는 쪽", "wakee", 22, "<"), ("횟수", "count", 8, ">"), ("/s", "per_s", 8, ">")])
    elif a.preset == "profile":
        print(f"샘플 {s['samples']}개 ({s['hz']}Hz)\n[프로세스별 CPU 비율]")
        _tbl(s["cpu"], [("comm", "comm", 22, "<"), ("샘플", "count", 8, ">"), ("%", "pct", 7, ">")])
        print("[커널 맨 위 함수]")
        _tbl(s["kernel_leaf"], [("comm", "comm", 20, "<"), ("함수", "frame", 44, "<"), ("%", "pct", 7, ">")])
        print("[사용자 맨 위 함수]")
        _tbl(s["user_leaf"], [("comm", "comm", 20, "<"), ("함수", "frame", 44, "<"), ("%", "pct", 7, ">")])
    elif a.preset == "psr":
        print(f"i915 PSR ({s['sec']}초): flush {s['psr_flush']}회 · invalidate {s.get('psr_invalidate', '?')}회 · exit {s['psr_exit']}회 · activate {s['psr_activate']}회")
        print("[화면 갱신(drm atomic 커밋)을 일으킨 프로세스]")
        _tbl(s["atomic_ioctl"], [("comm", "comm", 22, "<"), ("횟수", "count", 8, ">"), ("/s", "per_s", 8, ">")])
        print("(flush = 화면 갱신(플립) 횟수이고 위 표가 그 원인 프로세스. 이 기기(PSR1)에서는 갱신이 잦아도 invalidate/exit/activate 가 0 으로 나왔다 — PSR 에 들어가 있는 시간 비율은 이 카운터가 아니라 usageui 의 PSR 싱크 active 로 본다)")
    elif a.preset == "io":
        _tbl(s["rows"], [("comm", "comm", 22, "<"), ("요청", "count", 8, ">"), ("/s", "per_s", 8, ">"), ("바이트", "bytes", 12, ">")])
    elif a.preset == "net":
        _tbl(s["rows"], [("comm", "comm", 22, "<"), ("tcp 송신", "tcp_send", 9, ">"), ("tcp 수신", "tcp_recv", 9, ">"), ("udp 송신", "udp_send", 9, ">"), ("udp 수신", "udp_recv", 9, ">"), ("/s", "per_s", 8, ">")])
    elif a.preset == "exec":
        print(f"프로세스 {s['processes']}개 생성 ({s['forks_per_s']}/s)")
        _tbl(s["by_comm"], [("comm", "comm", 22, "<"), ("생성", "count", 7, ">"), ("/s", "per_s", 7, ">"), ("CPU ms", "cpu_ms", 10, ">"), ("수명 합 ms", "wall_ms", 12, ">")])
        print("[자식을 많이 만든 부모]")
        _tbl(s["top_parents"], [("pid", "pid", 8, ">"), ("comm", "comm", 20, "<"), ("자식", "children", 7, ">")])
        ev = res.get("events") or []
        if ev and not a.no_spans:
            for e in ev:
                core.append_jsonl(core.state_dir(), "events", e, t=e["t"])
            print(f"\n프로세스 스팬 {len(ev) // 2}개를 이벤트 로그에 적었습니다 → observectl trace --comp bpf --since {max(60, a.sec + 60)}s")


def cmd_wakers(a):
    r = request("wakers", {"sec": a.sec, "waking": a.waking}, a.sec + 30)
    if not r.get("ok"):
        sys.exit(r.get("error"))
    d = r["data"]
    print(f"{d['sec']}초 동안 총 {d['total']}건 ({d['total'] / d['sec']:.0f}/s)")
    for title, k in (("타이머 콜백(timer)", "timer"), ("하이타이머 콜백(hrtimer)", "hrtimer"), ("IRQ 핸들러", "irq"), ("workqueue 함수", "work"), ("깨우는 쪽(sched_waking)", "waker")):
        if d.get(k):
            print(f"\n== {title}")
            for x in d[k][:12]:
                print(f"  {x['per_s']:>7.1f}/s  {x['count']:>6}  {x['key']}")


def cmd_drmdebug(a):
    r = request("drmdebug", {"sec": a.sec}, a.sec + 30)
    print(json.dumps(r.get("data") or r, ensure_ascii=False))
    if r.get("ok"):
        print(f"로그: observectl timeline --at {core.hms((r['data']['from'] + r['data']['to']) / 2)} --span {a.sec} --journal all")


def cmd_display(a):
    print("주의: 읽는 순간 디스플레이가 깨어나 낮은 절전 상태가 깨질 수 있음", file=sys.stderr)
    r = request("display", {}, 30)
    d = r.get("data") or {}
    for k in ("package_cstate", "display_info", "power_domains"):
        print(f"== {k}\n{d.get(k, '')[:3000]}")


def segments(rows, settle):
    """표지(mark.t)가 같은 연속 표본을 한 구간으로 묶고, 표지 직후 settle 초는 버린다. [(조건, [표본…]), …]"""
    segs = []
    for r in rows:
        m = r.get("mark")
        if not m or not m.get("cond"):
            continue
        if segs and segs[-1][2] == m.get("t"):
            segs[-1][1].append(r)
        else:
            segs.append([m["cond"], [r], m.get("t")])
    return [(c, [r for r in g if r["t"] >= (t or 0) + settle]) for c, g, t in segs]


def expect_mismatch(seg, cond, expect):
    """구간 목록(seg)에서 조건 cond 의 표본 중 기대값("경로=값", 예: dev.wifi.ps=off)과 다른 개수와 전체 개수.
    A/B 조건을 실제로 바꿨는지 검증하는 용도 — 스크립트가 조건을 못 바꿨는데 통계만 내는 일을 막는다."""
    path, _, want = expect.partition("=")
    bad = tot = 0
    for c, g in seg:
        if c == cond:
            for r in g:
                tot += 1
                bad += str(get(r, path)) != want
    return bad, tot


segment_coulomb = ex.coulomb_w          # 구간의 누적 계량 평균 전력(W)과 양자화 오차(W) — 구현은 observe_explain 한 곳


AB_METRICS = ["psys_w", "pkg_w", "batt_vi_w", "coulomb_w"]
AB_LABELS = {"psys_w": "psys(RAPL, 약 1 W 누락)", "pkg_w": "패키지(RAPL)", "batt_vi_w": "순간 V×I", "coulomb_w": "누적 계량",
             "nd_psys_w": "Netdata psys(1초)", "nd_pkg_w": "Netdata 패키지(1초)", "nd_batt_vi_w": "Netdata V×I(1초)"}
ND_AB = {"nd_psys_w": "psys_w", "nd_pkg_w": "pkg_w", "nd_batt_vi_w": "batt_vi_w"}   # ab 지표 → 어댑터 신호
ND_MIN_COVERAGE = 0.9           # 구간에서 Netdata 데이터가 이 비율 미만이면 그 구간은 "관측 공백"(값 없음)


def netdata_segment_values(seg, provider=None):
    """구간마다 Netdata 1초 평균 {지표: 값 또는 None}. 구간 일부만 Netdata 가 켜져 있었으면(커버리지 미만) 없음으로 둔다.
    표본은 30초 간격이라 구간 끝에 한 간격을 더해 마지막 표본이 대표하는 시간까지 포함한다."""
    provider = provider or (lambda x, y: nd.snapshot(x, y, 0))
    snaps = [provider(g[0]["t"], g[-1]["t"] + 30) if g else None for _, g in seg]
    if not any(snaps):                       # 어댑터가 아예 응답하지 않음 → 호출자가 "응답 없음"으로 안내
        return None
    res = []
    for snap in snaps:
        if not snap or snap["coverage"] < ND_MIN_COVERAGE:
            res.append({k: None for k in ND_AB})
        else:
            res.append({k: snap["signals"].get(v) for k, v in ND_AB.items()})
    return res


def ab_checks(seg, allow):
    """교란 자동 검증. 덮개·AC 가 구간들 사이에서 다르면 무효(allow 로 허용), Wi-Fi SSID 가 다르면 경고. 반환 (무효 사유 목록, 경고 목록)."""
    bad, warn = [], []
    for name, path, hard in (("lid", "dev.lid", True), ("ac", "pw.ac", True), ("ssid", "dev.wifi.ssid", False)):
        if name in allow:
            continue
        vals = collections.Counter(str(get(r, path)) for _, g in seg for r in g)
        if len(vals) > 1:
            msg = f"{name} 값이 구간에 따라 다름 {dict(vals)}"
            (bad if hard else warn).append(msg)
    return bad, warn


def ab_rows(seg, ca, cb, metrics, threshold, ndv=None):
    """지표마다 (이름, A 구간값, B 구간값, 판정 dict, 신뢰 표시, 신뢰 가능 여부). ndv = netdata_segment_values 결과."""
    out = []
    for m in metrics:
        if m in ND_AB:                       # 쌍이 어긋나지 않게, 한 구간이라도 공백이면 이 지표는 판정하지 않는다
            vals = [d[m] for d in (ndv or [])]
            gaps = [f"{c}#{i + 1}" for i, ((c, _), v) in enumerate(zip(seg, vals)) if v is None]
            if not ndv or gaps:
                out.append((m, [], [], None, "(관측 공백: Netdata 가 꺼져 있던 구간 " + ", ".join(gaps) + " — 그 구간은 값이 없어 쌍을 만들 수 없음)" if ndv else "(Netdata 응답 없음)", False))
                continue
            A = [v for (c, _), v in zip(seg, vals) if c == ca]
            B = [v for (c, _), v in zip(seg, vals) if c == cb]
            if min(len(A), len(B)) < 2:
                out.append((m, A, B, None, "(값 부족)", False))
                continue
            out.append((m, A, B, stats.verdict(A, B, threshold), "Netdata 1초 평균", True))
            continue
        per = []
        for c, g in seg:
            if m == "coulomb_w":
                w, err = segment_coulomb(g)
                per.append((c, w, err, len(g)))
            else:
                per.append((c, mean_of(g, lambda r: get(r, ".".join(METRICS[m]))), None, len(g)))
        A = [w for c, w, _, _ in per if c == ca and w is not None and w == w]
        B = [w for c, w, _, _ in per if c == cb and w is not None and w == w]
        n = min(len(A), len(B))
        if n < 2:
            out.append((m, A, B, None, "(값 부족: 방전 중 구간이 필요)", False))
            continue
        v = stats.verdict(A, B, threshold)
        if m == "coulomb_w":
            err = max(e for c, w, e, _ in per if e is not None)
            ok = err <= threshold / 2
            note = f"오차 ±{err:.2f} W" + ("" if ok else " — 구간이 짧아 신뢰 낮음(5분 이상 권장)")
        elif m == "batt_vi_w":
            k = min(nn for _, _, _, nn in per)
            ok = k >= 8
            note = f"구간당 표본 {k}개" + ("" if ok else " — 순간값이라 노이즈 큼, 신뢰 낮음")
        else:
            ok, note = True, ""
        out.append((m, A, B, v, note, ok))
    return out


def confounders(seg, min_abs=10.0, ratio=3.0):
    """구간들에서 **한 구간에서만 CPU 가 튄 앱**(교란 의심). 반환 [(구간 번호, 앱, 그 구간 CPU, 다른 구간 중앙값)].
    앱 CPU = 코어 1개=100%. 튄 기준: 중앙값보다 min_abs 이상 크고 ratio 배 이상. 조건(A/B)을 바꾼 효과와 무관한 부하(브라우저 탭·빌드 등)가 한 구간을 오염시켰는지 잡는다."""
    per = []
    for _, g in seg:
        got = ex.apps_table(g)
        per.append({k: v["cpu"] for k, v in got[0].items()} if got else {})
    apps = set().union(*per) if per else set()
    out = []
    for app in apps:
        vals = [p.get(app, 0.0) for p in per]
        for i, v in enumerate(vals):
            others = sorted(vals[:i] + vals[i + 1:])
            med = others[len(others) // 2] if others else 0.0
            if v - med >= min_abs and v >= ratio * max(med, 0.5):
                out.append((i, app, v, med))
    return sorted(out)


def exclude_pairs(table, seg, ca, cb, flagged, threshold):
    """교란 구간이 든 쌍(같은 순번의 A·B)을 빼고 다시 판정. 반환 [(지표, 남은 쌍 수, 판정 dict 또는 None)]."""
    pos = {}
    cnt = {ca: 0, cb: 0}
    for i, (c, _) in enumerate(seg):
        pos[i] = (c, cnt[c])
        cnt[c] += 1
    bad_pairs = {pos[i][1] for i in flagged if i in pos}
    out = []
    for m, A, B, v, note, ok in table:
        if v is None or not ok:
            continue
        keep = [k for k in range(min(len(A), len(B))) if k not in bad_pairs]
        out.append((m, len(keep), stats.verdict([A[k] for k in keep], [B[k] for k in keep], threshold) if len(keep) >= 2 else None))
    return out


def cmd_ab(a):
    if a.metric == "batt_w":
        a.metric = "batt_vi_w"
    rows = samples(core.parse_when(a.since), core.parse_when(a.until) if a.until else None)
    seg = [(c, g) for c, g in segments(rows, a.settle) if len(g) >= a.min_samples]
    dropped = [(c, len(g)) for c, g in segments(rows, a.settle) if 0 < len(g) < a.min_samples]
    if dropped:
        print(f"(표본 {a.min_samples}개 미만인 짧은 구간 {len(dropped)}개는 제외: {dropped} — 표지 변경 직후의 잔여 표본 등)")
    if len(seg) < 4:
        sys.exit("A/B 구간이 4개 미만입니다. `observectl mark A` … `observectl mark B` … 를 번갈아 두 번 이상 하세요.")
    conds = []
    for c, _ in seg:
        if c not in conds:
            conds.append(c)
    ca, cb = conds[0], conds[1]
    order = "".join(c for c, _ in seg)
    allow = {x for x in (a.allow_mixed or "").split(",") if x}
    invalid, warn = [], []
    bad, w = ab_checks(seg, allow)
    invalid += bad
    warn += w
    # 짧아서 버려진 구간·안정화 구간에서 덮개/AC 가 달랐다면 시험 도중 조건이 바뀐 흔적(예: 중간에 덮개를 엶) — 경고
    used = {name: {str(get(r, path)) for _, g in seg for r in g} for name, path in (("lid", "dev.lid"), ("ac", "pw.ac"))}
    everything = [r for _, g in segments(rows, 0) for r in g]
    for name, path in (("lid", "dev.lid"), ("ac", "pw.ac")):
        extra = {str(get(r, path)) for r in everything} - used[name]
        if extra and name not in allow:
            warn.append(f"버려진 짧은 구간/안정화 구간에서 {name} 값이 {sorted(extra)} 로 달랐음 — 시험 도중 조건이 바뀐 흔적(해당 구간은 통계에서 빠짐)")
    for cond, expect in ((ca, a.expect_a), (cb, a.expect_b)):
        if expect:
            nbad, tot = expect_mismatch(seg, cond, expect)
            if nbad:
                invalid.append(f"{cond} 구간 표본 {tot}개 중 {nbad}개가 기대({expect})와 다름")
    for req in a.require or []:
        nbad = tot = 0
        path, _, want = req.partition("=")
        for _, g in seg:
            for r in g:
                tot += 1
                nbad += str(get(r, path)) != want
        if nbad:
            invalid.append(f"--require {req}: 표본 {tot}개 중 {nbad}개가 다름")
    metrics = AB_METRICS if a.metric == "all" else [a.metric]
    ndv = None
    if a.metric == "all" and not a.no_netdata or a.metric in ND_AB:
        ndv = netdata_segment_values(seg)
        if a.metric == "all":
            metrics = metrics + list(ND_AB)
    table = ab_rows(seg, ca, cb, metrics, a.threshold, ndv)
    n_in = [len(g) for _, g in seg]
    print(f"조건 순서 {order} · {ca}=기준 {cb}=변경 · 구간 {len(seg)}개(구간당 표본 {min(n_in)}~{max(n_in)}개) · 임계 {a.threshold} W · 구간 시작 {a.settle}초 제외")
    checks = ["덮개·AC 가 전 구간 동일" if not any(x.startswith(("lid", "ac")) for x in invalid) else None]
    print("자동 검증: " + (" · ".join(x for x in checks if x) or "✗ 교란 발견") + ("" if not (a.expect_a or a.expect_b or a.require) else " · 사용자 조건(--expect/--require) 적용"))
    for x in warn:
        print(f"⚠ {x}")
    print(f"{'지표':<24}{ca + ' 구간값':<26}{cb + ' 구간값':<26}{'쌍별 ' + cb + '−' + ca:<22}{'효과':>8}  판정 / 신뢰")
    for m, A, B, v, note, ok in table:
        if v is None:
            print(f"{AB_LABELS.get(m, m):<24}{note}")
            continue
        print(f"{AB_LABELS.get(m, m):<24}{' '.join(f'{x:.2f}' for x in A):<26}{' '.join(f'{x:.2f}' for x in B):<26}{' '.join(f'{x:+.2f}' for x in v['diffs']):<22}{v['effect']:>+8.2f}  {v['verdict']}" + (f"  [{note}]" if note else ""))
    conf = confounders(seg)
    if conf:
        print("⚠ 교란 의심 — 한 구간에서만 CPU 가 튄 앱(조건 변경과 무관한 부하일 수 있음):")
        for i, app, v, med in conf[:6]:
            print(f"    구간 {i + 1}({seg[i][0]}) {app} CPU {v:.0f}% (다른 구간 중앙값 {med:.1f}%)")
        redo = exclude_pairs(table, seg, ca, cb, {i for i, *_ in conf}, a.threshold)
        if redo:
            print("  → 교란 구간이 든 쌍을 뺀 재계산:")
            for m, n, v in redo:
                print(f"    {AB_LABELS.get(m, m):<24}" + (f"쌍 {n}개 효과 {v['effect']:+.2f} W  {v['verdict']}  (쌍별 {' '.join(f'{x:+.2f}' for x in v['diffs'])})" if v else f"쌍 {n}개 — 판정하기엔 부족"))
    if invalid:
        print("✗ 조건 검증 실패 — 이 시험은 무효입니다: " + "; ".join(invalid))
        print("종합: 무효(조건이 실제로 바뀌지 않았거나 다른 교란이 있음)")
        return
    usable = [(m, v) for m, _, _, v, _, ok in table if v is not None and ok]
    signs = {(-1 if v["effect"] < 0 else 1) for _, v in usable}
    labels = {v["verdict"] for _, v in usable}
    if not usable:
        overall = "판정 불가(신뢰할 수 있는 지표가 없음: 구간을 늘리세요)"
    elif len(signs) > 1:
        overall = "불확실 — 신뢰 가능한 지표끼리 부호가 다름: " + ", ".join(f"{AB_LABELS.get(m, m)} {v['effect']:+.2f}" for m, v in usable)
    elif labels == {"확인(측정)"}:
        overall = "확인(측정)"
    elif labels <= {"확인(측정)", "일치(약함, 2쌍)"}:
        overall = "일치(약함) — 같은 방향이나 쌍이 적음(3쌍 이상 필요)"
    else:
        overall = "불확실"
    low = [AB_LABELS.get(m, m) for m, _, _, v, _, ok in table if v is not None and not ok]
    print(f"종합: {overall}" + (f"   (신뢰 낮아 제외한 지표: {', '.join(low)})" if low else ""))
    mix = {x.get("state") for _, g in seg for x in g}
    if len(mix - {None, "unknown"}) > 1:
        print("⚠ 측정 구간에 low/high 상태가 섞여 있음 — 효과가 상태 전환에 가려질 수 있으니 `observectl window --by state` 로 확인하세요.")
    if order not in ("ABAB", "ABABAB", "BABA", "BABABA") and len(set(conds)) == 2:
        print(f"⚠ 구간 순서가 {order} — 교대(ABAB)가 아니면 드리프트와 구분되지 않습니다.")


def cmd_hyprtrace(a):
    path = os.path.expanduser("~/.config/uwsm/env-hyprland")
    begin, end = "# observe-managed begin", "# observe-managed end"
    txt = open(path).read() if os.path.exists(path) else ""
    if begin in txt:
        txt = txt[:txt.index(begin)] + txt[txt.index(end) + len(end) + 1:] if end in txt else txt[:txt.index(begin)]
    if a.mode == "on":
        txt = txt.rstrip("\n") + ("\n" if txt.strip() else "") + f"{begin}\nexport HYPRLAND_TRACE=1\n{end}\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(txt)
    print(f"Hyprland TRACE {a.mode}: 다음 로그인부터 적용 ({path}). 로그는 journal(uwsm_hyprland…)로 감 — 로그량 때문에 전력 측정과 동시에 켜지 말 것")


def main(argv=None):
    p = argparse.ArgumentParser(prog="observectl", description="관측 시스템")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(f=cmd_status)
    s = sub.add_parser("on"); s.add_argument("level", nargs="?", default="L0", choices=["L0", "L1"]); s.set_defaults(f=cmd_on)
    sub.add_parser("off").set_defaults(f=cmd_off)
    s = sub.add_parser("level"); s.add_argument("component"); s.add_argument("level"); s.set_defaults(f=cmd_level)
    s = sub.add_parser("mark"); s.add_argument("cond", nargs="?", default=""); s.add_argument("note", nargs="*"); s.add_argument("--clear", action="store_true"); s.set_defaults(f=cmd_mark)
    s = sub.add_parser("window"); s.add_argument("--no-netdata", action="store_true", help="Netdata 병기 표를 뺀다"); s.add_argument("--clean", action="store_true", help="내 세션 활동·빌드가 섞인 표본 제외"); s.add_argument("--since", default="-1h"); s.add_argument("--until"); s.add_argument("--by", default="state", choices=["state", "vt", "ssid", "mark", "lid", "ac", "wifips", "psr", "boot", "quirks", "flag", "none"]); s.set_defaults(f=cmd_window)
    s = sub.add_parser("energy"); s.add_argument("--clean", action="store_true", help="내 세션 활동·빌드가 섞인 표본 제외"); s.add_argument("--since", default="1h"); s.add_argument("--until"); s.add_argument("--by", default="state", choices=["state", "vt", "ssid", "mark", "lid", "ac", "wifips", "psr", "boot", "quirks", "flag", "none"]); s.set_defaults(f=cmd_energy)
    s = sub.add_parser("states"); s.add_argument("--since", default="-2h"); s.set_defaults(f=cmd_states)
    s = sub.add_parser("top"); s.add_argument("--since", default="-30m"); s.add_argument("--by", default="ctxsw", choices=["cpu", "ctxsw", "wake", "thr", "io", "app"], help="ctxsw=자발적 문맥 전환/s, cpu=코어 1개 기준 CPU%%. wake 는 ctxsw 의 옛 이름"); s.add_argument("-n", type=int, default=12); s.set_defaults(f=cmd_top)
    s = sub.add_parser("events"); s.add_argument("--since", default="-1h"); s.add_argument("--until"); s.add_argument("--comp"); s.add_argument("--level", default="trace", choices=list(core.LEVELS)); s.add_argument("--grep"); s.set_defaults(f=cmd_events)
    s = sub.add_parser("trace", help="스팬(구간) 폭포 · 구간별 에너지 · 이름별 요약"); s.add_argument("--since", default="-1h"); s.add_argument("--until"); s.add_argument("--comp"); s.add_argument("--name", help="이름에 포함된 글자"); s.add_argument("--min-ms", type=float, default=0); s.add_argument("--trace", help="트레이스 id 앞부분"); s.add_argument("-n", type=int, default=5, help="폭포로 보여 줄 최근 트레이스 수"); s.add_argument("--width", type=int, default=110); s.add_argument("--by", action="store_true", help="폭포 대신 이름별 요약표(횟수·소요·에너지)"); s.set_defaults(f=cmd_trace)
    s = sub.add_parser("explain", help="한 구간을 여러 출처(전력·상태·시스템·Netdata·프로세스·포커스·스팬)로 묶어 설명하고 기준 구간과 비교"); s.add_argument("--since", default="30m"); s.add_argument("--until"); s.add_argument("--at", help="중심 시각(HH:MM 등) — --span 초 만큼의 구간"); s.add_argument("--span", type=float, default=300); s.add_argument("--baseline", default="prev", help="none | prev(바로 앞의 같은 길이, 기본) | 시작..끝"); s.add_argument("--no-netdata", action="store_true"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_explain)
    s = sub.add_parser("ebpf", help="시간 제한형 eBPF 정밀 모드: tiers(단계·비용) | on <sample|counts|full> [--for 10m] | off | status"); s.add_argument("action", choices=["tiers", "on", "off", "status"]); s.add_argument("tier", nargs="?"); s.add_argument("--for", dest="for_", default="10m", help="제한 시간(기본 10m, 최대 60분)"); s.set_defaults(f=cmd_ebpf)
    s = sub.add_parser("query", help="범용 조회: 신호 여러 개를 시간 간격(--step)이나 그룹(--by)으로 묶어 집계(--agg). 신호 = 별칭(psys pkg vi core uncore pc8 pc10 cpu_all) · 표본 경로(pw.psys_w) · app:<앱>.cpu|ctxsw · proc:<comm>.cpu|ctxsw · nd:<Netdata 신호>"); s.add_argument("signal", nargs="+"); s.add_argument("--since", default="1h"); s.add_argument("--until"); s.add_argument("--step", help="시간 간격(예: 5m). 없으면 --by 로 묶음"); s.add_argument("--by", default="none", choices=["state", "vt", "ssid", "mark", "lid", "ac", "wifips", "psr", "boot", "quirks", "flag", "none"]); s.add_argument("--agg", default="mean", choices=list(qy.AGGS)); s.add_argument("--digits", type=int, default=2); s.set_defaults(f=cmd_query)
    s = sub.add_parser("nd", help="Netdata 어댑터(있을 때만): defs=신호 정의, stats=구간 평균, apps=앱 그룹 CPU, charts=차트 찾기, get=차트 값"); s.add_argument("what", choices=["defs", "stats", "apps", "charts", "get"]); s.add_argument("chart", nargs="?", help="charts: 이름 조각 · get: 차트 이름"); s.add_argument("--since", default="10m"); s.add_argument("--until"); s.add_argument("-n", type=int, default=10); s.set_defaults(f=cmd_nd)
    s = sub.add_parser("timeline"); s.add_argument("--at", required=True); s.add_argument("--span", type=float, default=60); s.add_argument("--journal", default="all", choices=["all", "warn", "none"]); s.set_defaults(f=cmd_timeline)
    s = sub.add_parser("bpf", help="eBPF(bpftrace) 프리셋을 N초 동안 실행: exec wake profile psr io net"); s.add_argument("preset", choices=["exec", "wake", "profile", "psr", "io", "net"]); s.add_argument("sec", nargs="?", type=int, default=10); s.add_argument("--comm", help="프로세스 이름 필터(영숫자·._- 15자)"); s.add_argument("-n", type=int, default=12, help="표의 상위 행 수"); s.add_argument("--no-spans", action="store_true", help="exec: 프로세스 스팬을 이벤트 로그에 적지 않음"); s.set_defaults(f=cmd_bpf)
    s = sub.add_parser("wakers"); s.add_argument("sec", nargs="?", type=int, default=10); s.add_argument("--waking", action="store_true"); s.set_defaults(f=cmd_wakers)
    s = sub.add_parser("drmdebug"); s.add_argument("sec", nargs="?", type=int, default=15); s.set_defaults(f=cmd_drmdebug)
    sub.add_parser("display").set_defaults(f=cmd_display)
    s = sub.add_parser("ab", help="번갈아(ABAB) 측정 판정: 기본은 psys·패키지·순간 V×I·누적 계량을 한꺼번에 비교하고 지표끼리 어긋나면 알림"); s.add_argument("--since", default="-3h"); s.add_argument("--until", help="이 시각까지만(앞뒤에 다른 시험이 이어 붙어 있을 때)"); s.add_argument("--metric", default="all", choices=["all"] + list(METRICS) + ["coulomb_w", "batt_w"] + list(ND_AB), help="all=네 지표 모두(기본). batt_w 는 batt_vi_w(순간 V×I)의 옛 이름"); s.add_argument("--threshold", type=float, default=0.3); s.add_argument("--settle", type=float, default=20)
    s.add_argument("--min-samples", type=int, default=5, help="구간당 최소 표본 수(미만이면 제외)")
    s.add_argument("--expect-a", help="A 구간 표본의 기대 조건 '경로=값' (예: dev.wifi.ps=off). 다르면 시험 무효"); s.add_argument("--expect-b", help="B 구간 표본의 기대 조건 (예: dev.wifi.ps=on)")
    s.add_argument("--require", action="append", help="모든 구간의 모든 표본이 만족해야 하는 조건 '경로=값'(여러 번 가능, 예: --require dev.lid=closed)")
    s.add_argument("--no-netdata", action="store_true", help="Netdata 1초 지표를 비교에서 뺀다"); s.add_argument("--allow-mixed", help="구간 사이에 달라도 되는 항목(쉼표: lid,ac,ssid). 기본은 덮개·AC 가 다르면 무효, SSID 가 다르면 경고"); s.set_defaults(f=cmd_ab)
    s = sub.add_parser("hyprtrace"); s.add_argument("mode", choices=["on", "off"]); s.set_defaults(f=cmd_hyprtrace)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
