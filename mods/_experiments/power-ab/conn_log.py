#!/usr/bin/env python3
"""conn_log — 이 노트북에서 **밖으로 나가는 새 연결**을 conntrack(/proc/net/nf_conntrack)에서 세어 프로세스·목적지별로 요약한다. **root 로 실행**.
핫스팟에서는 모든 연결이 폰의 SOCKS5 프록시로 가므로 노트북 쪽 연결 로그가 곧 프록시 로그다. 내용(URL/데이터)은 보지 않고 목적지 IP:포트와 개수만 센다.
  sudo conn_log.py [초=60] [주기 초=2]
- 대상: 원래 출발지가 이 노트북의 무선 인터페이스 주소(또는 127.0.0.1)이고 목적지가 사설대역이 아닌 연결(TCP/UDP).
- 프로세스는 같은 순간의 `ss -tunp` 로 지역 포트를 찾아 붙이는 최선 노력 방식이라(이미 끝난 연결은 알 수 없음) '?' 가 섞인다.
결과는 JSON 한 줄: 초당 새 연결 수, 프로토콜별, 프로세스별 상위, 목적지(IP:포트) 상위."""
import collections, ipaddress, json, re, subprocess, sys, time

SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 60
STEP = float(sys.argv[2]) if len(sys.argv) > 2 else 2


def wlan_ips():
    out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
    return {m[1] for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)/", out)}


def parse(line):
    """nf_conntrack 한 줄 → (proto, 원 src, sport, 원 dst, dport) 또는 None. 첫 번째 src=/dst= 가 원래 방향."""
    f = line.split()
    if len(f) < 4 or f[2] not in ("tcp", "udp"):
        return None
    d = dict()
    for x in f:
        if "=" in x and x.split("=")[0] not in d:
            d[x.split("=")[0]] = x.split("=")[1]
    try:
        return f[2], d["src"], int(d["sport"]), d["dst"], int(d["dport"])
    except (KeyError, ValueError):
        return None


def is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return a.is_private or a.is_loopback or a.is_multicast or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")


def owners():
    out = subprocess.run(["ss", "-tunpH"], capture_output=True, text=True).stdout
    m = {}
    for l in out.splitlines():
        f = l.split()
        pm = re.search(r'users:\(\("([^"]+)"', l)
        if len(f) >= 6 and pm:
            m[(f[0], f[4].rsplit(":", 1)[-1])] = pm[1]
    return m


def snapshot(mine):
    keys = set()
    try:
        for line in open("/proc/net/nf_conntrack"):
            p = parse(line)
            if p and (p[1] in mine or p[1] == "127.0.0.1") and not is_private(p[3]):
                keys.add(p)
    except OSError:
        pass
    return keys


def main():
    mine = wlan_ips()
    seen = snapshot(mine)
    new_total, proto, by_proc, by_dst = 0, collections.Counter(), collections.Counter(), collections.Counter()
    end = time.time() + SEC
    while time.time() < end:
        time.sleep(STEP)
        own = owners()
        for k in snapshot(mine) - seen:
            new_total += 1
            proto[k[0]] += 1
            by_proc[own.get((k[0], str(k[2])), "?")] += 1
            by_dst[f"{k[0]} {k[3]}:{k[4]}"] += 1
            seen.add(k)
    print(json.dumps({"seconds": SEC, "new_per_s": round(new_total / SEC, 2), "new_total": new_total, "proto": dict(proto),
                      "top_process": by_proc.most_common(6), "top_dest": by_dst.most_common(10)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
