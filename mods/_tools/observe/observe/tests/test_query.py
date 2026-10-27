#!/usr/bin/env python3
"""범용 조회 시험: 신호 해석(별칭·경로·app/proc·nd), 시간 간격·그룹 묶기, 집계, 옛 표본 처리, CLI."""
import contextlib, io, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-query-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
import observe_core as core, observe_query as qy, observe_cli
from harness import checker
check, finish = checker()

def row(t, psys, state="low", status="Discharging", vi=5.0, apps=None, proc=None):
    r = {"t": t, "state": state, "pw": {"psys_w": psys, "pkg_w": 2.0, "batt_vi_w": vi, "status": status}, "cs": {"pc10": 4.0}}
    if apps is not None: r["apps"] = apps
    if proc is not None: r["proc"] = proc
    return r
T0 = 1_000_000.0
rows = [row(T0 + i * 30, 4.0 + i, state="low" if i < 3 else "high", status="Discharging" if i != 1 else "Charging",
            apps=[{"app": "claude", "n": 2, "cpu_core_pct": 10.0 * i, "ctxsw_vol_s": 100.0}]) for i in range(6)]

check("parse_step", qy.parse_step("30s") == 30 and qy.parse_step("5m") == 300 and qy.parse_step("2h") == 7200 and qy.parse_step("90") == 90)
try: qy.parse_step("5분"); check("parse_step 오류", False)
except ValueError: check("parse_step 오류", True)
check("extract: 별칭·점 경로", qy.extract(rows[0], "psys") == 4.0 and qy.extract(rows[0], "pw.pkg_w") == 2.0 and qy.extract(rows[0], "pc10") == 4.0)
check("extract: vi 는 방전 중 표본만(충전 중이면 None)", qy.extract(rows[0], "vi") == 5.0 and qy.extract(rows[1], "vi") is None)
check("extract: 없는 경로는 None(오류 아님)", qy.extract(rows[0], "pw.nope") is None)
check("extract: app:<이름>.cpu — 앱 표에서 합산, 없는 앱은 0, 표가 없는 표본은 None", qy.extract(rows[2], "app:claude.cpu") == 20.0 and qy.extract(rows[2], "app:없음.cpu") == 0.0 and qy.extract(row(T0, 1), "app:claude.cpu") is None)
legacy = row(T0, 1, proc=[{"comm": "x", "cpu_core_pct": 5.0, "ctxsw_vol_leader_s": 9.0}])
check("extract: 옛 표본의 proc 전환 값은 쓰지 않음(L9), CPU 는 사용", qy.extract(legacy, "proc:x.ctxsw") is None and qy.extract(legacy, "proc:x.cpu") == 5.0)
try: qy.extract(rows[0], "app:claude.foo"); check("extract: 잘못된 필드", False)
except ValueError: check("extract: 잘못된 필드는 ValueError", True)
check("aggregate", qy.aggregate([1, 2, 3, 4, 100], "mean") == 22.0 and qy.aggregate([1, 2, 3, 4, 100], "p50") == 3 and qy.aggregate([1, 2, 3, 4, 100], "max") == 100 and qy.aggregate([None, 2], "count") == 1 and qy.aggregate([], "mean") is None and qy.aggregate([1, 2], "sum") == 3)
res = qy.run(rows, ["psys"], step=90)
check("run: 시간 간격 묶기(90초=표본 3개씩)", [(n, round(v[0], 2)) for _, n, v in res] == [(3, 5.0), (3, 8.0)], str(res))
res = qy.run(rows, ["psys", "vi"], key=lambda r: r["state"])
check("run: 그룹 묶기(상태)와 vi 의 방전 필터", {g: (n, round(v[0], 2), v[1]) for g, n, v in res} == {"high": (3, 8.0, 5.0), "low": (3, 5.0, 5.0)}, str(res))
check("run: 묶기 없으면 전체 한 줄", len(qy.run(rows, ["psys"])) == 1 and qy.run(rows, ["psys"])[0][1] == 6)
nds = {"net_rx_kbps": [(T0 + 5, 10.0), (T0 + 30, 20.0), (T0 + 400, 99.0)]}
res = qy.run(rows[:2], ["nd:net_rx_kbps"], nd_series=nds)
check("run: nd 신호는 표본 시각 ±15초 값만 평균, 데이터 없는 표본은 제외(공백)", res[0][2][0] == 15.0, str(res))
check("run: Netdata 데이터가 전혀 없는 그룹은 None(관측 공백)", qy.run(rows[3:], ["nd:net_rx_kbps"], nd_series=nds)[0][2][0] is None)
try: qy.run(rows, ["psys"], agg="zz"); check("run: 잘못된 집계", False)
except ValueError: check("run: 잘못된 집계는 ValueError", True)

os.makedirs(core.SAMPLE_DIR, exist_ok=True)
import time
now = time.time()
for i in range(6):
    r = row(now - 600 + i * 60, 4.0 + i); core.append_jsonl(core.SAMPLE_DIR, "samples", r, t=r["t"])
def cli(*argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): observe_cli.main(["query", *argv])
    except SystemExit as e:
        return buf.getvalue() + str(e)
    return buf.getvalue()
out = cli("psys", "pkg", "--since", "20m", "--step", "3m")
check("CLI: 시간 간격 표(헤더·열 2개)", "10m" not in out and "3m 간격" in out and "psys" in out and "pkg" in out, out)
out = cli("psys", "--since", "20m", "--by", "state", "--agg", "max")
check("CLI: 그룹·집계", "그룹 state" in out and "max" in out and "low" in out, out)
out = cli("nope.path", "--since", "20m")
check("CLI: 없는 경로는 '-' 로 표시(오류 아님)", "-" in out.splitlines()[-1], out)
out = cli("app:claude.xx", "--since", "20m")
check("CLI: 잘못된 신호 형식은 안내하고 종료", "형식은" in out, out)
finish("query")
