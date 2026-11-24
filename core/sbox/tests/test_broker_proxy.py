#!/usr/bin/env python3
"""sbox broker 송신 프록시 시험(plan dev-sandbox-pilot §29-25, S61). 네트워크 없음 — 로컬 소켓과 가짜 설정만 쓴다.
지키는 것(허용목록이 조용히 넓어지거나 파서가 잘못 통과시키는 것을 막는다):
 ① 와일드카드는 접미사만 맞고 본 도메인·비슷한 이름은 안 맞는다 ② 사설·루프백·CGNAT·IPv4 매핑 주소는 사설로 본다
 ③ ClientHello 에서 SNI 를 꺼내되 깨진·잘린·TLS 아닌 입력은 None ④ 모르는 클라이언트·허용 밖·CONNECT 아닌 요청은 403
 ⑤ 해석 결과가 사설 대역이면 허용된 이름이라도 거부 ⑥ SNI 포트에서 SNI 가 다르면 끊고, 같으면 통과 ⑦ 허용된 터널은 바이트를 그대로 전달
 ⑧ 투명 TLS 수신(S70-b-lite) ⑨ DNS 스텁: 허용된 이름만 broker IP, 나머지 NXDOMAIN, 깨진 질의 무시
실행: python3 -I core/sbox/tests/test_broker_proxy.py  (mods/_tools/run-tests.sh 의 sbox-broker-proxy)"""
import asyncio, json, os, ssl, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import broker_proxy as bp  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def client_hello(name):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    inb, outb = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(inb, outb, server_hostname=name)
    try:
        obj.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return outb.read()


# ① ②
check("wild 하위", bp.host_matches("*.github.com", "api.github.com"))
check("wild 본도메인 제외", not bp.host_matches("*.github.com", "github.com"))
check("wild 유사 이름 제외", not bp.host_matches("*.github.com", "evilgithub.com"))
check("대소문자", bp.host_matches("GitHub.com", "github.COM"))
check("rule 포트", bp.rule_matches("github.com:443", "github.com", 443) and not bp.rule_matches("github.com:443", "github.com", 80))
for ip in ("10.1.2.3", "127.0.0.1", "100.64.1.1", "169.254.1.1", "192.168.0.1", "172.20.0.1", "::ffff:10.0.0.1", "fe80::1"):
    check("사설 " + ip, bp.is_private(ip))
check("공인 1.1.1.1", not bp.is_private("1.1.1.1"))
# ③
check("sni 추출", bp.parse_sni(client_hello("registry.npmjs.org")) == "registry.npmjs.org")
ch = client_hello("example.com")
check("sni 잘림", bp.parse_sni(ch[:30]) is None and bp.parse_sni(ch[:5]) is None)
check("sni 비TLS", bp.parse_sni(b"GET / HTTP/1.1\r\n\r\n") is None and bp.parse_sni(b"") is None)
check("sni 깨진 길이", bp.parse_sni(ch[:5] + b"\xff" * 60) is None)


# ⑧ 매니페스트의 [network] egress 가 tools.write_manifest 로 다시 써져도 사라지지 않는다(2026-11-23 실제로 사라져 broker 허용이 0개가 됐음)
import egress  # noqa: E402
import tools  # noqa: E402
mp = os.path.join(tempfile.mkdtemp(), "m.toml")
tools.write_manifest(mp, "p", "/x", {}, {"compose": "latest"}, {}, tier="critical", network={"egress": ["api.stripe.com", "*.example.com:8443"]})
check("write_manifest 가 [network] 보존", egress.manifest_egress(mp) == ["api.stripe.com:443", "*.example.com:8443"], egress.manifest_egress(mp))
tools.write_manifest(mp, "p", "/x", {}, {}, {}, tier="critical", network=None)
check("network 없으면 허용 0개", egress.manifest_egress(mp) == [])


# S71 프리셋 계산: 자동(flavor·도구)·presets·egress·exclude(규칙·프리셋 이름)·매니페스트 없음·알 수 없는 프리셋
def pm(**net):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.toml")
    tools.write_manifest(p, "p", "/x", {"node": {"spec": "22", "source": "t"}}, {}, {}, tier=None, network=net or None)
    return p
r = egress.compute("sbox-ct-debian13-p", pm())
check("프리셋: debian+node+always", "deb.debian.org:443" in r and "registry.npmjs.org:443" in r and "github.com:443" in r and r["github.com:443"] == "git-github", sorted(r))
check("프리셋: 안 쓰는 도구는 없음", "static.crates.io:443" not in r and "archive.ubuntu.com:443" not in r)
r = egress.compute("sbox-ct-ubuntu2404-p", pm(presets=["rust"], egress=["api.stripe.com"], exclude=["claude.ai:443", "docker"]))
check("프리셋: presets·egress 추가", r.get("crates.io:443") == "rust" and r.get("api.stripe.com:443") == "egress" and "archive.ubuntu.com:443" in r)
check("프리셋: exclude 규칙·프리셋 이름", "claude.ai:443" not in r and "api.anthropic.com:443" in r and "registry-1.docker.io:443" not in r)
check("프리셋: --open 이면 전부", len(egress.compute("sbox-ct-debian13-x", None, open_all=True)) >= 27)
try:
    egress.compute("sbox-ct-debian13-x", None); check("프리셋: 매니페스트도 --open 도 없으면 거부", False)
except SystemExit:
    check("프리셋: 매니페스트도 --open 도 없으면 거부", True)
check("프리셋: 지정했지만 파일 없음(create 중) = flavor·always 만", "registry.npmjs.org:443" not in egress.compute("sbox-ct-debian13-x", "/nonexistent.toml") and "deb.debian.org:443" in egress.compute("sbox-ct-debian13-x", "/nonexistent.toml"))
try:
    egress.compute("sbox-ct-debian13-p", pm(presets=["nope"])); check("프리셋: 알 수 없는 이름 거부", False)
except SystemExit:
    check("프리셋: 알 수 없는 이름 거부", True)


# ⑩ ct NIC ACL(방식 B): 사설 대역 drop 은 broker 한 주소만 빼고 정확히 나머지 전부
import ipaddress  # noqa: E402
rules = egress.acl("x", "10.100.1.163", "3128")["egress"]
dropnets = [ipaddress.ip_network(c) for c in [r for r in rules if r["action"] == "drop"][0]["destination"].split(",")]
check("ACL: broker 는 drop 에 안 걸림", not any(ipaddress.ip_address("10.100.1.163") in n for n in dropnets))
check("ACL: 같은 /24 의 이웃은 drop", any(ipaddress.ip_address("10.100.1.162") in n for n in dropnets) and any(ipaddress.ip_address("10.100.1.164") in n for n in dropnets))
check("ACL: 호스트·다른 사설 대역은 drop", all(any(ipaddress.ip_address(a) in n for n in dropnets) for a in ("10.100.1.1", "10.0.0.1", "172.16.5.5", "192.168.1.1", "100.100.100.100", "169.254.169.254")))
check("ACL: 크기 합 = 사설 전체 − broker 1개", sum(n.num_addresses for n in dropnets) == sum(ipaddress.ip_network(x).num_addresses for x in egress.PRIVATE_NETS) - 1)
check("ACL: 공인 주소는 drop 에 안 걸림", not any(ipaddress.ip_address("20.200.245.247") in n for n in dropnets))
check("ACL: tcp 443·80 아무 곳 허용·udp 는 broker:53 만", any(r["action"] == "allow" and r.get("protocol") == "tcp" and "destination" not in r and r["destination_port"] == "443,80" for r in rules)
      and [r for r in rules if r.get("protocol") == "udp"] == [{"action": "allow", "protocol": "udp", "destination": "10.100.1.163/32", "destination_port": "53", "state": "enabled"}])
b2 = egress.acl("x", "192.168.7.7", "3128")["egress"][-1]["destination"].split(",")
check("ACL: broker 가 다른 사설 대역이어도 같은 규칙", not any(ipaddress.ip_address("192.168.7.7") in ipaddress.ip_network(c) for c in b2))


# ⑨ DNS 스텁 패킷: 질의 파싱·응답 조립
def dns_query(name, qtype=1, ident=0x1234, flags=0x0100):
    q = b"".join(bytes([len(x)]) + x.encode() for x in name.split(".")) + b"\0"
    return ident.to_bytes(2, "big") + flags.to_bytes(2, "big") + b"\0\1\0\0\0\0\0\0" + q + qtype.to_bytes(2, "big") + b"\0\1"


pq = bp.parse_question(dns_query("Registry.NPMJS.org"))
check("dns 질의 파싱", pq and pq[0] == 0x1234 and pq[1] == "registry.npmjs.org" and pq[2] == 1, pq)
check("dns 응답 패킷은 무시", bp.parse_question(dns_query("a.b", flags=0x8100)) is None)
check("dns 질문 둘은 거부", bp.parse_question(dns_query("a.b")[:4] + b"\0\2" + dns_query("a.b")[6:]) is None)
check("dns 압축 포인터 거부", bp.parse_question(b"\0\1\1\0\0\1\0\0\0\0\0\0\xc0\x0c\0\1\0\1") is None)
check("dns 잘린 입력 거부", bp.parse_question(dns_query("a.b")[:15]) is None and bp.parse_question(b"") is None)
ans = bp.build_answer(7, pq[3], 1, 0, ["140.82.112.3", "140.82.112.4"])
check("dns A 응답(둘)", ans[:2] == b"\0\7" and ans[3] & 0xF == 0 and ans[6:8] == b"\0\2" and ans.endswith(bytes([140, 82, 112, 4])), ans)
ans1 = bp.build_answer(7, pq[3], 1, 0, "140.82.112.3")
check("dns A 응답(하나, 문자열)", ans1[6:8] == b"\0\1" and ans1.endswith(bytes([140, 82, 112, 3])), ans1)
nx = bp.build_answer(7, pq[3], 1, 3)
check("dns NXDOMAIN", nx[3] & 0xF == 3 and nx[6:8] == b"\0\0")
check("dns AAAA 는 빈 답", bp.build_answer(7, pq[3], 28, 0, "140.82.112.3")[6:8] == b"\0\0")


async def echo_server():
    async def h(r, w):
        while True:
            d = await r.read(4096)
            if not d:
                break
            w.write(d); await w.drain()
        w.close()
    s = await asyncio.start_server(h, "127.0.0.1", 0)
    return s, s.sockets[0].getsockname()[1]


async def talk(proxy_port, raw, expect_close=False):
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(raw); await w.drain()
    head = await asyncio.wait_for(r.read(4096), 5)
    return r, w, head


async def run():
    es, eport = await echo_server()
    cfgfile = os.path.join(tempfile.mkdtemp(), "c.json")
    def write(cfg):
        json.dump(cfg, open(cfgfile, "w"))
        os.utime(cfgfile, ns=(0, os.stat(cfgfile).st_mtime_ns + 10**9 * write.n)); write.n += 1
    write.n = 1
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": [f"localhost:{eport}"]}}})
    bp._logf = open(os.devnull, "w")
    # 시험용: 사설 대상 허용 프록시와 거부 프록시
    px = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True)
    srv = await asyncio.start_server(px.handle, "127.0.0.1", 0)
    pport = srv.sockets[0].getsockname()[1]
    r, w, head = await talk(pport, f"CONNECT localhost:{eport} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    check("허용 터널 200", head.startswith(b"HTTP/1.1 200"), head)
    w.write(b"ping"); await w.drain()
    check("바이트 그대로 전달", await asyncio.wait_for(r.read(4), 5) == b"ping")
    w.close()
    r, w, head = await talk(pport, f"CONNECT localhost:{eport+1} HTTP/1.1\r\n\r\n".encode())
    check("허용 밖 포트 403", head.startswith(b"HTTP/1.1 403"), head)
    r, w, head = await talk(pport, b"GET http://example.com/ HTTP/1.1\r\n\r\n")
    check("CONNECT 아님 403", head.startswith(b"HTTP/1.1 403"), head)
    r, w, head = await talk(pport, b"CONNECT bad HTTP/1.1\r\n\r\n")
    check("잘못된 대상 400", head.startswith(b"HTTP/1.1 400"), head)
    write({"default_allow": [], "clients": {"10.9.9.9": {"name": "other", "allow": [f"localhost:{eport}"]}}})
    r, w, head = await talk(pport, f"CONNECT localhost:{eport} HTTP/1.1\r\n\r\n".encode())
    check("모르는 클라이언트 403", head.startswith(b"HTTP/1.1 403"), head)
    # 설정을 다시 읽는지(재시작 없이): 허용으로 되돌림
    write({"default_allow": [f"localhost:{eport}"], "clients": {"127.0.0.1": {"name": "t1", "allow": []}}})
    r, w, head = await talk(pport, f"CONNECT localhost:{eport} HTTP/1.1\r\n\r\n".encode())
    check("설정 재적용·default_allow", head.startswith(b"HTTP/1.1 200"), head)
    w.close()
    # ⑤ 사설 해석 거부
    px2 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=False)
    srv2 = await asyncio.start_server(px2.handle, "127.0.0.1", 0)
    p2 = srv2.sockets[0].getsockname()[1]
    r, w, head = await talk(p2, f"CONNECT localhost:{eport} HTTP/1.1\r\n\r\n".encode())
    check("허용 이름이 사설로 해석되면 403", head.startswith(b"HTTP/1.1 403"), head)
    # ⑥ SNI 포트
    bp.SNI_PORTS.add(eport)
    r, w, head = await talk(pport, f"CONNECT localhost:{eport} HTTP/1.1\r\n\r\n".encode())
    w.write(client_hello("evil.example")); await w.drain()
    data = await asyncio.wait_for(r.read(4096), 5)
    check("SNI 불일치는 끊김(에코 없음)", data == b"", data[:20])
    r, w, head = await talk(pport, f"CONNECT localhost:{eport} HTTP/1.1\r\n\r\n".encode())
    hello = client_hello("localhost")
    w.write(hello); await w.drain()
    check("SNI 일치는 통과(에코)", await asyncio.wait_for(r.readexactly(len(hello)), 5) == hello)
    w.close()
    bp.SNI_PORTS.discard(eport)
    # ⑧ 투명 TLS 수신(S70-b-lite): 프록시 요청 없이 ClientHello 만 보내도 SNI 로 판단·전달
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": [f"localhost:{eport}"]}}})
    px3 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, tls_upstream_port=eport)
    srv3 = await asyncio.start_server(px3.handle_tls, "127.0.0.1", 0, limit=32768)
    p3 = srv3.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", p3)
    hello = client_hello("localhost")
    w.write(hello); await w.drain()
    check("투명: 허용 SNI 는 전달(에코)", await asyncio.wait_for(r.readexactly(len(hello)), 5) == hello)
    w.close()
    r, w = await asyncio.open_connection("127.0.0.1", p3)
    w.write(client_hello("evil.example")); await w.drain()
    check("투명: 허용 밖 SNI 는 끊김", await asyncio.wait_for(r.read(4096), 5) == b"")
    w.close()
    r, w = await asyncio.open_connection("127.0.0.1", p3)
    w.write(b"GET / HTTP/1.1\r\n\r\n"); await w.drain()
    check("투명: TLS 아님·SNI 없음은 끊김", await asyncio.wait_for(r.read(4096), 5) == b"")
    w.close()
    r, w = await asyncio.open_connection("127.0.0.1", p3)
    w.write(hello[:20]); await w.drain(); w.write(hello[20:]); await w.drain()     # 조각나서 와도
    check("투명: 조각난 ClientHello", await asyncio.wait_for(r.readexactly(len(hello)), 5) == hello)
    w.close()
    px4 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=False, tls_upstream_port=eport)
    srv4 = await asyncio.start_server(px4.handle_tls, "127.0.0.1", 0, limit=32768)
    r, w = await asyncio.open_connection("127.0.0.1", srv4.sockets[0].getsockname()[1])
    w.write(hello); await w.drain()
    check("투명: 사설로 해석되면 끊김", await asyncio.wait_for(r.read(4096), 5) == b"")
    w.close()
    # 투명 평문 HTTP(80): 이름:80 이 명시된 이름만, Host 로 판단
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": [f"localhost:{eport}"]}}})
    px5 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, http_upstream_port=eport)
    srv5 = await asyncio.start_server(px5.handle_http, "127.0.0.1", 0, limit=9000)
    p5 = srv5.sockets[0].getsockname()[1]
    req = b"GET /x HTTP/1.1\r\nHost: localhost:80\r\n\r\n"
    r, w = await asyncio.open_connection("127.0.0.1", p5)
    w.write(req); await w.drain()
    check("투명 HTTP: 허용 Host 는 전달(에코)", await asyncio.wait_for(r.readexactly(len(req)), 5) == req)
    w.close()
    for bad in (b"GET / HTTP/1.1\r\nHost: evil.example\r\n\r\n", b"GET / HTTP/1.1\r\n\r\n", b"junk"):
        r, w = await asyncio.open_connection("127.0.0.1", p5)
        w.write(bad); await w.drain()
        if bad == b"junk":
            w.write_eof()
        check("투명 HTTP: 허용 밖·Host 없음·깨진 요청은 끊김 " + repr(bad[:12]), await asyncio.wait_for(r.read(4096), 15) == b"")
        w.close()
    srv5.close()
    # DNS 스텁 UDP 왕복
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["registry.npmjs.org:443", "*.github.com:443", "db.x:5432"]}}})
    loop = asyncio.get_running_loop()
    fake = {"registry.npmjs.org": ["104.16.1.1"], "api.github.com": ["140.82.112.5"], "deb.debian.org": ["151.101.2.132"], "priv.example": ["10.1.2.3"]}

    async def fake_resolver(name):
        if name == "boom.example":
            raise OSError("no")
        return fake.get(name, [])
    stub = bp.DnsStub(px3, fake_resolver)
    tr, _ = await loop.create_datagram_endpoint(lambda: stub, local_addr=("127.0.0.1", 0))
    dport = tr.get_extra_info("sockname")[1]

    class Q(asyncio.DatagramProtocol):
        def __init__(self): self.fut = loop.create_future()
        def datagram_received(self, d, a): self.fut.set_result(d)

    async def ask(name, qtype=1):
        qp = Q()
        t, _ = await loop.create_datagram_endpoint(lambda: qp, remote_addr=("127.0.0.1", dport))
        t.sendto(dns_query(name, qtype))
        d = await asyncio.wait_for(qp.fut, 5); t.close(); return d
    d = await ask("registry.npmjs.org")
    check("dns: 허용 이름 → 진짜 주소(broker IP 아님)", d[3] & 0xF == 0 and d.endswith(bytes([104, 16, 1, 1])), d)
    check("dns: 와일드카드 허용", (await ask("api.github.com")).endswith(bytes([140, 82, 112, 5])))
    check("dns: 허용 밖 → NXDOMAIN", (await ask("evil.example"))[3] & 0xF == 3)
    check("dns: 443 이 아닌 규칙만 있는 이름 → NXDOMAIN", (await ask("db.x"))[3] & 0xF == 3)
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["priv.example:443", "boom.example:443", "empty.example:443", "registry.npmjs.org:443"]}}})
    check("dns: 사설로 해석되는 이름은 SERVFAIL(재바인딩 방지)", (await ask("priv.example"))[3] & 0xF == 2)
    check("dns: 조회 실패는 SERVFAIL", (await ask("boom.example"))[3] & 0xF == 2 and (await ask("empty.example"))[3] & 0xF == 2)
    check("dns: 허용 이름 AAAA 는 빈 답", (await ask("registry.npmjs.org", 28))[6:8] == b"\0\0" and (await ask("registry.npmjs.org", 28))[3] & 0xF == 0)
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["deb.debian.org:80"]}}})
    check("dns: 80 만 허용된 이름도 진짜 주소", (await ask("deb.debian.org")).endswith(bytes([151, 101, 2, 132])))
    tr.close()
    for s in (srv, srv2, srv3, srv4, es):
        s.close()


asyncio.run(run())
print(f"{n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
