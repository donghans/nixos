"""embedlib — embedctl 의 코어: 기종·펌웨어 게이트, 상태 읽기(sysfs), 쓰기 동작(root helper 가 실행), 스냅샷.

이 파일은 MSI Summit E16Flip A12UDT(보드 MS-1592) 한 기종을 다룬다. 값의 의미는 그 기종·검증된 EC 펌웨어에서만 확인됐다(README 「기종 게이트」).
근거와 설계: ctx `plan/embedctl-lockdown`(이번 sysfs 전환), `plan/embedctl-구현`(원래 WMI 설계), `note/msi-summit-me-ec-충전상한-성능모드-분석`.

**lockdown(integrity) 아래에서 동작하도록 debugfs/WMI 를 쓰지 않는다.** 모든 접근은 sysfs 다:
  - 읽기 : 일반 사용자 권한으로 직접 읽는다(helper 불필요) — `/sys/devices/platform/msi-ec/*`(커널 모듈 msi-ec), BAT1, hwmon, DMI.
  - 쓰기 : 파일이 root 쓰기라 root helper(`embedctl-root@<동작>.service`, polkit 허용)가 게이트 → 쓰기 → 되읽기 확인 순서로 한다.
msi-ec 가 없으면(모듈 미적재·펌웨어가 모듈 허용 목록 밖 등) 게이트 상태가 `no_msi_ec` 이고 쓰기는 모두 거부한다.

경로는 모두 환경변수로 바꿀 수 있다(시험이 가짜 디렉터리를 쓴다): EMBEDCTL_MSIEC · EMBEDCTL_SYSFS_BAT · EMBEDCTL_SYSFS_AC · EMBEDCTL_HWMON · EMBEDCTL_DMI ·
EMBEDCTL_RUN · EMBEDCTL_SYSTEMCTL. 호출 시점에 읽으므로 시험이 중간에 바꿀 수 있다. 표준 라이브러리만 쓴다.
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
VERIFIED_FW = frozenset({"1592EMS1.111"})        # msi-ec 의 fw_version. 이 목록 밖에서는 쓰기를 거부한다(읽기만). 강제 옵션은 만들지 않는다.
# 성능 모드: msi-ec 가 이 펌웨어(CONF_G2_1)에서 광고하는 이름. EC 0xD2 에 turbo=0xC4 · eco=0xC2 · comfort=0xC1 을 통째로 쓴다(plan/embedctl-lockdown §3-A).
MODE_ORDER = ("turbo", "comfort", "eco")
# 예전 embedctl 의 `sport`(EC 0xC0)는 msi-ec 가 이 펌웨어에서 광고하지 않아 sysfs 로 쓸 수 없다 — 읽을 때만 `unknown (192)` 로 보이고, 쓰기는 비활성이다.
DISABLED_MODES = {"sport": "msi-ec 가 이 펌웨어에서 지원하지 않는다(EC 0xC0 은 sysfs 로 쓸 수 없고 읽으면 `unknown (192)`)"}
LEGACY_SPORT_RAW = 0xC0
# helper 인스턴스 이름의 허용 형식(동작 = 인스턴스). 범위(50..100)는 동작 단계에서 따로 검사한다. 읽기는 helper 를 거치지 않으므로 `status` 인스턴스는 없다.
# 끝은 `\Z` 다: `$` 는 끝의 개행 앞에서도 맞아서 `charge-80\n` 같은 이름이 통과한다(시험이 잡았다). root helper 의 입력 검증이므로 엄격해야 한다.
INSTANCE_RE = re.compile(r"^(charge-[1-9][0-9]{1,2}|mode-(turbo|comfort|eco)|boost-(on|off))\Z")      # 충전 값은 선행 0 없는 2~3자리(`charge-080` 같은 별칭 이름을 만들지 않는다)


class EcError(Exception):
    """sysfs 접근 실패(파일을 쓰지 못함 등). helper 종료 코드 4."""


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


def p_msiec(): return _env("EMBEDCTL_MSIEC", "/sys/devices/platform/msi-ec")
def p_bat(): return _env("EMBEDCTL_SYSFS_BAT", "/sys/class/power_supply/BAT1")
def p_ac(): return _env("EMBEDCTL_SYSFS_AC", "/sys/class/power_supply/ADP1")
def p_hwmon(): return _env("EMBEDCTL_HWMON", "/sys/class/hwmon")
def p_dmi(): return _env("EMBEDCTL_DMI", "/sys/class/dmi/id")
def p_run(): return _env("EMBEDCTL_RUN", "/run/embedctl")
def systemctl_cmd(): return _env("EMBEDCTL_SYSTEMCTL", "systemctl")


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


def msiec_file(name):
    return os.path.join(p_msiec(), name)


def sysfs_end_path():
    return os.path.join(p_bat(), "charge_control_end_threshold")


def msiec_present():
    """msi-ec 의 sysfs 디렉터리가 있나. 없으면 모듈이 안 올라온 것이다."""
    return os.path.isdir(p_msiec())


NO_MSIEC_HINT = ("msi-ec 가 없다 — 모듈이 올라오지 않았다(kernel-lockdown mod 가 꺼졌거나 lockdown 이 모듈 서명을 거부했을 수 있다), "
                 "또는 EC 펌웨어가 msi-ec 의 허용 목록 밖이라 모듈이 거부했다(`journalctl -k | grep -i msi-ec` 에 "
                 "`Your firmware version is not supported!`). 이 상태에서는 EC 상태를 읽을 수 없고 모든 쓰기를 거부한다")


# --- 성능 모드 해석 ---------------------------------------------------------------------------
def parse_mode(text):
    """msi-ec `shift_mode` 문자열을 해석한다. 읽지 못했으면 None.
    {"name", "raw", "text", "known"}: 이름이 MODE_ORDER 안이면 known. `unknown (192)` 는 레거시 sport(name "sport", known False),
    그 밖의 `unknown (N)` 은 name "unknown". `unspecified`(EC 값 0x80)는 name "unspecified"."""
    if text is None:
        return None
    t = text.strip()
    if t in MODE_ORDER:
        return {"name": t, "raw": None, "text": t, "known": True}
    m = re.match(r"^unknown \(([0-9]+)\)$", t)
    if m:
        raw = int(m.group(1))
        return {"name": "sport" if raw == LEGACY_SPORT_RAW else "unknown", "raw": raw, "text": t, "known": False}
    if t == "unspecified":
        return {"name": "unspecified", "raw": None, "text": t, "known": False}
    return {"name": "unknown", "raw": None, "text": t, "known": False}


def available_modes():
    """msi-ec 가 광고하는 모드 목록(`available_shift_modes`). 읽지 못하면 None."""
    t = _read(msiec_file("available_shift_modes"))
    return t.split() if t is not None else None


def writable_modes():
    """쓸 수 있는 모드 = msi-ec 가 광고하는 값 ∩ embedctl 의 정적 목록. msi-ec 가 없으면 빈 목록."""
    avail = available_modes()
    return [m for m in MODE_ORDER if avail and m in avail]


def parse_bool(text):
    """msi-ec cooler_boost: on/off."""
    return {"on": True, "off": False}.get(text)


# --- 쓰기(root 전용; helper 만 부른다) ----------------------------------------------------------
CHARGE_MIN, CHARGE_MAX = 50, 100                       # 시험으로 확인한 범위(커널은 5·0·101 을 거부, 하한은 6~49 사이 미확인)
GATE_REASON = {
    "unsupported_board": "지원하지 않는 기종이다",
    "unverified_fw": "검증되지 않은 EC 펌웨어다(검증된 목록: " + ", ".join(sorted(VERIFIED_FW)) + ")",
    "no_msi_ec": NO_MSIEC_HINT,
}


def _settle():
    """커널·EC 반영을 기다리는 시간. 시험은 0 으로 둔다."""
    try:
        time.sleep(float(os.environ.get("EMBEDCTL_SETTLE", "0.3")))
    except ValueError:
        time.sleep(0.3)


def sysfs_write(path, text):
    """sysfs 파일에 쓴다. 쓰기 경로는 전부 이 함수 하나다 — 시험이 이 함수를 대체해 msi-ec 의 부수 효과(충전 start 따라가기 등)를 흉내 낸다."""
    try:
        with open(path, "w") as f:
            f.write(text)
    except OSError as e:
        raise EcError(f"sysfs 쓰기 실패({path}): {e}") from e


def raw_state():
    """되읽기 비교용 원시 상태(문자열 그대로)."""
    return {"end": _read_int(sysfs_end_path()), "start": _read_int(os.path.join(p_bat(), "charge_control_start_threshold")),
            "mode": _read(msiec_file("shift_mode")), "boost": _read(msiec_file("cooler_boost"))}


def current_gate():
    return evaluate_gate(_read(os.path.join(p_dmi(), "board_name")), _read(msiec_file("fw_version")), _read(msiec_file("fw_release_date")))


def require_verified():
    """쓰기 직전 게이트를 다시 평가한다(기종 + 방금 읽은 msi-ec 펌웨어). 통과하지 못하면 GateError."""
    gate = current_gate()
    if gate["state"] != "verified":
        raise GateError(f"게이트 거부: {GATE_REASON[gate['state']]} (보드 {gate['board']!r}, 펌웨어 {gate['fw']!r}) — 쓰기를 하지 않았다")
    return gate


def parse_instance(inst):
    """INSTANCE_RE 를 통과한 이름을 (동작, 인자)로. charge-80 → ("charge", 80) · mode-eco → ("mode", "eco") · boost-on → ("boost", "on")."""
    if not INSTANCE_RE.match(inst):
        raise InputError(f"허용되지 않는 동작 이름: {inst!r}")
    kind, _, arg = inst.partition("-")
    return kind, (int(arg) if kind == "charge" else arg)


def apply_action(inst):
    """쓰기 동작 한 개를 실행하고 (before, after) 를 돌려준다. 게이트 → 쓰기 → 되읽기 확인 순서이며
    쓰지 않은 항목이 바뀌었거나 쓴 값이 기대와 다르면 MismatchError. 모드·Cooler Boost 는 어긋나면 이전 값으로 되돌리려 시도한다(최선 노력)."""
    kind, arg = parse_instance(inst)
    if kind == "charge" and not (CHARGE_MIN <= arg <= CHARGE_MAX):
        raise InputError(f"충전 상한은 {CHARGE_MIN}~{CHARGE_MAX} 만 허용한다(받은 값 {arg})")
    require_verified()
    if kind == "mode" and arg not in writable_modes():
        raise GateError(f"게이트 거부: msi-ec 가 모드 {arg!r} 를 광고하지 않는다(광고: {available_modes()}) — 쓰기를 하지 않았다")
    before = raw_state()
    if kind == "charge":
        path, text, field = sysfs_end_path(), str(arg), "end"
        expect = arg
    elif kind == "mode":
        path, text, field = msiec_file("shift_mode"), arg, "mode"
        expect = arg
    else:
        path, text, field = msiec_file("cooler_boost"), arg, "boost"
        expect = arg
    sysfs_write(path, text)
    _settle()
    after = raw_state()
    bad = []
    if after[field] != expect:
        bad.append(f"{field} 가 {after[field]!r} (기대 {expect!r})")
    for k in ("end", "mode", "boost"):
        if k != field and after[k] != before[k]:
            bad.append(f"쓰지 않은 {k} 가 {before[k]!r} → {after[k]!r} 로 바뀜")
    if bad:
        if kind == "mode" and parse_mode(before["mode"]) and parse_mode(before["mode"])["known"]:
            _try_write(msiec_file("shift_mode"), before["mode"])
        elif kind == "boost" and parse_bool(before["boost"]) is not None:
            _try_write(msiec_file("cooler_boost"), before["boost"])
        raise MismatchError("되읽기 값이 기대와 다르다: " + "; ".join(bad), before, after)
    return before, after


def _try_write(path, text):
    try:
        sysfs_write(path, text)
    except EcError:
        pass


# --- 동작 결과 문구(CLI·TUI 공용) ----------------------------------------------------------------
LABEL = {"charge": "충전 상한", "mode": "성능 모드", "boost": "Cooler Boost"}
RAW_KEY = {"charge": "end", "mode": "mode", "boost": "boost"}


def mode_label(text):
    """sysfs 문자열을 사람이 읽는 모드 이름으로: `unknown (192)` → `sport(레거시 값)`."""
    m = parse_mode(text)
    if m is None:
        return "알 수 없음"
    if m["name"] == "sport" and not m["known"]:
        return "sport(레거시 값, 변경 불가)"
    return m["name"] if m["known"] else m["text"]


def describe(kind, raw):
    if kind == "charge":
        return "미설정(100%)" if not raw["end"] else f"{raw['end']}%"
    if kind == "mode":
        return mode_label(raw["mode"])
    return "켜짐" if parse_bool(raw["boost"]) else "꺼짐"


def action_summary(kind, res):
    """helper 결과(before/after)를 (데이터, 한 줄 문구)로."""
    key = RAW_KEY[kind]
    b, af = res["before"], res["after"]
    changed = b[key] != af[key]
    line = f"{LABEL[kind]}: {describe(kind, b)} → {describe(kind, af)}" + ("" if changed else "  (이미 같은 값이었다)")
    if kind == "mode" and changed:
        pb = parse_mode(b["mode"])
        if pb and not pb["known"]:
            line += f"  (이전 값 {b['mode']!r} 으로는 sysfs 로 되돌릴 수 없다)"
    return {"action": kind, "before": b, "after": af, "changed": changed}, line


# --- restore 계획(CLI·TUI 공용) --------------------------------------------------------------------
class RestoreError(Exception):
    """복원할 수 없는 스냅샷/상태. code = 종료 코드(2 형식 · 3 거부). 아무것도 쓰기 전에 낸다."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def restore_plan(snap, st):
    """스냅샷 snap 을 지금 상태 st(collect_status 결과)에 맞추는 계획을 만든다. 하나라도 안 맞으면 RestoreError — 이 함수는 아무것도 쓰지 않는다.
    돌려주는 값: (계획 [{"kind","instance","text"}…], 참고 문구 […])."""
    if not isinstance(snap, dict) or snap.get("schema") != 2 or not isinstance(snap.get("gate"), dict):
        old = isinstance(snap, dict) and snap.get("schema") == 1
        raise RestoreError(2, "스냅샷 형식이 아니다(schema 2 가 아님)" + (" — schema 1 은 WMI/EC 바이트 시절의 옛 형식이라 복원하지 않는다" if old else ""))
    if st["gate"]["state"] != "verified":
        raise RestoreError(3, f"게이트 거부: {GATE_REASON.get(st['gate']['state'], st['gate']['state'])} — 복원하지 않았다")
    if st["charge"]["limit"] is None:
        raise RestoreError(3, "배터리 충전 임계값 파일을 읽지 못해 복원할 수 없다 — 복원하지 않았다")
    if snap["gate"].get("fw") != st["gate"]["fw"]:
        raise RestoreError(3, f"스냅샷의 EC 펌웨어({snap['gate'].get('fw')!r})가 지금({st['gate']['fw']!r})과 달라 복원하지 않는다")
    want_charge = (snap.get("charge") or {}).get("limit")
    mode, boost = snap.get("mode"), snap.get("boost")
    if not isinstance(want_charge, int) or not (CHARGE_MIN <= want_charge <= CHARGE_MAX):
        raise RestoreError(3, f"스냅샷의 충전 상한 {want_charge!r} 은 허용 범위({CHARGE_MIN}~{CHARGE_MAX})가 아니다 — 복원하지 않았다")
    if mode not in MODE_ORDER or mode not in writable_modes():
        raise RestoreError(3, f"스냅샷의 성능 모드 {mode!r} 는 복원하지 않는다({'·'.join(MODE_ORDER)} 만; sport 처럼 msi-ec 가 쓰지 못하는 값이거나 찍을 때 읽지 못했을 수 있다)")
    if not isinstance(boost, bool):
        raise RestoreError(3, "스냅샷에 Cooler Boost 값이 없다 — 복원하지 않았다")
    plan = []
    if st["charge"]["limit"] != want_charge:
        plan.append({"kind": "charge", "instance": f"charge-{want_charge}", "text": f"{LABEL['charge']}: {st['charge']['limit']}% → {want_charge}%"})
    if not st["mode"] or st["mode"]["name"] != mode:
        now = st["mode"]["name"] if st["mode"] else "알 수 없음"
        plan.append({"kind": "mode", "instance": f"mode-{mode}", "text": f"{LABEL['mode']}: {now} → {mode}"})
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
    """state: verified(쓰기 허용) · unverified_fw(읽기만) · unsupported_board(읽기만) · no_msi_ec(msi-ec 가 없어 펌웨어를 못 읽음; 쓰기 거부)."""
    if board != BOARD:
        state = "unsupported_board"
    elif fw is None:
        state = "no_msi_ec"
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


def collect_status():
    """전부 사용자 권한으로 읽는다(helper 없음). msi-ec 가 없어도 예외 없이 게이트 `no_msi_ec` 와 경고로 돌려준다."""
    warnings = []
    gate = current_gate()
    present = msiec_present()
    if not present:
        warnings.append(NO_MSIEC_HINT)
    mode = parse_mode(_read(msiec_file("shift_mode")))
    boost = parse_bool(_read(msiec_file("cooler_boost")))
    end, start = _read_int(sysfs_end_path()), _read_int(os.path.join(p_bat(), "charge_control_start_threshold"))
    charge = {"end": end, "start": start, "set": bool(end and end > 0), "limit": (end if end and end > 0 else 100) if end is not None else None}
    if mode is not None and mode["name"] == "unknown":
        warnings.append(f"성능 모드가 msi-ec 도 모르는 값이다: {mode['text']}")
    ac = _read(os.path.join(p_ac(), "online"))
    return {
        "gate": gate,
        "msi_ec": {"present": present, "available_modes": available_modes()},
        "charge": charge,
        "mode": mode,
        "modes": {"writable": writable_modes(), "disabled": sorted(DISABLED_MODES)},
        "boost": boost,
        "fans": read_fans(), "temp_pkg": read_temp_pkg(),
        "power": {"ac": None if ac is None else ac == "1", "status": _read(os.path.join(p_bat(), "status")), "capacity": _read_int(os.path.join(p_bat(), "capacity"))},
        "warnings": warnings,
    }


def make_snapshot(status):
    """전력 시험 전후 기록용 스냅샷(schema 2: sysfs 값만. schema 1 의 EC 바이트는 없다). 자동 저장은 하지 않는다 — 저장은 호출한 쪽이 `--out` 으로 한다."""
    return {
        "schema": 2,
        "time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "gate": status["gate"], "charge": status["charge"],
        "mode": status["mode"]["name"] if status["mode"] else None,
        "mode_text": status["mode"]["text"] if status["mode"] else None,
        "boost": status["boost"], "fans": status["fans"], "temp_pkg": status["temp_pkg"], "power": status["power"],
    }
