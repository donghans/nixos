"""observe_fleet — 여러 호스트(데스크톱·노트북)의 관측 요약을 공유 저장소(claude_ctx 의 Postgres)에 올려 서로 비교한다.

왜: 한 호스트의 기록만으로는 「이게 정상인가」를 모른다. 같은 앱이 노트북에서만 높거나, 한쪽에만 설치된 확장이 있으면 시험 전에 후보로 뽑을 수 있다
(2026-10-26 노트북 Vivaldi 의 번호 0 확장(비밀번호 관리자)의 서비스 워커 60초 주기 활동 — 데스크톱엔 없는 확장이었다, 장부 #133).
무엇을 올리나(요약만, 개인정보 없음): 시간별 앱 평균 CPU·자발적 문맥 전환(앱 이름 = observe 표본의 app), 시간별 평균 전력, 브라우저 확장 설치 목록(프로필 폴더 이름·확장 ID·버전·서비스 워커 유무 — 확장 이름·창 제목·주소는 올리지 않음).
접속은 claude_ctx.dsn() 과 같은 규칙(환경변수 > 서버 머신의 unix 소켓 > tailnet 이름). 표본 원본·프로세스 목록은 올리지 않는다.
표는 mods/_tools/claude-ctx/schema.sql 에 있다(observe_app_hourly·observe_power_hourly·observe_ext_inventory). 올리기는 멱등(같은 시간·앱은 덮어쓴다)."""
import glob, json, os, re, socket, subprocess, sys, time

HOUR = 3600
MIN_DELTA = 0.3          # 코어 1개=100% 기준 %p — 이보다 작은 차이는 비교하지 않는다
RATIO = 3.0              # 한쪽이 다른 쪽의 몇 배 이상이면 「한쪽에서만 높음」


def host():
    return os.environ.get("OBSERVE_FLEET_HOST") or socket.gethostname()


def dsn():
    d = os.environ.get("CLAUDE_CTX_DSN")
    if d:
        return d
    if os.path.exists("/run/postgresql/.s.PGSQL.5432"):
        return "host=/run/postgresql dbname=claude_ctx user=claude_ctx"
    return f"host={os.environ.get('CLAUDE_CTX_SERVER', 'beelink-ser7-co')} port=5432 dbname=claude_ctx user=claude_ctx"


def connect(timeout=5):
    import psycopg                      # observectl 래퍼가 psycopg 가 있는 파이썬으로 실행해야 한다(없으면 안내 후 종료)
    return psycopg.connect(dsn(), connect_timeout=timeout, autocommit=False)


# ------------------------------------------------------------------ 집계(순수 함수 — DB 없이 시험)
def hourly(rows):
    """observe 표본 목록 → (앱 집계, 전력 집계).
    앱: {(시각, 앱): [cpu 합, ctxsw 합, 표본 수]} — 그 시간의 모든 표본 수로 나눠야 평균(그 시간에 안 나온 표본은 0)이므로 시간별 전체 표본 수를 따로 둔다.
    전력: {시각: [psys 합, psys 수, pkg 합, pkg 수, 전체 표본 수]}. 시각 = 그 시간 정각(epoch 초)."""
    apps, power, total = {}, {}, {}
    for r in rows:
        t = r.get("t")
        if not isinstance(t, (int, float)):
            continue
        h = int(t // HOUR * HOUR)
        total[h] = total.get(h, 0) + 1
        for a in r.get("apps") or []:
            k = (h, a.get("app"))
            if not k[1]:
                continue
            v = apps.setdefault(k, [0.0, 0.0])
            v[0] += a.get("cpu_core_pct") or 0.0
            v[1] += a.get("ctxsw_vol_s") or 0.0
        pw = r.get("pw") or {}
        p = power.setdefault(h, [0.0, 0, 0.0, 0])
        if isinstance(pw.get("psys_w"), (int, float)):
            p[0] += pw["psys_w"]; p[1] += 1
        if isinstance(pw.get("pkg_w"), (int, float)):
            p[2] += pw["pkg_w"]; p[3] += 1
    app_rows = [(h, app, round(c / total[h], 3), round(x / total[h], 1), total[h]) for (h, app), (c, x) in apps.items()]
    power_rows = [(h, round(p[0] / p[1], 3) if p[1] else None, round(p[2] / p[3], 3) if p[3] else None, total[h]) for h, p in power.items()]
    return app_rows, power_rows


def ext_inventory(roots):
    """크로미움 계열 브라우저 프로필 폴더들 → [{browser, profile, ext_id, version, has_sw}]. roots = [(브라우저 이름, 데이터 폴더)].
    프로필 폴더 이름(Default·Profile 1)과 확장 ID·버전·서비스 워커 유무만 읽는다(manifest 의 이름·권한·주소는 읽어도 올리지 않는다)."""
    out = []
    for browser, root in roots:
        for prof in sorted(glob.glob(os.path.join(root, "Default")) + glob.glob(os.path.join(root, "Profile *"))):
            for ext in sorted(glob.glob(os.path.join(prof, "Extensions", "*"))):
                vers = sorted(glob.glob(os.path.join(ext, "*", "manifest.json")))
                if not vers:
                    continue
                try:
                    m = json.load(open(vers[-1]))
                except (OSError, ValueError):
                    continue
                bg = m.get("background") if isinstance(m.get("background"), dict) else {}
                out.append({"browser": browser, "profile": os.path.basename(prof), "ext_id": os.path.basename(ext),
                            "version": str(m.get("version", ""))[:32], "has_sw": bool(bg.get("service_worker"))})
    return out


# ------------------------------------------------------------------ 교차 호스트 인사이트용 요약(포커스·변경 구간·주기 활동·상시 유닛)
def focus_hourly(spans):
    """포커스 스팬(comp=windows, 이름 focus:<앱>) → [(시각, 앱, 초)] — 스팬이 시간 경계를 넘으면 나눈다. 아직 열려 있는 스팬은 뺀다. 창 제목은 애초에 기록되지 않는다."""
    acc = {}
    for s in spans:
        if s.get("comp") != "windows" or not str(s.get("name", "")).startswith("focus:") or s.get("t1") is None:
            continue
        app, t, end = s["name"][6:], s["t0"], s["t1"]
        while t < end:
            h = int(t // HOUR * HOUR)
            seg = min(end, h + HOUR) - t
            acc[(h, app)] = acc.get((h, app), 0.0) + seg
            t += seg
    return [(h, a, round(v, 1)) for (h, a), v in acc.items()]


def change_spans(spans):
    """nixup 전체 실행 구간(최상위 `nixup:run`) → [(t0, t1, 종류, 세부, 상태)]. 끝나지 않은 것은 뺀다."""
    return [(s["t0"], s["t1"], "nixup", str((s.get("attrs") or {}).get("sub", "")), s.get("status", "ok"))
            for s in spans if s.get("comp") == "nixup" and s.get("name") == "run" and s.get("t1") is not None]


def periodic_rows(events):
    """`browser.periodic` 이벤트 → [(시각, 계열, 주기 초, 상관, 튐 %p, 평균 %)]."""
    return [(e["t"], e.get("series", "?"), e.get("period_s"), e.get("corr"), e.get("burst_over_mean_pct"), e.get("mean_pct"))
            for e in events if e.get("ev") == "browser.periodic" and e.get("period_s") is not None]


UNIT_SKIP = re.compile(r"^(run-|session-|user@|user-runtime-dir@|dbus-:|systemd-.*@)")


def norm_unit(name):
    """유닛 이름에서 호스트마다 다른 인스턴스 해시(@197af3ef 등)를 @* 로 줄인다. 일시 유닛(run-·session-)은 None."""
    if UNIT_SKIP.match(name):
        return None
    return re.sub(r"@[0-9a-f]{6,}", "@*", name)


def running_units():
    """지금 active 인 서비스·타이머 이름만 [(범위, 유닛)] — user 와 system 둘 다(읽기 전용 systemctl)."""
    out = []
    for scope, args in (("user", ["--user"]), ("system", [])):
        try:
            r = subprocess.run(["systemctl", *args, "list-units", "--type=service,timer", "--state=active", "--no-legend", "--plain"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in r.stdout.splitlines():
            n = norm_unit(line.split()[0]) if line.split() else None
            if n:
                out.append((scope, n))
    return sorted(set(out))


def norm_key(name):
    """앱 이름 대응용 열쇠: 포커스 앱(창 클래스, 예 vivaldi-stable)과 프로세스 앱(vivaldi-bin)을 첫 토큰으로 맞춘다."""
    return re.split(r"[-._ ]+", (name or "").lower().lstrip("."))[0]


def change_effects(apps_by_host, host, t0, t1, window_h=2, min_delta=MIN_DELTA, ratio=2.0):
    """변경(nixup) 전후 `window_h` 시간(시간 경계로 맞춘 온전한 시간들)의 앱 평균 CPU 변화와 같은 시각 다른 호스트(대조군)의 변화를 비교한다.
    apps_by_host = {호스트: {시각: {앱: cpu}}}. 반환 (늘어남, 줄어듦, 사유) — 각 [(앱, 전, 후, 변화, 대조군 변화 또는 None)] 변화 큰 순, 사유는 판정 못 한 이유(None 이면 판정함).
    늘어남 = 변화 ≥ min_delta·후 ≥ ratio×전 이면서 대조군 변화가 변화의 절반 미만. 줄어듦은 반대 방향 같은 기준."""
    mine = apps_by_host.get(host) or {}
    h0 = int(t0 // HOUR * HOUR)
    h1 = int(-(-t1 // HOUR) * HOUR)
    before = [h0 - HOUR * k for k in range(window_h, 0, -1)]
    after = [h1 + HOUR * k for k in range(window_h)]
    if any(h not in mine for h in before + after):
        return [], [], f"전후 {window_h}시간 데이터가 아직 다 올라와 있지 않음(변경 뒤 {window_h}시간이 지나고 올려야 함)"

    def mean(d, hours):
        apps = {}
        for h in hours:
            for a, v in (d.get(h) or {}).items():
                apps[a] = apps.get(a, 0.0) + v
        return {a: v / len(hours) for a, v in apps.items()}

    mb, ma = mean(mine, before), mean(mine, after)
    ctrl = [(o, d) for o, d in apps_by_host.items() if o != host and all(h in d for h in before + after)]
    cb, ca = ({}, {})
    for _, d in ctrl:
        for k, v in mean(d, before).items():
            cb[k] = cb.get(k, 0.0) + v / len(ctrl)
        for k, v in mean(d, after).items():
            ca[k] = ca.get(k, 0.0) + v / len(ctrl)
    up, down = [], []
    for app in set(mb) | set(ma):
        b, a_ = mb.get(app, 0.0), ma.get(app, 0.0)
        d = a_ - b
        cd = (ca.get(app, 0.0) - cb.get(app, 0.0)) if ctrl else None
        row = (app, round(b, 2), round(a_, 2), round(d, 2), None if cd is None else round(cd, 2))
        if d >= min_delta and a_ >= ratio * max(b, 0.1) and (cd is None or cd < d / 2):
            up.append(row)
        elif -d >= min_delta and b >= ratio * max(a_, 0.1) and (cd is None or cd > d / 2):
            down.append(row)
    return sorted(up, key=lambda r: -r[3]), sorted(down, key=lambda r: r[3]), None


def priority(focus_secs, ref_means, target_means, min_delta=MIN_DELTA, focus_min=1.0):
    """교차 호스트 우선순위(순수). focus_secs={포커스 앱: 초}(사용자가 실제로 쓰는 호스트의 것), ref/target_means={앱: (cpu, ctxsw)}.
    반환 (포커스 앱 목록, 배경 목록, 사용 비중 상위) — 포커스 앱은 [(앱, 포커스 %, 대상 cpu, 기준 cpu, 초과)] 포커스 큰 순(끌 수 없고 고쳐 써야 하는 것),
    배경은 포커스 비중이 focus_min% 미만인 앱 중 대상이 기준보다 min_delta 이상 높은 것 [(앱, 대상 cpu, 기준 cpu, 초과)] 초과 큰 순(끄거나 줄일 수 있는 것)."""
    tot = sum(focus_secs.values()) or 1.0
    share = {}
    for app, sec in focus_secs.items():
        share[norm_key(app)] = share.get(norm_key(app), 0.0) + sec * 100 / tot
    names = {}
    for app in set(ref_means) | set(target_means):
        names.setdefault(norm_key(app), []).append(app)
    fg, bg, used = [], [], set()
    for k, pct in sorted(share.items(), key=lambda kv: -kv[1]):
        apps = names.get(k, [])
        tc = sum(target_means.get(a, (0.0, 0.0))[0] for a in apps)
        rc = sum(ref_means.get(a, (0.0, 0.0))[0] for a in apps)
        if pct >= focus_min:
            fg.append((k, round(pct, 1), round(tc, 2), round(rc, 2), round(tc - rc, 2)))
            used.add(k)
    for k, apps in names.items():
        if k in used:
            continue
        tc = sum(target_means.get(a, (0.0, 0.0))[0] for a in apps)
        rc = sum(ref_means.get(a, (0.0, 0.0))[0] for a in apps)
        if tc - rc >= min_delta:
            bg.append((sorted(apps)[0], round(tc, 2), round(rc, 2), round(tc - rc, 2)))
    mix = [(k, round(p, 1)) for k, p in sorted(share.items(), key=lambda kv: -kv[1])[:6]]
    return fg, sorted(bg, key=lambda r: -r[3]), mix


def units_only(units_by_host):
    """호스트 하나에만 있는 상시 유닛 → [(호스트, 범위, 유닛)] (units_by_host = {호스트: {(범위, 유닛)}})."""
    out = []
    for h, s in units_by_host.items():
        for u in s:
            if all(u not in o for hh, o in units_by_host.items() if hh != h):
                out.append((h, u[0], u[1]))
    return sorted(out)


# ------------------------------------------------------------------ 올리기 기록(실패해도 쌓아 뒀다 다음에 같이)
STATE_NAME = "fleet-push.json"
FIRST_SPAN = 26 * HOUR        # 처음 올릴 때(기록 없음) 되돌아볼 기간
MAX_BACK = 14 * 24 * HOUR     # 로컬 표본 보존 기간(14일) — 그보다 앞은 어차피 없다
OVERLAP = 2 * HOUR            # 마지막 성공 시각 앞쪽을 겹쳐 다시 올린다(그 시간의 부분 집계가 덮어써짐)


def state_path():
    import observe_core as core
    return os.path.join(core.state_dir(), STATE_NAME)


def read_state(path=None):
    try:
        with open(path or state_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_state(st, path=None):
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, path)


def since_for(st, now, first=FIRST_SPAN, max_back=MAX_BACK, overlap=OVERLAP):
    """이번에 올릴 표본의 시작 시각과 밀린 시간. 마지막 **성공** 시각(last_ok)에서 overlap 만큼 앞부터 — 실패한 동안의 표본이 다음 성공 때 함께 올라간다.
    반환 (시작 epoch 초, 밀린 초 또는 None(처음)). 로컬 보존 기간(max_back)보다 앞으로는 가지 않는다."""
    ok = st.get("last_ok")
    if not isinstance(ok, (int, float)):
        return now - first, None
    return max(ok - overlap, now - max_back), max(0.0, now - ok)


def record(st, now, ok, rows=None, error=None):
    """올리기 시도 결과를 상태에 반영(성공이면 last_ok 갱신·오류 지움, 실패면 오류만 남기고 last_ok 는 그대로)."""
    st = dict(st)
    st["last_try"] = now
    if ok:
        st["last_ok"] = now; st["rows"] = rows; st.pop("error", None)
    else:
        st["error"] = (error or "")[:200]
    return st


# ------------------------------------------------------------------ 올리기
LAST_SKIPPED = []      # 마지막 push 에서 표가 없어 건너뛴 인사이트 표 이름


def push(conn, hostname, app_rows, power_rows, inv, extra=None):
    """멱등 올리기. 같은 (호스트, 시각, 앱)은 덮어쓴다(부분 시간이 다음 올리기에 채워짐). 확장 목록은 호스트별로 통째로 교체한다."""
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO observe_app_hourly (host, hour, app, cpu_core_pct, ctxsw_vol_s, samples) VALUES (%s, to_timestamp(%s), %s, %s, %s, %s) "
                        "ON CONFLICT (host, hour, app) DO UPDATE SET cpu_core_pct = EXCLUDED.cpu_core_pct, ctxsw_vol_s = EXCLUDED.ctxsw_vol_s, samples = EXCLUDED.samples",
                        [(hostname, h, app, c, x, n) for h, app, c, x, n in app_rows])
        cur.executemany("INSERT INTO observe_power_hourly (host, hour, psys_w, pkg_w, samples) VALUES (%s, to_timestamp(%s), %s, %s, %s) "
                        "ON CONFLICT (host, hour) DO UPDATE SET psys_w = EXCLUDED.psys_w, pkg_w = EXCLUDED.pkg_w, samples = EXCLUDED.samples",
                        [(hostname, h, ps, pk, n) for h, ps, pk, n in power_rows])
        if inv is not None:
            cur.execute("DELETE FROM observe_ext_inventory WHERE host = %s", (hostname,))
            cur.executemany("INSERT INTO observe_ext_inventory (host, browser, profile, ext_id, version, has_sw) VALUES (%s, %s, %s, %s, %s, %s)",
                            [(hostname, e["browser"], e["profile"], e["ext_id"], e["version"], e["has_sw"]) for e in inv])
    # 교차 호스트 인사이트용 표(schema v5)는 서버가 아직 nixup 전이면 없을 수 있다 — 그래도 기본 요약(앱·전력·확장)은 올라가야 하므로 표별로 세이브포인트에 담아 없으면 건너뛴다
    LAST_SKIPPED.clear()
    ex = extra or {}
    jobs = [("focus", "observe_focus_hourly", "INSERT INTO observe_focus_hourly (host, hour, app, seconds) VALUES (%s, to_timestamp(%s), %s, %s) ON CONFLICT (host, hour, app) DO UPDATE SET seconds = EXCLUDED.seconds",
             lambda r: (hostname, r[0], r[1], r[2])),
            ("changes", "observe_changes", "INSERT INTO observe_changes (host, t0, t1, kind, detail, status) VALUES (%s, to_timestamp(%s), to_timestamp(%s), %s, %s, %s) ON CONFLICT (host, t0, kind) DO UPDATE SET t1 = EXCLUDED.t1, detail = EXCLUDED.detail, status = EXCLUDED.status",
             lambda r: (hostname, r[0], r[1], r[2], r[3], r[4])),
            ("periodic", "observe_periodic", "INSERT INTO observe_periodic (host, t, series, period_s, corr, burst_pct, mean_pct) VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
             lambda r: (hostname, r[0], r[1], r[2], r[3], r[4], r[5]))]
    for key, table, sql, mk in jobs:
        if not ex.get(key):
            continue
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany(sql, [mk(r) for r in ex[key]])
        except Exception as e:
            if type(e).__name__ != "UndefinedTable":
                raise
            LAST_SKIPPED.append(table)
    if ex.get("units") is not None:
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("DELETE FROM observe_units WHERE host = %s", (hostname,))
                cur.executemany("INSERT INTO observe_units (host, scope, unit) VALUES (%s, %s, %s)", [(hostname, sc, u) for sc, u in ex["units"]])
        except Exception as e:
            if type(e).__name__ != "UndefinedTable":
                raise
            LAST_SKIPPED.append("observe_units")
    conn.commit()
    return len(app_rows), len(power_rows), len(inv or [])


# ------------------------------------------------------------------ 비교
def host_means(conn, hostname, days):
    """최근 days 일 동안 호스트의 앱별 평균 CPU(코어 1개=100%)·평균 ctxsw/s — 시간별 표본 수로 가중(그 시간에 안 나온 앱은 0). 반환 ({앱: (cpu, ctxsw)}, 표본 수)."""
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(sum(samples), 0) FROM observe_power_hourly WHERE host = %s AND hour >= now() - make_interval(days => %s)", (hostname, days))
        total = int(cur.fetchone()[0])
        cur.execute("SELECT app, sum(cpu_core_pct * samples), sum(ctxsw_vol_s * samples) FROM observe_app_hourly "
                    "WHERE host = %s AND hour >= now() - make_interval(days => %s) GROUP BY app", (hostname, days))
        rows = cur.fetchall()
    return ({app: (c / total, x / total) for app, c, x in rows} if total else {}), total


def compare_means(ma, mb, min_delta=MIN_DELTA, ratio=RATIO):
    """두 호스트의 {앱: (cpu, ctxsw)} 비교(순수 함수). 반환 [(앱, a_cpu, b_cpu, a_ctx, b_ctx, 표시)] — a 가 b 보다 높은 쪽 우선, 차이 큰 순.
    표시: 'a만' = b 에 없음 · 'a↑' = a 가 b 의 ratio 배 이상 · 'b↑' 같은 반대 방향은 b 를 기준으로 다시 부르면 된다."""
    out = []
    for app in set(ma) | set(mb):
        ac, ax = ma.get(app, (0.0, 0.0))
        bc, bx = mb.get(app, (0.0, 0.0))
        if ac - bc < min_delta:
            continue
        flag = "a만" if app not in mb else ("a↑" if ac >= ratio * max(bc, 0.1) else "")
        if flag:
            out.append((app, ac, bc, ax, bx, flag))
    return sorted(out, key=lambda r: -(r[1] - r[2]))


def inventory(conn):
    """호스트별 확장 목록 → {호스트: {(브라우저, 확장 ID): (프로필들, 버전, 서비스 워커 유무)}}."""
    with conn.cursor() as cur:
        cur.execute("SELECT host, browser, ext_id, string_agg(profile, ',' ORDER BY profile), max(version), bool_or(has_sw) FROM observe_ext_inventory GROUP BY host, browser, ext_id")
        rows = cur.fetchall()
    inv = {}
    for h, b, e, profs, ver, sw in rows:
        inv.setdefault(h, {})[(b, e)] = (profs, ver, sw)
    return inv


def inventory_diff(inv):
    """호스트 하나에만 있는 확장(서비스 워커가 있으면 표시) → [(호스트, 브라우저, ID, 프로필, 버전, sw)]."""
    out = []
    hosts = list(inv)
    for h in hosts:
        for key, (profs, ver, sw) in inv[h].items():
            if all(key not in inv[o] for o in hosts if o != h):
                out.append((h, key[0], key[1], profs, ver, sw))
    return sorted(out, key=lambda r: (r[0], not r[5], r[2]))


# ------------------------------------------------------------------ 화면(usageui 호스트 탭)용 내보내기
def export(conn, me, days=3, top=40):
    """usageui 가 읽는 JSON(사전): 호스트별 시간별 전력, 앱 평균, 표본 수, 한 호스트에만 있는 확장. TUI 는 psycopg 가 없는 파이썬이라 observectl 가 대신 읽어 JSON 으로 준다."""
    with conn.cursor() as cur:
        cur.execute("SELECT host, extract(epoch FROM hour)::bigint, psys_w, pkg_w, samples FROM observe_power_hourly WHERE hour >= now() - make_interval(days => %s) ORDER BY host, hour", (days,))
        power = {}
        for h, t, ps, pk, n in cur.fetchall():
            power.setdefault(h, []).append([int(t), ps, pk, n])
    hosts = sorted(power)
    means, samples = {}, {}
    for h in hosts:
        m, n = host_means(conn, h, days)
        samples[h] = n
        means[h] = {a: [round(v[0], 3), round(v[1], 1)] for a, v in sorted(m.items(), key=lambda kv: -kv[1][0])[:top]}
    return {"version": 1, "fetched": int(time.time()), "days": days, "me": me, "hosts": hosts, "power": power, "means": means, "samples": samples,
            "inventory_diff": [list(r) for r in inventory_diff(inventory(conn))]}


# ------------------------------------------------------------------ 조회(교차 호스트 인사이트)
def fetch_apps_hourly(conn, days):
    """{호스트: {시각(epoch): {앱: cpu}}} — 시간별 앱 평균 CPU(전체 표본 대비)."""
    with conn.cursor() as cur:
        cur.execute("SELECT host, extract(epoch FROM hour)::bigint, app, cpu_core_pct FROM observe_app_hourly WHERE hour >= now() - make_interval(days => %s)", (days,))
        out = {}
        for h, t, a, c in cur.fetchall():
            out.setdefault(h, {}).setdefault(int(t), {})[a] = c
        cur.execute("SELECT host, extract(epoch FROM hour)::bigint FROM observe_power_hourly WHERE hour >= now() - make_interval(days => %s)", (days,))
        for h, t in cur.fetchall():
            out.setdefault(h, {}).setdefault(int(t), {})           # 앱이 하나도 없던 시간도 「데이터 있음」으로
    return out


def fetch_changes(conn, days):
    with conn.cursor() as cur:
        cur.execute("SELECT host, extract(epoch FROM t0)::float8, extract(epoch FROM t1)::float8, kind, detail, status FROM observe_changes WHERE t0 >= now() - make_interval(days => %s) AND t1 IS NOT NULL ORDER BY t0 DESC", (days,))
        return cur.fetchall()


def fetch_focus(conn, host, days):
    with conn.cursor() as cur:
        cur.execute("SELECT app, sum(seconds) FROM observe_focus_hourly WHERE host = %s AND hour >= now() - make_interval(days => %s) GROUP BY app", (host, days))
        return {a: float(s) for a, s in cur.fetchall()}


def fetch_periodic(conn, days):
    with conn.cursor() as cur:
        cur.execute("SELECT host, extract(epoch FROM t)::float8, series, period_s, corr, burst_pct, mean_pct FROM observe_periodic WHERE t >= now() - make_interval(days => %s) ORDER BY t DESC", (days,))
        return cur.fetchall()


def fetch_units(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT host, scope, unit FROM observe_units")
        out = {}
        for h, sc, u in cur.fetchall():
            out.setdefault(h, set()).add((sc, u))
        return out
