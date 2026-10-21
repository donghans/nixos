#!/usr/bin/env python3
"""앱 단위 집계 시험: 이름 정리·규칙·electron(app.asar)·커널 스레드, 수집기 app_table 의 합계 보존(커버리지 100%), 정규화(v3→v4 는 legacy 아님), explain·observectl top --by app."""
import contextlib, io, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-apps-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import observe_core as core, observe_apps as ap, observe_collector as col, observe_explain as ex, observe_cli
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

# --- 이름 정리·규칙
check("clean_name: Nix 래퍼 이름 정리(.claude-wrapped→claude, .Hyprland-wrapp→hyprland, 소문자)", [ap.clean_name(x) for x in (".claude-wrapped", ".Hyprland-wrapp", ".kitty-wrapped", "Vivaldi-bin")] == ["claude", "hyprland", "kitty", "vivaldi-bin"])
def app(pid, comm, exe, ppid=1, exe_of=None, ppid_of=None, cmd=None, cache=None):
    return ap.app_name(pid, comm, exe, ppid, exe_of or {}, ppid_of or {}, (lambda p: cmd.get(p, [])) if cmd else (lambda p: []), {} if cache is None else cache)
check("규칙: claude·vivaldi(도우미 포함)·kitty·hyprland 계열·tailscaled·nix 계열", [app(1, ".claude-wrapped", ".claude-wrapped"), app(2, "vivaldi-bin", "vivaldi-bin"), app(3, ".kitty-wrapped", ".kitty-wrapped"), app(4, ".Hyprland-wrapp", ".Hyprland-wrapped"), app(5, "start-hyprland", "start-hyprland"), app(6, ".tailscaled-wra", ".tailscaled-wrapped"), app(7, "nix-daemon", "nix-daemon"), app(8, "nixos-rebuild", "nixos-rebuild")] == ["claude", "vivaldi", "kitty", "hyprland", "hyprland", "tailscaled", "nix", "nix"])
check("규칙: netdata 와 그 플러그인(go.d·apps.plugin·debugfs.plugin)은 netdata 한 앱", {app(i, c, c) for i, c in enumerate(("netdata", "go.d.plugin", "apps.plugin.org", "debugfs.plugin."))} == {"netdata"})
check("규칙: 그 밖에는 정리한 이름 그대로(mongod, meilisearch)", app(9, "mongod", "mongod") == "mongod" and app(10, "meilisearch", "meilisearch") == "meilisearch")
check("커널 스레드(실행 파일 없음·부모 2)는 kernel, pid 2 자신도", app(100, "kworker/u64:2", "", ppid=2) == "kernel" and app(2, "kthreadd", "", ppid=0) == "kernel")
check("실행 파일을 못 읽어도(보호된 프로세스) 부모가 kthreadd 가 아니면 kernel 로 보지 않음", app(101, "electron", "", ppid=500) != "kernel")

# --- electron: 맨 위 electron 프로세스의 app.asar 로 앱 이름
ASAR = ["/nix/store/abcdefghijklmnopqrstuvwxyz012345-bitwarden-desktop-2026.5.0/opt/Bitwarden/resources/app.asar", "--autostart"]
check("asar_app_name: 저장소 이름에서 버전 제거", ap.asar_app_name(ASAR) == "bitwarden-desktop")
check("asar_app_name: 저장소 밖 경로는 resources 앞 디렉터리 이름", ap.asar_app_name(["/opt/Slack/resources/app.asar"]) == "slack" and ap.asar_app_name(["--type=zygote"]) is None)
exe_of = {10: "electron", 11: "electron", 12: "electron", 20: "electron", 21: "electron", 1: "systemd"}
ppid_of = {10: 1, 11: 10, 12: 11, 20: 1, 21: 20}
cmd = {10: ASAR, 20: ["/nix/store/abcdefghijklmnopqrstuvwxyz012345-slack-4.4/lib/slack/resources/app.asar"], 11: ["--type=zygote"], 12: ["--type=renderer"], 21: ["--type=gpu-process"]}
cache = {}
names = {p: ap.app_name(p, "electron", "electron", ppid_of[p], exe_of, ppid_of, lambda q: cmd.get(q, []), cache) for p in (10, 11, 12, 20, 21)}
check("electron: 도우미(zygote·renderer)도 루트의 asar 로 같은 앱, 다른 electron 앱은 따로", names == {10: "bitwarden-desktop", 11: "bitwarden-desktop", 12: "bitwarden-desktop", 20: "slack", 21: "slack"}, str(names))
check("electron: 루트 명령줄은 루트마다 한 번만 읽음(캐시)", set(cache) == {10, 20})
check("electron: asar 를 못 찾으면 'electron'", ap.app_name(30, "electron", "electron", 1, {30: "electron"}, {30: 1}, lambda q: ["--foo"], {}) == "electron")
check("electron: 명령줄을 못 읽어도 예외 없이 'electron'", ap.app_name(31, "electron", "electron", 1, {31: "electron"}, {31: 1}, lambda q: (_ for _ in ()).throw(OSError()), {}) == "electron")

# --- aggregate: 합계 보존
rows = [{"app": f"a{i}", "n": 1, "cpu_core_pct": float(30 - i), "ctxsw_vol_s": float(i), "rss_mb": 1.0} for i in range(30)] + [{"app": "idle", "n": 3, "cpu_core_pct": 0.0, "ctxsw_vol_s": 0.0, "rss_mb": 5.0}]
agg = ap.aggregate(rows, top=24)
check("aggregate: 상위 24개 + (기타) 한 행, 활동 없는 앱은 제외", len(agg) == 25 and agg[-1]["app"] == ap.OTHER and all(r["app"] != "idle" for r in agg))
check("aggregate: CPU·전환 합계가 (기타)까지 합치면 원래와 같다(커버리지 100%)", abs(sum(r["cpu_core_pct"] for r in agg) - sum(r["cpu_core_pct"] for r in rows)) < 0.05 and abs(sum(r["ctxsw_vol_s"] for r in agg) - sum(r["ctxsw_vol_s"] for r in rows)) < 0.5)

# --- 수집기 app_table (가짜 프로세스 표)
class FakeSampler(col.Sampler):
    def __init__(self):
        self.level = "L0"; self.apps = ap.AppResolver()
fs = FakeSampler()
HZ = col.HZ
def pt(comm, exe, ticks, vol, ppid=1, rss=250):
    return (comm, exe, ticks, vol, rss, (0, 0), ppid)
prev = {1: pt("systemd", "systemd", 0, 0, 0), 10: pt("electron", "electron", 0, 0, 1), 11: pt("electron", "electron", 0, 0, 10), 12: pt("electron", "electron", 0, 0, 11),
        50: pt("netdata", "netdata", 0, 0), 51: pt("go.d.plugin", "go.d.plugin", 0, 0, 50), 60: pt("kworker/0:1", "", 0, 0, 2), 61: pt("kworker/1:1", "", 0, 0, 2)}
cur = {1: pt("systemd", "systemd", 0, 10, 0), 10: pt("electron", "electron", HZ * 2, 100, 1), 11: pt("electron", "electron", HZ * 1, 50, 10), 12: pt("electron", "electron", HZ * 3, 70, 11),
       50: pt("netdata", "netdata", HZ * 4, 300), 51: pt("go.d.plugin", "go.d.plugin", HZ * 1, 100, 50), 60: pt("kworker/0:1", "", HZ * 1, 60, 2), 61: pt("kworker/1:1", "", HZ * 1, 40, 2),
       99: pt("newproc", "newproc", HZ * 9, 999)}                                    # 이전 표에 없는 새 프로세스는 건너뜀
import observe_collector as _c
col.rd = lambda path, default="": ("\0".join(ASAR) if path.endswith("/10/cmdline") else "")      # 루트(pid 10)의 명령줄만 읽힘
rows = {r["app"]: r for r in fs.app_table(cur, prev, 10.0)}
check("app_table: electron 3개 프로세스가 bitwarden-desktop 한 앱(CPU (2+1+3)초/10초 = 60%, 전환 (100+50+70)/10 = 22/s)", rows["bitwarden-desktop"]["n"] == 3 and abs(rows["bitwarden-desktop"]["cpu_core_pct"] - 60.0) < 0.1 and abs(rows["bitwarden-desktop"]["ctxsw_vol_s"] - 22.0) < 0.1, str(rows.get("bitwarden-desktop")))
check("app_table: netdata 와 플러그인이 한 앱(CPU 50%, 전환 40/s)", rows["netdata"]["n"] == 2 and abs(rows["netdata"]["cpu_core_pct"] - 50.0) < 0.1 and abs(rows["netdata"]["ctxsw_vol_s"] - 40.0) < 0.1, str(rows.get("netdata")))
check("app_table: 커널 스레드가 kernel 한 앱, 이전 표에 없던 새 프로세스는 제외", rows["kernel"]["n"] == 2 and "newproc" not in rows and abs(rows["kernel"]["cpu_core_pct"] - 20.0) < 0.1, str(rows.get("kernel")))
check("app_table: 모든 프로세스의 CPU 합과 앱 합이 같음(커버리지 100%)", abs(sum(r["cpu_core_pct"] for r in rows.values()) - sum((cur[p][2] - prev[p][2]) / HZ / 10.0 * 100 for p in prev)) < 0.2)

# --- explain: apps 표
T = 1_700_000_000.0
def srow(i, apps, legacy=False):
    return {"v": 4, "t": T + i * 30, "dt": 30, "state": "low", "pw": {"psys_w": 5.0, "pkg_w": 2.0, "batt_vi_w": 5.0, "status": "Discharging", "ac": 0}, "irq": {"cpu_all_pct": 3.0, "ctxt_s": 2000, "intr_s": 1000},
            "dev": {"lid": "closed", "vt": "tty1"}, "proc": [], "apps": apps}
base = [srow(i, [{"app": "netdata", "n": 7, "cpu_core_pct": 4.0, "ctxsw_vol_s": 360.0, "rss_mb": 100.0}, {"app": "claude", "n": 2, "cpu_core_pct": 5.0, "ctxsw_vol_s": 100.0, "rss_mb": 400.0}]) for i in range(0, 10)]
cur_ = [srow(i, [{"app": "netdata", "n": 7, "cpu_core_pct": 4.0, "ctxsw_vol_s": 360.0, "rss_mb": 100.0}, {"app": "claude", "n": 2, "cpu_core_pct": 5.0, "ctxsw_vol_s": 100.0, "rss_mb": 400.0}, {"app": "nix", "n": 9, "cpu_core_pct": 130.0, "ctxsw_vol_s": 900.0, "rss_mb": 800.0}]) for i in range(10, 20)]
res = ex.build(base + cur_, [], T + 300, T + 600, (T, T + 300), None)
text = "\n".join(ex.render(res, core.hms))
check("explain: 앱 단위 표(커버리지 100% 문구)와 앱 이름·프로세스 수", "앱 단위(전체 프로세스를 앱으로 묶은 합" in text and "커버리지 100%" in text and "netdata" in text and "nix" in text, text)
check("explain: 달라진 것 순위가 앱 CPU 로(nix 0 → 130 '신규', 프로세스 행과 이중 집계 없음)", any(c["kind"] == "앱 CPU" and c["name"] == "nix" and c["rel"] == float("inf") for c in res["changes"]) and not any(c["kind"] == "프로세스 CPU" for c in res["changes"]), str(res["changes"]))
check("explain: apps 가 있으면 '긴 꼬리' 경고를 내지 않음", not any("긴 꼬리" in n for n in res["notes"]))
check("apps_table: apps 가 없는 표본(v3 이하)이면 None → explain 은 옛 표로 대체", ex.apps_table([{"t": 1, "proc": []}]) is None)

# --- observectl top --by app
for r in base + cur_:
    core.append_jsonl(core.SAMPLE_DIR, "samples", {**r, "t": time.time() - 600 + (r["t"] - T)}, t=time.time() - 600 + (r["t"] - T))
def cli(*argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            observe_cli.main(["top", *argv])
    except SystemExit as e:
        return buf.getvalue() + "EXIT:" + str(e)
    return buf.getvalue()
out = cli("--since", "30m", "--by", "app")
check("observectl top --by app: 앱 이름·합계 순위(nix 가 위)·열 제목", "앱(전체 프로세스 합)" in out and out.index("nix") < out.index("netdata") and "claude" in out, out)
# 정규화: v3 표본은 legacy 가 아니고 apps 가 없을 뿐
n3 = core.normalize_sample({"v": 3, "t": 1.0, "proc": [{"comm": "x", "ctxsw_vol_s": 5.0}]})
check("normalize: v3 → v4 는 legacy 가 아님(apps 가 없을 뿐, 이름·값 유지)", n3["v"] == 4 and "legacy" not in n3 and n3["proc"][0]["ctxsw_vol_s"] == 5.0)
finish("apps")
