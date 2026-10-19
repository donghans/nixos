#!/usr/bin/env python3
"""pm_snapshot — PCI/USB/오디오/네트워크 장치의 런타임 절전 상태를 한 파일로 저장하고 두 스냅샷의 차이를 보여준다.
  pm_snapshot.py save <파일>        지금 상태 저장(JSON)
  pm_snapshot.py diff <앞> <뒤>     바뀐 장치만 출력
독을 뺐다 꽂은 뒤 전력이 달라지는 원인(어느 컨트롤러의 절전 상태가 바뀌는지)을 찾는 데 쓴다."""
import glob, json, os, sys


def rd(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def snap() -> dict:
    out = {}
    for d in sorted(glob.glob("/sys/bus/pci/devices/*")):
        n = os.path.basename(d)
        drv = os.path.basename(os.path.realpath(f"{d}/driver")) if os.path.exists(f"{d}/driver") else "-"
        out[f"pci {n} ({drv})"] = f"{rd(d + '/power/runtime_status')}/{rd(d + '/power/control')}/{rd(d + '/power_state')}"
    for d in sorted(glob.glob("/sys/bus/usb/devices/[0-9]*")):
        n = os.path.basename(d)
        if ":" in n:
            continue
        out[f"usb {n} {rd(d + '/product') or ''}"] = f"{rd(d + '/power/runtime_status')}/{rd(d + '/power/control')}"
    for d in sorted(glob.glob("/sys/class/net/*")):
        n = os.path.basename(d)
        if n != "lo":
            out[f"net {n}"] = rd(d + "/operstate")
    out["meta"] = f"{rd('/sys/class/power_supply/ADP1/online')} AC"
    return out


def main(argv):
    if argv[:1] == ["save"] and len(argv) == 2:
        json.dump(snap(), open(argv[1], "w"), ensure_ascii=False, indent=1)
        print(f"저장: {argv[1]} ({len(snap())}개 항목)")
        return 0
    if argv[:1] == ["diff"] and len(argv) == 3:
        a, b = json.load(open(argv[1])), json.load(open(argv[2]))
        n = 0
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print(f"{k}\n    {a.get(k)}  →  {b.get(k)}")
                n += 1
        print(f"\n바뀐 항목 {n}개 / 전체 {len(set(a) | set(b))}개")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
