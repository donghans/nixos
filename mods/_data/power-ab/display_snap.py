#!/usr/bin/env python3
"""display_snap — 디스플레이/패키지 절전 관련 상태를 한 번에 저장하고 두 저장본을 비교한다. **root 로 실행**(debugfs).
  sudo display_snap.py save <디렉터리>        # i915_display_info, DMC, PSR, pmc_core(패키지 C-state, slp_s0, substate), DRM 커넥터
  python3 display_snap.py diff <디렉터리A> <디렉터리B>   # 숫자 카운터는 제외하고 상태 줄이 달라진 곳만 보여 준다
용도: 쉬는 전력이 낮은 상태(≈4 W)와 높은 상태(≈6 W)에서 하드웨어 상태가 어디서 달라지는지 찾는다."""
import difflib, glob, os, re, subprocess, sys, time

GPU = "/sys/kernel/debug/dri/0000:00:02.0"
PMC = "/sys/kernel/debug/pmc_core"
FILES = [f"{GPU}/i915_display_info", f"{GPU}/i915_dmc_info", f"{GPU}/i915_edp_psr_status", f"{GPU}/i915_power_domain_info",
         f"{PMC}/package_cstate_show", f"{PMC}/substate_requirements", f"{PMC}/substate_live_status_registers", f"{PMC}/pch_ip_power_gating_status",
         f"{PMC}/ltr_show"]


def rd(p):
    try:
        return open(p).read()
    except OSError as e:
        return f"(읽기 실패: {e})\n"


def save(d):
    os.makedirs(d, exist_ok=True)
    for f in FILES:
        open(os.path.join(d, os.path.basename(f) + ".txt"), "w").write(rd(f))
    pmc_a = {k: rd(f"{PMC}/{k}") for k in ("slp_s0_residency_usec", "substate_residencies")}
    time.sleep(10)
    with open(os.path.join(d, "residency_10s.txt"), "w") as out:
        out.write("slp_s0 증가(us/10s): %d\n" % (int(rd(f"{PMC}/slp_s0_residency_usec").strip() or 0) - int(pmc_a["slp_s0_residency_usec"].strip() or 0)))
        out.write(f"substate_residencies(전):\n{pmc_a['substate_residencies']}\n후:\n{rd(PMC + '/substate_residencies')}")
    drm = "\n".join(f"{os.path.basename(c)}: status={rd(c + '/status').strip()} enabled={rd(c + '/enabled').strip()} dpms={rd(c + '/dpms').strip()}" for c in sorted(glob.glob("/sys/class/drm/card*-*")))
    open(os.path.join(d, "drm_connectors.txt"), "w").write(drm + f"\nVT={rd('/sys/class/tty/tty0/active').strip()} lid={rd('/proc/acpi/button/lid/LID0/state').strip()}\n")
    print("저장:", d)


def norm(t):
    """숫자 카운터/시간처럼 매번 달라지는 값은 지워서 상태 줄만 비교."""
    t = re.sub(r"\b\d{4,}\b", "N", t)
    return [l.rstrip() for l in t.splitlines() if l.strip()]


def diff(a, b):
    n = 0
    for f in sorted(os.listdir(a)):
        pb = os.path.join(b, f)
        if not os.path.exists(pb) or f == "residency_10s.txt":
            continue
        ch = [l for l in difflib.unified_diff(norm(rd(os.path.join(a, f))), norm(rd(pb)), "A", "B", lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        if ch:
            n += 1
            print(f"== {f} ({len(ch)}줄 다름)")
            print("\n".join(ch[:40]))
    print(f"\n다른 파일 {n}개")


if __name__ == "__main__":
    if sys.argv[1] == "save":
        save(sys.argv[2])
    else:
        diff(sys.argv[2], sys.argv[3])
