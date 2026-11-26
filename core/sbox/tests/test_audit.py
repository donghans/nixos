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
SK = {"type": "disk", "readonly": "true", "source": "/nix/store/abc-hm_x", "path": "/etc/claude-code/.claude/skills/donghans-x"}
check("스킬 읽기 전용 마운트는 허용", not any("sbox-skill" in b for b in mut(lambda d: d["expanded_devices"].update({"sbox-skill-donghans-x": dict(SK)}))))
check("읽기 전용 아닌 스킬 장치는 위반", any("sbox-skill-" in b and "읽기 전용" in b for b in mut(lambda d: d["expanded_devices"].update({"sbox-skill-donghans-x": dict(SK, readonly="false")}))))
check("nix store 밖 출처의 스킬 장치는 위반", any("nix store" in b for b in mut(lambda d: d["expanded_devices"].update({"sbox-skill-donghans-x": dict(SK, source="/home/donghans/.claude/skills/x")}))))
check("관리 스킬 경로 밖의 스킬 장치는 위반", any("관리 스킬 경로" in b for b in mut(lambda d: d["expanded_devices"].update({"sbox-skill-donghans-x": dict(SK, path="/home/sbox/.claude/skills/x")}))))
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

# --- 방식 B 불변식(pilot §29-37): ct NIC·공유 ACL·broker 게이트웨이·호스트 sbox-guard ---
import egress  # noqa: E402
def eg(f):
    d = copy.deepcopy(GOOD); d["expanded_devices"]["eth0"].update({"security.acls": "sbox-egress", "security.acls.default.egress.action": "drop",
        "security.ipv4_filtering": "true", "ipv4.address": "10.100.1.205"}); f(d); return audit.check_ct_egress(d)
check("ACL 없는 ct 는 위반 아닌 주의", eg(lambda d: d["expanded_devices"]["eth0"].pop("security.acls")) == ([], eg(lambda d: d["expanded_devices"]["eth0"].pop("security.acls"))[1]) and eg(lambda d: d["expanded_devices"]["eth0"].pop("security.acls"))[1] != [])
check("연결된 ct 정상", eg(lambda d: None) == ([], []), eg(lambda d: None))
check("다른 ACL 이름", eg(lambda d: d["expanded_devices"]["eth0"].update({"security.acls": "x"}))[0] != [])
check("기본 송신 allow", eg(lambda d: d["expanded_devices"]["eth0"].update({"security.acls.default.egress.action": "allow"}))[0] != [])
check("ipv4_filtering 끔", eg(lambda d: d["expanded_devices"]["eth0"].update({"security.ipv4_filtering": "false"}))[0] != [])
check("ct 대역 밖 주소", eg(lambda d: d["expanded_devices"]["eth0"].update({"ipv4.address": "10.100.1.150"}))[0] != [])
BIP = "10.100.1.163"
GACL = egress.acl("sbox-egress", BIP, "3128")
check("ACL 정상", audit.check_acl(GACL, BIP) == [])
a2 = copy.deepcopy(GACL); a2["egress"].insert(0, {"action": "allow", "protocol": "tcp", "destination_port": "22", "state": "enabled"})
check("ACL 에 허용 추가", audit.check_acl(a2, BIP) != [])
a3 = copy.deepcopy(GACL); a3["egress"][-1]["destination"] = "192.168.0.0/16"
check("사설 drop 축소", audit.check_acl(a3, BIP) != [])
check("ACL 못 읽음", audit.check_acl(None, BIP) != [])
RS = "table inet sbox_gateway_filter {\n\tchain forwardguard {\n\t\ttype filter hook forward priority filter; policy drop;\n\t}\n}\n"
check("broker 정상", audit.check_broker("0\n", RS) == [])
check("broker ip_forward 1", audit.check_broker("1\n", RS) != [])
check("broker policy accept", audit.check_broker("0", RS.replace("policy drop", "policy accept")) != [])
check("broker masquerade", audit.check_broker("0", RS + "table ip n { chain p { masquerade } }") != [])
check("broker forward accept", audit.check_broker("0", RS.replace("policy drop;\n", "policy drop;\n\t\tiifname eth0 accept\n")) != [])
check("broker 못 읽음은 None", audit.check_broker(None, RS) is None)
HG = 'table inet sbox-guard {\n\tchain forward {\n\t\tiifname "sboxbr0" oifname != "sboxbr0" ip saddr 10.100.1.200-10.100.1.250 drop\n\t}\n}\n'
check("호스트 가드 정상", audit.check_host_guard(HG) == [])
check("호스트 가드 표 없음", audit.check_host_guard("table inet x {\n}\n") != [])
check("호스트 가드 규칙 없음", audit.check_host_guard(HG.replace(" drop\n", " accept\n")) != [])
check("호스트 못 읽음은 None", audit.check_host_guard(None) is None)
# 관문(S3, U26): 표지가 있는 ct 만, 점검 결과에서 실패한 항목이 위반
G_ON = {"expanded_config": {"user.sbox.gate": "1"}}
OKRES = [("관문 파일이 root 소유 755", True, "root 755"), ("관리 설정 env.CLAUDE_CODE_SHELL 이 관문 경로", True, "")]
BADRES = OKRES + [("관리 설정이 root 소유 644(에이전트가 못 고침)", False, "sbox 666")]
check("관문: 표지가 없는 ct 는 점검 대상이 아니다", audit.check_gate({"expanded_config": {}}, BADRES) == ([], []))
check("관문: 표지 값이 1 이 아니면 대상이 아니다", audit.check_gate({"expanded_config": {"user.sbox.gate": "0"}}, BADRES) == ([], []))
check("관문: 모두 통과하면 위반 없음", audit.check_gate(G_ON, OKRES) == ([], []))
bad, note = audit.check_gate(G_ON, BADRES)
check("관문: 실패한 점검 항목은 위반(항목 이름·상세 포함)", len(bad) == 1 and "root 소유 644" in bad[0] and "sbox 666" in bad[0] and note == [], (bad, note))
bad, note = audit.check_gate(G_ON, None)
check("관문: 못 쟀으면(정지 등) 위반이 아니라 주의", bad == [] and len(note) == 1 and "실행 중이 아니라" in note[0], (bad, note))
print(f"{n['ok']} 통과 / {n['bad']} 실패"); sys.exit(1 if n["bad"] else 0)
