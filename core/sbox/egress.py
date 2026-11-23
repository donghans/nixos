#!/usr/bin/env python3
"""sbox broker 클라이언트 표 계산기 (plan dev-sandbox-pilot §29-25). 호스트가 상태 파일을 만들어 broker ct 에 밀어 넣는다(정본은 호스트).
  egress.py set    --state F --name N --ip IP [--manifest M] [--allow H[:P]]...   클라이언트 추가·갱신
  egress.py remove --state F --name N
  egress.py show   --state F
상태 파일 = broker_proxy.py 의 설정 형식({"default_allow": [...], "clients": {IP: {"name", "allow"}}}). 기본 허용 세트는 egress.toml.
"""
import argparse, json, os, sys, tempfile, tomllib

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


def defaults():
    with open(os.path.join(HERE, "egress.toml"), "rb") as f:
        return [norm(r) for r in tomllib.load(f).get("default_allow", [])]


def manifest_egress(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        return [norm(r) for r in tomllib.load(f).get("network", {}).get("egress", [])]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["set", "remove", "show"])
    ap.add_argument("--state", required=True)
    ap.add_argument("--name"); ap.add_argument("--ip"); ap.add_argument("--manifest")
    ap.add_argument("--allow", action="append", default=[])
    a = ap.parse_args(argv)
    data = load(a.state)
    if a.cmd == "show":
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)); return 0
    if not a.name:
        raise SystemExit("--name 이 필요합니다")
    data["default_allow"] = defaults()
    clients = data.setdefault("clients", {})
    for ip in [ip for ip, c in clients.items() if c.get("name") == a.name]:
        del clients[ip]                                  # 이름이 같으면 이전 IP 항목을 지운다(IP 가 바뀐 경우)
    if a.cmd == "set":
        if not a.ip:
            raise SystemExit("--ip 가 필요합니다")
        extra = sorted(set(manifest_egress(a.manifest) + [norm(r) for r in a.allow]))
        clients[a.ip] = {"name": a.name, "allow": extra}
        print(f"{a.name} {a.ip}: 기본 {len(data['default_allow'])}개 + 추가 {len(extra)}개")
    save(a.state, data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
