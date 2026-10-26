#!/usr/bin/env python3
"""procctl 시험: plan→apply→escalate, 계획 변조·만료·재적용 거부, 에이전트 모드(자기 세션 자식 트리 범위·상한·타인 계획 거부·소프트/하드 보호), 사람 모드, 읽기 전용 명령.
에이전트는 prctl 로 comm 을 `claude` 로 바꾼 가짜 세션 루트(드라이버)가 procctl 을 자식으로 실행해 **실제 조상 사슬**로 만든다.
사람 모드는 이중 fork 로 조상에 LLM 세션이 없게 한다. 종료 대상은 시험이 prctl 로 고유 이름을 붙여 띄운 프로세스뿐이다."""
import json, os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
TMP = tempfile.mkdtemp(prefix="procctl-test-")
ENV = dict(os.environ, PROCUI_STATE_DIR=os.path.join(TMP, "state"), PROCUI_CONFIG=os.path.join(TMP, "none.toml"))
os.environ.update(PROCUI_STATE_DIR=ENV["PROCUI_STATE_DIR"], PROCUI_CONFIG=ENV["PROCUI_CONFIG"])
for p in (ROOT, os.path.join(DATA, "observe"), os.path.join(DATA, "_testkit")):
    sys.path.insert(0, p)
import procplan as pp, procscan as ps
from harness import checker
check, finish = checker()
CTL = os.path.join(ROOT, "procctl.py")
TAG = f"pc{os.getpid() % 100000}"

DRIVER = r'''
import ctypes, json, subprocess, sys, time
ctypes.CDLL(None).prctl(15, b"claude")
kids = []
def child(name, ign=False):
    body = "trap '' TERM; while :; do sleep 1; done" if ign else f"import ctypes,time; ctypes.CDLL(None).prctl(15, b'{name}'); time.sleep(300)"
    return subprocess.Popen(["sh", "-c", body] if ign else [sys.executable, "-c", body])
for line in sys.stdin:
    c = json.loads(line)
    if c[0] == "spawn":
        pr = child(c[1], c[2] if len(c) > 2 else False); kids.append(pr); time.sleep(0.5); print(json.dumps({"pid": pr.pid}), flush=True)
    elif c[0] == "spawnmany":
        ps_ = [child(f"{c[1]}{i}") for i in range(c[2])]; kids += ps_; time.sleep(1.0); print(json.dumps({"pids": [p.pid for p in ps_]}), flush=True)
    elif c[0] == "run":
        r = subprocess.run([sys.executable, c[1]] + c[2:], capture_output=True, text=True)
        print(json.dumps({"rc": r.returncode, "out": r.stdout, "err": r.stderr}), flush=True)
    elif c[0] == "reap":
        print(json.dumps({"rc": [k.poll() for k in kids]}), flush=True)
    elif c[0] == "quit":
        for k in kids:
            k.kill(); k.wait()
        break
'''
agent = subprocess.Popen([sys.executable, "-c", DRIVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=ENV)
def ask(*cmd):
    agent.stdin.write(json.dumps(list(cmd)) + "\n"); agent.stdin.flush()
    return json.loads(agent.stdout.readline())
def actl(*args):
    r = ask("run", CTL, *args)
    return r["rc"], r["out"], r["err"]
HUMAN = r'''
import os, sys, subprocess, json
rfd, wfd = os.pipe()
if os.fork():
    os.close(wfd); buf = b""
    while True:
        d = os.read(rfd, 65536)
        if not d: break
        buf += d
    sys.stdout.write(buf.decode()); sys.exit(0)
os.close(rfd); os.setsid()
if os.fork(): os._exit(0)
r = subprocess.run([sys.executable, sys.argv[1]] + sys.argv[2:], capture_output=True, text=True)
os.write(wfd, json.dumps({"rc": r.returncode, "out": r.stdout, "err": r.stderr}).encode()); os._exit(0)
'''
def hctl(*args):
    r = subprocess.run([sys.executable, "-c", HUMAN, CTL, *args], capture_output=True, text=True, env=ENV, timeout=60)
    d = json.loads(r.stdout)
    return d["rc"], d["out"], d["err"]
def spawn_out(name):
    pr = subprocess.Popen([sys.executable, "-c", f"import ctypes,time; ctypes.CDLL(None).prctl(15, b'{name}'); time.sleep(300)"], env=ENV)
    time.sleep(0.5); return pr
def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False
def plans():
    d = os.path.join(TMP, "state", "plans")
    return {f[:-5]: json.load(open(os.path.join(d, f))) for f in os.listdir(d)} if os.path.isdir(d) else {}

# --- 사람 모드: 호출자 판별
rc, out, err = hctl("plan", "--filter", f"{TAG}zz")
check("사람 모드(이중 fork): 대상 지정은 있으나 일치하는 프로세스가 없으면 종료 코드 2", rc == 2, (rc, out, err))
rc, out, err = hctl("plan")
check("대상 지정 없는 plan 은 거부(전체 선택 없음) 종료 코드 2", rc == 2 and "지정해야" in err)
# --- 에이전트: 범위
a_child = ask("spawn", f"{TAG}in")["pid"]
outsider = spawn_out(f"{TAG}out")
rc, out, err = actl("plan", "--filter", TAG, "--json")
pl = json.loads(out)["data"] if rc == 0 else {}
check("에이전트 plan(기본 범위=자기 세션 자식 트리): 자기 자식만 대상, 바깥 프로세스는 범위 밖으로", rc == 0 and [t["pid"] for t in pl["targets"]] == [a_child] and [o["pid"] for o in pl["out_of_scope"]] == [outsider.pid] and pl["caller"]["agent"] is True and pl["selection"]["scope"] == "session", (rc, out[:300], err))
check("계획 파일이 저장되고 만료·서명이 있음(만료 약 10분)", pl["id"] in plans() and 590 < pl["expires"] - pl["created"] < 610 and len(pl["sig"]) == 64)
rc, out, err = actl("plan", "--pid", str(outsider.pid))
check("에이전트가 바깥 프로세스만 지정하면 범위 밖이라 대상 없음(2), 바깥 프로세스는 건드리지 않음", rc == 2 and "범위 밖" in out + err and alive(outsider.pid))
rc, out, err = actl("plan", "--pid", str(agent.pid), "--scope", "user")
check("에이전트가 자기 세션 루트(조상)를 지정하면 하드 보호로 전부 제외(4)", rc == 4 and "조상" in out + err, (rc, out, err))
# --- 에이전트 apply
rc, out, err = actl("apply", pl["id"], "--json")
res = json.loads(out)["data"]
check("에이전트 apply: SIGTERM 으로 자기 자식 종료, 바깥 프로세스는 생존", rc == 0 and res["sent"] == 1 and res["survivors"] == [] and outsider.poll() is None)
ask("reap")
check("자식이 실제로 종료됨(수거 후)", not alive(a_child) or ask("reap")["rc"][0] is not None)
rc, out, err = actl("apply", pl["id"])
check("같은 계획을 다시 apply 하면 거부(3, 이미 적용됨)", rc == 3 and "이미 적용" in err)
# --- 사람이 만든 계획을 에이전트가 적용 시도
b_child = ask("spawn", f"{TAG}b")["pid"]
rc, out, err = hctl("plan", "--pid", str(b_child), "--json")
hp = json.loads(out)["data"]
check("사람 모드 plan: caller.agent False, 기본 범위 user", rc == 0 and hp["caller"]["agent"] is False and hp["selection"]["scope"] == "user" and [t["pid"] for t in hp["targets"]] == [b_child], (rc, out[:200], err))
rc, out, err = actl("apply", hp["id"])
check("에이전트는 사람이 만든 계획을 적용할 수 없음(3)", rc == 3 and "자기 세션이 만든 계획" in err and alive(b_child))
# --- 변조·만료
d = plans()[hp["id"]]; d["targets"][0]["pid"] = outsider.pid
json.dump(d, open(os.path.join(TMP, "state", "plans", hp["id"] + ".json"), "w"))
rc, out, err = hctl("apply", hp["id"])
check("계획 파일의 대상을 고쳐 쓰면 apply 거부(3, 변조) — 바깥 프로세스 생존", rc == 3 and "변조" in err and outsider.poll() is None)
rc, out, err = hctl("plan", "--pid", str(b_child), "--ttl", "1", "--json")
short = json.loads(out)["data"]; time.sleep(2.2)
rc, out, err = hctl("apply", short["id"])
check("만료된 계획은 거부(3)", rc == 3 and "만료" in err and alive(b_child))
rc, out, err = hctl("apply", "zzzz0000"); rc2, _, err2 = hctl("apply", "../etc")
check("없는 계획 ID·경로 문자가 든 ID 는 거부(3)", rc == 3 and rc2 == 3)
# --- 사람 모드 apply·로그
rc, out, err = hctl("plan", "--pid", str(b_child), "--json"); good = json.loads(out)["data"]
rc, out, err = hctl("apply", good["id"], "--json")
check("사람 모드 apply: 종료", rc == 0 and json.loads(out)["data"]["sent"] == 1)
time.sleep(0.3); ask("reap")
rc, out, err = hctl("log", "--tail", "5")
check("log: 기록에 그룹(procctl:…)·이름·결과가 남고 명령 인자 키 없음", f"{TAG}b" in out and "procctl:" in out and "sent" in out and "argv" not in out and "cmdline" not in out)
# --- SIGTERM 무시 → escalate
ign = ask("spawn", f"{TAG}ign", True)["pid"]
rc, out, err = actl("plan", "--pid", str(ign), "--json"); ip = json.loads(out)["data"]
rc, out, err = actl("escalate", ip["id"])
check("apply 전 escalate 는 거부(3)", rc == 3 and "먼저" in err)
rc, out, err = actl("apply", ip["id"], "--term-wait", "0.5", "--json"); r1 = json.loads(out)["data"]
check("SIGTERM 을 무시하는 대상은 살아남은 목록에 남음(apply 는 성공 0)", rc == 0 and [s["pid"] for s in r1["survivors"]] == [ign] and alive(ign))
rc, out, err = actl("escalate", ip["id"], "--json"); r2 = json.loads(out)["data"]
time.sleep(0.5); ask("reap")
check("escalate: 살아남은 대상에 SIGKILL, 종료됨", rc == 0 and r2["signal"] == "SIGKILL" and r2["sent"] == 1 and r2["survivors"] == [])
# --- 상한
many = ask("spawnmany", f"{TAG}m", 21)["pids"]
rc, out, err = actl("plan", "--filter", f"{TAG}m")
check("에이전트 대상 21개 > 상한 20 이면 plan 거부(2)", rc == 2 and "상한" in err, (rc, out[:100], err))
rc, out, err = actl("plan", "--filter", f"{TAG}m", "--scope", "user")
check("상한은 --scope user 로도 못 넘음(2)", rc == 2 and "상한" in err)
rc, out, err = hctl("plan", "--filter", f"{TAG}m", "--json")
check("사람 모드는 상한 없이 21개 계획 가능", rc == 0 and len(json.loads(out)["data"]["targets"]) == 21)
# --- 하드 보호(사람 모드)
rc, out, err = hctl("plan", "--pid", "1", "--scope", "user")
check("PID 1 은 어떤 모드에서도 제외(4, init)", rc == 4 and "PID 1" in out + err)
# --- 소프트 보호 이름은 CLI 로 못 풂(옵션 자체가 없음)
rc, out, err = hctl("plan", "--pid", "1", "--override", "x")
check("override 옵션은 존재하지 않음(argparse 오류 2)", rc == 2)
# --- 읽기 전용 명령
rc, out, err = hctl("groups", "--view", "소유", "--json"); g = json.loads(out)["data"]
check("groups --json: 뷰·그룹 목록(합계·잠금 수)", rc == 0 and g["view"] == "소유" and g["groups"] and {"group", "n", "cpu", "rss_mib", "protected"} <= set(g["groups"][0]))
rc, out, err = hctl("groups", "--view", "없는뷰")
check("모르는 뷰는 2, 가능한 뷰 이름을 알려 줌", rc == 2 and "소유" in err)
rc, out, err = hctl("show", str(agent.pid), "--json"); sh = json.loads(out)["data"]
check("show <pid> --json: 그룹(뷰별)·보호 사유(LLM 세션)·세부", rc == 0 and sh["pid"] == agent.pid and "소유" in sh["groups"] and any(x["code"] == "llm-session" for x in sh["protection"]) and sh["detail"])
rc, out, err = hctl("show", "내 작업", "--view", "소유", "--json"); sg = json.loads(out)["data"]
check("show <그룹>: 구성원 목록", rc == 0 and sg["group"] == "내 작업" and sg["members"])
rc, out, err = hctl("show", "999999999")
check("없는 pid 는 2", rc == 2)
for pr_ in [outsider]:
    pr_.kill(); pr_.wait()
rc, out, err = hctl("apply", "zzznoplan", "--json"); env = json.loads(out)
check("--json 실패도 공통 봉투(ok=false·error·exit_code=종료 코드)", rc == 3 and env["ok"] is False and env["exit_code"] == 3 and env["command"] == "apply" and env["error"], out[:200])
agent.stdin.write(json.dumps(["quit"]) + "\n"); agent.stdin.flush(); agent.wait(timeout=10)
finish("procctl")
