#!/usr/bin/env python3
"""posture-doctor — 사용 모드 허브와 소비자들이 제대로 이어져 있는지 한 번에 점검한다.

  posture-doctor            점검하고 결과를 표시(문제가 있으면 종료 코드 1)
  posture-doctor --json     같은 내용을 JSON 으로

오늘(2026-10-19) 실제로 겪은 문제들을 잡도록 만들었다. 시험(가짜 도구)이 못 잡는 "통합" 단계의 고장이 목적이다:
  - 사용자 서비스 환경(systemctl --user show-environment)에 Hyprland 변수가 없거나 죽은 값(중첩 Hyprland 시험이 오염시킴) → 서비스의 hyprctl 이 전부 실패
  - 허브 데몬이 죽었거나 센서/덮개 읽기 오류
  - posture-apply 소비자가 실패 중
  - 덮개는 열렸는데 화면이 꺼진 채(백라이트 0, 저장된 밝기가 남아 있음) / 반대로 닫혔는데 켜진 채
  - 상태 파일과 실제 덮개 상태(ACPI)가 어긋남
각 항목은 OK / WARN / FAIL 과 해결 힌트를 낸다. 시험용 환경변수: POSTURE_STATE_DIR, DOCTOR_SYSTEMCTL, DOCTOR_HYPRCTL, DOCTOR_JOURNALCTL, DOCTOR_RUNTIME_DIR, DOCTOR_BACKLIGHT_DIR, DOCTOR_LID_STATE
"""
import glob
import json
import os
import subprocess
import sys

STATE_DIR = os.environ.get("POSTURE_STATE_DIR", "/run/posture")
SYSTEMCTL = os.environ.get("DOCTOR_SYSTEMCTL", "systemctl")
HYPRCTL = os.environ.get("DOCTOR_HYPRCTL", "hyprctl")
JOURNALCTL = os.environ.get("DOCTOR_JOURNALCTL", "journalctl")
RUNTIME = os.environ.get("DOCTOR_RUNTIME_DIR") or os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
BACKLIGHT = os.environ.get("DOCTOR_BACKLIGHT_DIR", "/sys/class/backlight")
LID_STATE = os.environ.get("DOCTOR_LID_STATE", "")

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def run(*cmd, timeout=10) -> tuple[int, str]:
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def read_json(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def manager_env() -> dict:
    """사용자 서비스(systemd --user)가 보는 환경. 서비스에서 도는 소비자는 이 값으로 hyprctl 을 부른다."""
    rc, out = run(SYSTEMCTL, "--user", "show-environment")
    env = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        env[k] = v
    return env


# ───────────────────────── 점검 항목 (각각 (등급, 이름, 설명, 힌트) 목록을 돌려줌) ─────────────────────────
def check_daemon() -> list:
    rc, _ = run(SYSTEMCTL, "is-active", "--quiet", "posture-daemon.service")
    if rc != 0:
        return [(FAIL, "허브 데몬", "posture-daemon 이 실행 중이 아님 (CLI 는 안전한 기본값 laptop/덮개 열림을 돌려줌)", "sudo systemctl restart posture-daemon; journalctl -u posture-daemon -n 20")]
    st = read_json(os.path.join(STATE_DIR, "state.json"))
    if not st:
        return [(FAIL, "허브 상태 파일", f"{STATE_DIR}/state.json 이 없거나 깨짐", "sudo systemctl restart posture-daemon")]
    out = [(OK, "허브 데몬", f"실행 중, 모드 {st.get('mode')}, 덮개 {st.get('lid')}, 방향 {st.get('orientation')}", "")]
    for name, val in (st.get("sensors") or {}).items():
        if val == "error":
            out.append((WARN, f"센서 {name}", "읽기 오류(허브가 이 센서를 포기함)", "journalctl -u posture-daemon; sudo systemctl restart posture-daemon"))
    return out


def check_manager_env() -> list:
    env = manager_env()
    sig, wl = env.get("HYPRLAND_INSTANCE_SIGNATURE", ""), env.get("WAYLAND_DISPLAY", "")
    fix = ("서비스에서 부르는 hyprctl 이 전부 실패한다. 복구: systemctl --user set-environment WAYLAND_DISPLAY=<소켓> HYPRLAND_INSTANCE_SIGNATURE=<서명> HYPRLAND_CMD=… DISPLAY=… "
           "(값은 Hyprland 안의 셸에서 printenv 로) 또는 재로그인")
    out = []
    if not sig:
        out.append((FAIL, "서비스 환경: HYPRLAND_INSTANCE_SIGNATURE", "비어 있음 — 중첩 Hyprland 시험 뒤에 흔함", fix))
    else:
        d = os.path.join(RUNTIME, "hypr", sig)
        rc, _ = run(HYPRCTL, "-i", sig, "version")
        if not os.path.isdir(d):
            out.append((FAIL, "서비스 환경: HYPRLAND_INSTANCE_SIGNATURE", f"{sig[:24]}… 인스턴스 디렉터리가 없음(죽은 인스턴스를 가리킴)", fix))
        elif rc != 0:
            out.append((FAIL, "서비스 환경: HYPRLAND_INSTANCE_SIGNATURE", "인스턴스에 연결 안 됨(hyprctl -i 실패)", fix))
        else:
            out.append((OK, "서비스 환경: HYPRLAND_INSTANCE_SIGNATURE", "살아 있는 인스턴스를 가리킴", ""))
    if not wl or not os.path.exists(os.path.join(RUNTIME, wl)):
        out.append((FAIL, "서비스 환경: WAYLAND_DISPLAY", f"'{wl}' 소켓이 없음(죽은 디스플레이를 가리킴)", fix))
    else:
        out.append((OK, "서비스 환경: WAYLAND_DISPLAY", wl, ""))
    return out


def check_path_unit() -> list:
    rc, _ = run(SYSTEMCTL, "--user", "is-active", "--quiet", "posture-apply.path")
    if rc != 0:
        return [(FAIL, "posture-apply.path", "상태 변경 감시 유닛이 실행 중이 아님 → 소비자가 안 불림", "systemctl --user start posture-apply.path")]
    return [(OK, "posture-apply.path", "상태 변경 감시 중", "")]


def check_consumer_failures() -> list:
    """마지막으로 끝난 한 패스(직전 'applied:' 와 마지막 'applied:' 사이)에서 실패한 소비자가 있는지.
    (주의: 부팅 직후 약 30초는 시각이 9시간 앞서 옛 기록이 섞이므로 시각이 아니라 기록의 순서로 본다)"""
    rc, out = run(JOURNALCTL, "--user", "-b", "-t", "posture-apply", "-o", "cat", "-n", "80", "--no-pager")
    if rc != 0:
        return [(WARN, "소비자 실행 기록", "저널을 읽지 못함", "")]
    lines = out.splitlines()
    done = [i for i, l in enumerate(lines) if l.startswith("applied:")]
    if not done:
        return [(OK, "소비자 실행", "아직 실행 기록 없음", "")]
    start = done[-2] + 1 if len(done) > 1 else 0
    failed = [l for l in lines[start:done[-1]] if "소비자 실패" in l]
    if failed:
        names = sorted({l.split("소비자 실패:")[-1].strip().split("/bin/")[-1] for l in failed})
        return [(WARN, "소비자 실행", "마지막 실행에서 실패한 소비자: " + ", ".join(names), "그 명령을 서비스 환경에서 직접 실행해 오류를 본다: systemd-run --user --wait --pty <명령>")]
    return [(OK, "소비자 실행", "마지막 실행에서 실패 없음", "")]


def lid_from_acpi() -> str | None:
    paths = [LID_STATE] if LID_STATE else sorted(glob.glob("/proc/acpi/button/lid/*/state"))
    for p in paths:
        try:
            v = open(p).read().split(":")[-1].strip()
            if v in ("open", "closed"):
                return v
        except OSError:
            pass
    return None


def check_lid_and_screen() -> list:
    st = read_json(os.path.join(STATE_DIR, "state.json")) or {}
    hub = st.get("lid")
    acpi = lid_from_acpi()
    out = []
    if acpi and hub and acpi != hub:
        out.append((FAIL, "덮개 상태", f"허브는 {hub}, 실제(ACPI)는 {acpi} — 이벤트를 놓쳤거나 데몬 문제", "sudo systemctl restart posture-daemon"))
    elif acpi:
        out.append((OK, "덮개 상태", f"허브와 ACPI 모두 {acpi}", ""))
    # 화면(백라이트)
    bl = sorted(glob.glob(os.path.join(BACKLIGHT, "*")))
    if bl:
        try:
            cur = int(open(os.path.join(bl[0], "actual_brightness")).read())
        except (OSError, ValueError):
            cur = None
        saved = os.path.join(RUNTIME, "lid_brightness")
        applied = (open(os.path.join(RUNTIME, "lid_applied")).read().strip() if os.path.exists(os.path.join(RUNTIME, "lid_applied")) else None)
        lid = hub or acpi
        if cur == 0 and lid == "open":
            out.append((FAIL, "화면", "덮개는 열렸는데 백라이트가 0 (저장된 밝기: " + ("있음" if os.path.exists(saved) else "없음") + ")", "lid-screen on  (없으면 밝기 키)"))
        elif cur not in (None, 0) and lid == "closed":
            out.append((WARN, "화면", "덮개는 닫혔는데 백라이트가 켜져 있음(방금 닫았다면 잠시 뒤 꺼짐)", "lid-policy"))
        elif cur is not None:
            out.append((OK, "화면", f"백라이트 {cur}, 덮개 {lid}, 마지막 적용 {applied}", ""))
    return out


CHECKS = [check_daemon, check_manager_env, check_path_unit, check_consumer_failures, check_lid_and_screen]


def main(argv) -> int:
    rows = []
    for fn in CHECKS:
        try:
            rows += fn()
        except Exception as e:                      # 점검 자체가 죽어서 다른 점검을 가리지 않게
            rows.append((WARN, fn.__name__, f"점검 중 예외: {e}", ""))
    if "--json" in argv:
        print(json.dumps([{"level": l, "name": n, "detail": d, "hint": h} for l, n, d, h in rows], ensure_ascii=False))
    else:
        icon = {OK: "✔", WARN: "!", FAIL: "✘"}
        for l, n, d, h in rows:
            print(f"{icon[l]} [{l}] {n}: {d}")
            if h and l != OK:
                print(f"      → {h}")
        bad = sum(1 for r in rows if r[0] == FAIL); warn = sum(1 for r in rows if r[0] == WARN)
        print(f"\n{len(rows)}개 점검: 문제 {bad}, 경고 {warn}")
    return 1 if any(r[0] == FAIL for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
