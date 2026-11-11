#!/usr/bin/env python3
"""embedctl root helper 시험(sysfs 전환판: msi-ec 가짜 디렉터리 위에서).
(1) 인스턴스 이름 검증: 검증 실패 시 아무것도 만들지 않음. (2) 쓰기 동작(charge/mode/boost): 값·다른 항목 불변·범위 거부·게이트 거부(쓰기 0회)·되읽기 불일치(롤백 시도)·sysfs 실패.
(3) flock 직렬화. (4) 끝단: CLI → 가짜 systemctl(= 실제 helper 코드, 상태는 디스크의 가짜 sysfs 파일) → 결과 파일 → CLI. restore 포함.
`python3 -I` 로 돌므로 sys.path 를 직접 구성한다."""
import fcntl, json, os, stat, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "ctlkit"), os.path.join(TOOLS, "_lib", "testkit")):
    sys.path.insert(0, p)
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp(prefix="embedctl-helper-test-")
RUN = os.path.join(T, "run"); BAT = os.path.join(T, "bat"); DMI = os.path.join(T, "dmi"); MSI = os.path.join(T, "msiec")
for d in (BAT, DMI, MSI):
    os.makedirs(d)
os.environ.update(EMBEDCTL_RUN=RUN, EMBEDCTL_SYSFS_BAT=BAT, EMBEDCTL_DMI=DMI, EMBEDCTL_MSIEC=MSI, EMBEDCTL_SETTLE="0")
def put(path, text):
    with open(path, "w") as f: f.write(text)
def reset_tree(end="0", start="-10", mode="comfort", boost="off", fw="1592EMS1.111", avail="turbo\neco\ncomfort\n", board="MS-1592", msiec=True):
    import shutil; shutil.rmtree(MSI, ignore_errors=True)
    if msiec:
        os.makedirs(MSI)
        put(f"{MSI}/fw_version", fw + "\n"); put(f"{MSI}/fw_release_date", "2022-06-29T09:52:28\n")
        put(f"{MSI}/shift_mode", mode + "\n"); put(f"{MSI}/available_shift_modes", avail); put(f"{MSI}/cooler_boost", boost + "\n")
    put(f"{BAT}/charge_control_end_threshold", end + "\n"); put(f"{BAT}/charge_control_start_threshold", start + "\n")
    put(f"{BAT}/status", "Full\n"); put(f"{BAT}/capacity", "100\n"); put(f"{DMI}/board_name", board + "\n")
reset_tree()
import embedlib as lib, embedhelper

writes = []
FLAGS = {"ignore": False, "side_effect": False, "fail": False}
def sysfs_write(path, text):               # msi-ec 커널 모듈의 부수 효과를 흉내 낸다
    name = os.path.basename(path); writes.append((name, text))
    if FLAGS["fail"]: raise lib.EcError(f"sysfs 쓰기 실패({path}): 시험용 강제 실패")
    if FLAGS["ignore"]: return
    if name == "charge_control_end_threshold":
        n = int(text); put(path, f"{n}\n"); put(f"{BAT}/charge_control_start_threshold", f"{n - 10}\n")
    else:
        put(path, text + "\n")
        if FLAGS["side_effect"] and name == "shift_mode": put(f"{MSI}/cooler_boost", "on\n")
lib.sysfs_write = sysfs_write

def listing(): return sorted(os.listdir(RUN)) if os.path.isdir(RUN) else []
def result(inst): return json.load(open(os.path.join(RUN, f"last-{inst}.json")))
def rd(name): return open(f"{MSI}/{name}").read().strip()
def reset_all(**kw):
    reset_tree(**kw); FLAGS.update(ignore=False, side_effect=False, fail=False); writes.clear()

# --- 1. 이름 검증: 실패하면 결과 파일도 락 파일도 만들지 않는다 ---------------------------------
for bad in ("", "status", "charge-5000", "charge-080", "charge-00", "mode-user", "mode-sport", "charge-80\n", "../etc/passwd", "boost-on;reboot", "CHARGE-80", "write-0xD7", "charge-80 "):
    rc = embedhelper.main(["embedhelper", bad])
    check(f"잘못된 이름 {bad!r}: 종료 코드 2", rc == 2, f"rc={rc}")
check("잘못된 이름만 보낸 뒤에는 아무 파일도 없음(디렉터리도 안 만듦)", listing() == [], str(listing()))
check("인자 수가 틀려도(0개·2개) 종료 코드 2", embedhelper.main(["embedhelper"]) == 2 and embedhelper.main(["embedhelper", "charge-80", "extra"]) == 2)
check("잘못된 이름으로 sysfs 를 한 번도 건드리지 않음", writes == [], str(writes))

# --- 2-a. 충전 상한 ------------------------------------------------------------------------------
reset_all()
rc = embedhelper.main(["embedhelper", "charge-80"]); r = result("charge-80")
check("charge-80: 종료 코드 0, ok, code 0", rc == 0 and r["ok"] and r["code"] == 0, str(r))
check("charge-80: before 미설정(end 0) → after end 80(start 70)", r["before"]["end"] == 0 and r["after"]["end"] == 80 and r["after"]["start"] == 70, str((r["before"], r["after"])))
check("charge-80: 쓰지 않은 모드·부스트 불변", (r["after"]["mode"], r["after"]["boost"]) == ("comfort", "off"))
check("charge-80: 쓰기는 end 파일 한 번뿐", writes == [("charge_control_end_threshold", "80")], str(writes))
check("charge-80: instance 와 time, 결과 파일 권한 0644", r["instance"] == "charge-80" and abs(r["time"] - time.time()) < 5 and stat.S_IMODE(os.stat(os.path.join(RUN, "last-charge-80.json")).st_mode) == 0o644)
check("charge-80: 임시 파일이 남지 않고 락 파일이 있음", [f for f in listing() if f.endswith(".tmp")] == [] and "lock" in listing(), str(listing()))
rc = embedhelper.main(["embedhelper", "charge-100"]); r = result("charge-100")
check("charge-100: end 100", rc == 0 and r["after"]["end"] == 100)
rc = embedhelper.main(["embedhelper", "charge-50"]); check("charge-50(하한): 허용", rc == 0 and result("charge-50")["after"]["end"] == 50)
writes.clear()
for bad in ("charge-49", "charge-101", "charge-10"):
    rc = embedhelper.main(["embedhelper", bad]); r = result(bad)
    check(f"{bad}: 범위 밖이라 종료 코드 2, code 2, 쓰기 0회", rc == 2 and r["ok"] is False and r["code"] == 2 and "허용한다" in r["error"] and writes == [], f"rc={rc} {r.get('error')} {writes}")

# --- 2-b. 성능 모드: msi-ec 가 광고하는 이름으로만 --------------------------------------------------
reset_all()
for name in ("eco", "turbo", "comfort"):
    rc = embedhelper.main(["embedhelper", f"mode-{name}"]); r = result(f"mode-{name}")
    check(f"mode-{name}: shift_mode → {name}, 충전·부스트 불변", rc == 0 and r["after"]["mode"] == name and rd("shift_mode") == name and (r["after"]["end"], r["after"]["boost"]) == (0, "off"), str(r["after"]))
check("mode: 쓰기는 shift_mode 파일에 이름 그대로(세 번)", writes == [("shift_mode", "eco"), ("shift_mode", "turbo"), ("shift_mode", "comfort")], str(writes))
writes.clear()
rc = embedhelper.main(["embedhelper", "mode-comfort"]); r = result("mode-comfort")
check("이미 같은 값이어도 성공(before == after)", rc == 0 and r["before"] == r["after"], str(r))
reset_all(avail="eco\ncomfort\n")
rc = embedhelper.main(["embedhelper", "mode-turbo"]); r = result("mode-turbo")
check("msi-ec 가 turbo 를 광고하지 않으면 종료 코드 3, 쓰기 0회", rc == 3 and "광고하지 않는다" in r["error"] and writes == [], f"rc={rc} {r.get('error')} {writes}")
reset_all(mode="unknown (192)")
rc = embedhelper.main(["embedhelper", "mode-comfort"]); r = result("mode-comfort")
check("레거시 sport(unknown (192))에서 comfort 로는 바꿀 수 있다(되돌릴 수는 없음을 문구가 알림)", rc == 0 and r["before"]["mode"] == "unknown (192)" and r["after"]["mode"] == "comfort"
      and "되돌릴 수 없다" in lib.action_summary("mode", r)[1], str(r))

# --- 2-c. Cooler Boost ---------------------------------------------------------------------------
reset_all()
for start, inst, want in (("off", "boost-on", "on"), ("on", "boost-off", "off")):
    put(f"{MSI}/cooler_boost", start + "\n")
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"{inst}: {start} → {want}, 충전·모드 불변", rc == 0 and r["after"]["boost"] == want and (r["after"]["end"], r["after"]["mode"]) == (0, "comfort"), str(r["after"]))

# --- 2-d. 게이트 거부: 쓰기 0회 -------------------------------------------------------------------
reset_all(fw="1592EMS1.109")
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"미검증 펌웨어에서 {inst}: 종료 코드 3, code 3, 쓰기 0회", rc == 3 and r["code"] == 3 and "게이트 거부" in r["error"] and "검증되지 않은" in r["error"] and writes == [], f"rc={rc} {r['error']} {writes}")
reset_all(board="MS-9999")
rc = embedhelper.main(["embedhelper", "mode-eco"]); r = result("mode-eco")
check("다른 보드에서 쓰기: 종료 코드 3, 지원하지 않는 기종, 쓰기 0회", rc == 3 and "지원하지 않는 기종" in r["error"] and writes == [], str(r["error"]))
reset_all(msiec=False)
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"msi-ec 가 없으면 {inst}: 종료 코드 3, 이유에 msi-ec 와 허용 목록, 쓰기 0회", rc == 3 and "msi-ec 가 없다" in r["error"] and "허용 목록" in r["error"] and writes == [], f"rc={rc} {r['error']} {writes}")

# --- 2-e. 되읽기 불일치·sysfs 실패 ----------------------------------------------------------------------
reset_all(); FLAGS["ignore"] = True
for inst in ("charge-80", "mode-eco", "boost-on"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"쓰기가 반영되지 않으면 {inst}: 종료 코드 5, code 5, before/after 기록", rc == 5 and r["code"] == 5 and "되읽기" in r["error"] and r["before"] and r["after"], f"rc={rc} {r.get('error')}")
reset_all(); FLAGS["side_effect"] = True
rc = embedhelper.main(["embedhelper", "mode-eco"]); r = result("mode-eco")
check("모드를 쓰자 다른 항목(부스트)이 함께 바뀌면 종료 코드 5 + 부스트 지적 + 이전 모드로 되돌리기 시도", rc == 5 and "boost" in r["error"] and writes[-1] == ("shift_mode", "comfort"), f"rc={rc} {r.get('error')} {writes}")
reset_all(mode="unknown (192)"); FLAGS["ignore"] = True
rc = embedhelper.main(["embedhelper", "mode-eco"])
check("이전 값이 모르는 값(unknown)이면 되돌리기를 시도하지 않는다(쓸 수 없는 값을 쓰지 않음)", rc == 5 and writes == [("shift_mode", "eco")], str(writes))
reset_all(); FLAGS["fail"] = True
for inst in ("charge-80", "boost-on", "mode-eco"):
    rc = embedhelper.main(["embedhelper", inst]); r = result(inst)
    check(f"sysfs 쓰기 실패 → {inst}: 종료 코드 4, code 4", rc == 4 and r["code"] == 4 and "sysfs 접근 실패" in r["error"], str(r))
reset_all()

# --- 3. flock 직렬화: 다른 사람이 락을 잡고 있으면 helper 는 기다린다 ------------------------------
done = threading.Event()
with open(os.path.join(RUN, "lock"), "a") as held:
    fcntl.flock(held, fcntl.LOCK_EX)
    th = threading.Thread(target=lambda: (embedhelper.main(["embedhelper", "boost-on"]), done.set()))
    th.start(); time.sleep(0.4)
    waited = not done.is_set()
    fcntl.flock(held, fcntl.LOCK_UN)
th.join(5)
check("락이 잡혀 있는 동안 helper 는 끝나지 않고 풀리면 끝남", waited and done.is_set())
check("모든 시험 뒤 임시 파일이 남지 않음", [f for f in listing() if f.endswith(".tmp")] == [], str(listing()))

# --- 4. 끝단: CLI → (가짜 systemctl = 실제 helper 코드, 상태는 디스크의 가짜 sysfs) → 결과 파일 → CLI ---------
E2E = os.path.join(T, "e2e"); os.makedirs(E2E)
E_BAT, E_DMI, E_MSI = (os.path.join(E2E, x) for x in ("bat", "dmi", "msiec")); [os.makedirs(d) for d in (E_BAT, E_DMI, E_MSI)]
put(f"{E_DMI}/board_name", "MS-1592\n")
WLOG, SLOG = f"{E2E}/writes.log", f"{E2E}/systemctl.log"
ENV = dict(os.environ, EMBEDCTL_RUN=f"{E2E}/run", EMBEDCTL_DMI=E_DMI, EMBEDCTL_SYSFS_BAT=E_BAT, EMBEDCTL_MSIEC=E_MSI, EMBEDCTL_SYSFS_AC=f"{E2E}/noac", EMBEDCTL_HWMON=f"{E2E}/nohwmon",
           EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl_e2e.py"), EMBEDCTL_SETTLE="0", EMBEDCTL_TLP_CONF=f"{E2E}/no-tlp.conf", EMBEDCTL_TLP_D=f"{E2E}/no-tlp.d",
           FAKE_WRITES_LOG=WLOG, PYTHONDONTWRITEBYTECODE="1")
def e2e_reset(end="0", mode="comfort", boost="off", fw="1592EMS1.111", avail="turbo\neco\ncomfort\n"):
    for f in (WLOG, SLOG):
        if os.path.exists(f): os.remove(f)
    put(f"{E_MSI}/fw_version", fw + "\n"); put(f"{E_MSI}/fw_release_date", "2022-06-29T09:52:28\n"); put(f"{E_MSI}/shift_mode", mode + "\n")
    put(f"{E_MSI}/available_shift_modes", avail); put(f"{E_MSI}/cooler_boost", boost + "\n")
    put(f"{E_BAT}/charge_control_end_threshold", end + "\n"); put(f"{E_BAT}/charge_control_start_threshold", ("-10" if end == "0" else str(int(end) - 10)) + "\n")
    put(f"{E_BAT}/status", "Full\n"); put(f"{E_BAT}/capacity", "100\n")
def cli(*args, **extra):
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "embedctl.py"), *args], capture_output=True, text=True, env=dict(ENV, **extra))
    return r.returncode, r.stdout, r.stderr
def e_rd(name): return open(f"{E_MSI}/{name}").read().strip()
def e_end(): return open(f"{E_BAT}/charge_control_end_threshold").read().strip()
def wlog(): return open(WLOG).read() if os.path.exists(WLOG) else ""

e2e_reset(end="80", mode="eco", boost="on")
rc, out, err = cli("status", "--json")
d = json.loads(out)["data"] if rc == 0 else {}
check("끝단 status: helper 없이 읽힘 — 게이트 verified, eco·부스트 켜짐·충전 80", rc == 0 and d["gate"]["state"] == "verified" and d["mode"]["name"] == "eco" and d["boost"] is True and d["charge"]["limit"] == 80, f"rc={rc} {out[:300]} {err[:200]}")
check("끝단 status: 읽기만으로는 systemctl 을 부르지 않음", not os.path.exists(SLOG) and wlog() == "")
e2e_reset()

rc, out, err = cli("charge", "80")
check("끝단 charge 80: 종료 코드 0, 미설정(100%) → 80%", rc == 0 and "미설정(100%) → 80%" in out, f"rc={rc} {out} {err}")
check("끝단 charge 80: sysfs end 80, 쓰기는 end 파일 한 번", e_end() == "80" and wlog().strip() == "sysfs charge_control_end_threshold=80", wlog())
rc, out, err = cli("charge", "49"); check("끝단 charge 49: argparse 가 거부(종료 코드 2), 쓰기 없음", rc == 2 and "허용한다" in err and wlog().strip() == "sysfs charge_control_end_threshold=80")
rc, out, err = cli("charge", "abc"); check("끝단 charge abc: 종료 코드 2", rc == 2)
rc, out, err = cli("charge", "100", "--json"); j = json.loads(out)
check("끝단 charge 100 --json: ok, data.action·before·after·changed", rc == 0 and j["ok"] and j["data"]["action"] == "charge" and j["data"]["before"]["end"] == 80 and j["data"]["after"]["end"] == 100 and j["data"]["changed"] is True, out[:300])
rc, out, err = cli("charge", "100"); check("끝단: 같은 값을 다시 쓰면 「이미 같은 값」", rc == 0 and "이미 같은 값" in out, out)

rc, out, err = cli("mode", "eco"); check("끝단 mode eco: comfort → eco", rc == 0 and "comfort → eco" in out and e_rd("shift_mode") == "eco", out)
rc, out, err = cli("mode", "turbo"); check("끝단 mode turbo: eco → turbo", rc == 0 and "eco → turbo" in out and e_rd("shift_mode") == "turbo", out)
rc, out, err = cli("mode", "sport"); check("끝단 mode sport: 사용 불가라 종료 코드 2, 쓰기 없음", rc == 2 and "쓸 수 없다" in err and e_rd("shift_mode") == "turbo", err)
rc, out, err = cli("mode", "user"); check("끝단 mode user: 선택지에 없어 종료 코드 2", rc == 2)
rc, out, err = cli("boost", "on"); check("끝단 boost on: 꺼짐 → 켜짐", rc == 0 and "꺼짐 → 켜짐" in out and e_rd("cooler_boost") == "on", out)
rc, out, err = cli("boost", "off", "--json"); j = json.loads(out)
check("끝단 boost off --json", rc == 0 and j["data"]["after"]["boost"] == "off" and e_rd("cooler_boost") == "off")

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
e2e_reset(fw="1592EMS1.222")
rc, out, err = cli("charge", "80")
check("끝단 게이트 거부(미검증 펌웨어): 종료 코드 3, 메시지, 쓰기 0회", rc == 3 and "게이트 거부" in err and wlog() == "" and e_end() == "0", f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", "--json"); j = json.loads(out)
check("끝단 게이트 거부 --json: ok=false, exit_code 3, error", rc == 3 and j["ok"] is False and j["exit_code"] == 3 and "게이트 거부" in j["error"], out[:300])
import shutil; shutil.rmtree(E_MSI); os.makedirs(E_MSI)
rc, out, err = cli("boost", "on")
check("끝단 msi-ec 없음: 종료 코드 3 + 모듈/허용 목록 이유, 쓰기 0회", rc == 3 and "msi-ec 가 없다" in err and wlog() == "", f"rc={rc} {err}")
e2e_reset()
rc, out, err = cli("boost", "on", FAKE_IGNORE_WRITES="1")
check("끝단 되읽기 불일치: 종료 코드 5", rc == 5 and "되읽기" in err, f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", FAKE_SET_FAIL="1")
check("끝단 sysfs 쓰기 실패: 종료 코드 4", rc == 4 and "sysfs 접근 실패" in err, f"rc={rc} {err}")
rc, out, err = cli("mode", "eco", EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), FAKE_RC="1")
check("끝단 polkit 거부 흉내(systemctl 실패): 종료 코드 4 + 이유", rc == 4 and "helper 실패" in err and "로컬 세션" in err, f"rc={rc} {err}")

# --- 5. restore ----------------------------------------------------------------------------------
e2e_reset(end="80", mode="eco", boost="on")                              # 스냅샷 대상 상태: 충전 80 · eco · 부스트 켜짐
SNAP = f"{E2E}/snap.json"
rc, out, err = cli("snapshot", "--out", SNAP)
snap = json.load(open(SNAP)); check("restore 준비: 스냅샷이 80·eco·부스트 켜짐을 담음", rc == 0 and snap["charge"]["limit"] == 80 and snap["mode"] == "eco" and snap["boost"] is True and snap["schema"] == 2, str(snap))
e2e_reset(end="100", mode="comfort", boost="off"); open(WLOG, "w").close()   # 지금 상태: 100 · comfort · 꺼짐
rc, out, err = cli("restore", SNAP, "--dry-run")
check("restore --dry-run: 계획 3줄을 보이고 쓰기 0회", rc == 0 and "복원 계획(적용하지 않음)" in out and out.count("[") >= 3 and "charge-80" in out and "mode-eco" in out and "boost-on" in out and wlog() == "", f"rc={rc} {out} {err}")
rc, out, err = cli("restore", SNAP)
check("restore: 3개 모두 적용(충전 80 · eco · 부스트 켜짐)", rc == 0 and e_end() == "80" and e_rd("shift_mode") == "eco" and e_rd("cooler_boost") == "on", f"rc={rc} {out} {err}")
rc, out, err = cli("restore", SNAP)
check("restore: 이미 같은 상태면 할 일 없음", rc == 0 and "할 일이 없다" in out, out)
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
e2e_reset(end="100", mode="comfort", boost="off"); open(WLOG, "w").close()
before_files = (e_end(), e_rd("shift_mode"), e_rd("cooler_boost"))
for label, path, code, needle in (
    ("다른 펌웨어의 스냅샷", corrupted(fw="1592EMS1.109"), 3, "달라 복원하지 않는다"),
    ("sport 모드(쓸 수 없음)", corrupted(mode="sport"), 3, "복원하지 않는다"),
    ("user 모드", corrupted(mode="user"), 3, "복원하지 않는다"),
    ("충전 상한 49", corrupted(limit=49), 3, "허용 범위"),
    ("모드 없음", corrupted(mode=None), 3, "복원하지 않는다"),
    ("부스트 값 없음", corrupted(boost=None), 3, "Cooler Boost 값이 없다"),
    ("schema 1(옛 WMI 형식)", corrupted(schema=1), 2, "옛 형식"),
):
    rc, out, err = cli("restore", path)
    check(f"restore {label}: 종료 코드 {code}, 이유, 쓰기 0회·상태 불변", rc == code and needle in err and wlog() == "" and (e_end(), e_rd("shift_mode"), e_rd("cooler_boost")) == before_files, f"rc={rc} {err} {wlog()}")
rc, out, err = cli("restore", f"{E2E}/없음.json"); check("restore: 없는 파일은 종료 코드 2", rc == 2 and "읽지 못했다" in err)
put(f"{E2E}/notjson.json", "{깨짐"); rc, out, err = cli("restore", f"{E2E}/notjson.json"); check("restore: JSON 이 아니면 종료 코드 2", rc == 2)
e2e_reset(fw="1592EMS1.222")
rc, out, err = cli("restore", SNAP)
check("restore: 지금 게이트가 검증 상태가 아니면 종료 코드 3", rc == 3 and "게이트 거부" in err and wlog() == "")
rc, out, err = cli("restore", SNAP, EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), FAKE_RC="1")
check("restore: 게이트가 막혀 있으면 helper 를 부르기 전에 거부(종료 코드 3)", rc == 3)

# 중간 실패: 첫 항목은 적용되고 둘째에서 실패하면 적용된 것과 이유를 알린다
e2e_reset(end="100", mode="comfort", boost="off")
rc, out, err = cli("restore", SNAP, "--json", FAKE_FAIL_ON="mode-eco"); j = json.loads(out)
check("restore 중간 실패: 종료 코드 4, 이미 적용된 charge-80 을 알림, 상태는 부분 적용", rc == 4 and j["ok"] is False and "charge-80" in j["error"] and e_end() == "80" and e_rd("shift_mode") == "comfort" and j["data"]["applied"][0]["instance"] == "charge-80", f"rc={rc} {out[:400]}")

# 스냅샷의 충전 상한이 「미설정」이었던 경우: 100% 로 복원하고 알림
e2e_reset(end="0")
rc, out, err = cli("snapshot", "--out", f"{E2E}/unset.json"); u = json.load(open(f"{E2E}/unset.json"))
check("미설정 스냅샷: charge.set=false, limit=100", u["charge"]["set"] is False and u["charge"]["limit"] == 100)
e2e_reset(end="80")
rc, out, err = cli("restore", f"{E2E}/unset.json")
check("미설정 복원: 100% 로 쓰고 「미설정은 100% 로 복원」 안내", rc == 0 and e_end() == "100" and "미설정은 sysfs 로 되돌릴 수 없어 100% 로 복원한다" in out, f"rc={rc} {out} {err}")

finish("embedctl helper")
