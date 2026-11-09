#!/usr/bin/env python3
"""embedctl 코어 시험(읽기 전용 부분): 펌웨어 문자열 파싱, 게이트 판정, 상태 모으기(직접/helper/불가), CLI 출력과 --json 봉투, 스냅샷, helper 인스턴스 이름 검증.
실제 EC·sysfs·systemctl 을 건드리지 않는다: 가짜 sysfs/hwmon/DMI 디렉터리, 가짜 systemctl, 메모리 속 EC 에뮬레이터를 쓴다.
`python3 -I` 로 돌므로 sys.path 를 직접 구성한다(선례: observe/process-manager/tests/test_procctl.py)."""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); TOOLS = os.path.dirname(os.path.dirname(ROOT))
for p in (ROOT, os.path.join(TOOLS, "_lib", "ctlkit"), os.path.join(TOOLS, "_lib", "testkit")):
    sys.path.insert(0, p)
from harness import checker
check, finish = checker()

T = tempfile.mkdtemp(prefix="embedctl-test-")
def w(rel, text):
    path = os.path.join(T, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(text)

# --- 가짜 sysfs/hwmon/DMI ---------------------------------------------------------------
def reset_fs(end="0", start="-10", board="MS-1592", ac="1"):
    w("bat/charge_control_end_threshold", end + "\n"); w("bat/charge_control_start_threshold", start + "\n")
    w("bat/status", "Full\n"); w("bat/capacity", "100\n"); w("ac/online", ac + "\n")
    w("dmi/board_name", board + "\n")
    w("hwmon/hwmon3/name", "msi_wmi_platform\n")
    for i, v in enumerate((2840, 2711, 0, 0), 1): w(f"hwmon/hwmon3/fan{i}_input", f"{v}\n")
    w("hwmon/hwmon5/name", "coretemp\n"); w("hwmon/hwmon5/temp1_input", "30000\n")
reset_fs()
os.makedirs(os.path.join(T, "run"), exist_ok=True); os.makedirs(os.path.join(T, "wmi"), exist_ok=True)
for n in ("get_data", "set_data", "get_ec"): w("wmi/" + n, "")

ENV = dict(os.environ, EMBEDCTL_SYSFS_BAT=f"{T}/bat", EMBEDCTL_SYSFS_AC=f"{T}/ac", EMBEDCTL_HWMON=f"{T}/hwmon", EMBEDCTL_DMI=f"{T}/dmi",
           EMBEDCTL_RUN=f"{T}/run", EMBEDCTL_SYSTEMCTL=os.path.join(HERE, "fake_systemctl.py"), EMBEDCTL_DEBUGFS_ROOT=f"{T}/nodebugfs",
           PYTHONDONTWRITEBYTECODE="1")
ENV.pop("EMBEDCTL_WMI_DEBUGFS", None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("EMBEDCTL_")})
import embedlib as lib

CTL = os.path.join(ROOT, "embedctl.py")
def cli(*args, **extra):
    env = dict(ENV, **extra)
    r = subprocess.run([sys.executable, "-I", CTL, *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr

FW_RAW = b"\x01\x81" + b"1592EMS1.1110629202209:52:28" + b"\0\0"          # 실제 기기의 get_ec 응답 모양(바이트 2.. 에 버전+날짜가 붙음)
FIXTURE = {"ok": True, "data": {"fw": "1592EMS1.111", "fw_date": "0629202209:52:28", "ec": {"d7": 0x80, "d2": 0xC1, "b98": 0x02}}}
FIX = f"{T}/fixture.json"; json.dump(FIXTURE, open(FIX, "w"))

# --- 1. 펌웨어 문자열 파싱 -------------------------------------------------------------------
check("parse_fw: 버전과 날짜를 분리", lib.parse_fw(FW_RAW) == ("1592EMS1.111", "0629202209:52:28"), str(lib.parse_fw(FW_RAW)))
check("parse_fw: 날짜 꼴이 아니면 통째로 버전", lib.parse_fw(b"\x01\x00ABC123\0") == ("ABC123", None), str(lib.parse_fw(b"\x01\x00ABC123\0")))
check("parse_fw: 새 버전도 분리", lib.parse_fw(b"\x01\x81" + b"1592EMS1.2000101202409:00:00")[0] == "1592EMS1.200", str(lib.parse_fw(b"\x01\x81" + b"1592EMS1.2000101202409:00:00")))

# --- 2. 게이트 --------------------------------------------------------------------------------
check("gate: 검증된 기종+펌웨어 = verified", lib.evaluate_gate("MS-1592", "1592EMS1.111")["state"] == "verified")
check("gate: 목록 밖 펌웨어 = unverified_fw", lib.evaluate_gate("MS-1592", "1592EMS1.109")["state"] == "unverified_fw")
check("gate: 다른 보드 = unsupported_board", lib.evaluate_gate("MS-9999", "1592EMS1.111")["state"] == "unsupported_board")
check("gate: 펌웨어를 못 읽음 = unknown", lib.evaluate_gate("MS-1592", None)["state"] == "unknown")
check("gate: 보드가 None 이어도 예외 없이 unsupported_board", lib.evaluate_gate(None, "x")["state"] == "unsupported_board")

# --- 3. 모드 해독 -----------------------------------------------------------------------------
for raw, name in ((0xC0, "sport"), (0xC1, "comfort"), (0xC2, "eco"), (0xC3, "user")):
    m = lib.decode_mode(raw)
    check(f"mode 0x{raw:02X} = {name}, 지원·활성", m["name"] == name and m["supported"] and m["active"], str(m))
check("mode: 비트7·6 이 꺼져 있으면 미지원·비활성", (lib.decode_mode(0x01)["supported"], lib.decode_mode(0x01)["active"]) == (False, False))

# --- 4. helper 인스턴스 이름 검증 ------------------------------------------------------------
for ok in ("status", "charge-80", "charge-100", "mode-eco", "mode-sport", "mode-comfort", "boost-on", "boost-off"):
    check(f"인스턴스 허용: {ok}", bool(lib.INSTANCE_RE.match(ok)))
for bad in ("", "charge-5000", "charge-8", "charge-80;x", "mode-user", "mode-ECO", "boost-", "boost-on ", "../x", "status\n", "charge--80", "write-0xD7"):
    check(f"인스턴스 거부: {bad!r}", not lib.INSTANCE_RE.match(bad))
try:
    lib.helper_call("mode-user"); check("helper_call: 허용 밖 이름은 systemctl 호출 전에 거부", False)
except lib.HelperError:
    check("helper_call: 허용 밖 이름은 systemctl 호출 전에 거부", True)

# --- 5. 상태 모으기: 직접(root) 경로 — 메모리 속 EC 에뮬레이터 ---------------------------------
EC = {0xD7: 0x80, 0xD2: 0xC1, 0x98: 0x02}
def fake_wmi_call(method, req):
    if method == "get_ec": return FW_RAW.ljust(32, b"\0")
    if method == "get_data": return bytes([1, EC[req[0]]]).ljust(32, b"\0")
    raise AssertionError("읽기 전용 단계에서 쓰기 호출이 일어남: " + method)
real_call = lib.wmi_call
lib.wmi_call = fake_wmi_call
os.environ["EMBEDCTL_WMI_DEBUGFS"] = f"{T}/wmi"
st = lib.collect_status()
check("direct: access = direct", st["access"] == "direct", st["access"])
check("direct: 게이트 verified, 펌웨어 1592EMS1.111", st["gate"]["state"] == "verified" and st["gate"]["fw"] == "1592EMS1.111", str(st["gate"]))
check("direct: EC 바이트", st["ec"] == {"d7": 0x80, "d2": 0xC1, "b98": 0x02}, str(st["ec"]))
check("direct: 모드 comfort, 부스트 꺼짐", st["mode"]["name"] == "comfort" and st["boost"] is False)
check("direct: 충전 상한 미설정 → limit 100", st["charge"]["set"] is False and st["charge"]["limit"] == 100 and st["charge"]["end"] == 0, str(st["charge"]))
check("direct: 팬·온도·전원", st["fans"] == [2840, 2711, 0, 0] and st["temp_pkg"] == 30.0 and st["power"] == {"ac": True, "status": "Full", "capacity": 100}, str((st["fans"], st["temp_pkg"], st["power"])))
check("direct: 경고 없음", st["warnings"] == [], str(st["warnings"]))
EC[0x98] = 0x82
check("direct: 부스트 비트7 켜짐 해독", lib.collect_status()["boost"] is True)
EC[0x98] = 0x02
reset_fs(end="80"); EC[0xD7] = 0xE4
st2 = lib.collect_status()
check("direct: sysfs(80)와 EC(100) 불일치 경고", any("다르다" in x for x in st2["warnings"]), str(st2["warnings"]))
check("direct: end=80 → set, limit 80", st2["charge"]["set"] and st2["charge"]["limit"] == 80)
reset_fs(); EC[0xD7] = 0x80
def failing_call(method, req): return bytes([0]) + bytes(31)
lib.wmi_call = failing_call
st3 = lib.collect_status()
check("direct: 펌웨어 실패 응답이면 access = unavailable + 경고(예외 없음)", st3["access"] == "unavailable" and st3["ec"] is None and any("실패" in x for x in st3["warnings"]), str((st3["access"], st3["warnings"])))
lib.wmi_call = real_call
del os.environ["EMBEDCTL_WMI_DEBUGFS"]

# --- 6. CLI: helper 경로 ----------------------------------------------------------------------
LOG = f"{T}/systemctl.log"
rc, out, err = cli("status", "--json", FAKE_RESULT=FIX, FAKE_LOG=LOG)
env_ = json.loads(out) if out.strip().startswith("{") else {}
check("CLI helper: 종료 코드 0, 봉투 키", rc == 0 and {"command", "ok", "structured", "exit_code", "data"} <= set(env_), f"rc={rc} {out[:200]} {err[:200]}")
d = env_.get("data", {})
check("CLI helper: access = helper, 게이트 verified", d.get("access") == "helper" and d.get("gate", {}).get("state") == "verified", str(d.get("gate")))
check("CLI helper: EC·모드 comfort", d.get("ec") == {"d7": 128, "d2": 193, "b98": 2} and d.get("mode", {}).get("name") == "comfort")
check("CLI helper: 봉투 command/exit_code", env_.get("command") == "embedctl status" and env_.get("exit_code") == 0 and env_.get("ok") is True)
check("CLI helper: systemctl 은 start --no-ask-password embedctl-root@status.service", "start --no-ask-password embedctl-root@status.service" in open(LOG).read(), open(LOG).read())

rc, out, err = cli("status", FAKE_RESULT=FIX)
check("CLI 텍스트: 종료 코드 0 과 핵심 줄", rc == 0 and "1592EMS1.111 (검증됨)" in out and "comfort" in out and "미설정 = 100% 로 동작" in out and "fan1 2840" in out and "AC 연결 · Full 100%" in out, out)

# --- 7. CLI: helper 실패(SSH 세션·polkit 거부)는 열화 동작 --------------------------------------
rc, out, err = cli("status", "--json", FAKE_RESULT=FIX, FAKE_RC="1")
d = json.loads(out)
check("열화: 종료 코드 0, access = unavailable, 게이트 unknown", rc == 0 and d["data"]["access"] == "unavailable" and d["data"]["gate"]["state"] == "unknown", f"rc={rc} {out[:300]}")
check("열화: 사용자 권한 항목은 그대로(팬·충전·전원)", d["data"]["fans"] == [2840, 2711, 0, 0] and d["data"]["charge"]["limit"] == 100 and d["data"]["power"]["ac"] is True)
check("열화: EC 항목은 비어 있고 notes 에 이유", d["data"]["ec"] is None and d["data"]["mode"] is None and d["data"]["boost"] is None and any("로컬 세션" in n for n in d.get("notes", [])), str(d.get("notes")))
rc, out, err = cli("status", FAKE_RESULT=FIX, FAKE_RC="1")
check("열화 텍스트: 알 수 없음 표시와 (주의)", rc == 0 and "알 수 없음(EC 를 읽지 못함)" in out and "(주의)" in out, out)
rc, out, err = cli("status", "--json", FAKE_RESULT=FIX, FAKE_NO_RESULT="1")
check("결과 파일 없음 = 열화(예외 없음)", rc == 0 and json.loads(out)["data"]["access"] == "unavailable")
for f in os.listdir(f"{T}/run"): os.remove(os.path.join(T, "run", f))
rc, out, err = cli("status", "--json", FAKE_RESULT=FIX, FAKE_SKEW="-3600")
check("오래된 결과 파일 = 이 요청의 것이 아니므로 열화", rc == 0 and json.loads(out)["data"]["access"] == "unavailable" and any("이 요청의 것이 아니다" in n for n in json.loads(out).get("notes", [])), out[:300])
bad = dict(FIXTURE, ok=False, error="게이트 거부"); json.dump(bad, open(f"{T}/bad.json", "w"))
rc, out, err = cli("status", "--json", FAKE_RESULT=f"{T}/bad.json")
check("helper 가 실패를 보고하면 열화 + 이유", rc == 0 and json.loads(out)["data"]["access"] == "unavailable" and any("게이트 거부" in n for n in json.loads(out).get("notes", [])))

bad2 = {"ok": False, "code": 3, "error": "게이트 거부: 펌웨어 미검증"}; json.dump(bad2, open(f"{T}/bad2.json", "w"))
rc, out, err = cli("status", "--json", FAKE_RESULT=f"{T}/bad2.json", FAKE_RC="1", FAKE_RESULT_ON_FAIL="1")
check("helper 가 비정상 종료하며 남긴 이유가 systemctl 의 일반 문구 대신 메시지에 들어감", rc == 0 and any("게이트 거부: 펌웨어 미검증" in n for n in json.loads(out).get("notes", [])), out[:300])
os.environ.update(FAKE_RESULT=f"{T}/bad2.json", FAKE_RC="1", FAKE_RESULT_ON_FAIL="1")
try:
    lib.helper_call("status"); check("helper_call: 결과 파일의 code 가 HelperError.code 로 전달", False)
except lib.HelperError as e:
    check("helper_call: 결과 파일의 code(3)가 HelperError.code 로 전달", e.code == 3, str(e.code))
for k in ("FAKE_RESULT", "FAKE_RC", "FAKE_RESULT_ON_FAIL"): os.environ.pop(k, None)
os.environ.update(FAKE_RC="1")
try:
    lib.helper_call("status"); check("helper_call: 결과 파일이 없으면 code 4", False)
except lib.HelperError as e:
    check("helper_call: 결과 파일 없는 실패는 code 4", e.code == 4, str(e.code))
os.environ.pop("FAKE_RC", None)

# --- 8. 게이트가 데이터에 반영되는지 -------------------------------------------------------------
other = {"ok": True, "data": {"fw": "1592EMS1.109", "fw_date": None, "ec": {"d7": 0xE4, "d2": 0xC1, "b98": 0x02}}}; json.dump(other, open(f"{T}/other.json", "w"))
rc, out, err = cli("status", "--json", FAKE_RESULT=f"{T}/other.json")
check("미검증 펌웨어 → unverified_fw, fw_verified=false", json.loads(out)["data"]["gate"]["state"] == "unverified_fw" and json.loads(out)["data"]["gate"]["fw_verified"] is False)
rc, out, err = cli("status", FAKE_RESULT=f"{T}/other.json")
check("미검증 펌웨어 텍스트에 「쓰기 거부」", "쓰기 거부" in out, out)
reset_fs(board="MS-1500")
rc, out, err = cli("status", "--json", FAKE_RESULT=FIX)
check("다른 보드 → unsupported_board", json.loads(out)["data"]["gate"]["state"] == "unsupported_board", out[:200])
reset_fs()

# --- 9. 스냅샷 ---------------------------------------------------------------------------------
snap_path = f"{T}/snap/s1.json"; os.makedirs(os.path.dirname(snap_path))
rc, out, err = cli("snapshot", "--out", snap_path, FAKE_RESULT=FIX)
s = json.load(open(snap_path))
check("snapshot --out: 파일 작성, schema 1, 값", rc == 0 and s["schema"] == 1 and s["mode"] == "comfort" and s["boost"] is False and s["ec"]["d7"] == 128 and s["gate"]["state"] == "verified", f"rc={rc} {err[:200]}")
check("snapshot: 호스트·시각·전원 기록", bool(s["host"]) and "T" in s["time"] and s["power"]["status"] == "Full" and s["fans"] == [2840, 2711, 0, 0])
before = set(os.listdir(T))
rc, out, err = cli("snapshot", FAKE_RESULT=FIX)
check("snapshot(--out 없음): 표준출력에 JSON, 파일을 만들지 않음", rc == 0 and json.loads(out)["schema"] == 1 and set(os.listdir(T)) == before)
rc, out, err = cli("snapshot", "--json", "--out", snap_path, FAKE_RESULT=FIX)
check("snapshot --json: 봉투 data 에 스냅샷과 written 경로", rc == 0 and json.loads(out)["data"]["written"] == snap_path and json.loads(out)["data"]["schema"] == 1, out[:200])
rc, out, err = cli("snapshot", "--out", f"{T}/없는폴더/x.json", FAKE_RESULT=FIX)
check("snapshot: 쓸 수 없는 경로는 오류 종료(조용히 넘기지 않음)", rc != 0 and "스냅샷을 쓰지 못했다" in err, f"rc={rc} {err[:200]}")

# --- 10. 쓰기 명령의 인자 검증은 helper 를 부르기 전에 끝난다(argparse, 종료 코드 2) ---------------------------------
if os.path.exists(LOG): os.remove(LOG)
for cmdline in (("charge", "49"), ("charge", "101"), ("charge", "abc"), ("charge", "-5"), ("mode", "user"), ("mode", "turbo"), ("boost", "maybe"), ("restore",)):
    rc, out, err = cli(*cmdline, FAKE_RESULT=FIX, FAKE_LOG=LOG)
    check(f"{' '.join(cmdline)}: 사용법 오류 종료 코드 2", rc == 2, f"rc={rc} {err[:120]}")
check("잘못된 인자는 systemctl 을 한 번도 부르지 않음", not os.path.exists(LOG), open(LOG).read() if os.path.exists(LOG) else "")
rc, out, err = cli("charge", "49", FAKE_RESULT=FIX)
check("charge 49 의 오류 문구에 허용 범위와 「100 이 상한 없음」", "50~100" in err and "상한 없음" in err, err)

finish("embedctl core")
