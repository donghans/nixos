#!/usr/bin/env python3
"""sbox broker 클라이언트 표 계산기 (plan dev-sandbox-pilot §29-25). 호스트가 상태 파일을 만들어 broker ct 에 밀어 넣는다(정본은 호스트).
  egress.py set    --state F --name N --ip IP [--manifest M] [--allow H[:P]]...   클라이언트 추가·갱신
  egress.py remove --state F --name N
  egress.py show   --state F
  egress.py acl    --broker IP [--port 3128]   ct NIC ACL(JSON, 방식 B)
상태 파일 = broker_proxy.py 의 설정 형식({"default_allow": [...], "clients": {IP: {"name", "allow"}}}). 허용 프리셋은 egress-presets.toml(S71) — 클라이언트별 allow 는 프리셋·매니페스트로 계산해 채운다.
"""
import argparse, ipaddress, json, os, re, sys, tempfile, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))


# 아무나 하위 이름·버킷·페이지를 만들 수 있는 서비스의 접미사 — 와일드카드로 허용하면 공격자 소유 이름이 통과한다(pilot §29-45). 정확한 호스트는 허용 가능. 항목을 늘릴 때는 이유를 적는다.
USER_CONTENT_SUFFIXES = {
    "github.io", "githubusercontent.com", "amazonaws.com", "cloudfront.net", "appspot.com", "web.app", "firebaseapp.com", "pages.dev", "workers.dev",
    "vercel.app", "netlify.app", "herokuapp.com", "azurewebsites.net", "blob.core.windows.net", "azureedge.net", "onrender.com", "fly.dev", "ngrok.io",
    "ngrok-free.app", "trycloudflare.com", "gitlab.io", "bitbucket.io", "r2.dev", "supabase.co", "repl.co", "glitch.me", "000webhostapp.com"}


def norm(rule):
    h, sep, p = rule.strip().lower().rpartition(":")
    if not sep or not p.isdigit():
        h, p = rule.strip().lower(), "443"
    if not h or any(c in h for c in " /\\\t") or h.count("*") > 1 or ("*" in h and not h.startswith("*.")):
        raise SystemExit(f"잘못된 허용 항목: {rule!r} (호스트[:포트], 와일드카드는 맨 앞 `*.` 만)")
    if not h.isascii() or any(not (c.isalnum() or c in ".-_*") for c in h):
        raise SystemExit(f"잘못된 허용 항목: {rule!r} (ASCII 영숫자·`.`·`-`·`_` 만 — IDN 은 punycode 로)")
    if h.startswith("*."):
        base = h[2:]
        if base.count(".") < 1 or base in USER_CONTENT_SUFFIXES or any(base.endswith("." + x) for x in USER_CONTENT_SUFFIXES):
            raise SystemExit(f"허용할 수 없는 와일드카드: {rule!r} — 공개 접미사(`*.com`)이거나 아무나 하위 이름을 만들 수 있는 서비스({base})라, 허용하면 공격자 소유 이름으로 데이터를 보낼 수 있다. 필요한 정확한 호스트를 적으세요")
    return f"{h}:{p}"


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"default_allow": [], "clients": {}}


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def presets_table():
    with open(os.path.join(HERE, "egress-presets.toml"), "rb") as f:
        return tomllib.load(f)


def manifest_data(path):
    """None = 매니페스트를 지정하지 않음(= 프로젝트 없음, 최소 세트 요청). 지정했는데 아직 파일이 없으면 {}(create 중 — flavor·always 만 계산, 도구 적용 뒤 다시 계산)."""
    if not path:
        return None
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def manifest_egress(path):
    d = manifest_data(path) or {}
    return [norm(r) for r in d.get("network", {}).get("egress", [])]


def flavor_of(name):
    m = re.match(r"sbox-ct-([a-z]+)\d", name or "")
    return m.group(1) if m else None


def compute(name, manifest_path, extra=(), minimal=False):
    """ct 하나의 허용목록 → (규칙 → 출처 표시 dict). 출처 = 프리셋 이름 | "egress" | "--allow"."""
    t = presets_table()
    pre = t.get("preset", {})
    m = manifest_data(manifest_path)
    net = (m or {}).get("network", {})
    if m is None:
        if not minimal:
            raise SystemExit("매니페스트가 지정되지 않았습니다 — --manifest 를 주거나, 프로젝트 없이 최소 세트(always+flavor)만 쓰려면 --minimal 을 명시하세요")
        m = {}                                      # 프로젝트 없음 = 매니페스트가 비어 있는 것과 같다: always + flavor 프리셋뿐(도구·프로젝트 허용 없음)
    if True:
        names = list(t.get("always", []))
        names += t.get("auto", {}).get("flavor", {}).get(flavor_of(name), [])
        have = set()
        for sec in ("inferred", "override", "resolved"):
            have |= set(m.get(sec, {}))
        for tool, ps in t.get("auto", {}).get("tool", {}).items():
            if tool in have:
                names += ps
        names += net.get("presets", [])
    unknown = [n for n in names if n not in pre]
    if unknown:
        raise SystemExit(f"알 수 없는 프리셋: {', '.join(unknown)} (있는 것: {', '.join(sorted(pre))})")
    excl = [e.strip() for e in net.get("exclude", [])]
    skip_presets = {e for e in excl if e in pre}
    skip_rules = {norm(e) for e in excl if e not in pre}
    out = {}
    for n in dict.fromkeys(names):
        if n in skip_presets:
            continue
        for r in pre[n].get("allow", []):
            out.setdefault(norm(r), n)
    for r in manifest_egress(manifest_path):
        out.setdefault(r, "egress")
    for r in extra:
        out.setdefault(norm(r), "--allow")
    for r in skip_rules:
        out.pop(r, None)
    return out


PRIVATE_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"]


def private_minus(broker_ip):
    """사설 대역 전체에서 broker 한 주소만 뺀 CIDR 목록. Incus ACL 은 drop 이 allow 보다 먼저 평가되므로(pilot §29-35 ②)
    「사설 대역 drop」 은 broker 를 제외해서 만들어야 broker 로 가는 길이 열려 있다."""
    b = ipaddress.ip_network(broker_ip + "/32")
    out = []
    for n in PRIVATE_NETS:
        net = ipaddress.ip_network(n)
        out += [str(x) for x in (net.address_exclude(b) if b.subnet_of(net) else [net])]
    return out


INJECT_PORT = "3130"   # 키 주입 어댑터(S64) 수신 포트 — ct 가 broker 로 평문 요청을 보내는 곳


def acl(name, broker_ip, proxy_port):
    """ct 의 NIC ACL(방식 B, pilot §29-37): broker 의 프록시·DNS, 어디로든 tcp 443·80(broker 의 redirect 가 받음), 사설 대역은 broker 를 빼고 drop.
    기본 egress 동작은 NIC 쪽에서 drop 으로 따로 지정한다. 그래서 UDP(QUIC)·그 밖의 포트는 broker 의 udp 53 외에는 막힌다."""
    return {"name": name, "description": "sbox ct 송신(방식 B): broker(프록시·DNS)와 어디로든 tcp 443·80(broker 게이트웨이가 redirect), 사설 대역은 broker 만 예외로 drop", "egress": [
        {"action": "allow", "protocol": "tcp", "destination": broker_ip + "/32", "destination_port": f"{proxy_port},{INJECT_PORT},53", "state": "enabled"},
        {"action": "allow", "protocol": "udp", "destination": broker_ip + "/32", "destination_port": "53", "state": "enabled"},
        {"action": "allow", "protocol": "tcp", "destination_port": "443,80", "state": "enabled"},
        {"action": "drop", "destination": ",".join(private_minus(broker_ip)), "state": "enabled"}], "ingress": []}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["set", "remove", "show", "acl", "inject-set", "inject-get", "inject-clear"])
    ap.add_argument("--adapter", default="anthropic"); ap.add_argument("--placeholder")
    ap.add_argument("--state")
    ap.add_argument("--broker"); ap.add_argument("--port", default="3128"); ap.add_argument("--acl-name", default="sbox-egress")
    ap.add_argument("--name"); ap.add_argument("--ip"); ap.add_argument("--manifest")
    ap.add_argument("--allow", action="append", default=[]); ap.add_argument("--minimal", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "acl":
        if not a.broker:
            raise SystemExit("--broker 가 필요합니다")
        print(json.dumps(acl(a.acl_name, a.broker, a.port)))
        return 0
    if not a.state:
        raise SystemExit("--state 가 필요합니다")
    data = load(a.state)
    if a.cmd == "show":
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)); return 0
    if not a.name:
        raise SystemExit("--name 이 필요합니다")
    data["default_allow"] = []                           # S71 부터 공통 세트 없음 — 전부 클라이언트별(프리셋 계산 결과)
    clients = data.setdefault("clients", {})
    old_inject = {}
    for ip in [ip for ip, c in clients.items() if c.get("name") == a.name]:
        old_inject = clients[ip].get("inject") or old_inject   # 키 주입 자리표시자는 허용목록을 다시 계산해도 유지한다
        if a.cmd != "inject-set" and a.cmd != "inject-clear" and a.cmd != "inject-get":
            del clients[ip]                              # 이름이 같으면 이전 IP 항목을 지운다(IP 가 바뀐 경우)
    if a.cmd == "inject-get":
        ent = next((c for c in clients.values() if c.get("name") == a.name), None)
        print(((ent or {}).get("inject") or {}).get(a.adapter, {}).get("placeholder", ""))
        return 0
    if a.cmd in ("inject-set", "inject-clear"):
        ent = next((c for c in clients.values() if c.get("name") == a.name), None)
        if ent is None:
            raise SystemExit(f"{a.name} 는 broker 에 연결돼 있지 않습니다 — 먼저 'sboxctl egress {a.name}'")
        if a.cmd == "inject-set":
            if not a.placeholder or len(a.placeholder) < 40 or "placeholder" not in a.placeholder:
                raise SystemExit("--placeholder 는 40자 이상이고 'placeholder' 표지가 들어 있어야 합니다(사람·스캐너가 가짜임을 알아보게)")
            ent.setdefault("inject", {})[a.adapter] = {"placeholder": a.placeholder}
        else:
            (ent.get("inject") or {}).pop(a.adapter, None)
        save(a.state, data)
        return 0
    if a.cmd == "set":
        if not a.ip:
            raise SystemExit("--ip 가 필요합니다")
        rules = compute(a.name, a.manifest, a.allow, a.minimal)
        clients[a.ip] = {"name": a.name, "allow": sorted(rules), "sources": dict(sorted(rules.items()))}
        if old_inject:
            clients[a.ip]["inject"] = old_inject
        by = {}
        for s_ in rules.values():
            by[s_] = by.get(s_, 0) + 1
        print(f"{a.name} {a.ip}: 허용 {len(rules)}개 (" + ", ".join(f"{k} {v}" for k, v in by.items()) + ")")
    save(a.state, data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
