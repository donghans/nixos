#!/usr/bin/env python3
"""power_knobs — 절전에 영향을 주는 sysfs/proc 설정 값을 한 번에 저장하고 두 저장본의 차이를 보인다. **읽기 전용, 일반 권한으로 됨**(debugfs 안 씀 → 화면 상태를 건드리지 않음).
  power_knobs.py save <파일>       # 지금 값을 JSON 으로 저장
  power_knobs.py diff <A> <B>      # 달라진 설정만 출력
용도: AC 를 꽂았다 뽑은 뒤처럼 "설정이 원래대로 안 돌아온 것 같은" 상태를 전/중/후 스냅샷으로 비교해 어떤 설정이 남았는지 찾는다(2026-10-20: AC 분리 뒤 패키지가 PC3 에 2시간 막힘).
포함: CPU(governor/EPP/EPB/주파수 한계/intel_pstate), platform_profile, PCIe ASPM 정책과 장치별 link 설정, PCI/USB/NVMe/SCSI 런타임 PM·링크 전력,
      i915/GT(RPS, SLPC 프로파일), 오디오/Wi-Fi 절전, vm/nmi 튜닝, TLP 마지막 적용(/run/tlp)."""
import glob, json, os, subprocess, sys, collections

def rd(p):
    try:
        return open(p).read().strip()
    except OSError:
        return None

def uniq(paths):
    c = collections.Counter(rd(p) for p in paths)
    return dict(c) if c else None

def snap():
    k = {}
    cpu = "/sys/devices/system/cpu"
    for name in ("scaling_governor", "energy_performance_preference", "scaling_max_freq", "scaling_min_freq"):
        k[f"cpu.{name}"] = uniq(glob.glob(f"{cpu}/cpu[0-9]*/cpufreq/{name}"))
    k["cpu.energy_perf_bias"] = uniq(glob.glob(f"{cpu}/cpu[0-9]*/power/energy_perf_bias"))
    for f in ("status", "no_turbo", "max_perf_pct", "min_perf_pct", "hwp_dynamic_boost"):
        k[f"intel_pstate.{f}"] = rd(f"{cpu}/intel_pstate/{f}")
    k["platform_profile"] = rd("/sys/firmware/acpi/platform_profile")
    k["pcie_aspm.policy"] = rd("/sys/module/pcie_aspm/parameters/policy")
    for d in sorted(glob.glob("/sys/bus/pci/devices/*")):
        n = os.path.basename(d)
        k[f"pci.{n}.power_control"] = rd(d + "/power/control")
        for f in sorted(glob.glob(d + "/link/*")):
            k[f"pci.{n}.link.{os.path.basename(f)}"] = rd(f)
    for d in sorted(glob.glob("/sys/bus/usb/devices/[0-9]*")):
        if os.path.exists(d + "/power/control"):
            k[f"usb.{os.path.basename(d)}.control"] = rd(d + "/power/control")
            k[f"usb.{os.path.basename(d)}.autosuspend_ms"] = rd(d + "/power/autosuspend_delay_ms")
    for d in sorted(glob.glob("/sys/class/scsi_host/host*")):
        k[f"scsi.{os.path.basename(d)}.link_pm"] = rd(d + "/link_power_management_policy")
    for d in sorted(glob.glob("/sys/class/nvme/nvme*")):
        k[f"nvme.{os.path.basename(d)}.control"] = rd(d + "/device/power/control")
    gt = "/sys/class/drm/card1/gt/gt0"
    for f in ("rps_min_freq_mhz", "rps_max_freq_mhz", "rps_boost_freq_mhz", "slpc_power_profile", "rc6_enable"):
        k[f"gt.{f}"] = rd(f"{gt}/{f}")
    k["snd_hda.power_save"] = rd("/sys/module/snd_hda_intel/parameters/power_save")
    k["snd_hda.power_save_controller"] = rd("/sys/module/snd_hda_intel/parameters/power_save_controller")
    k["vm.laptop_mode"] = rd("/proc/sys/vm/laptop_mode")
    k["vm.dirty_writeback_centisecs"] = rd("/proc/sys/vm/dirty_writeback_centisecs")
    k["kernel.nmi_watchdog"] = rd("/proc/sys/kernel/nmi_watchdog")
    k["tlp.last_pwr"] = rd("/run/tlp/last_pwr")
    for d in glob.glob("/sys/class/power_supply/*"):
        if rd(d + "/type") == "Mains":
            k["ac.online"] = rd(d + "/online")
    try:
        iw = [p for p in glob.glob("/nix/store/*-iw-*/bin/iw")][:1]
        if iw:
            k["wifi.power_save"] = subprocess.run([iw[0], "dev", "wlan0", "get", "power_save"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        pass
    return k

def main():
    if sys.argv[1] == "save":
        json.dump(snap(), open(sys.argv[2], "w"), ensure_ascii=False, indent=0, sort_keys=True)
        print("저장:", sys.argv[2])
    else:
        a, b = json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
        keys = sorted(set(a) | set(b))
        diff = [(k, a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)]
        print(f"달라진 설정 {len(diff)}개 / 전체 {len(keys)}개")
        for k, x, y in diff:
            print(f"  {k}: {x} → {y}")

if __name__ == "__main__":
    main()
