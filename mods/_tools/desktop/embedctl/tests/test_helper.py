#!/usr/bin/env python3
"""embedctl root helper 시험.
(1) 인스턴스 이름 검증: 검증 실패 시 아무것도 만들지 않음. (2) status 결과 파일·flock·임시 파일 정리.
(3) 쓰기 동작(charge/mode/boost): 값·비트 보존·범위 거부·게이트 거부(쓰기 0회)·되읽기 불일치(롤백 시도)·EC 실패, 모두 메모리 속 EC 에뮬레이터 위에서.
(4) 끝단: CLI → 가짜 systemctl(= 실제 helper 코드, 파일에 EC 상태 유지) → 결과 파일 → CLI. restore 포함.
`python3 -I` 로 돌므로 sys.path 를 직접 구성한다."""
import fcntl, json, os, stat, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "ctlkit"), os.path.join(TOOLS, "_lib", "testkit")):
    sys.path.insert(0, p)
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp(prefix="embedctl-helper-test-")
RUN = os.path.join(T, "run"); BAT = os.path.join(T, "bat"); DMI = os.path.join(T, "dmi")
os.makedirs(BAT); os.makedirs(DMI)
os.environ.update(EMBEDCTL_RUN=RUN, EMBEDCTL_SYSFS_BAT=BAT, EMBEDCTL_DMI=DMI, EMBEDCTL_SETTLE="0")
def put(path, text):
    with open(path, "w") as f: f.write(text)
def reset_bat(end="0", start="-10"):
    put(f"{BAT}/charge_control_end_threshold", end + "\n"); put(f"{BAT}/charge_control_start_threshold", start + "\n")
    put(f"{BAT}/status", "Full\n"); put(f"{BAT}/capacity", "100\n")
reset_bat(); put(f"{DMI}/board_name", "MS-1592\n")
import embedlib as lib, embedhelper

FW = b"1592EMS1.1110629202209:52:28"
calls, writes = [], []
EC = {0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}
MODE = {"fw": FW, "ignore": False, "side_effect": False, "set_fail": False}
def emu(method, req):
    calls.append(method)
    if method == "get_ec": return (b"\x01\x81" + MODE["fw"]).ljust(32, b"\0")
    if method == "get_data": return bytes([1, EC[req[0]]]).ljust(32, b"\0")
    if method == "set_data":
        writes.append(("ec", req[0], req[1]))
        if MODE["set_fail"]: return bytes(32)
        if not MODE["ignore"]:
            EC[req[0]] = req[1]
            if MODE["side_effect"] and req[0] == 0xD2: EC[0x98] |= 0x80
        return b"\x01".ljust(32, b"\0")
    raise AssertionError("알 수 없는 메서드: " + method)
def sysfs_write(n):                       # msi_ec 연동 흉내: sysfs 파일과 EC[0xD7] 이 함께 바뀐다
    writes.append(("sysfs", n))
    if MODE["ignore"]: return
    put(f"{BAT}/charge_control_end_threshold", f"{n}\n"); put(f"{BAT}/charge_control_start_threshold", f"{n - 10}\n")
    EC[0xD7] = 0x80 + n
lib.wmi_call = emu; lib.sysfs_write_end = sysfs_write

def listing(): return sorted(os.listdir(RUN)) if os.path.isdir(RUN) else []
def result(inst): return json.load(open(os.path.join(RUN, f"last-{inst}.json")))
def reset_all():
    EC.update({0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}); reset_bat(); put(f"{DMI}/board_name", "MS-1592\n")
    MODE.update(fw=FW, ignore=False, side_effect=False, set_fail=False); calls.clear(); writes.clear()

# --- 1. 이름 검증: 실패하면 결과 파일도 락 파일도 만들지 않는다 ---------------------------------
for bad in ("", "charge-5000", "mode-user", "status\n", "../etc/passwd", "boost-on;reboot", "STATUS", "write-0xD7", "charge-80 "):
    rc = embedhelper.main(["embedhelper", bad])
    check(f"잘못된 이름 {bad!r}: 종료 코드 2", rc == 2, f"rc={rc}")
check("잘못된 이름만 보낸 뒤에는 아무 파일도 없음(디렉터리도 안 만듦)", listing() == [], str(listing()))
check("인자 수가 틀려도(0개·2개) 종료 코드 2", embedhelper.main(["embedhelper"]) == 2 and embedhelper.main(["embedhelper", "status", "extra"]) == 2)
check("잘못된 이름으로 EC 를 한 번도 건드리지 않음", calls == [] and writes == [], str((calls, writes)))

# --- 2. status ------------------------------------------------------------------------------
rc = embedhelper.main(["embedhelper", "status"]); res = result("status")
check("status: 종료 코드 0, 결과 ok·code 0", rc == 0 and res["ok"] is True and res["code"] == 0, str(res))
check("status: 결과에 펌웨어·EC 바이트", res["data"]["fw"] == "1592EMS1.111" and res["data"]["fw_date"] == "0629202209:52:28" and res["data"]["ec"] == {"d7": 0x80, "d2": 0xC1, "b98": 0x02}, str(res["data"]))
check("status: instance 와 time", res["instance"] == "status" and abs(res["time"] - time.time()) < 5)
check("status: EC 는 읽기(get_ec/get_data)만 호출, 쓰기 0회", set(calls) == {"get_ec", "get_data"} and writes == [], str((calls, writes)))
check("status: 임시 파일이 남지 않고 락 파일이 있음", [f for f in listing() if f.endswith(".tmp")] == [] and "lock" in listing(), str(listing()))
check("status: 결과 파일 권한 0644(사용자가 읽음)", stat.S_IMODE(os.stat(os.path.join(RUN, "last-status.json")).st_mode) == 0o644)

# --- 3-a. 충전 상한 ------------------------------------------------------------------------------
reset_all()
rc = embedhelper.main(["embedhelper", "charge-80"]); r = result("charge-80")
check("charge-80: 종료 코드 0, ok", rc == 0 and r["ok"] and r["code"] == 0, str(r))
check("charge-80: before 미설정(end 0, d7 0x80) → after end 80, d7 0xD0", r["before"]["end"] == 0 and r["before"]["d7"] == 0x80 and r["after"]["end"] == 80 and r["after"]["d7"] == 0xD0, str((r["before"], r["after"])))
check("charge-80: 쓰지 않은 d2·b98 불변", (r["after"]["d2"], r["after"]["b98"]) == (0xC1, 0x02))
check("charge-80: 쓰기는 sysfs 한 번뿐(EC set_data 0회)", writes == [("sysfs", 80)], str(writes))
rc = embedhelper.main(["embedhelper", "charge-100"]); r = result("charge-100")
check("charge-100: d7 0xE4", rc == 0 and r["after"]["d7"] == 0xE4 and r["after"]["end"] == 100)
rc = embedhelper.main(["embedhelper", "charge-50"]); check("charge-50(하한): 허용", rc == 0 and result("charge-50")["after"]["d7"] == 0xB2)
writes.clear()
for bad in ("charge-49", "charge-101", "charge-00", "charge-10"):
    rc = embedhelper.main(["embedhelper", bad]); r = result(bad)
    check(f"{bad}: 범위 밖이라 종료 코드 2, code 2, 쓰기 0회", rc == 2 and r["ok"] is False and r["code"] == 2 and "허용한다" in r["error"] and writes == [], f"rc={rc} {r.get('error')} {writes}")

# --- 3-b. 성능 모드: 하위 2비트만 바꾸고 나머지는 보존 -------------------------------------------------
reset_all()
for name, want in (("eco", 0xC2), ("sport", 0xC0), ("comfort", 0xC1)):
    rc = embedhelper.main(["embedhelper", f"mode-{name}"]); r = result(f"mode-{name}")
    check(f"mode-{name}: 0xD2 → 0x{want:02X}, d7·b98 불변", rc == 0 and r["after"]["d2"] == want and (r["after"]["d7"], r["after"]["b98"]) == (0x80, 0x02), str(r["after"]))
EC[0xD2] = 0xE5
rc = embedhelper.main(["embedhelper", "mode-eco"])
check("mode-eco: 다른 비트(0xE5 의 0x24)를 보존해 0xE6", rc == 0 and EC[0xD2] == 0xE6, f"0x{EC[0xD2]:02X}")
EC[0xD2] = 0xC1; writes.clear()
rc = embedhelper.main(["embedhelper", "mode-comfort"]); r = result("mode-comfort")
check("이미 같은 값이어도 성공(before == after)", rc == 0 and r["before"] == r["after"], str(r))

# --- 3-c. Cooler Boost: 비트7 만 -----------------------------------------------------------------
reset_all()
for start, inst, want in ((0x02, "boost-on", 0x82), (0x82, "boost-off", 0x02), (0x1A, "boost-on", 0x9A), (0x9A, "boost-off", 0x1A)):
    EC[0x98] = start
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"{inst}: 0x{start:02X} → 0x{want:02X}(다른 비트 보존), d7·d2 불변", rc == 0 and r["after"]["b98"] == want and (r["after"]["d7"], r["after"]["d2"]) == (0x80, 0xC1), str(r["after"]))

# --- 3-d. 게이트 거부: 쓰기 0회 -------------------------------------------------------------------
reset_all(); MODE["fw"] = b"1592EMS1.1090101202009:00:00"
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"미검증 펌웨어에서 {inst}: 종료 코드 3, code 3, 쓰기 0회", rc == 3 and r["code"] == 3 and "게이트 거부" in r["error"] and "검증되지 않은" in r["error"] and writes == [], f"rc={rc} {r['error']} {writes}")
reset_all(); put(f"{DMI}/board_name", "MS-9999\n")
rc = embedhelper.main(["embedhelper", "mode-eco"]); r = result("mode-eco")
check("다른 보드에서 쓰기: 종료 코드 3, 지원하지 않는 기종, 쓰기 0회", rc == 3 and "지원하지 않는 기종" in r["error"] and writes == [], str(r["error"]))
reset_all(); MODE["fw"] = b"\0"
rc = embedhelper.main(["embedhelper", "boost-on"])
check("펌웨어 문자열이 비어 있으면(unknown) 쓰기 거부", rc == 3 and writes == [])

# --- 3-e. 되읽기 불일치·EC 실패 ----------------------------------------------------------------------
reset_all(); MODE["ignore"] = True
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"쓰기가 반영되지 않으면 {inst}: 종료 코드 5, code 5, before/after 기록", rc == 5 and r["code"] == 5 and "되읽기" in r["error"] and r["before"] and r["after"], f"rc={rc} {r.get('error')}")
reset_all()
def sysfs_only(n):                         # sysfs 값은 바뀌는데 EC 바이트는 따라가지 않는 경우(msi_ec 가 EC 에 못 쓴 상황)
    writes.append(("sysfs", n)); put(f"{BAT}/charge_control_end_threshold", f"{n}\n")
lib.sysfs_write_end = sysfs_only
rc = embedhelper.main(["embedhelper", "charge-80"]); r = result("charge-80")
check("sysfs 는 80 인데 EC[0xD7] 이 따라가지 않으면 종료 코드 5 + EC[0xD7] 지적", rc == 5 and "EC[0xD7]" in r["error"] and r["after"]["end"] == 80 and r["after"]["d7"] == 0x80, f"rc={rc} {r.get('error')}")
lib.sysfs_write_end = sysfs_write
reset_all(); MODE["side_effect"] = True
rc = embedhelper.main(["embedhelper", "mode-eco"]); r = result("mode-eco")
check("다른 바이트가 함께 바뀌면(0x98) 종료 코드 5 + 이전 값으로 되돌리기 시도", rc == 5 and "b98" in r["error"] and writes[-1] == ("ec", 0xD2, 0xC1), f"rc={rc} {r.get('error')} {writes}")
reset_all(); MODE["set_fail"] = True
rc = embedhelper.main(["embedhelper", "boost-on"]); r = result("boost-on")
check("set_data 실패 응답 → 종료 코드 4", rc == 4 and r["code"] == 4 and "EC 접근 실패" in r["error"], str(r))
reset_all()
def sysfs_fail(n): raise lib.EcError("sysfs 쓰기 거부(시험)")
lib.sysfs_write_end = sysfs_fail
rc = embedhelper.main(["embedhelper", "charge-80"])
check("sysfs 쓰기 실패 → 종료 코드 4", rc == 4 and "sysfs 쓰기 거부" in result("charge-80")["error"])
lib.sysfs_write_end = sysfs_write

# --- 4. flock 직렬화: 다른 사람이 락을 잡고 있으면 helper 는 기다린다 ------------------------------
reset_all(); done = threading.Event()
with open(os.path.join(RUN, "lock"), "a") as held:
    fcntl.flock(held, fcntl.LOCK_EX)
    th = threading.Thread(target=lambda: (embedhelper.main(["embedhelper", "status"]), done.set()))
    th.start(); time.sleep(0.4)
    waited = not done.is_set()
    fcntl.flock(held, fcntl.LOCK_UN)
th.join(5)
check("락이 잡혀 있는 동안 helper 는 끝나지 않고 풀리면 끝남", waited and done.is_set())
check("모든 시험 뒤 임시 파일이 남지 않음", [f for f in listing() if f.endswith(".tmp")] == [], str(listing()))

# --- 5. 끝단: CLI → (가짜 systemctl = 실제 helper 코드, EC 상태는 파일에 유지) → 결과 파일 → CLI ------------
E2E = os.path.join(T, "e2e"); os.makedirs(E2E)
E_BAT = os.path.join(E2E, "bat"); E_DMI = os.path.join(E2E, "dmi"); os.makedirs(E_BAT); os.makedirs(E_DMI)
put(f"{E_DMI}/board_name", "MS-1592\n")
STATE, WLOG, SLOG = f"{E2E}/ec.json", f"{E2E}/writes.log", f"{E2E}/systemctl.log"
ENV = dict(os.environ, EMBEDCTL_RUN=f"{E2E}/run", EMBEDCTL_DMI=E_DMI, EMBEDCTL_SYSFS_BAT=E_BAT, EMBEDCTL_SYSFS_AC=f"{E2E}/noac", EMBEDCTL_HWMON=f"{E2E}/nohwmon",
           EMBEDCTL_DEBUGFS_ROOT=f"{E2E}/nodebugfs", EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl_e2e.py"), EMBEDCTL_SETTLE="0",
           EMBEDCTL_TLP_CONF=f"{E2E}/no-tlp.conf", EMBEDCTL_TLP_D=f"{E2E}/no-tlp.d", FAKE_EC_STATE=STATE, FAKE_WRITES_LOG=WLOG, PYTHONDONTWRITEBYTECODE="1")
ENV.pop("EMBEDCTL_WMI_DEBUGFS", None)
def e2e_reset(ec=None):
    for f in (WLOG, SLOG):
        if os.path.exists(f): os.remove(f)
    json.dump(ec or {"d7": 0x80, "d2": 0xC1, "b98": 0x02}, open(STATE, "w"))
    put(f"{E_BAT}/charge_control_end_threshold", "0\n" if not ec or ec["d7"] == 0x80 else f"{ec['d7'] - 0x80}\n"); put(f"{E_BAT}/charge_control_start_threshold", "-10\n")
    put(f"{E_BAT}/status", "Full\n"); put(f"{E_BAT}/capacity", "100\n")
def cli(*args, **extra):
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "embedctl.py"), *args], capture_output=True, text=True, env=dict(ENV, **extra))
    return r.returncode, r.stdout, r.stderr
def ec_state(): return json.load(open(STATE))
def wlog(): return open(WLOG).read() if os.path.exists(WLOG) else ""

e2e_reset()
e2e_reset({"d7": 0xD0, "d2": 0xC2, "b98": 0x82})
rc, out, err = cli("status", "--json")
d = json.loads(out)["data"] if rc == 0 else {}
check("끝단 status: access = helper, 게이트 verified, eco·부스트 켜짐·충전 80", rc == 0 and d["access"] == "helper" and d["gate"]["state"] == "verified" and d["mode"]["name"] == "eco" and d["boost"] is True and d["charge"]["limit"] == 80, f"rc={rc} {out[:300]} {err[:200]}")
check("끝단 status: sysfs(80)와 EC(0xD0) 일치하니 경고 없음", d["warnings"] == [], str(d.get("warnings")))
e2e_reset()

rc, out, err = cli("charge", "80")
check("끝단 charge 80: 종료 코드 0, 미설정(100%) → 80% 와 EC 바이트 표시", rc == 0 and "미설정(100%) → 80%" in out and "0x80 → 0xD0" in out, f"rc={rc} {out} {err}")
check("끝단 charge 80: 상태 파일 d7 0xD0, sysfs 80, 쓰기는 sysfs 한 번", ec_state()["d7"] == 0xD0 and open(f"{E_BAT}/charge_control_end_threshold").read().strip() == "80" and wlog().strip() == "sysfs end=80", wlog())
rc, out, err = cli("charge", "49"); check("끝단 charge 49: argparse 가 거부(종료 코드 2), 쓰기 없음", rc == 2 and "허용한다" in err and wlog().strip() == "sysfs end=80")
rc, out, err = cli("charge", "abc"); check("끝단 charge abc: 종료 코드 2", rc == 2)
rc, out, err = cli("charge", "100", "--json"); j = json.loads(out)
check("끝단 charge 100 --json: ok, data.action·before·after·changed", rc == 0 and j["ok"] and j["data"]["action"] == "charge" and j["data"]["before"]["end"] == 80 and j["data"]["after"]["end"] == 100 and j["data"]["changed"] is True, out[:300])
rc, out, err = cli("charge", "100"); check("끝단: 같은 값을 다시 쓰면 「이미 같은 값」", rc == 0 and "이미 같은 값" in out, out)

rc, out, err = cli("mode", "eco"); check("끝단 mode eco: comfort → eco, EC 0xC1 → 0xC2", rc == 0 and "comfort → eco" in out and "0xC1 → 0xC2" in out and ec_state()["d2"] == 0xC2, out)
rc, out, err = cli("mode", "user"); check("끝단 mode user: 선택지에 없어 종료 코드 2", rc == 2)
rc, out, err = cli("boost", "on"); check("끝단 boost on: 꺼짐 → 켜짐, 0x02 → 0x82", rc == 0 and "꺼짐 → 켜짐" in out and ec_state()["b98"] == 0x82, out)
rc, out, err = cli("boost", "off", "--json"); j = json.loads(out)
check("끝단 boost off --json", rc == 0 and j["data"]["after"]["b98"] == 0x02 and ec_state()["b98"] == 0x02)

# TLP 충돌 경고
put(f"{E2E}/tlp.conf", '# 주석\nSTOP_CHARGE_THRESH_BAT0="80"\n')
rc, out, err = cli("charge", "90", EMBEDCTL_TLP_CONF=f"{E2E}/tlp.conf")
check("TLP 가 충전 상한을 설정하고 있으면 (주의) 경고", rc == 0 and "(주의) TLP 설정에 STOP_CHARGE_THRESH_BAT0=80" in out, out)
rc, out, err = cli("charge", "90", "--json", EMBEDCTL_TLP_CONF=f"{E2E}/tlp.conf")
check("TLP 경고는 --json 에서 notes 와 data.warnings", any("STOP_CHARGE_THRESH_BAT0" in n for n in json.loads(out).get("notes", [])) and json.loads(out)["data"]["warnings"], out[:300])
put(f"{E2E}/tlp.conf", '#STOP_CHARGE_THRESH_BAT0="80"\n')
rc, out, err = cli("charge", "95", EMBEDCTL_TLP_CONF=f"{E2E}/tlp.conf")
check("주석 처리된 TLP 설정은 경고하지 않음", rc == 0 and "(주의)" not in out, out)

# 실패 경로의 종료 코드·메시지
e2e_reset()
rc, out, err = cli("charge", "80", FAKE_FW="1592EMS1.2220101202509:00:00")
check("끝단 게이트 거부: 종료 코드 3, 메시지에 게이트 거부, 쓰기 0회", rc == 3 and "게이트 거부" in err and wlog() == "" and ec_state()["d7"] == 0x80, f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", "--json", FAKE_FW="1592EMS1.2220101202509:00:00"); j = json.loads(out)
check("끝단 게이트 거부 --json: ok=false, exit_code 3, error", rc == 3 and j["ok"] is False and j["exit_code"] == 3 and "게이트 거부" in j["error"], out[:300])
rc, out, err = cli("boost", "on", FAKE_IGNORE_WRITES="1")
check("끝단 되읽기 불일치: 종료 코드 5", rc == 5 and "되읽기" in err, f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", FAKE_SET_FAIL="1")
check("끝단 EC 쓰기 실패: 종료 코드 4", rc == 4 and "EC 접근 실패" in err, f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), FAKE_RC="1")
check("끝단 polkit 거부 흉내(systemctl 실패): 종료 코드 4 + 이유", rc == 4 and "helper 실패" in err and "로컬 세션" in err, f"rc={rc} {err}")

# --- 6. restore ----------------------------------------------------------------------------------
e2e_reset({"d7": 0xD0, "d2": 0xC2, "b98": 0x82})                        # 스냅샷 대상 상태: 충전 80 · eco · 부스트 켜짐
SNAP = f"{E2E}/snap.json"
rc, out, err = cli("snapshot", "--out", SNAP)
snap = json.load(open(SNAP)); check("restore 준비: 스냅샷이 80·eco·부스트 켜짐을 담음", rc == 0 and snap["charge"]["limit"] == 80 and snap["mode"] == "eco" and snap["boost"] is True, str(snap))
e2e_reset({"d7": 0xE4, "d2": 0xC1, "b98": 0x02}); open(WLOG, "w").close()   # 지금 상태: 100 · comfort · 꺼짐
rc, out, err = cli("restore", SNAP, "--dry-run")
check("restore --dry-run: 계획 3줄을 보이고 쓰기 0회", rc == 0 and "복원 계획(적용하지 않음)" in out and out.count("[") >= 3 and "charge-80" in out and "mode-eco" in out and "boost-on" in out and wlog() == "", f"rc={rc} {out} {err}")
rc, out, err = cli("restore", SNAP)
check("restore: 3개 모두 적용(충전 80 · eco · 부스트 켜짐)", rc == 0 and ec_state() == {"d7": 0xD0, "d2": 0xC2, "b98": 0x82}, f"rc={rc} {ec_state()} {out} {err}")
rc, out, err = cli("restore", SNAP)
check("restore: 이미 같은 상태면 할 일 없음(쓰기 추가 없음)", rc == 0 and "할 일이 없다" in out, out)
rc, out, err = cli("restore", SNAP, "--json"); j = json.loads(out)
check("restore --json: plan 비어 있음", rc == 0 and j["data"]["plan"] == [] and j["data"]["applied"] == [])

# 검증 실패 시 아무것도 쓰지 않는다
def corrupted(**kw):
    s = json.loads(json.dumps(snap))
    for k, v in kw.items():
        if k == "fw": s["gate"]["fw"] = v
        elif k == "limit": s["charge"]["limit"] = v
        else: s[k] = v
    path = f"{E2E}/bad-{len(os.listdir(E2E))}.json"; json.dump(s, open(path, "w")); return path
e2e_reset({"d7": 0xE4, "d2": 0xC1, "b98": 0x02}); before_state = ec_state(); open(WLOG, "w").close()
for label, path, code, needle in (
    ("다른 펌웨어의 스냅샷", corrupted(fw="1592EMS1.109"), 3, "달라 복원하지 않는다"),
    ("user 모드", corrupted(mode="user"), 3, "복원하지 않는다"),
    ("충전 상한 49", corrupted(limit=49), 3, "허용 범위"),
    ("모드 없음(EC 를 못 읽고 찍은 스냅샷)", corrupted(mode=None), 3, "복원하지 않는다"),
    ("부스트 값 없음", corrupted(boost=None), 3, "Cooler Boost 값이 없다"),
    ("schema 2", corrupted(schema=2), 2, "형식이 아니다"),
):
    rc, out, err = cli("restore", path)
    check(f"restore {label}: 종료 코드 {code}, 이유, 쓰기 0회·상태 불변", rc == code and needle in err and wlog() == "" and ec_state() == before_state, f"rc={rc} {err} {wlog()}")
rc, out, err = cli("restore", f"{E2E}/없음.json"); check("restore: 없는 파일은 종료 코드 2", rc == 2 and "읽지 못했다" in err)
put(f"{E2E}/notjson.json", "{깨짐"); rc, out, err = cli("restore", f"{E2E}/notjson.json"); check("restore: JSON 이 아니면 종료 코드 2", rc == 2)
rc, out, err = cli("restore", SNAP, FAKE_FW="1592EMS1.2220101202509:00:00")
check("restore: 지금 게이트가 검증 상태가 아니면 종료 코드 3", rc == 3 and "게이트 거부" in err and wlog() == "")
rc, out, err = cli("restore", SNAP, EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), FAKE_RC="1")
check("restore: helper 를 못 쓰면(EC 를 못 읽음) 종료 코드 4", rc == 4 and "읽지 못해 복원할 수 없다" in err)

# 중간 실패: 첫 항목은 적용되고 둘째에서 실패하면 적용된 것과 이유를 알린다
e2e_reset({"d7": 0xE4, "d2": 0xC1, "b98": 0x02})
rc, out, err = cli("restore", SNAP, "--json", FAKE_FAIL_ON="mode-eco"); j = json.loads(out)
check("restore 중간 실패: 종료 코드 4, 이미 적용된 charge-80 을 알림, 상태는 부분 적용", rc == 4 and j["ok"] is False and "charge-80" in j["error"] and ec_state()["d7"] == 0xD0 and ec_state()["d2"] == 0xC1 and j["data"]["applied"][0]["instance"] == "charge-80", f"rc={rc} {out[:400]}")

# 스냅샷의 충전 상한이 「미설정」이었던 경우: 100% 로 복원하고 알림
e2e_reset({"d7": 0x80, "d2": 0xC1, "b98": 0x02})
rc, out, err = cli("snapshot", "--out", f"{E2E}/unset.json"); u = json.load(open(f"{E2E}/unset.json"))
check("미설정 스냅샷: charge.set=false, limit=100", u["charge"]["set"] is False and u["charge"]["limit"] == 100)
e2e_reset({"d7": 0xD0, "d2": 0xC1, "b98": 0x02})
rc, out, err = cli("restore", f"{E2E}/unset.json")
check("미설정 복원: 100% 로 쓰고 「미설정은 100% 로 복원」 안내", rc == 0 and ec_state()["d7"] == 0xE4 and "미설정은 sysfs 로 되돌릴 수 없어 100% 로 복원한다" in out, f"rc={rc} {out} {err}")

finish("embedctl helper")
