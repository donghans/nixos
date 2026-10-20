#!/usr/bin/env python3
"""observectl — 관측 시스템 CLI (사용자 권한). 켜고 끄기, 구간 요약, 타임라인, 깨움 원인 프로파일, A/B 통계.

  observectl status                         상태(수집기 켜짐 여부, 데이터 양, 마지막 표본)
  observectl on [L0|L1] / observectl off           수집 켜기(L0 30초, L1 5초+스레드/IO) / 끄기  (path 유닛이 수집기를 띄우고 내림 — sudo 불필요)
  observectl level <컴포넌트|*> <수준>        이벤트 로그 수준(trace|debug|info|warn|error)을 즉시 변경
  observectl mark <조건> [메모] / --clear     실험 조건 표지(A/B …). 이후 표본이 이 조건으로 묶임
  observectl window [--since 11:00 --until 11:30 --by state|vt|ssid|mark|lid|ac]   그룹별 전력/C-state 요약
  observectl energy [--since 1h --by state|quirks]   누적 계량(charge_now) 기준 평균 전력을 psys·V×I 와 나란히 비교(측정 검증용)
  observectl states [--since 2h]           low/high(깊은 절전 여부) 전환 시각과 지속 시간
  observectl top [--since 30m] [--by cpu|wake|thr|io]   프로세스/스레드 상위
  observectl events [--since 1h --comp displayui --level debug --grep 키워드]   우리 유틸리티 이벤트 로그
  observectl timeline --at 12:09:37 [--span 60]   그 순간 전후의 표본·이벤트·journal·커널 로그를 시간순으로 합침
  observectl wakers [초=10] [--waking]      ftrace 로 CPU 를 깨우는 원인(타이머/하이타이머 함수, IRQ, workqueue)을 센다 (root 작업은 수집기가 대행)
  observectl drmdebug [초=15]               drm.debug 를 잠시 켬(로그는 timeline 으로)
  observectl display                        디스플레이/PMC debugfs 스냅샷(주의: 읽는 것이 디스플레이를 깨워 상태를 바꿀 수 있음)
  observectl ab [--metric psys_w] [--threshold 0.3] [--settle 20]   observectl mark 로 나눈 A/B 구간을 통계로 판정(임계 이상 + 모든 쌍 같은 부호일 때만 '확인')
  observectl hyprtrace on|off               다음 로그인부터 Hyprland TRACE 로그(HYPRLAND_TRACE=1). 켜면 로그/전력에 영향이 있으니 필요할 때만
"""
import argparse, collections, json, os, subprocess, sys, time, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe_core as core
import observe_stats as stats

METRICS = {"psys_w": ("pw", "psys_w"), "pkg_w": ("pw", "pkg_w"), "batt_w": ("pw", "batt_w"), "core_w": ("pw", "core_w"), "uncore_w": ("pw", "uncore_w")}


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
    kc = next((p["cpu"] for p in r.get("proc", []) if p["comm"] == "kmscon"), 0)
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
    if by == "boot":
        return get(s, "dev.boot") or "?"
    if by == "quirks":
        return get(s, "dev.quirks") or "?"
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
        for lst, key in ((g["psys"], "pw.psys_w"), (g["vi"], "pw.batt_w")):
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
    print("(batt 열은 방전 중인 표본만 평균: 충전 중의 전류는 방전 전력이 아님)")
    print(f"{'그룹':<18}{'n':>4}{'batt':>7}{'psys':>7}{'pkg':>6}{'core':>6}{'pc8%':>6}{'pc10%':>6}{'깨어남/s':>9}{'cpu%':>6}")
    for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        wake = mean_of(g, lambda r: sum(p.get("wake", 0) for p in r.get("proc", [])))
        print(f"{str(k)[:17]:<18}{len(g):>4}{fmt(mean_of(g, lambda r: get(r, 'pw.batt_w') if get(r, 'pw.status') == 'Discharging' else None), 7)}{fmt(mean_of(g, lambda r: get(r, 'pw.psys_w')), 7)}{fmt(mean_of(g, lambda r: get(r, 'pw.pkg_w')))}"
              f"{fmt(mean_of(g, lambda r: get(r, 'pw.core_w')))}{fmt(mean_of(g, lambda r: get(r, 'cs.pc8')), 6, 1)}{fmt(mean_of(g, lambda r: get(r, 'cs.pc10')), 6, 1)}{fmt(wake, 9, 0)}{fmt(mean_of(g, lambda r: get(r, 'irq.cpu_busy_pct')), 6, 1)}")


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
    rows = samples(core.parse_when(a.since))
    if not rows:
        sys.exit("표본이 없습니다")
    acc = collections.defaultdict(lambda: [0.0, 0.0, 0])
    if a.by == "thr":
        for r in rows:
            for t in r.get("thr", []):
                k = f"{t['comm']}/{t['thr']}"
                acc[k][0] += t["cpu"]; acc[k][1] += t["wake"]; acc[k][2] += 1
    elif a.by == "io":
        for r in rows:
            for t in r.get("io", []):
                acc[t["comm"]][0] += t["rd_bps"]; acc[t["comm"]][1] += t["wr_bps"]; acc[t["comm"]][2] += 1
    else:
        for r in rows:
            for p in r.get("proc", []):
                k = p["comm"] if not p["exe"] or p["exe"].startswith(p["comm"][:6]) else f"{p['comm']}({p['exe']})"
                acc[k][0] += p["cpu"]; acc[k][1] += p["wake"]; acc[k][2] += 1
    n = len(rows)
    key = (lambda kv: -kv[1][1]) if a.by in ("wake", "io") else (lambda kv: -kv[1][0])
    head = "이름              읽기B/s  쓰기B/s" if a.by == "io" else "이름                          cpu%   깨어남/s  (등장)"
    print(f"표본 {n}개 평균 기준(등장하지 않은 표본은 0 으로 계산) · 정렬 {a.by}\n{head}")
    for k, (c, w, m) in sorted(acc.items(), key=key)[:a.n]:
        print(f"{k[:28]:<28}{c / n:>8.2f}{w / n:>10.1f}   ({m}/{n})")


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


def cmd_ab(a):
    rows = samples(core.parse_when(a.since))
    seg = [(c, g) for c, g in segments(rows, a.settle) if len(g) >= a.min_samples]
    dropped = [(c, len(g)) for c, g in segments(rows, a.settle) if 0 < len(g) < a.min_samples]
    if dropped:
        print(f"(표본 {a.min_samples}개 미만인 짧은 구간 {len(dropped)}개는 제외: {dropped} — 표지 변경 직후의 잔여 표본 등)")
    if len(seg) < 4:
        sys.exit("A/B 구간이 4개 미만입니다. `observectl mark A` … `observectl mark B` … 를 번갈아 두 번 이상 하세요.")
    path = METRICS[a.metric]
    conds = []
    for c, _ in seg:
        if c not in conds:
            conds.append(c)
    ca, cb = conds[0], conds[1]
    A = [mean_of(g, lambda r: get(r, ".".join(path))) for c, g in seg if c == ca]
    B = [mean_of(g, lambda r: get(r, ".".join(path))) for c, g in seg if c == cb]
    # 교대 순서(A B A B)가 아닌 경우를 경고
    order = "".join(c for c, _ in seg)
    st = stats.verdict(A, B, a.threshold)
    invalid = []
    for cond, expect in ((ca, a.expect_a), (cb, a.expect_b)):
        if expect:
            bad, tot = expect_mismatch(seg, cond, expect)
            if bad:
                invalid.append(f"{cond} 구간 표본 {tot}개 중 {bad}개가 기대({expect})와 다름")
    mix = {x.get("state") for _, g in seg for x in g}
    print(f"조건 순서 {order} · {ca}=기준 {cb}=변경 · 지표 {a.metric} · 임계 {a.threshold} W · 구간 시작 {a.settle}초 제외")
    print(f"{ca}: {', '.join(f'{x:.2f}' for x in A)} (평균 {st['mean_a']:.2f}, sd {st['sd_a']:.2f})")
    print(f"{cb}: {', '.join(f'{x:.2f}' for x in B)} (평균 {st['mean_b']:.2f}, sd {st['sd_b']:.2f})")
    ci = st["ci95"]
    print(f"쌍별 {cb}−{ca}: {', '.join(f'{x:+.2f}' for x in st['diffs'])} → 평균 효과 {st['effect']:+.3f} W"
          + (f" · 95% CI [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else " · CI 는 쌍 3개 이상부터") + f" · 부호검정 p={st['sign_p']:.2f}")
    if invalid:
        print("✗ 조건 검증 실패 — 이 시험은 무효입니다: " + "; ".join(invalid))
        print("판정: 무효(조건이 실제로 바뀌지 않음)")
        return
    print(f"판정: {st['verdict']}" + (" (조건 검증 통과)" if a.expect_a or a.expect_b else " (조건 검증 안 함)"))
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
    s = sub.add_parser("window"); s.add_argument("--clean", action="store_true", help="내 세션 활동·빌드가 섞인 표본 제외"); s.add_argument("--since", default="-1h"); s.add_argument("--until"); s.add_argument("--by", default="state", choices=["state", "vt", "ssid", "mark", "lid", "ac", "wifips", "boot", "quirks", "none"]); s.set_defaults(f=cmd_window)
    s = sub.add_parser("energy"); s.add_argument("--clean", action="store_true", help="내 세션 활동·빌드가 섞인 표본 제외"); s.add_argument("--since", default="1h"); s.add_argument("--until"); s.add_argument("--by", default="state", choices=["state", "vt", "ssid", "mark", "lid", "ac", "wifips", "boot", "quirks", "none"]); s.set_defaults(f=cmd_energy)
    s = sub.add_parser("states"); s.add_argument("--since", default="-2h"); s.set_defaults(f=cmd_states)
    s = sub.add_parser("top"); s.add_argument("--since", default="-30m"); s.add_argument("--by", default="wake", choices=["cpu", "wake", "thr", "io"]); s.add_argument("-n", type=int, default=12); s.set_defaults(f=cmd_top)
    s = sub.add_parser("events"); s.add_argument("--since", default="-1h"); s.add_argument("--until"); s.add_argument("--comp"); s.add_argument("--level", default="trace", choices=list(core.LEVELS)); s.add_argument("--grep"); s.set_defaults(f=cmd_events)
    s = sub.add_parser("timeline"); s.add_argument("--at", required=True); s.add_argument("--span", type=float, default=60); s.add_argument("--journal", default="all", choices=["all", "warn", "none"]); s.set_defaults(f=cmd_timeline)
    s = sub.add_parser("wakers"); s.add_argument("sec", nargs="?", type=int, default=10); s.add_argument("--waking", action="store_true"); s.set_defaults(f=cmd_wakers)
    s = sub.add_parser("drmdebug"); s.add_argument("sec", nargs="?", type=int, default=15); s.set_defaults(f=cmd_drmdebug)
    sub.add_parser("display").set_defaults(f=cmd_display)
    s = sub.add_parser("ab"); s.add_argument("--since", default="-3h"); s.add_argument("--metric", default="psys_w", choices=list(METRICS)); s.add_argument("--threshold", type=float, default=0.3); s.add_argument("--settle", type=float, default=20)
    s.add_argument("--min-samples", type=int, default=5, help="구간당 최소 표본 수(미만이면 제외)")
    s.add_argument("--expect-a", help="A 구간 표본의 기대 조건 '경로=값' (예: dev.wifi.ps=off). 다르면 시험 무효"); s.add_argument("--expect-b", help="B 구간 표본의 기대 조건 (예: dev.wifi.ps=on)"); s.set_defaults(f=cmd_ab)
    s = sub.add_parser("hyprtrace"); s.add_argument("mode", choices=["on", "off"]); s.set_defaults(f=cmd_hyprtrace)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
