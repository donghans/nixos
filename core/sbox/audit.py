#!/usr/bin/env python3
"""sbox 격리 불변식 점검(읽기 전용) — plan dev-sandbox-pilot S62 의 첫 조각(2026-11-23). 인스턴스 설정이 sboxctl 이 만든 모양에서 벗어났는지 본다.
`raw.*` 키는 Incus 가 안전한 키만 노출하는 대신 LXC·QEMU·AppArmor·seccomp 설정을 그대로 주입하는 우회 통로라(마운트·AppArmor 끄기 등 격리를 풀 수 있음)
sboxctl 이 쓰는 값 외에는 전부 위반으로 본다. 사용: audit.py (모든 sbox-* 인스턴스) | audit.py NAME…   종료 코드 1 = 위반 있음.
"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egress  # noqa: E402

SLICE = "sbox.slice"
BROKER_PORT = "3128"
CT_RANGE = "10.100.1.200-10.100.1.250"
BROKER_SUFFIX = "-broker"


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


def sh(cmd):
    """명령 출력(문자열). 실행할 수 없거나 실패하면 None — 못 쟀음과 정상을 구분하려고."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_ct_egress(inst, expected_acl_name="sbox-egress"):
    """방식 B(pilot §29-37) ct 쪽 불변식. 반환 (위반, 주의). ACL 이 아직 안 붙은 ct 는 위반이 아니라 주의(설치 뒤 `sboxctl egress` 로 연결하는 흐름)."""
    nic = inst.get("expanded_devices", {}).get("eth0", {})
    bad, note = [], []
    acls = nic.get("security.acls")
    if not acls:
        note.append("송신 통제(NIC ACL)가 아직 연결되지 않음 — 'sboxctl egress NAME' 전까지는 호스트 sbox-guard 만이 막고 있음")
        return bad, note
    if acls != expected_acl_name:
        bad.append(f"NIC ACL 이 {expected_acl_name} 하나가 아님: {acls}")
    if nic.get("security.acls.default.egress.action") != "drop":
        bad.append("NIC ACL 기본 송신 동작이 drop 이 아님")
    if nic.get("security.ipv4_filtering") != "true":
        bad.append("ipv4_filtering 이 꺼져 있음(주소 위조 방지)")
    ip = nic.get("ipv4.address", "")
    m = re.fullmatch(r"10\.100\.1\.(\d+)", ip)
    if not m or not 200 <= int(m.group(1)) <= 250:
        bad.append(f"ct 고정 주소가 ct 대역({CT_RANGE})이 아님: {ip!r} — 호스트 forward 가드가 적용되지 않음")
    return bad, note


def check_acl(actual, broker_ip):
    """공유 ACL 이 egress.acl() 이 만드는 규칙과 정확히 같은지(사설 대역 drop 에서 broker 외 예외가 끼어들지 않았는지 포함)."""
    if actual is None:
        return ["ACL sbox-egress 를 읽지 못함"]
    want = egress.acl("sbox-egress", broker_ip, BROKER_PORT)
    if actual.get("ingress"):
        return ["ACL 에 ingress 규칙이 있음"]
    if actual.get("egress") != want["egress"]:
        return ["ACL 송신 규칙이 egress.acl() 이 만드는 모양과 다름(허용이 늘었거나 사설 대역 drop 이 달라짐)"]
    return []


def check_broker(ip_forward, ruleset):
    """broker 게이트웨이 불변식: ip_forward=0, forward 체인 policy drop, masquerade·forward accept 규칙 없음. 읽지 못했으면 None."""
    if ip_forward is None or ruleset is None:
        return None
    bad = []
    if ip_forward.strip() != "0":
        bad.append(f"broker 의 net.ipv4.ip_forward={ip_forward.strip()} (0 이어야 함)")
    if not re.search(r"chain forwardguard \{[^}]*hook forward[^}]*policy drop", ruleset, re.S):
        bad.append("broker 에 forward 기본 거부(policy drop) 체인이 없음")
    if "masquerade" in ruleset or "snat" in ruleset:
        bad.append("broker nft 에 masquerade/snat 규칙이 있음(열린 라우터가 될 수 있음)")
    m = re.search(r"chain forwardguard \{.*?\n\t\}", ruleset, re.S)
    if m and re.search(r"\baccept\b", m.group(0)):
        bad.append("broker forward 체인에 accept 규칙이 있음")
    return bad


def check_host_guard(ruleset):
    """호스트 sbox-guard 가 ct 대역의 브리지 밖 forward 를 drop 하는지. 읽지 못했으면 None."""
    if ruleset is None:
        return None
    m = re.search(r"table inet sbox-guard \{.*?\n\}", ruleset, re.S)
    if not m:
        return ["호스트에 nft 표 sbox-guard 가 없음"]
    if not re.search(r'iifname "sboxbr0" oifname != "sboxbr0" ip saddr 10\.100\.1\.200-10\.100\.1\.250 drop', m.group(0)):
        return ["sbox-guard forward 에 ct 대역→브리지 밖 drop 규칙이 없음"]
    return []


def main(argv):
    names = argv or [i["name"] for i in q("/1.0/instances?recursion=1") if i["name"].startswith("sbox-")]
    total = 0
    insts = q("/1.0/instances?recursion=1")
    broker = next((i for i in insts if i["name"].startswith("sbox-") and i["name"].endswith(BROKER_SUFFIX)), None)
    broker_ip = (broker or {}).get("expanded_devices", {}).get("eth0", {}).get("ipv4.address")
    for n in names:
        inst = q(f"/1.0/instances/{n}")
        bad, note = check(inst), []
        if inst["type"] == "container" and not n.endswith(BROKER_SUFFIX):
            b2, note = check_ct_egress(inst)
            bad += b2
        print(("OK    " if not bad else "위반  ") + n)
        for b in bad:
            print("      - " + b)
        for b in note:
            print("      · 주의: " + b)
        total += len(bad)
    # 호스트·broker 쪽 방식 B 불변식(점검 대상 이름과 무관하게 한 번). 읽지 못하면 위반이 아니라 「못 쟀음」으로 따로 알린다.
    host = []
    if broker_ip:
        try:
            host.append(("ACL sbox-egress", check_acl(q("/1.0/network-acls/sbox-egress"), broker_ip)))
        except subprocess.CalledProcessError:
            host.append(("ACL sbox-egress", None))
    if broker:
        # 최소 NixOS 이미지에는 PATH·sysctl 이 없다 — ct 안의 bash 로 /proc 를 읽고(`incus file pull` 은 호스트 네트워크 이름공간 값을 읽어 틀린다 — 2026-11-25 실제로 속음) nft 는 절대 경로로 부른다(pilot §29-76)
        host.append(("broker 게이트웨이", check_broker(sh(["incus", "exec", broker["name"], "--", "/run/current-system/sw/bin/bash", "-c", "read -r v < /proc/sys/net/ipv4/ip_forward; echo $v"]),
                                                     sh(["incus", "exec", broker["name"], "--", "/run/current-system/sw/bin/nft", "list", "ruleset"]))))
    host.append(("호스트 sbox-guard", check_host_guard(sh(["nft", "list", "ruleset"]) or sh(["sudo", "-n", "nft", "list", "ruleset"]))))
    for label, res in host:
        if res is None:
            print(f"못 쟀음 {label} (읽기 권한·명령 없음)")
        else:
            print(("OK    " if not res else "위반  ") + label)
            for b in res:
                print("      - " + b)
            total += len(res)
    print(f"점검 {len(names)}개, 위반 {total}건")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
