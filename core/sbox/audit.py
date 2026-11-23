#!/usr/bin/env python3
"""sbox 격리 불변식 점검(읽기 전용) — plan dev-sandbox-pilot S62 의 첫 조각(2026-11-23). 인스턴스 설정이 sboxctl 이 만든 모양에서 벗어났는지 본다.
`raw.*` 키는 Incus 가 안전한 키만 노출하는 대신 LXC·QEMU·AppArmor·seccomp 설정을 그대로 주입하는 우회 통로라(마운트·AppArmor 끄기 등 격리를 풀 수 있음)
sboxctl 이 쓰는 값 외에는 전부 위반으로 본다. 사용: audit.py (모든 sbox-* 인스턴스) | audit.py NAME…   종료 코드 1 = 위반 있음.
"""
import json, subprocess, sys

SLICE = "sbox.slice"


def q(path):
    return json.loads(subprocess.run(["incus", "query", path], capture_output=True, text=True, check=True).stdout)


def expected_raw_lxc(name):
    return f"lxc.cgroup.dir.container={SLICE}/lxc.payload.{name}\nlxc.cgroup.dir.monitor={SLICE}/lxc.monitor.{name}"


def check(inst):
    name, kind, bad = inst["name"], inst["type"], []
    cfg, dev = inst.get("expanded_config", {}), inst.get("expanded_devices", {})
    raw = {k: v for k, v in cfg.items() if k.startswith("raw.") or k.startswith("linux.")}
    if kind == "container":
        if inst.get("profiles") != ["sbox-ct"]:
            bad.append(f"프로필이 sbox-ct 하나가 아님: {inst.get('profiles')}")
        if cfg.get("security.privileged", "false") == "true":
            bad.append("특권 컨테이너(security.privileged=true)")
        for k, v in raw.items():
            if k == "raw.lxc":
                if v.strip() != expected_raw_lxc(name):
                    bad.append("raw.lxc 가 sboxctl 이 쓰는 두 줄과 다름: " + repr(v[:200]))
            else:
                bad.append(f"{k} 가 설정돼 있음(허용 안 됨)")
        for d, c in dev.items():
            t = c.get("type")
            if d == "eth0" and t == "nic" and c.get("network") == "sboxbr0":
                if c.get("security.port_isolation") != "true" and not name.endswith("-broker"):
                    bad.append("eth0 의 포트 격리가 꺼져 있음(broker 는 예외)")
            elif d == "root" and t == "disk" and c.get("path") == "/":
                if not c.get("size"):
                    bad.append("루트 디스크에 size 한도가 없음")
            elif d.startswith("tools-") and t == "disk" and c.get("readonly") == "true":
                pass
            else:
                bad.append(f"허용 목록에 없는 장치 {d}: {c}")
        if cfg.get("security.idmap.isolated") != "true":
            bad.append("security.idmap.isolated 가 꺼져 있음")
    else:  # virtual-machine
        for k, v in raw.items():
            if not (k == "raw.qemu" and v.strip() == "-cpu host,-vmx"):
                bad.append(f"{k}={v[:80]!r} (허용 안 됨)")
    return bad


def main(argv):
    names = argv or [i["name"] for i in q("/1.0/instances?recursion=1") if i["name"].startswith("sbox-")]
    total = 0
    for n in names:
        bad = check(q(f"/1.0/instances/{n}"))
        print(("OK    " if not bad else "위반  ") + n)
        for b in bad:
            print("      - " + b)
        total += len(bad)
    print(f"점검 {len(names)}개, 위반 {total}건")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
