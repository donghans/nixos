#!/usr/bin/env python3
"""sbox 망 관점(vantage) 교차 확인용 탐침 — 표준 라이브러리만 쓰는 단독 스크립트(원격 호스트에 ssh 로 파이프해 실행할 수 있게).

사용: python3 probe.py '<URL 목록 JSON>' [라벨]      표준출력: JSON
각 URL 에 대해 본문 sha256·크기·HTTP 상태와, 그 호스트의 TLS 인증서(전체 sha256·발급 CA·일련번호·유효기간), 이 관점에서 풀린 IP 목록을 기록한다.
**어느 망에서 실행했는지가 의미**다(집 유선·휴대폰 핫스팟·클라우드 인스턴스 등) — 같은 URL 을 여러 망에서 받아 결과를 비교하면
특정 망·지역에만 가짜 응답을 주는 공격(국지적 DNS·BGP 하이재킹, 해당 ISP 의 가로채기)을 알아챌 수 있다. 비교는 `tools.py crosscheck`.
개인정보: 목록의 공개 URL 에만 접속하며, 이 호스트의 이름·계정·경로는 기록하지 않는다(라벨은 호출자가 정한 이름).
"""
import hashlib
import json
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request

MAX_BODY = 8 * 1024 * 1024


def tls_info(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=20) as sk:
        with ctx.wrap_socket(sk, server_hostname=host) as ss:
            der = ss.getpeercert(True)
            c = ss.getpeercert()
    iss = {k: v for t in c.get("issuer", ()) for k, v in t}
    return {
        "cert_sha256": hashlib.sha256(der).hexdigest(),
        "issuer": iss.get("organizationName") or iss.get("commonName"),
        "serial": c.get("serialNumber"),
        "not_before": c.get("notBefore"),
        "not_after": c.get("notAfter"),
    }


def main():
    urls = json.loads(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else "unnamed"
    hosts = {}
    results = []
    for u in urls:
        host = urllib.parse.urlsplit(u).hostname
        if host not in hosts:
            try:
                ips = sorted({a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
            except Exception as e:  # noqa: BLE001
                ips = [f"해석 실패: {str(e)[:40]}"]
            try:
                tls = tls_info(host)
            except Exception as e:  # noqa: BLE001
                tls = {"error": str(e)[:80]}
            hosts[host] = {"ips": ips, "tls": tls}
        r = {"url": u, "host": host}
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "sbox-tools/1.0"})
            with urllib.request.urlopen(req, timeout=40) as resp:  # noqa: S310 — 호출자가 준 공개 https 주소
                body = resp.read(MAX_BODY + 1)
                r["status"] = resp.status
            r["size"] = len(body)
            r["truncated"] = len(body) > MAX_BODY
            r["sha256"] = hashlib.sha256(body[:MAX_BODY]).hexdigest()
        except Exception as e:  # noqa: BLE001
            r["error"] = str(e)[:100]
        results.append(r)
    print(json.dumps({"label": label, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "hosts": hosts, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
