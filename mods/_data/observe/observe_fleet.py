"""observe_fleet — 여러 호스트(데스크톱·노트북)의 관측 요약을 공유 저장소(claude_ctx 의 Postgres)에 올려 서로 비교한다.

왜: 한 호스트의 기록만으로는 「이게 정상인가」를 모른다. 같은 앱이 노트북에서만 높거나, 한쪽에만 설치된 확장이 있으면 시험 전에 후보로 뽑을 수 있다
(2026-10-26 노트북 Vivaldi 의 1Password 서비스 워커 60초 주기 활동 — 데스크톱엔 없는 확장이었다, 장부 #133).
무엇을 올리나(요약만, 개인정보 없음): 시간별 앱 평균 CPU·자발적 문맥 전환(앱 이름 = observe 표본의 app), 시간별 평균 전력, 브라우저 확장 설치 목록(프로필 폴더 이름·확장 ID·버전·서비스 워커 유무 — 확장 이름·창 제목·주소는 올리지 않음).
접속은 claude_ctx.dsn() 과 같은 규칙(환경변수 > 서버 머신의 unix 소켓 > tailnet 이름). 표본 원본·프로세스 목록은 올리지 않는다.
표는 mods/_data/claude-ctx/schema.sql 에 있다(observe_app_hourly·observe_power_hourly·observe_ext_inventory). 올리기는 멱등(같은 시간·앱은 덮어쓴다)."""
import glob, json, os, socket, sys, time

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
def push(conn, hostname, app_rows, power_rows, inv):
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
