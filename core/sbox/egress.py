#!/usr/bin/env python3
"""sbox broker 클라이언트 표 계산기 (plan dev-sandbox-pilot §29-25). 호스트가 상태 파일을 만들어 broker ct 에 밀어 넣는다(정본은 호스트).
  egress.py set    --state F --name N --ip IP [--manifest M] [--allow H[:P]]...   클라이언트 추가·갱신
  egress.py remove --state F --name N
  egress.py show   --state F
상태 파일 = broker_proxy.py 의 설정 형식({"default_allow": [...], "clients": {IP: {"name", "allow"}}}). 허용 프리셋은 egress-presets.toml(S71) — 클라이언트별 allow 는 프리셋·매니페스트로 계산해 채운다.
"""
import argparse, json, os, re, sys, tempfile, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))


def norm(rule):
    h, sep, p = rule.strip().lower().rpartition(":")
    if not sep or not p.isdigit():
        h, p = rule.strip().lower(), "443"
    if not h or any(c in h for c in " /\\\t") or h.count("*") > 1 or ("*" in h and not h.startswith("*.")):
        raise SystemExit(f"잘못된 허용 항목: {rule!r} (호스트[:포트], 와일드카드는 맨 앞 `*.` 만)")
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
    """None = 매니페스트를 지정하지 않음(= 열린 허용 요청). 지정했는데 아직 파일이 없으면 {}(create 중 — flavor·always 만 계산, 도구 적용 뒤 다시 계산)."""
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


def compute(name, manifest_path, extra=(), open_all=False):
    """ct 하나의 허용목록 → (규칙 → 출처 표시 dict). 출처 = 프리셋 이름 | "egress" | "--allow"."""
    t = presets_table()
    pre = t.get("preset", {})
    m = manifest_data(manifest_path)
    net = (m or {}).get("network", {})
    if m is None:
        if not open_all:
            raise SystemExit("매니페스트가 지정되지 않았습니다 — --manifest 를 주거나, 프로젝트 없이 모든 프리셋을 허용하려면 --open 을 명시하세요")
        names = list(pre)                           # 열린 허용: 모든 프리셋(위험 — 호출한 쪽이 사용자 확인을 받는다)
    else:
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


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["set", "remove", "show"])
    ap.add_argument("--state", required=True)
    ap.add_argument("--name"); ap.add_argument("--ip"); ap.add_argument("--manifest")
    ap.add_argument("--allow", action="append", default=[]); ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    data = load(a.state)
    if a.cmd == "show":
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)); return 0
    if not a.name:
        raise SystemExit("--name 이 필요합니다")
    data["default_allow"] = []                           # S71 부터 공통 세트 없음 — 전부 클라이언트별(프리셋 계산 결과)
    clients = data.setdefault("clients", {})
    for ip in [ip for ip, c in clients.items() if c.get("name") == a.name]:
        del clients[ip]                                  # 이름이 같으면 이전 IP 항목을 지운다(IP 가 바뀐 경우)
    if a.cmd == "set":
        if not a.ip:
            raise SystemExit("--ip 가 필요합니다")
        rules = compute(a.name, a.manifest, a.allow, a.open)
        clients[a.ip] = {"name": a.name, "allow": sorted(rules), "sources": dict(sorted(rules.items()))}
        by = {}
        for s_ in rules.values():
            by[s_] = by.get(s_, 0) + 1
        print(f"{a.name} {a.ip}: 허용 {len(rules)}개 (" + ", ".join(f"{k} {v}" for k, v in by.items()) + ")")
    save(a.state, data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
