#!/usr/bin/env python3
"""embedctl root helper 시험: 인스턴스 이름 검증(검증 실패 시 아무것도 만들지 않음), status 결과 파일, 미구현 동작 거부(EC 쓰기 호출 0회), EC 실패 보고,
flock 직렬화, 임시 파일 정리, 그리고 CLI→systemctl→helper→결과 파일→CLI 끝단 경로(가짜 systemctl 이 실제 helper 코드를 에뮬레이터 위에서 실행).
`python3 -I` 로 돌므로 sys.path 를 직접 구성한다."""
import fcntl, json, os, stat, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "ctlkit"), os.path.join(TOOLS, "_lib", "testkit")):
    sys.path.insert(0, p)
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp(prefix="embedctl-helper-test-")
RUN = os.path.join(T, "run")
os.environ["EMBEDCTL_RUN"] = RUN
import embedlib as lib, embedhelper

FW = b"1592EMS1.1110629202209:52:28"
calls = []
EC = {0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}
def emu(method, req):
    calls.append(method)
    if method == "get_ec": return (b"\x01\x81" + FW).ljust(32, b"\0")
    if method == "get_data": return bytes([1, EC[req[0]]]).ljust(32, b"\0")
    raise AssertionError("쓰기 호출이 일어남: " + method)
lib.wmi_call = emu

def listing(): return sorted(os.listdir(RUN)) if os.path.isdir(RUN) else []

# --- 1. 이름 검증: 실패하면 결과 파일도 락 파일도 만들지 않는다 ---------------------------------
for bad in ("", "charge-5000", "mode-user", "status\n", "../etc/passwd", "boost-on;reboot", "STATUS", "write-0xD7", "charge-80 "):
    rc = embedhelper.main(["embedhelper", bad])
    check(f"잘못된 이름 {bad!r}: 종료 코드 2", rc == 2, f"rc={rc}")
check("잘못된 이름만 보낸 뒤에는 아무 파일도 없음(디렉터리도 안 만듦)", listing() == [], str(listing()))
check("인자 수가 틀려도(0개·2개) 종료 코드 2", embedhelper.main(["embedhelper"]) == 2 and embedhelper.main(["embedhelper", "status", "extra"]) == 2)
check("잘못된 이름으로 EC 를 한 번도 건드리지 않음", calls == [], str(calls))

# --- 2. status ------------------------------------------------------------------------------
rc = embedhelper.main(["embedhelper", "status"])
res = json.load(open(os.path.join(RUN, "last-status.json")))
check("status: 종료 코드 0, 결과 ok·code 0", rc == 0 and res["ok"] is True and res["code"] == 0, str(res))
check("status: 결과에 펌웨어·EC 바이트", res["data"]["fw"] == "1592EMS1.111" and res["data"]["fw_date"] == "0629202209:52:28" and res["data"]["ec"] == {"d7": 0x80, "d2": 0xC1, "b98": 0x02}, str(res["data"]))
check("status: 결과 instance 와 time", res["instance"] == "status" and abs(res["time"] - time.time()) < 5)
check("status: EC 는 읽기(get_ec/get_data)만 호출", set(calls) == {"get_ec", "get_data"}, str(calls))
check("status: 임시 파일이 남지 않고 락 파일이 있음", [f for f in listing() if f.endswith(".tmp")] == [] and "lock" in listing(), str(listing()))
check("status: 결과 파일 권한 0644(사용자가 읽음)", stat.S_IMODE(os.stat(os.path.join(RUN, "last-status.json")).st_mode) == 0o644)

# --- 3. 아직 구현되지 않은 동작은 EC 를 건드리지 않고 거부 --------------------------------------------
calls.clear()
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst])
    r = json.load(open(os.path.join(RUN, f"last-{inst}.json")))
    check(f"{inst}: 미구현이라 종료 코드 2, ok=false, 이유 기록", rc == 2 and r["ok"] is False and r["code"] == 2 and "아직 구현되지 않았다" in r["error"], str(r))
check("미구현 동작은 EC 호출 0회(읽기도 안 함)", calls == [], str(calls))

# --- 4. EC 접근 실패 -------------------------------------------------------------------------
def failing(method, req): return bytes(32)
lib.wmi_call = failing
rc = embedhelper.main(["embedhelper", "status"])
r = json.load(open(os.path.join(RUN, "last-status.json")))
check("EC 실패: 종료 코드 4, ok=false, code 4, 이유", rc == 4 and r["ok"] is False and r["code"] == 4 and "EC 접근 실패" in r["error"], str(r))
def raising(method, req): raise lib.EcError("debugfs 없음")
lib.wmi_call = raising
rc = embedhelper.main(["embedhelper", "status"])
check("EC 예외(debugfs 없음)도 종료 코드 4", rc == 4 and "debugfs 없음" in json.load(open(os.path.join(RUN, "last-status.json")))["error"])
lib.wmi_call = emu

# --- 5. flock 직렬화: 다른 사람이 락을 잡고 있으면 helper 는 기다린다 ------------------------------
done = threading.Event()
with open(os.path.join(RUN, "lock"), "a") as held:
    fcntl.flock(held, fcntl.LOCK_EX)
    th = threading.Thread(target=lambda: (embedhelper.main(["embedhelper", "status"]), done.set()))
    th.start(); time.sleep(0.4)
    waited = not done.is_set()
    fcntl.flock(held, fcntl.LOCK_UN)
th.join(5)
check("락이 잡혀 있는 동안 helper 는 끝나지 않고 풀리면 끝남", waited and done.is_set())

# --- 6. 끝단: CLI → (가짜 systemctl = 실제 helper 코드) → 결과 파일 → CLI ------------------------------
E2E_RUN = os.path.join(T, "e2e-run")
DMI = os.path.join(T, "dmi"); os.makedirs(DMI); open(os.path.join(DMI, "board_name"), "w").write("MS-1592\n")
BAT = os.path.join(T, "bat"); os.makedirs(BAT)
for n, v in (("charge_control_end_threshold", "80"), ("charge_control_start_threshold", "70"), ("status", "Charging"), ("capacity", "55")):
    open(os.path.join(BAT, n), "w").write(v + "\n")
ENV = dict(os.environ, EMBEDCTL_RUN=E2E_RUN, EMBEDCTL_DMI=DMI, EMBEDCTL_SYSFS_BAT=BAT, EMBEDCTL_SYSFS_AC=os.path.join(T, "noac"), EMBEDCTL_HWMON=os.path.join(T, "nohwmon"),
           EMBEDCTL_DEBUGFS_ROOT=os.path.join(T, "nodebugfs"), EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl_e2e.py"), PYTHONDONTWRITEBYTECODE="1")
ENV.pop("EMBEDCTL_WMI_DEBUGFS", None)
def cli(*args, **extra):
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "embedctl.py"), *args], capture_output=True, text=True, env=dict(ENV, **extra))
    return r.returncode, r.stdout, r.stderr
rc, out, err = cli("status", "--json", FAKE_EC=json.dumps({"d7": 0xD0, "d2": 0xC2, "b98": 0x82}))
d = json.loads(out)["data"] if rc == 0 else {}
check("끝단: access = helper, 게이트 verified", rc == 0 and d.get("access") == "helper" and d["gate"]["state"] == "verified", f"rc={rc} {out[:300]} {err[:200]}")
check("끝단: EC 값이 CLI 까지 전달(eco, 부스트 켜짐, 충전 80)", d["mode"]["name"] == "eco" and d["boost"] is True and d["ec"]["d7"] == 0xD0 and d["charge"]["limit"] == 80, str(d.get("mode")))
check("끝단: sysfs(80)와 EC(0xD0=80) 일치하므로 경고 없음", d["warnings"] == [], str(d.get("warnings")))
rc, out, err = cli("status", "--json", FAKE_EC=json.dumps({"d7": 0xE4}))
check("끝단: EC(100)와 sysfs(80) 불일치 경고", any("다르다" in w for w in json.loads(out)["data"]["warnings"]))
rc, out, err = cli("status", "--json", FAKE_EC_FAIL="1")
dd = json.loads(out)
check("끝단: helper 가 EC 실패를 보고하면 열화(종료 코드 0) + helper 의 이유가 메시지에 들어감", rc == 0 and dd["data"]["access"] == "unavailable" and any("EC 접근 실패" in n for n in dd.get("notes", [])), out[:400])
rc, out, err = cli("status", "--json", FAKE_FW="1592EMS1.2220101202509:00:00")
check("끝단: 목록 밖 펌웨어는 unverified_fw", json.loads(out)["data"]["gate"]["state"] == "unverified_fw" and json.loads(out)["data"]["gate"]["fw"] == "1592EMS1.222")

finish("embedctl helper")
