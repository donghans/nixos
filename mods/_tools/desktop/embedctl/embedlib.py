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
    """EC/WMI 접근 실패(펌웨어가 실패 응답을 주었거나 debugfs 를 못 연 경우)."""


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
        why = (r.stderr or r.stdout or "").strip().splitlines()
        raise HelperError(f"helper 실패({unit}, 종료 코드 {r.returncode}): {why[-1] if why else '이유 없음'} — 로컬 세션에서 실행해야 한다(SSH 세션은 polkit 이 거부할 수 있다)", code=4)
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
