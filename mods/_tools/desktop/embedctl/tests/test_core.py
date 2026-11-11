#!/usr/bin/env python3
"""embedctl 코어 시험(읽기 전용 부분): 모드 문자열 해석, 게이트 판정, 상태 모으기(msi-ec 있음/없음/미검증/다른 기종), CLI 출력과 --json 봉투, 스냅샷, helper 인스턴스 이름 검증, 쓰기 인자 검증.
실제 sysfs·systemctl 을 건드리지 않는다: 가짜 msi-ec/BAT/hwmon/DMI 디렉터리와 가짜 systemctl 을 쓴다. 읽기는 helper 를 거치지 않으므로(lockdown 아래 sysfs 전환) systemctl 이 불리면 실패다.
`python3 -I` 로 돌므로 sys.path 를 직접 구성한다(선례: observe/process-manager/tests/test_procctl.py)."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "ctlkit"), os.path.join(TOOLS, "_lib", "testkit")):
    sys.path.insert(0, p)
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp(prefix="embedctl-test-")
def w(rel, text):
    path = os.path.join(T, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(text)

# --- 가짜 sysfs: msi-ec · BAT · AC · hwmon · DMI ------------------------------------------------
def reset_fs(end="0", start="-10", board="MS-1592", ac="1", mode="comfort", boost="off", fw="1592EMS1.111", avail="turbo\neco\ncomfort\n", msiec=True):
    shutil.rmtree(f"{T}/msiec", ignore_errors=True)
    if msiec:
        w("msiec/fw_version", fw + "\n"); w("msiec/fw_release_date", "2022-06-29T09:52:28\n")
        w("msiec/shift_mode", mode + "\n"); w("msiec/available_shift_modes", avail); w("msiec/cooler_boost", boost + "\n")
    w("bat/charge_control_end_threshold", end + "\n"); w("bat/charge_control_start_threshold", start + "\n")
    w("bat/status", "Full\n"); w("bat/capacity", "100\n"); w("ac/online", ac + "\n")
    w("dmi/board_name", board + "\n")
    w("hwmon/hwmon3/name", "msi_wmi_platform\n")
    for i, v in enumerate((2840, 2711, 0, 0), 1): w(f"hwmon/hwmon3/fan{i}_input", f"{v}\n")
    w("hwmon/hwmon5/name", "coretemp\n"); w("hwmon/hwmon5/temp1_input", "30000\n")
reset_fs()
os.makedirs(os.path.join(T, "run"), exist_ok=True)

LOG = f"{T}/systemctl.log"
ENV = dict(os.environ, EMBEDCTL_MSIEC=f"{T}/msiec", EMBEDCTL_SYSFS_BAT=f"{T}/bat", EMBEDCTL_SYSFS_AC=f"{T}/ac", EMBEDCTL_HWMON=f"{T}/hwmon", EMBEDCTL_DMI=f"{T}/dmi",
           EMBEDCTL_RUN=f"{T}/run", EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), FAKE_LOG=LOG, PYTHONDONTWRITEBYTECODE="1")
os.environ.update({k: v for k, v in ENV.items() if k.startswith("EMBEDCTL_")})
import embedlib as lib

CTL = os.path.join(ROOT, "embedctl.py")
def cli(*args, **extra):
    env = dict(ENV, **extra)
    r = subprocess.run([sys.executable, "-I", CTL, *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr
def systemctl_calls(): return open(LOG).read() if os.path.exists(LOG) else ""

# --- 1. 모드 문자열 해석 -----------------------------------------------------------------------
for text, name, known in (("turbo", "turbo", True), ("comfort", "comfort", True), ("eco", "eco", True),
                          ("unknown (192)", "sport", False), ("unknown (7)", "unknown", False), ("unspecified", "unspecified", False), ("???", "unknown", False)):
    m = lib.parse_mode(text)
    check(f"parse_mode({text!r}) = {name}, known={known}", m["name"] == name and m["known"] is known and m["text"] == text, str(m))
check("parse_mode: unknown (192) 의 원시 값은 192(레거시 sport = EC 0xC0)", lib.parse_mode("unknown (192)")["raw"] == 0xC0)
check("parse_mode: 읽지 못했으면(None) None", lib.parse_mode(None) is None)
check("mode_label: 레거시 sport 는 변경 불가를 밝힌다", "sport" in lib.mode_label("unknown (192)") and "변경 불가" in lib.mode_label("unknown (192)"))
check("mode_label: 알려진 이름은 그대로, 모르는 값은 원문", lib.mode_label("eco") == "eco" and lib.mode_label("unknown (7)") == "unknown (7)")
check("parse_bool: on/off 외에는 None", (lib.parse_bool("on"), lib.parse_bool("off"), lib.parse_bool("x"), lib.parse_bool(None)) == (True, False, None, None))
check("DISABLED_MODES 에 sport 가 있고 MODE_ORDER 에는 없다", "sport" in lib.DISABLED_MODES and "sport" not in lib.MODE_ORDER and lib.MODE_ORDER == ("turbo", "comfort", "eco"))

# --- 2. 게이트 ------------------------------------------------------------------------------------
check("gate: 검증된 기종+펌웨어 = verified", lib.evaluate_gate("MS-1592", "1592EMS1.111")["state"] == "verified")
check("gate: 목록 밖 펌웨어 = unverified_fw", lib.evaluate_gate("MS-1592", "1592EMS1.109")["state"] == "unverified_fw")
check("gate: 다른 보드 = unsupported_board", lib.evaluate_gate("MS-9999", "1592EMS1.111")["state"] == "unsupported_board")
check("gate: 펌웨어를 못 읽음(msi-ec 없음) = no_msi_ec", lib.evaluate_gate("MS-1592", None)["state"] == "no_msi_ec")
check("gate: 보드가 None 이어도 예외 없이 unsupported_board", lib.evaluate_gate(None, "x")["state"] == "unsupported_board")
check("GATE_REASON 에 no_msi_ec 가 있고 원인 둘(모듈 미적재·허용 목록 밖)을 말한다", "허용 목록" in lib.GATE_REASON["no_msi_ec"] and "올라오지" in lib.GATE_REASON["no_msi_ec"])

# --- 3. helper 인스턴스 이름 검증 --------------------------------------------------------------------
for ok in ("charge-80", "charge-100", "mode-eco", "mode-turbo", "mode-comfort", "boost-on", "boost-off"):
    check(f"인스턴스 허용: {ok}", bool(lib.INSTANCE_RE.match(ok)))
for bad in ("", "status", "charge-5000", "charge-8", "charge-80;x", "mode-user", "mode-sport", "mode-ECO", "boost-", "boost-on ", "../x", "charge-80\n", "charge--80", "write-0xD7"):
    check(f"인스턴스 거부: {bad!r}", not lib.INSTANCE_RE.match(bad))
try:
    lib.helper_call("mode-sport"); check("helper_call: 허용 밖 이름(sport)은 systemctl 호출 전에 거부", False)
except lib.HelperError:
    check("helper_call: 허용 밖 이름(sport)은 systemctl 호출 전에 거부", True)

# --- 4. 상태 모으기(helper 를 거치지 않는다) --------------------------------------------------------
st = lib.collect_status()
check("status: 게이트 verified, 펌웨어 1592EMS1.111, 날짜", st["gate"]["state"] == "verified" and st["gate"]["fw"] == "1592EMS1.111" and st["gate"]["fw_date"] == "2022-06-29T09:52:28", str(st["gate"]))
check("status: access·ec 필드는 더 이상 없다", "access" not in st and "ec" not in st, str(sorted(st)))
check("status: 모드 comfort, 쓸 수 있는 모드는 turbo·comfort·eco 순서", st["mode"]["name"] == "comfort" and st["mode"]["known"] and st["modes"]["writable"] == ["turbo", "comfort", "eco"] and st["modes"]["disabled"] == ["sport"], str((st["mode"], st["modes"])))
check("status: 부스트 꺼짐", st["boost"] is False)
check("status: 충전 상한 미설정 → limit 100", st["charge"]["set"] is False and st["charge"]["limit"] == 100 and st["charge"]["end"] == 0, str(st["charge"]))
check("status: 팬·온도·전원", st["fans"] == [2840, 2711, 0, 0] and st["temp_pkg"] == 30.0 and st["power"] == {"ac": True, "status": "Full", "capacity": 100}, str((st["fans"], st["temp_pkg"], st["power"])))
check("status: msi-ec 있음, 경고 없음", st["msi_ec"]["present"] is True and st["warnings"] == [], str((st["msi_ec"], st["warnings"])))
reset_fs(boost="on", end="80", start="70")
st = lib.collect_status()
check("status: 부스트 켜짐·충전 80", st["boost"] is True and st["charge"]["set"] and st["charge"]["limit"] == 80)
reset_fs(mode="unknown (192)")
st = lib.collect_status()
check("status: EC 가 0xC0(Windows 가 남긴 Sport)이면 sport(레거시)로 읽힌다 — 쓰기 선택지에는 없다", st["mode"]["name"] == "sport" and not st["mode"]["known"] and "sport" not in st["modes"]["writable"] and st["warnings"] == [], str((st["mode"], st["warnings"])))
reset_fs(mode="unknown (9)")
check("status: msi-ec 도 모르는 값은 경고", any("모르는 값" in x for x in lib.collect_status()["warnings"]))
reset_fs(avail="eco\ncomfort\n")
check("status: msi-ec 가 turbo 를 광고하지 않으면 쓸 수 있는 모드에서도 빠진다", lib.collect_status()["modes"]["writable"] == ["comfort", "eco"])
reset_fs(fw="1592EMS1.109")
st = lib.collect_status()
check("status: 목록 밖 펌웨어 → unverified_fw", st["gate"]["state"] == "unverified_fw" and st["gate"]["fw_verified"] is False)
reset_fs(board="MS-1500")
check("status: 다른 보드 → unsupported_board", lib.collect_status()["gate"]["state"] == "unsupported_board")
reset_fs(msiec=False)
st = lib.collect_status()
check("status: msi-ec 디렉터리가 없으면 예외 없이 no_msi_ec + 경고(이유 두 가지)", st["gate"]["state"] == "no_msi_ec" and st["msi_ec"]["present"] is False and st["mode"] is None and st["boost"] is None and st["modes"]["writable"] == []
      and any("허용 목록" in x for x in st["warnings"]), str((st["gate"], st["warnings"])))
check("status: msi-ec 가 없어도 사용자 권한 항목(충전 파일·팬·전원)은 그대로", st["charge"]["limit"] == 100 and st["fans"] == [2840, 2711, 0, 0] and st["power"]["ac"] is True)
reset_fs()

# --- 5. CLI: 읽기는 helper 없이 ----------------------------------------------------------------------
rc, out, err = cli("status", "--json")
env_ = json.loads(out) if out.strip().startswith("{") else {}
check("CLI status --json: 종료 코드 0, 봉투 키", rc == 0 and {"command", "ok", "structured", "exit_code", "data"} <= set(env_), f"rc={rc} {out[:200]} {err[:200]}")
d = env_.get("data", {})
check("CLI status: 게이트 verified, 모드 comfort", d.get("gate", {}).get("state") == "verified" and d.get("mode", {}).get("name") == "comfort", str(d.get("gate")))
check("CLI status: 봉투 command/exit_code", env_.get("command") == "embedctl status" and env_.get("exit_code") == 0 and env_.get("ok") is True)
check("CLI status: systemctl(helper)을 한 번도 부르지 않는다", systemctl_calls() == "", systemctl_calls())
rc, out, err = cli("status")
check("CLI 텍스트: 종료 코드 0 과 핵심 줄", rc == 0 and "1592EMS1.111 (검증됨)" in out and "comfort" in out and "미설정 = 100% 로 동작" in out and "fan1 2840" in out and "AC 연결 · Full 100%" in out, out)
check("CLI 텍스트: 모드 선택지에 turbo·comfort·eco 와 sport(사용 불가), EC 접근 줄 없음", "turbo · comfort · eco" in out and "sport(사용 불가)" in out and "EC 접근" not in out, out)
reset_fs(mode="unknown (192)")
rc, out, err = cli("status")
check("CLI 텍스트: 레거시 sport 는 「변경 불가」로 표시", rc == 0 and "sport(레거시 값, 변경 불가)" in out and "shift_mode=unknown (192)" in out, out)
reset_fs(msiec=False)
rc, out, err = cli("status", "--json"); d = json.loads(out)
check("msi-ec 없음: 종료 코드 0, 게이트 no_msi_ec, notes 에 이유", rc == 0 and d["data"]["gate"]["state"] == "no_msi_ec" and any("msi-ec 가 없다" in n for n in d.get("notes", [])), f"rc={rc} {out[:300]}")
rc, out, err = cli("status")
check("msi-ec 없음 텍스트: 알 수 없음 표시와 (주의)", rc == 0 and "알 수 없음(msi-ec 없음)" in out and "(주의)" in out, out)
reset_fs(fw="1592EMS1.222")
rc, out, err = cli("status")
check("미검증 펌웨어 텍스트에 「쓰기 거부」", "쓰기 거부" in out, out)
reset_fs()
check("읽기 CLI 들은 끝까지 systemctl 을 부르지 않았다", systemctl_calls() == "", systemctl_calls())

# --- 6. 스냅샷(schema 2) ---------------------------------------------------------------------------
snap_path = f"{T}/snap/s1.json"; os.makedirs(os.path.dirname(snap_path))
rc, out, err = cli("snapshot", "--out", snap_path)
s = json.load(open(snap_path))
check("snapshot --out: 파일 작성, schema 2, 값", rc == 0 and s["schema"] == 2 and s["mode"] == "comfort" and s["mode_text"] == "comfort" and s["boost"] is False and s["gate"]["state"] == "verified", f"rc={rc} {err[:200]}")
check("snapshot: EC 바이트(ec)는 없고 호스트·시각·전원 기록", "ec" not in s and bool(s["host"]) and "T" in s["time"] and s["power"]["status"] == "Full" and s["fans"] == [2840, 2711, 0, 0])
before = set(os.listdir(T))
rc, out, err = cli("snapshot")
check("snapshot(--out 없음): 표준출력에 JSON, 파일을 만들지 않음", rc == 0 and json.loads(out)["schema"] == 2 and set(os.listdir(T)) == before)
rc, out, err = cli("snapshot", "--json", "--out", snap_path)
check("snapshot --json: 봉투 data 에 스냅샷과 written 경로", rc == 0 and json.loads(out)["data"]["written"] == snap_path and json.loads(out)["data"]["schema"] == 2, out[:200])
rc, out, err = cli("snapshot", "--out", f"{T}/없는폴더/x.json")
check("snapshot: 쓸 수 없는 경로는 오류 종료(조용히 넘기지 않음)", rc != 0 and "스냅샷을 쓰지 못했다" in err, f"rc={rc} {err[:200]}")
reset_fs(mode="unknown (192)")
rc, out, err = cli("snapshot", "--json")
check("snapshot: 레거시 sport 는 mode=sport, mode_text 원문 기록", json.loads(out)["data"]["mode"] == "sport" and json.loads(out)["data"]["mode_text"] == "unknown (192)", out[:200])
reset_fs()

# --- 7. restore 계획(순수 함수: 아무것도 쓰지 않는다) -----------------------------------------------
def snapd(**kw):
    x = json.loads(json.dumps(s))
    for k, v in kw.items():
        if k == "fw": x["gate"]["fw"] = v
        elif k == "limit": x["charge"]["limit"] = v
        else: x[k] = v
    return x
now = lib.collect_status()
plan, notes = lib.restore_plan(snapd(mode="eco", boost=True, limit=80), now)
check("restore_plan: 충전·모드·부스트 3개 계획", [p["instance"] for p in plan] == ["charge-80", "mode-eco", "boost-on"], str(plan))
check("restore_plan: 같은 상태면 빈 계획", lib.restore_plan(snapd(), now)[0] == [])
for label, snap, code, needle in (
    ("schema 1(옛 형식)", snapd(schema=1), 2, "옛 형식"),
    ("schema 3", snapd(schema=3), 2, "형식이 아니다"),
    ("다른 펌웨어", snapd(fw="1592EMS1.109"), 3, "달라 복원하지 않는다"),
    ("sport 모드(쓸 수 없음)", snapd(mode="sport"), 3, "복원하지 않는다"),
    ("user 모드", snapd(mode="user"), 3, "복원하지 않는다"),
    ("모드 없음", snapd(mode=None), 3, "복원하지 않는다"),
    ("충전 상한 49", snapd(limit=49), 3, "허용 범위"),
    ("부스트 값 없음", snapd(boost=None), 3, "Cooler Boost 값이 없다"),
):
    try:
        lib.restore_plan(snap, now); check(f"restore_plan {label}: 거부", False)
    except lib.RestoreError as e:
        check(f"restore_plan {label}: 종료 코드 {code}, 이유", e.code == code and needle in e.msg, f"{e.code} {e.msg}")
reset_fs(msiec=False)
try:
    lib.restore_plan(snapd(), lib.collect_status()); check("restore_plan: msi-ec 없음이면 거부", False)
except lib.RestoreError as e:
    check("restore_plan: msi-ec 없음이면 게이트 거부(종료 코드 3)", e.code == 3 and "게이트 거부" in e.msg, e.msg)
reset_fs(mode="unknown (192)")
plan, _ = lib.restore_plan(snapd(mode="comfort"), lib.collect_status())
check("restore_plan: 지금 레거시 sport 여도 comfort 로 복원 계획을 세운다", any(p["instance"] == "mode-comfort" for p in plan), str(plan))
reset_fs()

# --- 8. 쓰기 명령의 인자 검증은 helper 를 부르기 전에 끝난다(argparse, 종료 코드 2) ---------------------------------
if os.path.exists(LOG): os.remove(LOG)
for cmdline in (("charge", "49"), ("charge", "101"), ("charge", "abc"), ("charge", "-5"), ("mode", "sport"), ("mode", "user"), ("mode", "foo"), ("boost", "maybe"), ("restore",)):
    rc, out, err = cli(*cmdline)
    check(f"{' '.join(cmdline)}: 사용법 오류 종료 코드 2", rc == 2, f"rc={rc} {err[:120]}")
check("잘못된 인자는 systemctl 을 한 번도 부르지 않음", systemctl_calls() == "", systemctl_calls())
rc, out, err = cli("charge", "49")
check("charge 49 의 오류 문구에 허용 범위와 「100 이 상한 없음」", "50~100" in err and "상한 없음" in err, err)
rc, out, err = cli("mode", "sport")
check("mode sport 의 오류 문구: 사용할 수 없는 이유와 선택지(turbo·comfort·eco)", "쓸 수 없다" in err and "turbo, comfort, eco" in err, err)
rc, out, err = cli("mode", "--help")
check("mode --help 에 sport 사용 불가 안내(줄바꿈은 무시)", "sport 는 사용 불가" in " ".join(out.split()), out)

finish("embedctl core")
