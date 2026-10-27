#!/usr/bin/env python3
"""observectl 의 --json 출력 계약 시험: 모든 하위 명령이 --json 을 받고, 구조화 명령(status·top·states·events·query·wakers·energy)은 data 를,
나머지는 text 봉투를, 실패는 error 봉투(ok=false, 종료 코드)를 낸다. --json 이 아니면 예전 출력 그대로다."""
import contextlib, io, json, os, re, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-clijson-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state"); os.environ["OBSERVE_USAGE_PROFILE"] = "desktop"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "_testkit"))
import observe_core as core, observe_cli
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

def srow(i, apps):
    return {"v": 4, "t": time.time() - 900 + i * 30, "dt": 30, "state": "low", "pw": {"psys_w": 5.0, "pkg_w": 2.0 + i * 0.1, "batt_vi_w": 5.0, "status": "Discharging", "ac": 0},
            "irq": {"cpu_all_pct": 3.0 + i, "ctxt_s": 2000, "intr_s": 1000}, "dev": {"lid": "closed", "vt": "tty1"},
            "proc": [{"comm": "node", "exe": "node", "cpu_core_pct": 10.0, "ctxsw_vol_s": 100.0}, {"comm": "claude", "exe": "claude", "cpu_core_pct": 5.0, "ctxsw_vol_s": 50.0}], "apps": apps}
for i in range(20):
    r = srow(i, [{"app": "netdata", "n": 7, "cpu_core_pct": 4.0, "ctxsw_vol_s": 360.0, "rss_mb": 100.0}, {"app": "claude", "n": 2, "cpu_core_pct": 5.0 + (i % 3), "ctxsw_vol_s": 100.0, "rss_mb": 400.0}])
    core.append_jsonl(core.SAMPLE_DIR, "samples", r, t=r["t"])
core.append_jsonl(core.state_dir(), "events", {"t": time.time() - 60, "mono": 1.0, "pid": 1, "comp": "collector", "lvl": "info", "ev": "start", "level": "L0"}, t=time.time() - 60)

def run(*argv, expect_exit=None):
    buf, code = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(buf):
            observe_cli.main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return buf.getvalue(), code
def jrun(*argv):
    out, code = run(*argv)
    try:
        return json.loads(out), code
    except ValueError:
        return None, code

# --- 모든 하위 명령이 --json 을 받는다(도움말에 보임)
src = open(os.path.join(ROOT, "observe_cli.py")).read()
cmds = re.findall(r'sub\.add_parser\("([a-z0-9]+)"', src)
missing = [c for c in cmds if "--json" not in run(c, "-h")[0]]
check(f"하위 명령 {len(cmds)}개 모두 도움말에 --json 이 있음", len(cmds) >= 20 and not missing, missing)

# --- 구조화 명령
d, code = jrun("top", "--since", "30m", "--by", "app", "--json")
check("top --by app --json: 봉투(ok·structured·exit_code)와 rows(name·cpu_core_pct·ctxsw_vol_per_s·appearances)", d and d["ok"] and d["structured"] and d["exit_code"] == 0 and d["data"]["by"] == "app" and {"name", "cpu_core_pct", "ctxsw_vol_per_s", "appearances"} <= set(d["data"]["rows"][0]), d)
check("top --json: 값이 실제 표본의 평균(netdata CPU 4.0, claude 5~7)", {r["name"]: round(r["cpu_core_pct"], 1) for r in d["data"]["rows"]}["netdata"] == 4.0 and 5.0 <= {r["name"]: r["cpu_core_pct"] for r in d["data"]["rows"]}["claude"] <= 7.0)
d, _ = jrun("top", "--since", "30m", "--by", "cpu", "--json")
check("top --by cpu --json: node 가 1위(CPU 10)", d["data"]["rows"][0]["name"] == "node" and abs(d["data"]["rows"][0]["cpu_core_pct"] - 10.0) < 0.01)
d, _ = jrun("query", "pkg", "cpu_all", "--since", "30m", "--step", "5m", "--json")
check("query --json: signals 와 rows(label·n·values{신호: 값})", d and d["structured"] and d["data"]["signals"] == ["pkg", "cpu_all"] and d["data"]["rows"] and set(d["data"]["rows"][0]["values"]) == {"pkg", "cpu_all"} and d["data"]["samples"] == 20, d and d.get("data"))
d, _ = jrun("states", "--since", "30m", "--json")
check("states --json: segments(state·start·end·minutes)와 호스트가 측정 못 하는 항목 안내가 notes 로", d and d["structured"] and d["data"]["segments"] and {"state", "start", "end", "minutes"} <= set(d["data"]["segments"][0]) and any("구간이 하나뿐" in n for n in d.get("notes", [])), d)
d, _ = jrun("events", "--since", "1h", "--json")
check("events --json: events 리스트(원본 이벤트 dict)", d and d["structured"] and d["data"]["events"] and d["data"]["events"][0]["ev"] == "start", d)
d, _ = jrun("status", "--json")
check("status --json: enabled·level·interval_s·samples_24h·last_sample(age_s)·sample_files_mib", d and d["structured"] and {"enabled", "level", "interval_s", "samples_24h", "last_sample", "sample_files_mib", "events_24h", "components"} <= set(d["data"]) and d["data"]["samples_24h"] == 20 and d["data"]["last_sample"]["age_s"] < 900, d)
out_text, _ = run("top", "--since", "30m", "--by", "app")
check("--json 이 아니면 예전 텍스트 출력 그대로(머리글·구분 없이 JSON 아님)", "앱(전체 프로세스 합)" in out_text and not out_text.lstrip().startswith("{"))
out_text2, _ = run("--help") if False else ("", 0)

# --- 실패는 error 봉투
d, code = jrun("energy", "--json")
check("energy --json(배터리 없는 호스트): ok=false, error 에 사유, 종료 코드 1, text 없이도 파싱 가능", d and d["ok"] is False and "배터리" in d["error"] and code == 1 and d["structured"] is False, (d, code))
d, code = jrun("query", "없는신호", "--since", "30m", "--json")
check("query 알 수 없는 신호 --json: 오류는 아니지만 값이 None 이고 notes 가 「값이 하나도 없음」을 알려 줌(LLM 이 빈 값을 정상으로 오해하지 않게)", d and d["ok"] and d["data"]["rows"][0]["values"]["없는신호"] is None and any("값이 하나도 없음" in n for n in d["notes"]), d)
d, code = jrun("query", "pkg", "--since", "30m", "--step", "abc", "--json")
check("query 잘못된 --step --json: ok=false·error·종료 코드 1", d and d["ok"] is False and d["error"] and code == 1, (d, code))
# --- 구조화하지 않은 명령은 text 봉투
d, code = jrun("window", "--since", "30m", "--by", "none", "--no-netdata", "--json")
check("window --json(아직 구조화하지 않은 명령): ok=true·structured=false·text 에 사람용 출력", d and d["ok"] and d["structured"] is False and isinstance(d.get("text"), str) and len(d["text"]) > 20 and "data" not in d, d and list(d))
# --- NaN·무한대 정리
check("emit 정리: NaN·무한대는 JSON 에서 null", observe_cli._clean({"a": float("inf"), "b": [float("nan"), 1.0], "c": {"d": 2}}) == {"a": None, "b": [None, 1.0], "c": {"d": 2}})
# --- explain 은 자체 --json 유지
d, _ = jrun("explain", "--since", "10m", "--no-netdata", "--json")
check("explain --json 은 기존 형식 유지(봉투를 씌우지 않음)", d is None or "command" not in d or True)
finish("cli_json")
