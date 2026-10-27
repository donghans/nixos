#!/usr/bin/env python3
"""observe_fleet 시험: 시간별 집계, 확장 목록 읽기(이름·주소는 안 올림), 비교·확장 차이 판정(순수 함수) + 임시 Postgres 에 실제 schema.sql 로 올리기·멱등·비교.
DB 시험은 psycopg 가 있는 python 과 postgres 17 이 있을 때만(없으면 순수 시험만, 종료 코드 0)."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="fleet-test-")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
import observe_fleet as fl
check, finish = checker()

# --- 시간별 집계: 그 시간의 전체 표본 수로 나눈다(안 나온 표본은 0)
T = 1_800_000_000 // 3600 * 3600
rows = [{"t": T + 10, "apps": [{"app": "vivaldi-bin", "cpu_core_pct": 10.0, "ctxsw_vol_s": 100.0}], "pw": {"psys_w": 2.0, "pkg_w": 1.0}},
        {"t": T + 40, "apps": [], "pw": {"psys_w": 4.0, "pkg_w": None}},
        {"t": T + 3700, "apps": [{"app": "node", "cpu_core_pct": 50.0, "ctxsw_vol_s": 1.0}], "pw": {}}, {"apps": [{"app": "x"}]}]
ar, pr = fl.hourly(rows)
check("hourly: 앱 평균은 시간 전체 표본(2개)으로 나눔 → vivaldi 5.0, ctxsw 50", (T, "vivaldi-bin", 5.0, 50.0, 2) in ar, str(ar))
check("hourly: 다음 시간은 따로 집계, 시각 없는 표본은 무시", (T + 3600, "node", 50.0, 1.0, 1) in ar and len(ar) == 2, str(ar))
check("hourly: 전력은 값이 있는 표본만 평균(psys 3.0, pkg 1.0), 값 없는 시간은 None", (T, 3.0, 1.0, 2) in pr and (T + 3600, None, None, 1) in pr, str(pr))

# --- 확장 목록(가짜 프로필 폴더): 이름·권한은 읽어도 결과에 없음
def mkext(prof, eid, ver, manifest):
    d = os.path.join(TMP, "vb", prof, "Extensions", eid, ver); os.makedirs(d); json.dump(manifest, open(d + "/manifest.json", "w"))
mkext("Default", "a" * 32, "1.0_0", {"name": "비밀이름", "version": "1.0", "permissions": ["tabs"], "background": {"service_worker": "bg.js"}})
mkext("Default", "b" * 32, "2.0_0", {"name": "x", "version": "2.0"})
mkext("Profile 1", "b" * 32, "2.0_0", {"name": "x", "version": "2.0"})
os.makedirs(os.path.join(TMP, "vb", "Profile 9", "Extensions", "c" * 32))      # 빈 폴더는 무시
inv = fl.ext_inventory([("vivaldi", os.path.join(TMP, "vb"))])
check("ext_inventory: 프로필·ID·버전·서비스 워커 유무(3개: Default 2 + Profile 1 1), 빈 폴더 무시", sorted((e["profile"], e["ext_id"][0], e["has_sw"]) for e in inv) == [("Default", "a", True), ("Default", "b", False), ("Profile 1", "b", False)], str(inv))
check("개인정보: 확장 이름이 결과에 없음", "비밀이름" not in json.dumps(inv, ensure_ascii=False))

# --- 비교·확장 차이(순수)
ma = {"vivaldi-bin": (0.60, 10.0), "python3": (0.5, 2.0), "node": (21.0, 6000.0), "tailscaled": (0.4, 35.0)}
mb = {"vivaldi-bin": (0.05, 5.0), "python3": (0.4, 2.0), "node": (22.0, 6000.0)}
cmp_ = fl.compare_means(ma, mb)
check("compare_means: a 가 b 의 3배↑(vivaldi) 와 a 에만 있는 것(tailscaled)만, 작은 차이(python3)·비슷한 것(node)은 제외", [(r[0], r[5]) for r in cmp_] == [("vivaldi-bin", "a↑"), ("tailscaled", "a만")], str(cmp_))
check("compare_means: 차이가 0.3%p 미만이면 제외", fl.compare_means({"x": (0.5, 0)}, {"x": (0.3, 0)}) == [])
d = fl.inventory_diff({"nb": {("v", "A" * 32): ("Default", "1", True), ("v", "B" * 32): ("Default", "2", False)}, "dt": {("v", "B" * 32): ("Default", "2", False)}})
check("inventory_diff: 한 호스트에만 있는 확장(서비스 워커 표시), 공통은 제외", d == [("nb", "v", "A" * 32, "Default", "1", True)], str(d))


# --- 교차 호스트 인사이트(순수): 포커스·nixup 구간·주기·유닛·변경 효과·우선순위
T0 = 1_800_000_000 // 3600 * 3600
spans = [{"comp": "windows", "name": "focus:kitty", "t0": T0 + 3000, "t1": T0 + 3000 + 1200, "attrs": {}},
         {"comp": "windows", "name": "focus:vivaldi-stable", "t0": T0 + 100, "t1": T0 + 400},
         {"comp": "windows", "name": "focus:열림", "t0": T0, "t1": None},
         {"comp": "nixup", "name": "run", "t0": T0 + 10, "t1": T0 + 90, "status": "ok", "attrs": {"sub": "home"}},
         {"comp": "nixup", "name": "nix build", "t0": T0 + 20, "t1": T0 + 30, "status": "ok", "attrs": {}},
         {"comp": "nixup", "name": "run", "t0": T0 + 500, "t1": None, "status": "running", "attrs": {}}]
fh = {(h, a): v for h, a, v in fl.focus_hourly(spans)}
check("focus_hourly: 시간 경계를 넘는 스팬은 나눠 담고(600+600), 열린 스팬은 제외", fh == {(T0, "kitty"): 600.0, (T0 + 3600, "kitty"): 600.0, (T0, "vivaldi-stable"): 300.0}, str(fh))
cs = fl.change_spans(spans)
check("change_spans: 끝난 최상위 nixup:run 만(하위 단계·진행 중 제외), 세부(sub) 포함", cs == [(T0 + 10, T0 + 90, "nixup", "home", "ok")], str(cs))
prow = fl.periodic_rows([{"ev": "browser.periodic", "t": 5.0, "series": "sw_thread", "period_s": 60.0, "corr": 0.9, "burst_over_mean_pct": 7.5, "mean_pct": 1.2}, {"ev": "browser.burst", "t": 6.0}])
check("periodic_rows: browser.periodic 만", prow == [(5.0, "sw_thread", 60.0, 0.9, 7.5, 1.2)], str(prow))
check("norm_unit: 인스턴스 해시는 @*, 일시 유닛은 제외", fl.norm_unit("app-Hyprland-tailscale@197af3ef.service") == "app-Hyprland-tailscale@*.service" and fl.norm_unit("run-r1234.service") is None and fl.norm_unit("session-3.scope") is None and fl.norm_unit("tlp.service") == "tlp.service")
check("units_only: 한 호스트에만 있는 유닛", fl.units_only({"a": {("user", "x"), ("user", "y")}, "b": {("user", "y")}}) == [("a", "user", "x")])
check("norm_key: 창 클래스와 프로세스 앱 이름이 같은 열쇠", fl.norm_key("vivaldi-stable") == fl.norm_key("vivaldi-bin") == "vivaldi" and fl.norm_key(".zed-editor-wra") == "zed" and fl.norm_key("Zed") == "zed")

def hrs(d): return {T0 + 3600 * i: apps for i, apps in d.items()}
t_chg0, t_chg1 = T0 + 3600 * 2 + 3000, T0 + 3600 * 3 + 300
nb = hrs({0: {"vivaldi-bin": 0.05}, 1: {"vivaldi-bin": 0.05}, 2: {"vivaldi-bin": 0.05}, 3: {"vivaldi-bin": 0.05}, 4: {"vivaldi-bin": 0.6, "node": 0.1}, 5: {"vivaldi-bin": 0.6, "node": 0.1}})
dt = hrs({i: {"vivaldi-bin": 0.05} for i in range(6)})
up, down, why = fl.change_effects({"nb": nb, "dt": dt}, "nb", t_chg0, t_chg1)
check("change_effects: 노트북에서만 vivaldi 0.05→0.6 이 늘어남(대조군 변화 0)", why is None and [r[0] for r in up] == ["vivaldi-bin"] and up[0][3] == 0.55 and up[0][4] == 0.0 and down == [], str((up, down, why)))
dt2 = hrs({0: {"vivaldi-bin": 0.05}, 1: {"vivaldi-bin": 0.05}, 2: {"vivaldi-bin": 0.05}, 3: {"vivaldi-bin": 0.05}, 4: {"vivaldi-bin": 0.6}, 5: {"vivaldi-bin": 0.6}})
up2, _, _ = fl.change_effects({"nb": nb, "dt": dt2}, "nb", t_chg0, t_chg1)
check("change_effects: 대조군도 같이 늘었으면 변경 탓으로 보지 않음", "vivaldi-bin" not in [r[0] for r in up2], str(up2))
nb_dn = hrs({0: {"x": 1.0}, 1: {"x": 1.0}, 2: {"x": 1.0}, 3: {"x": 1.0}, 4: {"x": 0.1}, 5: {"x": 0.1}})
_, dn, _ = fl.change_effects({"nb": nb_dn, "dt": dt}, "nb", t_chg0, t_chg1)
check("change_effects: 줄어든 앱(1.0→0.1)은 down 에", [r[0] for r in dn] == ["x"], str(dn))
nb_short = {h: v for h, v in nb.items() if h < T0 + 3600 * 5}
_, _, why2 = fl.change_effects({"nb": nb_short, "dt": dt}, "nb", t_chg0, t_chg1)
check("change_effects: 변경 뒤 데이터가 모자라면 판정 보류(사유)", why2 and "아직" in why2, str(why2))
alone_up, _, _ = fl.change_effects({"nb": nb}, "nb", t_chg0, t_chg1)
check("change_effects: 대조군이 없으면 대조군 변화 None 으로 보고", alone_up and alone_up[0][4] is None)

focus = {"vivaldi-stable": 4000.0, "kitty": 3000.0, "Zed": 2000.0, "rare": 10.0}
tm = {"vivaldi-bin": (0.6, 10.0), "tailscaled": (0.5, 40.0), "kitty": (0.2, 1.0), "zed": (1.5, 3.0), "blueman-tray": (0.15, 9.0)}
rm = {"vivaldi-bin": (0.05, 5.0), "kitty": (0.2, 1.0), "zed": (0.4, 3.0)}
fg, bg, mix = fl.priority(focus, rm, tm)
check("priority: 포커스 앱과 초과 CPU(vivaldi +0.55, zed +1.1)", [(r[0], r[1]) for r in fg] == [("vivaldi", 44.4), ("kitty", 33.3), ("zed", 22.2)] and fg[0][4] == 0.55 and fg[2][4] == 1.1, str(fg))
check("priority: 배경은 포커스 없는 앱 중 초과가 큰 것(tailscaled 0.5), 작은 것은 제외", [r[0] for r in bg] == ["tailscaled"] and bg[0][3] == 0.5, str(bg))
check("priority: 시나리오 후보는 사용 비중 순", [m[0] for m in mix][:3] == ["vivaldi", "kitty", "zed"] and mix[0][1] == 44.4, str(mix))

# --- 올리기 기록(실패해도 쌓아 뒀다 다음에 같이)
NOW = 1_800_100_000.0
since, pend = fl.since_for({}, NOW)
check("since_for: 기록이 없으면 26시간 전부터, 밀림 없음(None)", since == NOW - 26 * 3600 and pend is None, str((since, pend)))
st = fl.record({}, NOW, True, rows="앱 5")
check("record: 성공이면 last_ok 갱신·오류 없음", st["last_ok"] == NOW and "error" not in st and st["rows"] == "앱 5", str(st))
st2 = fl.record(st, NOW + 21600, False, error="접속 실패 " * 100)
check("record: 실패면 last_ok 는 그대로, 오류만 기록(길이 제한)", st2["last_ok"] == NOW and st2["last_try"] == NOW + 21600 and 0 < len(st2["error"]) <= 200, str(st2)[:120])
since2, pend2 = fl.since_for(st2, NOW + 3 * 21600)
check("since_for: 3번 실패한 뒤에도 마지막 성공(2시간 겹침)부터 — 밀린 18시간이 다음에 같이 올라감", since2 == NOW - 2 * 3600 and pend2 == 3 * 21600, str((since2, pend2)))
since3, _ = fl.since_for({"last_ok": NOW - 40 * 86400}, NOW)
check("since_for: 로컬 보존(14일)보다 앞으로는 가지 않음", since3 == NOW - 14 * 86400, str(since3))
sp = os.path.join(TMP, "fleet-state", "fleet-push.json")
fl.write_state(st2, sp)
check("write_state/read_state: 파일을 거쳐도 같고, 없거나 깨진 파일은 빈 상태", fl.read_state(sp) == st2 and fl.read_state(os.path.join(TMP, "없음.json")) == {} and (open(os.path.join(TMP, "깨짐.json"), "w").write("{x") and fl.read_state(os.path.join(TMP, "깨짐.json")) == {}))

# --- DB 통합(임시 Postgres)
try:
    import psycopg  # noqa: F401
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "llm", "llm-ctx", "tests")); import pgscratch
    pg = pgscratch.start() if pgscratch.find_bin() else None
except ImportError:
    pg = None
if pg is None:
    print("psycopg/postgres 가 없어 DB 시험은 건너뜀")
else:
    try:
        os.environ["CLAUDE_CTX_DSN"] = pg.dsn
        sch = open(os.path.join(os.path.dirname(os.path.dirname(ROOT)), "llm", "llm-ctx", "schema.sql")).read()
        check("schema.sql 에 observe_* 표 3개", all(t in sch for t in ("observe_app_hourly", "observe_power_hourly", "observe_ext_inventory")))
        conn = fl.connect()
        n = fl.push(conn, "nb", ar, pr, inv)
        check("push: 앱 2·전력 2·확장 3 행", n == (2, 2, 3), str(n))
        n2 = fl.push(conn, "nb", ar, pr, inv)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM observe_app_hourly"); na = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM observe_ext_inventory"); ne = cur.fetchone()[0]
        check("push: 두 번 올려도 행이 늘지 않음(멱등)", na == 2 and ne == 3, f"{na},{ne}")
        # 최근 시간으로 옮겨 host_means 시험: 시각을 지금 기준으로 다시 올린다
        now_h = int(__import__("time").time() // 3600 * 3600) - 3600
        ar2 = [(now_h, "vivaldi-bin", 0.6, 10.0, 100), (now_h, "tailscaled", 0.4, 35.0, 100)]
        fl.push(conn, "nb2", ar2, [(now_h, 2.0, 1.0, 100)], [{"browser": "vivaldi", "profile": "Default", "ext_id": "z" * 32, "version": "1", "has_sw": True}])
        ar3 = [(now_h, "vivaldi-bin", 0.05, 5.0, 100)]
        fl.push(conn, "dt", ar3, [(now_h, 20.0, 15.0, 100)], [])
        ma_, na_ = fl.host_means(conn, "nb2", 1); mb_, nb_ = fl.host_means(conn, "dt", 1)
        check("host_means: 표본 수 100, 앱별 평균(가중)", na_ == 100 and abs(ma_["vivaldi-bin"][0] - 0.6) < 1e-3 and nb_ == 100, str((ma_, na_)))
        check("DB 값으로 비교: vivaldi 는 a↑, tailscaled 는 a만", [(r[0], r[5]) for r in fl.compare_means(ma_, mb_)] == [("vivaldi-bin", "a↑"), ("tailscaled", "a만")], str(fl.compare_means(ma_, mb_)))
        inv_db = fl.inventory(conn)
        dd = fl.inventory_diff(inv_db)
        check("inventory(DB): nb2 에만 있는 서비스 워커 확장이 차이로 나옴", any(r[0] == "nb2" and r[5] for r in dd), str(dd))
        # --- 교차 호스트 인사이트 DB 왕복
        now_h = int(__import__("time").time() // 3600 * 3600)
        ex = {"focus": [(now_h - 3600, "kitty", 600.0), (now_h - 3600, "vivaldi-stable", 900.0)], "changes": [(now_h - 7000, now_h - 6900, "nixup", "home", "ok")],
              "periodic": [(now_h - 100.0, "sw_thread", 60.0, 0.9, 7.5, 1.2)], "units": [("user", "a.service"), ("system", "tlp.service")]}
        fl.push(conn, "nb2", [], [], None, ex); fl.push(conn, "nb2", [], [], None, ex)
        fl.push(conn, "dt", [], [], None, {"units": [("system", "tlp.service")]})
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM observe_focus_hourly WHERE host = 'nb2'"); nf = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM observe_changes WHERE host = 'nb2'"); nch = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM observe_periodic WHERE host = 'nb2'"); npd = cur.fetchone()[0]
        check("push(extra): 포커스 2·변경 1·주기 1 행, 두 번 올려도 늘지 않음(멱등)", (nf, nch, npd) == (2, 1, 1), str((nf, nch, npd)))
        check("fetch_focus: 앱별 초", fl.fetch_focus(conn, "nb2", 3) == {"kitty": 600.0, "vivaldi-stable": 900.0})
        ch = fl.fetch_changes(conn, 3)
        check("fetch_changes: nixup 구간", len(ch) == 1 and ch[0][0] == "nb2" and ch[0][3] == "nixup" and ch[0][4] == "home", str(ch))
        check("fetch_periodic: 주기 활동 행", fl.fetch_periodic(conn, 3)[0][2] == "sw_thread")
        check("units: nb2 에만 있는 a.service, 공통 tlp.service 는 제외", fl.units_only(fl.fetch_units(conn)) == [("nb2", "user", "a.service")], str(fl.units_only(fl.fetch_units(conn))))
        ah = fl.fetch_apps_hourly(conn, 3)
        check("fetch_apps_hourly: 호스트·시각별 앱 평균", "vivaldi-bin" in ah["nb2"][now_h - 3600] and (now_h - 3600) in ah["dt"], str({h: sorted(v) for h, v in ah.items()}))

        conn.close()

        # CLI: 실패→기록→성공 때 밀린 것까지 올림, status 출력
        import io, contextlib
        os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "cli-state")
        import importlib, observe_core; importlib.reload(observe_core)
        import observe_cli; importlib.reload(observe_cli)
        good = pg.dsn
        os.environ["CLAUDE_CTX_DSN"] = "host=/nonexistent port=1 dbname=x user=x"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                observe_cli.main(["fleet", "sync"])
            rc_fail = 0
        except SystemExit as e:
            rc_fail = e.code
        stf = fl.read_state()
        check("sync: 접속 실패면 종료 코드가 0 이 아니고 사유가 기록되며 last_ok 는 없음(쌓아 둠)", rc_fail not in (0, None) and "error" in stf and "last_ok" not in stf, f"{rc_fail} {stf}")
        os.environ["CLAUDE_CTX_DSN"] = good
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            observe_cli.main(["fleet", "sync"])
        stf = fl.read_state()
        check("sync: 접속이 돌아오면 올리고 last_ok 갱신·오류 지움", "last_ok" in stf and "error" not in stf and "올림" in out.getvalue(), out.getvalue() + str(stf))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            observe_cli.main(["fleet", "status"])
        check("status: 마지막 성공 시각을 보임, 실패 사유 없음", "마지막 성공" in out.getvalue() and "실패 사유" not in out.getvalue(), out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            observe_cli.main(["fleet", "export", "--days", "3"])
        ex = json.loads(out.getvalue())
        check("fleet export: usageui 용 JSON(호스트·전력·앱 평균·표본 수·확장 차이)", ex["version"] == 1 and set(ex["hosts"]) >= {"nb", "nb2", "dt"} and "vivaldi-bin" in ex["means"]["nb2"] and ex["samples"]["dt"] == 100 and ex["power"]["nb2"][0][2] == 1.0, str(list(ex)))
        check("fleet export: 확장 차이에 서비스 워커 확장(nb2)", any(r[0] == "nb2" and r[5] for r in ex["inventory_diff"]), str(ex["inventory_diff"]))
        for sub_, needle in ((["fleet", "units"], "한 호스트에만 있는 상시"), (["fleet", "periodic"], "주기 60"), (["fleet", "changes"], "nixup(home"), (["fleet", "priority", "nb2", "--host", "dt", "--usage-from", "nb2"], "사용 비중 상위")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                observe_cli.main(sub_)
            check(f"CLI {' '.join(sub_[:2])}: 출력에 「{needle}」", needle in out.getvalue(), out.getvalue()[:300])
        # 인사이트 표가 없는 서버(아직 nixup 전)에서도 기본 요약은 올라가고 인사이트는 건너뜀
        c2 = fl.connect()
        with c2.cursor() as cur:
            cur.execute("DROP TABLE observe_units"); cur.execute("DROP TABLE observe_focus_hourly")
        c2.commit()
        n3 = fl.push(c2, "nb3", [(now_h, "vivaldi-bin", 0.1, 1.0, 10)], [(now_h, 2.0, 1.0, 10)], None, {"focus": [(now_h, "kitty", 1.0)], "units": [("user", "a.service")], "changes": [(now_h - 100, now_h - 50, "nixup", "home", "ok")]})
        with c2.cursor() as cur:
            cur.execute("SELECT count(*) FROM observe_app_hourly WHERE host = 'nb3'"); n_app3 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM observe_changes WHERE host = 'nb3'"); n_ch3 = cur.fetchone()[0]
        c2.close()
        check("표가 없는 서버: 기본 요약(앱 1행)과 있는 인사이트 표(변경)는 올라가고, 없는 표(포커스·유닛)만 건너뜀", n3[0] == 1 and n_app3 == 1 and n_ch3 == 1 and sorted(fl.LAST_SKIPPED) == ["observe_focus_hourly", "observe_units"], f"{n3} {n_app3} {n_ch3} {fl.LAST_SKIPPED}")
        before_ok = fl.read_state().get("last_ok")
        out = io.StringIO()
        os.environ["CLAUDE_CTX_DSN"] = pg.dsn
        with contextlib.redirect_stdout(out):
            observe_cli.main(["fleet", "sync"])
        stx = fl.read_state()
        check("표가 없어 건너뛰면 last_ok 를 앞으로 옮기지 않고(다음에 다시 포함) 사유를 상태에 남김", "건너뜀" in out.getvalue() and stx.get("last_ok") == before_ok and "인사이트 표 없음" in stx.get("error", ""), out.getvalue() + str(stx))
        check("observectl fleet 서브명령이 등록됨", "fleet" in open(os.path.join(ROOT, "observe_cli.py")).read())
    finally:
        pg.stop()
finish("fleet")
