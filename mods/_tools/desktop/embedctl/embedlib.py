"""embedlib — embedctl 의 코어: 기종·펌웨어 게이트, EC 상태 읽기, 상태 모으기, 스냅샷.

이 파일은 MSI Summit E16Flip A12UDT(보드 MS-1592) 한 기종의 EC 를 다룬다. 주소 의미는 그 기종·검증된 EC 펌웨어에서만 확인됐다(README 「기종 게이트」).
근거와 설계: ctx `plan/embedctl-구현`, `note/msi-summit-me-ec-충전상한-성능모드-분석`.

EC 바이트를 읽는 길은 둘이다.
  - direct : root 로 MSI WMI debugfs(`msi-wmi-platform-*/get_data`)를 직접 연다(helper 와 개발용).
  - helper : 사용자 CLI 는 `systemctl start embedctl-root@status.service` 로 root helper 를 부르고 `/run/embedctl/last-status.json` 을 읽는다.
어느 쪽도 안 되면 EC 필드는 비우고(`access = "unavailable"`) 사용자 권한으로 읽히는 부분(DMI·sysfs·hwmon)만 보여 준다.

경로는 모두 환경변수로 바꿀 수 있다(시험이 가짜 디렉터리를 쓴다): EMBEDCTL_SYSFS_BAT · EMBEDCTL_SYSFS_AC · EMBEDCTL_HWMON · EMBEDCTL_DMI ·
EMBEDCTL_RUN · EMBEDCTL_SYSTEMCTL · EMBEDCTL_WMI_DEBUGFS · EMBEDCTL_DEBUGFS_ROOT. 호출 시점에 읽으므로 시험이 중간에 바꿀 수 있다.
표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import socket
import subprocess
import time

# --- 이 기종에서 확인된 값 -------------------------------------------------------------
BOARD = "MS-1592"
VERIFIED_FW = frozenset({"1592EMS1.111"})        # EC 펌웨어 문자열. 이 목록 밖에서는 쓰기를 거부한다(읽기만). 강제 옵션은 만들지 않는다.
EC_CHARGE, EC_MODE, EC_BOOST = 0xD7, 0xD2, 0x98   # 충전 상한(하위 7비트) · 성능 모드(비트7 지원·비트6 활성·하위 2비트) · Cooler Boost(비트7)
MODES = {0: "sport", 1: "comfort", 2: "eco", 3: "user"}
# helper 인스턴스 이름의 허용 형식(동작 = 인스턴스). 범위(50..100)는 동작 단계에서 따로 검사한다.
# 끝은 `\Z` 다: `$` 는 끝의 개행 앞에서도 맞아서 `status\n` 같은 이름이 통과한다(시험이 잡았다). root helper 의 입력 검증이므로 엄격해야 한다.
INSTANCE_RE = re.compile(r"^(status|charge-[0-9]{2,3}|mode-(sport|comfort|eco)|boost-(on|off))\Z")


class EcError(Exception):
    """EC/WMI 접근 실패(펌웨어가 실패 응답을 주었거나 debugfs 를 못 연 경우). helper 종료 코드 4."""


class InputError(Exception):
    """허용 범위 밖 입력(예: 충전 상한 49). helper 종료 코드 2."""


class GateError(Exception):
    """기종·펌웨어 게이트가 쓰기를 거부. helper 종료 코드 3."""


class MismatchError(Exception):
    """쓴 뒤 되읽은 값이 기대와 다름. before/after 를 들고 있다. helper 종료 코드 5."""

    def __init__(self, msg, before=None, after=None):
        super().__init__(msg)
        self.before, self.after = before, after


class HelperError(Exception):
    """root helper 호출 실패(polkit 거부·유닛 실패·결과 파일 없음/오래됨). code = 종료 코드(2 입력 · 3 게이트 거부 · 4 권한/helper 실패 · 5 되읽기 불일치)."""

    def __init__(self, msg, code=4):
        super().__init__(msg)
        self.code = code


# --- 경로(환경변수로 바꿀 수 있음) ----------------------------------------------------------
def _env(name, default):
    return os.environ.get(name) or default


def p_bat(): return _env("EMBEDCTL_SYSFS_BAT", "/sys/class/power_supply/BAT1")
def p_ac(): return _env("EMBEDCTL_SYSFS_AC", "/sys/class/power_supply/ADP1")
def p_hwmon(): return _env("EMBEDCTL_HWMON", "/sys/class/hwmon")
def p_dmi(): return _env("EMBEDCTL_DMI", "/sys/class/dmi/id")
def p_run(): return _env("EMBEDCTL_RUN", "/run/embedctl")
def systemctl_cmd(): return _env("EMBEDCTL_SYSTEMCTL", "systemctl")


def wmi_dir():
    """MSI WMI debugfs 디렉터리(`msi-wmi-platform-<GUID>-0`). debugfs 는 root 전용이라 일반 사용자는 못 찾는다(None)."""
    d = os.environ.get("EMBEDCTL_WMI_DEBUGFS")
    if d:
        return d
    found = sorted(glob.glob(os.path.join(_env("EMBEDCTL_DEBUGFS_ROOT", "/sys/kernel/debug"), "msi-wmi-platform-*")))
    return found[0] if found else None


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _read_int(path):
    v = _read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- WMI 낮은 층(root 전용; 시험은 이 함수를 대체한다) -----------------------------------------
def direct_ok():
    d = wmi_dir()
    return bool(d) and os.access(os.path.join(d, "get_data"), os.R_OK | os.W_OK)


def wmi_call(method, req):
    """debugfs 의 `<method>` 파일에 32바이트 요청을 쓰고 응답 32바이트를 읽는다. 응답 첫 바이트가 1 이면 성공."""
    d = wmi_dir()
    if not d:
        raise EcError("MSI WMI debugfs 를 찾을 수 없다(root 가 아니거나 msi_wmi_platform 이 없음)")
    path = os.path.join(d, method)
    req = bytes(req).ljust(32, b"\0")[:32]
    try:
        with open(path, "wb") as f:
            f.write(req)
        with open(path, "rb") as f:
            return f.read(32)
    except OSError as e:
        raise EcError(f"{method}: {e}") from e


def ec_get(idx):
    r = wmi_call("get_data", bytes([idx]))
    if len(r) < 2 or r[0] != 1:
        raise EcError(f"get_data(0x{idx:02X}) 실패 응답 {r[:4].hex()}")
    return r[1]


def parse_fw(raw):
    """`get_ec` 응답에서 EC 펌웨어 문자열과 날짜를 뗀다. 바이트 2.. 에 `<버전><MMDDYYYYHH:MM:SS>` 가 구분자 없이 붙어 있다
    (예: `1592EMS1.1110629202209:52:28` → 버전 `1592EMS1.111`, 날짜 `0629202209:52:28`). 날짜 꼴이 아니면 날짜 없이 통째로 버전으로 본다."""
    s = bytes(raw)[2:30].split(b"\0")[0].decode("ascii", "replace")
    m = re.match(r"^(.+?)([0-9]{10}:[0-9]{2}:[0-9]{2})$", s)
    return (m.group(1), m.group(2)) if m else (s, None)


def collect_ec_direct():
    """root 로 EC 를 직접 읽는다. helper 의 `status` 동작도 이것을 쓴다."""
    fw, date = parse_fw(wmi_call("get_ec", bytes(32)))
    return {"fw": fw, "fw_date": date, "ec": {"d7": ec_get(EC_CHARGE), "d2": ec_get(EC_MODE), "b98": ec_get(EC_BOOST)}}


# --- 쓰기(root 전용; helper 만 부른다) ----------------------------------------------------------
CHARGE_MIN, CHARGE_MAX = 50, 100                       # 시험으로 확인한 범위(커널은 5·0·101 을 거부, 하한은 6~49 사이 미확인)
MODE_BITS = {"sport": 0, "comfort": 1, "eco": 2}       # `user`(3)는 쓰지 않는다: 사용자 팬 곡선의 저장 위치를 모른다
GATE_REASON = {
    "unsupported_board": "지원하지 않는 기종이다",
    "unverified_fw": "검증되지 않은 EC 펌웨어다(검증된 목록: " + ", ".join(sorted(VERIFIED_FW)) + ")",
    "unknown": "EC 펌웨어를 읽지 못했다",
}


def _settle():
    """EC 반영을 기다리는 시간. 시험은 0 으로 둔다."""
    try:
        time.sleep(float(os.environ.get("EMBEDCTL_SETTLE", "0.3")))
    except ValueError:
        time.sleep(0.3)


def sysfs_end_path():
    return os.path.join(p_bat(), "charge_control_end_threshold")


def sysfs_write_end(n):
    """커널(msi_ec)에 충전 상한을 쓴다. msi_ec 가 범위를 검사하고 EC[0xD7] 을 0x80+N 으로 바꾼다. 시험이 EC 연동을 흉내 내려고 이 함수를 대체한다."""
    try:
        with open(sysfs_end_path(), "w") as f:
            f.write(str(int(n)))
    except OSError as e:
        raise EcError(f"충전 상한 쓰기 실패({sysfs_end_path()}): {e}") from e


def ec_set(idx, val):
    r = wmi_call("set_data", bytes([idx, val & 0xFF]))
    if len(r) < 1 or r[0] != 1:
        raise EcError(f"set_data(0x{idx:02X}=0x{val & 0xFF:02X}) 실패 응답 {bytes(r[:4]).hex()}")


def raw_state():
    return {"d7": ec_get(EC_CHARGE), "d2": ec_get(EC_MODE), "b98": ec_get(EC_BOOST), "end": _read_int(sysfs_end_path())}


def require_verified():
    """쓰기 직전 게이트를 다시 평가한다(기종 + 방금 읽은 EC 펌웨어). 통과하지 못하면 GateError."""
    data = collect_ec_direct()
    gate = evaluate_gate(_read(os.path.join(p_dmi(), "board_name")), data["fw"], data["fw_date"])
    if gate["state"] != "verified":
        raise GateError(f"게이트 거부: {GATE_REASON[gate['state']]} (보드 {gate['board']!r}, 펌웨어 {gate['fw']!r}) — 쓰기를 하지 않았다")
    return gate


def parse_instance(inst):
    """INSTANCE_RE 를 통과한 이름을 (동작, 인자)로. status → ("status", None) · charge-80 → ("charge", 80) · mode-eco → ("mode", "eco") · boost-on → ("boost", "on")."""
    if not INSTANCE_RE.match(inst):
        raise InputError(f"허용되지 않는 동작 이름: {inst!r}")
    if inst == "status":
        return "status", None
    kind, _, arg = inst.partition("-")
    return kind, (int(arg) if kind == "charge" else arg)


def apply_action(inst):
    """쓰기 동작 한 개를 실행하고 (before, after) 를 돌려준다. 게이트 → 쓰기 → 되읽기 확인 순서이며
    다른 EC 바이트가 바뀌었거나 기대와 다르면 MismatchError. 모드·Cooler Boost 는 어긋나면 이전 값으로 되돌리려 시도한다(최선 노력)."""
    kind, arg = parse_instance(inst)
    if kind == "status":
        raise InputError("status 는 쓰기 동작이 아니다")
    if kind == "charge" and not (CHARGE_MIN <= arg <= CHARGE_MAX):
        raise InputError(f"충전 상한은 {CHARGE_MIN}~{CHARGE_MAX} 만 허용한다(받은 값 {arg})")
    require_verified()
    before = raw_state()
    expect = dict(before)
    restore_addr = None
    if kind == "charge":
        sysfs_write_end(arg)
        expect["end"] = arg
    elif kind == "mode":
        new = (before["d2"] & 0xFC) | MODE_BITS[arg]       # 비트7(지원)·비트6(활성)과 나머지 비트는 보존하고 하위 2비트만 바꾼다
        ec_set(EC_MODE, new)
        expect["d2"], restore_addr = new, (EC_MODE, before["d2"])
    else:                                                    # boost
        new = (before["b98"] | 0x80) if arg == "on" else (before["b98"] & 0x7F)
        ec_set(EC_BOOST, new)
        expect["b98"], restore_addr = new, (EC_BOOST, before["b98"])
    _settle()
    after = raw_state()
    bad = []
    if kind == "charge":
        if (after["d7"] & 0x7F) != arg:
            bad.append(f"EC[0xD7] 하위 7비트가 {after['d7'] & 0x7F} (기대 {arg})")
        if after["end"] != arg:
            bad.append(f"sysfs 충전 상한이 {after['end']} (기대 {arg})")
        for k in ("d2", "b98"):
            if after[k] != before[k]:
                bad.append(f"쓰지 않은 {k} 가 0x{before[k]:02X} → 0x{after[k]:02X} 로 바뀜")
    else:
        for k in ("d7", "d2", "b98"):
            if after[k] != expect[k]:
                bad.append(f"{k} 가 0x{after[k]:02X} (기대 0x{expect[k]:02X})")
    if bad:
        if restore_addr:
            try:
                ec_set(*restore_addr)
            except EcError:
                pass
        raise MismatchError("되읽기 값이 기대와 다르다: " + "; ".join(bad), before, after)
    return before, after


# --- 동작 결과 문구(CLI·TUI 공용) ----------------------------------------------------------------
LABEL = {"charge": "충전 상한", "mode": "성능 모드", "boost": "Cooler Boost"}
EC_KEY = {"charge": ("d7", EC_CHARGE), "mode": ("d2", EC_MODE), "boost": ("b98", EC_BOOST)}


def describe(kind, raw):
    if kind == "charge":
        return "미설정(100%)" if not raw["end"] else f"{raw['end']}%"
    if kind == "mode":
        return MODES[raw["d2"] & 0x03]
    return "켜짐" if raw["b98"] & 0x80 else "꺼짐"


def action_summary(kind, res):
    """helper 결과(before/after)를 (데이터, 한 줄 문구)로."""
    key, addr = EC_KEY[kind]
    b, af = res["before"], res["after"]
    changed = b[key] != af[key] or b["end"] != af["end"]
    line = f"{LABEL[kind]}: {describe(kind, b)} → {describe(kind, af)}  [EC 0x{addr:02X}: 0x{b[key]:02X} → 0x{af[key]:02X}]" + ("" if changed else "  (이미 같은 값이었다)")
    return {"action": kind, "before": b, "after": af, "changed": changed}, line


# --- restore 계획(CLI·TUI 공용) --------------------------------------------------------------------
class RestoreError(Exception):
    """복원할 수 없는 스냅샷/상태. code = 종료 코드(2 형식 · 3 거부 · 4 EC 를 못 읽음). 아무것도 쓰기 전에 낸다."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def restore_plan(snap, st):
    """스냅샷 snap 을 지금 상태 st(collect_status 결과)에 맞추는 계획을 만든다. 하나라도 안 맞으면 RestoreError — 이 함수는 아무것도 쓰지 않는다.
    돌려주는 값: (계획 [{"kind","instance","text"}…], 참고 문구 […])."""
    if not isinstance(snap, dict) or snap.get("schema") != 1 or not isinstance(snap.get("gate"), dict):
        raise RestoreError(2, "스냅샷 형식이 아니다(schema 1 이 아님)")
    if st["access"] == "unavailable":
        raise RestoreError(4, "EC 를 읽지 못해 복원할 수 없다: " + ("; ".join(st["warnings"]) or "이유 없음"))
    if st["gate"]["state"] != "verified":
        raise RestoreError(3, f"게이트 거부: {GATE_REASON.get(st['gate']['state'], st['gate']['state'])} — 복원하지 않았다")
    if snap["gate"].get("fw") != st["gate"]["fw"]:
        raise RestoreError(3, f"스냅샷의 EC 펌웨어({snap['gate'].get('fw')!r})가 지금({st['gate']['fw']!r})과 달라 복원하지 않는다")
    want_charge = (snap.get("charge") or {}).get("limit")
    mode, boost = snap.get("mode"), snap.get("boost")
    if not isinstance(want_charge, int) or not (CHARGE_MIN <= want_charge <= CHARGE_MAX):
        raise RestoreError(3, f"스냅샷의 충전 상한 {want_charge!r} 은 허용 범위({CHARGE_MIN}~{CHARGE_MAX})가 아니다 — 복원하지 않았다")
    if mode not in MODE_BITS:
        raise RestoreError(3, f"스냅샷의 성능 모드 {mode!r} 는 복원하지 않는다(sport·comfort·eco 만; 스냅샷을 찍을 때 EC 를 읽지 못했을 수도 있다)")
    if not isinstance(boost, bool):
        raise RestoreError(3, "스냅샷에 Cooler Boost 값이 없다 — 복원하지 않았다")
    plan = []
    if st["charge"]["limit"] != want_charge:
        plan.append({"kind": "charge", "instance": f"charge-{want_charge}", "text": f"{LABEL['charge']}: {st['charge']['limit']}% → {want_charge}%"})
    if st["mode"]["name"] != mode:
        plan.append({"kind": "mode", "instance": f"mode-{mode}", "text": f"{LABEL['mode']}: {st['mode']['name']} → {mode}"})
    if st["boost"] != boost:
        plan.append({"kind": "boost", "instance": f"boost-{'on' if boost else 'off'}",
                     "text": f"{LABEL['boost']}: {'켜짐' if st['boost'] else '꺼짐'} → {'켜짐' if boost else '꺼짐'}"})
    notes = []
    if not (snap.get("charge") or {}).get("set") and want_charge == 100 and st["charge"]["set"]:
        notes.append("스냅샷의 충전 상한은 「미설정」이었다. 미설정은 sysfs 로 되돌릴 수 없어 100% 로 복원한다(동작은 같다)")
    return plan, notes


# --- 스냅샷 저장 위치(TUI 가 쓴다; CLI 는 --out 으로 명시할 때만 저장) -----------------------------------
def snapshot_dir():
    base = os.environ.get("EMBEDCTL_SNAPSHOT_DIR")
    if base:
        return base
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "embedctl", "snapshots")


def save_snapshot(status):
    """스냅샷을 snapshot_dir() 에 `YYYYmmdd-HHMMSS.json` 으로 저장하고 경로를 돌려준다(같은 초면 -2, -3 …)."""
    d = snapshot_dir()
    os.makedirs(d, exist_ok=True)
    stem = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path, n = os.path.join(d, stem + ".json"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, f"{stem}-{n}.json")
    with open(path, "w") as f:
        json.dump(make_snapshot(status), f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path


def list_snapshots():
    """저장된 스냅샷 경로를 최신순으로."""
    return sorted(glob.glob(os.path.join(snapshot_dir(), "*.json")), reverse=True)


# --- TLP 충돌 경고 ---------------------------------------------------------------------------
def tlp_charge_settings():
    """TLP 설정 파일이 충전 임계값을 지정하고 있으면 [(파일, 이름, 값)] 을 돌려준다. TLP 가 다음 적용 때 embedctl 의 값을 덮어쓸 수 있다."""
    files = [os.environ.get("EMBEDCTL_TLP_CONF") or "/etc/tlp.conf"]
    files += sorted(glob.glob(os.path.join(os.environ.get("EMBEDCTL_TLP_D") or "/etc/tlp.d", "*.conf")))
    found = []
    for f in files:
        try:
            lines = open(f).read().splitlines()
        except OSError:
            continue
        for ln in lines:
            m = re.match(r"^\s*(STOP_CHARGE_THRESH_BAT[01])\s*=\s*\"?([0-9]+)\"?", ln)
            if m:
                found.append((f, m.group(1), int(m.group(2))))
    return found


# --- helper 호출(사용자 쪽) ------------------------------------------------------------------
def helper_call(instance, timeout=20):
    """`systemctl start embedctl-root@<instance>.service` 를 부르고 그 인스턴스의 결과 파일을 읽어 돌려준다.
    비대화형이므로 암호를 묻지 않는다(polkit 이 거부하면 즉시 실패). 결과 파일이 없거나 요청 시작보다 오래됐으면 실패로 본다."""
    if not INSTANCE_RE.match(instance):
        raise HelperError(f"허용되지 않는 동작 이름: {instance!r}")
    t0 = time.time()
    unit = f"embedctl-root@{instance}.service"
    try:
        r = subprocess.run([systemctl_cmd(), "start", "--no-ask-password", unit], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HelperError(f"helper 를 시작하지 못했다({unit}): {e}") from e
    path = os.path.join(p_run(), f"last-{instance}.json")
    res, why_not = None, None
    try:
        with open(path) as f:
            res = json.load(f)
    except (OSError, ValueError) as e:
        why_not = f"helper 결과 파일을 읽지 못했다({path}): {e}"
    # 결과의 time 은 helper 가 요청 뒤에 찍으므로 t0 이상이어야 한다. 여유를 두면 직전 요청의 같은 인스턴스 결과를 이번 것으로 착각한다(시험이 잡았다).
    if res is not None and (res.get("instance") != instance or float(res.get("time", 0)) < t0):
        why_not = f"helper 결과가 이 요청의 것이 아니다({path}: instance={res.get('instance')!r}, time={res.get('time')})"
        res = None
    if r.returncode != 0:
        if res is not None and res.get("error"):     # helper 가 직접 남긴 이유가 systemctl 의 일반 문구보다 정확하다
            raise HelperError(f"helper 실패({unit}): {res['error']}", code=res.get("code") or 4)
        why = [x for x in (r.stderr or r.stdout or "").strip().splitlines() if x.strip()]
        raise HelperError(f"helper 실패({unit}, 종료 코드 {r.returncode}): {why[0] if why else '이유 없음'} — 로컬 세션에서 실행해야 한다(SSH 세션 등 세션 밖에서는 polkit 이 거부한다)", code=4)
    if res is None:
        raise HelperError(why_not, code=4)
    if not res.get("ok"):
        raise HelperError(f"helper 가 실패를 보고했다: {res.get('error')}", code=res.get("code") or 4)
    return res


def write_result(instance, ok, data=None, before=None, after=None, error=None, code=0):
    """helper 가 결과를 남긴다: 임시 파일에 쓴 뒤 rename(읽는 쪽이 반쯤 쓴 파일을 보지 않게). code = 실패 때의 종료 코드."""
    d = p_run()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"last-{instance}.json")
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump({"instance": instance, "time": time.time(), "ok": ok, "code": code, "data": data, "before": before, "after": after, "error": error}, f, ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return path


# --- 게이트 ---------------------------------------------------------------------------------
def evaluate_gate(board, fw, fw_date=None):
    """state: verified(쓰기 허용) · unverified_fw(읽기만) · unsupported_board(읽기만) · unknown(펌웨어를 못 읽음; 쓰기 거부)."""
    if board != BOARD:
        state = "unsupported_board"
    elif fw is None:
        state = "unknown"
    elif fw in VERIFIED_FW:
        state = "verified"
    else:
        state = "unverified_fw"
    return {"board": board, "board_ok": board == BOARD, "fw": fw, "fw_date": fw_date, "fw_verified": fw in VERIFIED_FW if fw else False, "state": state}


# --- 상태 모으기 ----------------------------------------------------------------------------
def _hwmon_by_name(name):
    for h in sorted(glob.glob(os.path.join(p_hwmon(), "hwmon*"))):
        if _read(os.path.join(h, "name")) == name:
            return h
    return None


def read_fans():
    h = _hwmon_by_name("msi_wmi_platform")
    if not h:
        return None
    out = []
    for i in range(1, 5):
        v = _read_int(os.path.join(h, f"fan{i}_input"))
        if v is not None:
            out.append(v)
    return out or None


def read_temp_pkg():
    h = _hwmon_by_name("coretemp")
    v = _read_int(os.path.join(h, "temp1_input")) if h else None
    return None if v is None else v / 1000.0


def decode_mode(d2):
    return {"name": MODES[d2 & 0x03], "supported": bool(d2 & 0x80), "active": bool(d2 & 0x40), "raw": d2}


def collect_status():
    """사용자 권한으로 읽을 수 있는 것 + (가능하면) EC. EC 를 못 읽어도 예외 없이 `access = "unavailable"` 로 돌려준다."""
    warnings = []
    board = _read(os.path.join(p_dmi(), "board_name"))
    access, ecdata = "unavailable", None
    if direct_ok():
        try:
            ecdata, access = collect_ec_direct(), "direct"
        except EcError as e:
            warnings.append(f"EC 직접 읽기 실패: {e}")
    else:
        try:
            ecdata, access = helper_call("status")["data"], "helper"
        except HelperError as e:
            warnings.append(str(e))
    fw = ecdata.get("fw") if ecdata else None
    gate = evaluate_gate(board, fw, ecdata.get("fw_date") if ecdata else None)
    ec = ecdata.get("ec") if ecdata else None

    end, start = _read_int(os.path.join(p_bat(), "charge_control_end_threshold")), _read_int(os.path.join(p_bat(), "charge_control_start_threshold"))
    charge = {"end": end, "start": start, "set": bool(end and end > 0), "limit": (end if end and end > 0 else 100) if end is not None else None}
    if ec is not None and end is not None and (ec["d7"] & 0x7F) != end:
        warnings.append(f"sysfs 충전 상한({end})과 EC[0xD7] 하위 7비트({ec['d7'] & 0x7F})가 다르다")

    ac = _read(os.path.join(p_ac(), "online"))
    return {
        "gate": gate, "access": access, "ec": ec,
        "charge": charge,
        "mode": decode_mode(ec["d2"]) if ec else None,
        "boost": bool(ec["b98"] & 0x80) if ec else None,
        "fans": read_fans(), "temp_pkg": read_temp_pkg(),
        "power": {"ac": None if ac is None else ac == "1", "status": _read(os.path.join(p_bat(), "status")), "capacity": _read_int(os.path.join(p_bat(), "capacity"))},
        "warnings": warnings,
    }


def make_snapshot(status):
    """전력 시험 전후 기록용 스냅샷(schema 1). 자동 저장은 하지 않는다 — 저장은 호출한 쪽이 `--out` 으로 한다."""
    return {
        "schema": 1,
        "time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "gate": status["gate"], "ec": status["ec"], "charge": status["charge"],
        "mode": status["mode"]["name"] if status["mode"] else None,
        "boost": status["boost"], "fans": status["fans"], "temp_pkg": status["temp_pkg"], "power": status["power"],
    }
