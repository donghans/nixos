#!/usr/bin/env python3
"""eBPF 프리셋 시험: 프로그램 검증(주입 방지), 출력 파서/요약, exec 스팬 변환, 수집기 job_bpf(가짜 bpftrace), observectl bpf 출력."""
import contextlib, io, json, os, stat, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-bpf-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "_testkit"))
import observe_core as core, observe_bpf as bpf, observe_collector as col, observe_cli, observe_trace as tr
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

# --- 프로그램 문자열
for p in bpf.PRESETS:
    prog = bpf.program(p, 7)
    check(f"program({p}): 7초 뒤 종료 구문 포함", "interval:s:7 { exit(); }" in prog, prog)
check("program: comm 필터가 조건으로 들어감", '/comm == "electron"/' in bpf.program("wake", 5, "electron"))
for bad in ('x"; exit(); //', "a b", "", "너무너무너무너무너무너무길다길다길다", "a{b"):
    try:
        bpf.program("wake", 5, bad); check(f"comm 주입 거부: {bad!r}", False)
    except ValueError:
        check(f"comm 주입 거부: {bad!r}", True)
try:
    bpf.program("nope", 5); check("알 수 없는 프리셋 거부", False)
except ValueError:
    check("알 수 없는 프리셋 거부", True)
check("exec 프로그램은 exe 이름 경로를 str(filename) 으로, 명령 인자는 보지 않음", "str(args->filename)" in bpf.program("exec", 5) and "argv" not in bpf.program("exec", 5))

# --- 파서
OUT = "\n".join(json.dumps(x) for x in [
    {"type": "attached_probes", "count": 2, "data": {"probes": 2}},
    {"type": "printf", "data": "E 100 1 bash 1000000000 /nix/store/abc-bash/bin/bash\n"},
    {"type": "printf", "data": "E 101 100 git 1100000000 /nix/store/xyz-git/bin/git\n"},
    {"type": "printf", "data": "X 101 git 1600000000 250000000\n"},
    {"type": "printf", "data": "E 102 100 git 1700000000 /nix/store/xyz-git/bin/git\n"},
    {"type": "printf", "data": "X 102 git 1800000000 50000000\n"},
    {"type": "printf", "data": "X 100 bash 2000000000 400000000\n"},
    {"type": "printf", "data": "X 55 oldproc 1900000000 1\n"},
    {"type": "map", "data": {"@w": {"systemd-logind,.blueman-tray-w": 3, "PD[go.d],rcu_preempt": 7, "a,b,electron": 5}}},
]) + "\n깨진줄\n"
lines, maps = bpf.parse_output(OUT)
check("parse_output: printf 줄·맵·깨진 줄 무시", len(lines) == 7 and maps["w"]["PD[go.d],rcu_preempt"] == 7, str((len(lines), maps)))
procs = bpf.parse_exec(lines)
check("parse_exec: exe 는 경로가 아니라 이름만", procs[101]["exe"] == "git" and procs[100]["exe"] == "bash" and "/nix" not in json.dumps(procs))
check("parse_exec: 종료만 본 프로세스는 시작 없음(t0_ns None)", procs[55]["t0_ns"] is None and procs[100]["cpu_ns"] == 400000000)
w = bpf.summarize("wake", lines, maps, 10)
check("wake 요약: 깨우는 쪽/깨어나는 쪽 집계(쉼표 든 comm 은 마지막 쉼표 기준)", w["total"] == 15 and w["by_waker"][0] == {"comm": "PD[go.d]", "count": 7, "per_s": 0.7} and {"comm": "a,b", "count": 5, "per_s": 0.5} in w["by_waker"], str(w["by_waker"]))
check("wake 요약: 쌍 목록", w["pairs"][0]["waker"] == "PD[go.d]" and w["pairs"][0]["wakee"] == "rcu_preempt" and w["pairs"][0]["per_s"] == 0.7)
e = bpf.summarize("exec", lines, maps, 10)
check("exec 요약: 시작 3개(100,101,102)·종료만 본 55 제외, comm 별 생성 수/CPU", e["processes"] == 3 and e["by_comm"][0]["comm"] == "git" and e["by_comm"][0]["count"] == 2 and abs(e["by_comm"][0]["cpu_ms"] - 300.0) < 1e-6, str(e))
check("exec 요약: 자식 많이 만든 부모", e["top_parents"][0]["pid"] == 100 and e["top_parents"][0]["children"] == 2 and e["forks_per_s"] == 0.3)
ev = bpf.exec_spans(lines, lambda ns: 5000.0 + ns / 1e9)
sp = {s["pid"]: s for s in tr.build_spans(ev)}
check("exec_spans: 스팬 3개·순서", sorted(sp) == [100, 101, 102] and ev == sorted(ev, key=lambda x: x["t"]))
check("exec_spans: 자식은 부모 스팬 아래, 같은 trace, 부모 없는 pid 100 은 루트", sp[101]["parent"] == sp[100]["id"] and sp[102]["parent"] == sp[100]["id"] and sp[100]["parent"] is None and sp[101]["trace"] == sp[100]["trace"] == sp[100]["id"], str(sp))
check("exec_spans: 소요(ms)·CPU(ms)·상태", sp[101]["ms"] == 500.0 and sp[101]["attrs"]["cpu_ms"] == 250.0 and sp[101]["status"] == "ok" and sp[100]["comp"] == "bpf")
check("exec_spans 가 observectl trace 의 트리로 정렬됨", [(d, s["name"]) for d, s in tr.order_tree(list(sp.values()))] == [(0, "bash"), (1, "git"), (1, "git")])
pm = {"cpu": {"electron": 60, "claude": 30, "kworker": 10}, "kleaf": {"electron,\n  _raw_spin_unlock_irqrestore+0x1a\n": 20, "claude,\n  do_syscall_64+0x2\n": 5}, "uleaf": {"claude,\n  0x7f12\n": 9}}
pr = bpf.summarize("profile", [], pm, 10)
check("profile 요약: 프로세스별 CPU %, 커널/사용자 맨 위 함수", pr["cpu"][0] == {"comm": "electron", "count": 60, "pct": 60.0} and pr["kernel_leaf"][0]["frame"].startswith("_raw_spin_unlock") and pr["kernel_leaf"][0]["pct"] == 20.0 and pr["user_leaf"][0]["comm"] == "claude", str(pr))
ps = bpf.summarize("psr", [], {"atomic": {"Hyprland": 80, "kitty": 3}, "psr_flush": {"": 90}, "psr_invalidate": {"": 7}, "psr_exit": {"": 12}}, 10)
check("psr 요약: atomic 커밋 comm 별·flush/exit/activate(없으면 0)", ps["atomic_ioctl"][0] == {"comm": "Hyprland", "count": 80, "per_s": 8.0} and ps["psr_flush"] == 90 and ps["psr_invalidate"] == 7 and ps["psr_exit"] == 12 and ps["psr_activate"] == 0, str(ps))
nt = bpf.summarize("net", [], {"tcp_send": {"tailscaled": 4, "curl": 1}, "udp_recv": {"tailscaled": 6}}, 10)
check("net 요약: comm 별 합산·정렬", nt["rows"][0]["comm"] == "tailscaled" and nt["rows"][0]["tcp_send"] == 4 and nt["rows"][0]["udp_recv"] == 6 and nt["rows"][0]["per_s"] == 1.0, str(nt))
io_ = bpf.summarize("io", [], {"n": {"nix": 10, "git": 2}, "bytes": {"nix": 40960}}, 10)
check("io 요약: 횟수·바이트(없으면 0)", io_["rows"][0] == {"comm": "nix", "count": 10, "per_s": 1.0, "bytes": 40960} and io_["rows"][1]["bytes"] == 0)

# --- 수집기 job_bpf (가짜 bpftrace)
fake = os.path.join(TMP, "fake_bpftrace.py")
open(fake, "w").write('''#!/usr/bin/env python3
import json, sys
prog = sys.argv[sys.argv.index("-e") + 1]
if "FAIL" in prog: sys.stderr.write("ERROR: boom\\n"); sys.exit(1)
if "sched_process_exec" in prog:
    for l in %r: print(json.dumps({"type": "printf", "data": l + "\\n"}))
elif "sched_waking" in prog:
    print(json.dumps({"type": "map", "data": {"@w": {"a,b": 4}}}))
elif "drm_mode_atomic" in prog:
    print(json.dumps({"type": "map", "data": {"@atomic": {"Hyprland": 20}, "@psr_flush": 20}}))
''' % (lines,))
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
col.BPFTRACE = fake
r = col.job_bpf({"preset": "wake", "sec": 3})
check("job_bpf(wake): 요약", r["rc"] == 0 and r["summary"]["total"] == 4 and r["sec"] == 3, str(r))
r = col.job_bpf({"preset": "exec", "sec": 5})
check("job_bpf(exec): 요약 + 스팬 이벤트", r["summary"]["processes"] == 3 and len(r["events"]) == 6 and all("span" in e for e in r["events"]))
now = __import__("time").time()
check("job_bpf(exec): 이벤트 시각이 지금 근처(monotonic → epoch 변환)", all(abs(e["t"] - now) < 86400 * 400 for e in r["events"]))
r = col.job_bpf({"preset": "wake", "sec": 5, "comm": 'x"; exit(); //'})
check("job_bpf: 잘못된 comm 은 error(실행 안 함)", "error" in r and "comm" in r["error"])
r = col.job_bpf({"preset": "nope"})
check("job_bpf: 알 수 없는 프리셋은 error", "error" in r)
r = col.job_bpf({"preset": "wake", "sec": 999})
check("job_bpf: sec 는 60 으로 제한", r["sec"] == 60)
col.BPFTRACE = None
check("job_bpf: bpftrace 가 없으면 안내 error", "bpftrace" in col.job_bpf({"preset": "wake"})["error"])
col.BPFTRACE = fake
check("collector JOBS 에 bpf 등록", col.JOBS.get("bpf") is col.job_bpf)

# --- observectl bpf 출력
def _fake_request(typ, args, wait):
    """수집기 process_requests 와 같은 봉투 {id,type,ok,data|error}. (봉투 없이 돌려주던 이전 스텁은 실제 형식과 달라 CLI 버그를 못 잡았다)"""
    try:
        return {"id": "t", "type": typ, "ok": True, "data": col.JOBS[typ](args)}
    except Exception as e:
        return {"id": "t", "type": typ, "ok": False, "error": f"{type(e).__name__}: {e}"}
observe_cli.request = _fake_request
def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        observe_cli.main(["bpf", *argv])
    return buf.getvalue()
out = run("wake", "3")
check("observectl bpf wake: 표 출력", "깨우는 쪽" in out and "a,b" not in out.split("[쌍]")[0].split("[깨우는 쪽]")[0] and "합계 4회" in out, out)
out = run("psr", "3")
check("observectl bpf psr: flush 횟수와 Hyprland", "flush 20회" in out and "invalidate 0회" in out and "Hyprland" in out, out)
out = run("exec", "5")
check("observectl bpf exec: 생성 수와 스팬 기록 안내", "프로세스 3개 생성" in out and "스팬 3개" in out, out)
spans = tr.build_spans(list(core.iter_jsonl(core.state_dir(), "events", 0, 1e12)))
check("observectl bpf exec: 이벤트 로그에 프로세스 스팬이 실제로 적힘(comp=bpf)", sum(1 for s in spans if s["comp"] == "bpf") == 3)
n0 = len(list(core.iter_jsonl(core.state_dir(), "events", 0, 1e12)))
run("exec", "5", "--no-spans")
check("--no-spans 는 이벤트 로그에 쓰지 않음", len(list(core.iter_jsonl(core.state_dir(), "events", 0, 1e12))) == n0)
# 수집기 job 이 오류를 돌려주는 경우(잘못된 comm)도 CLI 가 안내만 하고 끝나야 한다
try:
    run("wake", "3", "--comm", 'x"; exit(); //')
    check("잘못된 comm: 오류 안내 후 종료", False)
except SystemExit as e:
    check("잘못된 comm: 오류 안내 후 종료", "comm" in str(e), str(e))
class _Env:  # 실제 process_requests 를 거친 결과 형식으로도 확인(requests 디렉터리 → results 파일)
    pass
col.BPFTRACE = fake
os.makedirs(core.REQ_DIR, exist_ok=True); os.makedirs(core.RES_DIR, exist_ok=True)
json.dump({"id": "bpf-real", "type": "bpf", "args": {"preset": "wake", "sec": 2}}, open(os.path.join(core.REQ_DIR, "bpf-real.json"), "w"))
col.process_requests()
real = json.load(open(os.path.join(core.RES_DIR, "bpf-real.json")))
check("process_requests 결과는 {ok, data} 봉투 — CLI 가 기대하는 형식", real["ok"] is True and real["data"]["summary"]["total"] == 4, str(real)[:200])
observe_cli.request = lambda typ, args, wait: real
out = run("wake", "2")
check("실제 결과 파일 형식으로 observectl bpf 가 출력", "합계 4회" in out, out)
finish("bpf")
