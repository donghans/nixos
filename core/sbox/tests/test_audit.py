#!/usr/bin/env python3
"""sbox 격리 불변식 점검(audit.py) 시험 — incus 없이 가짜 인스턴스 설정으로(plan dev-sandbox-pilot S62 첫 조각).
지키는 것: 정상 설정은 통과하고, `raw.*` 로 격리를 푸는 설정·특권·낯선 장치·프로필 이탈·포트 격리 끔·idmap 끔은 모두 위반으로 잡힌다(조용히 통과하면 안 됨).
실행: python3 -I core/sbox/tests/test_audit.py  (mods/_tools/run-tests.sh 의 sbox-audit)"""
import copy, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import audit  # noqa: E402

n = {"ok": 0, "bad": 0}
def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond: print("  FAIL", name, extra)

N = "sbox-ct-debian13-x"
GOOD = {"name": N, "type": "container", "profiles": ["sbox-ct"],
        "expanded_config": {"security.idmap.isolated": "true", "raw.lxc": audit.expected_raw_lxc(N), "limits.memory": "8GiB"},
        "expanded_devices": {"eth0": {"type": "nic", "network": "sboxbr0", "security.port_isolation": "true"},
                             "root": {"type": "disk", "path": "/", "pool": "default", "size": "10GiB"},
                             "tools-node-22": {"type": "disk", "readonly": "true", "source": "/x", "path": "/opt/tools/node/22"}}}
check("정상 통과", audit.check(GOOD) == [], audit.check(GOOD))

def mut(f):
    d = copy.deepcopy(GOOD); f(d); return audit.check(d)
check("raw.lxc 에 마운트 추가", any("raw.lxc" in b for b in mut(lambda d: d["expanded_config"].update({"raw.lxc": audit.expected_raw_lxc(N) + "\nlxc.mount.entry=/ host none bind 0 0"}))))
check("raw.apparmor", any("raw.apparmor" in b for b in mut(lambda d: d["expanded_config"].update({"raw.apparmor": "x"}))))
check("raw.seccomp", any("raw.seccomp" in b for b in mut(lambda d: d["expanded_config"].update({"raw.seccomp": "x"}))))
check("raw.idmap", any("raw.idmap" in b for b in mut(lambda d: d["expanded_config"].update({"raw.idmap": "both 0 0"}))))
check("특권", any("특권" in b for b in mut(lambda d: d["expanded_config"].update({"security.privileged": "true"}))))
check("프로필 이탈", any("프로필" in b for b in mut(lambda d: d.update({"profiles": ["default"]}))))
check("idmap 격리 끔", any("idmap" in b for b in mut(lambda d: d["expanded_config"].update({"security.idmap.isolated": "false"}))))
check("낯선 장치(호스트 경로)", any("허용 목록에 없는" in b for b in mut(lambda d: d["expanded_devices"].update({"home": {"type": "disk", "source": "/home/x", "path": "/h"}}))))
check("읽기 전용 아닌 tools-", any("tools-" in b for b in mut(lambda d: d["expanded_devices"]["tools-node-22"].update({"readonly": "false"}))))
check("USB 장치", any("허용 목록에 없는" in b for b in mut(lambda d: d["expanded_devices"].update({"u": {"type": "usb"}}))))
check("포트 격리 끔", any("포트 격리" in b for b in mut(lambda d: d["expanded_devices"]["eth0"].update({"security.port_isolation": "false"}))))
check("루트 size 없음", any("size" in b for b in mut(lambda d: d["expanded_devices"]["root"].pop("size"))))
check("다른 브리지", any("허용 목록에 없는" in b for b in mut(lambda d: d["expanded_devices"]["eth0"].update({"network": "incusbr0"}))))
B = "sbox-ct-debian13-broker"
bro = copy.deepcopy(GOOD); bro["name"] = B; bro["expanded_config"]["raw.lxc"] = audit.expected_raw_lxc(B); bro["expanded_devices"]["eth0"]["security.port_isolation"] = "false"
check("broker 는 포트 격리 예외", audit.check(bro) == [], audit.check(bro))
VM = {"name": "sbox-vm-x", "type": "virtual-machine", "expanded_config": {"raw.qemu": "-cpu host,-vmx"}, "expanded_devices": {}}
check("vm 정상", audit.check(VM) == [])
vm2 = copy.deepcopy(VM); vm2["expanded_config"]["raw.qemu"] = "-cpu host"
check("vm raw.qemu 변경", audit.check(vm2) != [])
print(f"{n['ok']} 통과 / {n['bad']} 실패"); sys.exit(1 if n["bad"] else 0)
