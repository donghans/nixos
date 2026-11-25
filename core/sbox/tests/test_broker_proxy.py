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


async def local_resolver(name):          # 시험은 실제 DNS 를 쓰지 않는다
    return ["127.0.0.1"] if name == "localhost" else []


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
# 모호한 ClientHello 거부(pilot §29-45): ECH·중복 확장·여러 server_name
def hello_ext(exts):
    sn = "example.com".encode()
    ext_sni = b"\x00\x00" + (len(sn) + 5).to_bytes(2, "big") + (len(sn) + 3).to_bytes(2, "big") + b"\x00" + len(sn).to_bytes(2, "big") + sn
    allx = b"".join(exts) if exts else ext_sni
    body = b"\x01" + (2 + 32 + 1 + 2 + 2 + 2 + 2 + len(allx)).to_bytes(3, "big") + b"\x03\x03" + b"\0" * 32 + b"\0" + b"\x00\x02\x13\x01" + b"\x01\x00" + len(allx).to_bytes(2, "big") + allx
    return b"\x16\x03\x01" + len(body).to_bytes(2, "big") + body
SNI = lambda n: b"\x00\x00" + (len(n) + 5).to_bytes(2, "big") + (len(n) + 3).to_bytes(2, "big") + b"\x00" + len(n).to_bytes(2, "big") + n
check("hello 정상", bp.parse_hello(hello_ext([])) == ("example.com", ""))
check("hello ECH 확장 → ech", bp.parse_hello(hello_ext([SNI(b"example.com"), b"\xfe\x0d\x00\x02ab"])) == ("example.com", "ech") and bp.parse_sni(hello_ext([SNI(b"example.com"), b"\xfe\x0d\x00\x02ab"])) is None)
check("hello 중복 확장 → dup-ext", bp.parse_hello(hello_ext([SNI(b"example.com"), SNI(b"evil.example")]))[1] == "dup-ext")
two = b"\x00\x00" + (2 + 3 + 11 + 3 + 12).to_bytes(2, "big") + (3 + 11 + 3 + 12).to_bytes(2, "big") + b"\x00\x00\x0bexample.com" + b"\x00\x00\x0cevil.example"
check("hello 이름 여러 개 → multi-name", bp.parse_hello(hello_ext([two]))[1] == "multi-name", bp.parse_hello(hello_ext([two])))
check("비 ASCII·이상한 호스트는 valid_host 거부", not bp.valid_host("é.example.com") and not bp.valid_host("a b.com") and not bp.valid_host("") and not bp.valid_host("a/b.com") and bp.valid_host("registry.npmjs.org") and bp.valid_host("a_b.example.com"))
check("문서·테스트 대역도 사설로 취급", all(bp.is_private(x) for x in ("192.0.2.1", "198.51.100.7", "203.0.113.9", "192.88.99.1")) and not bp.is_private("8.8.8.8"))


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
rm = egress.compute("sbox-ct-debian13-x", None, minimal=True)
check("프리셋: --minimal(프로젝트 없음)은 always+flavor 만", "deb.debian.org:443" in rm and "github.com:443" in rm and "registry.npmjs.org:443" not in rm and "static.crates.io:443" not in rm and rm == egress.compute("sbox-ct-debian13-x", "/nonexistent.toml"), sorted(rm))
try:
    egress.compute("sbox-ct-debian13-x", None); check("프리셋: 매니페스트도 --minimal 도 없으면 거부", False)
except SystemExit:
    check("프리셋: 매니페스트도 --minimal 도 없으면 거부", True)
def norm_fails(r):
    try:
        egress.norm(r); return False
    except SystemExit:
        return True
check("와일드카드: 공개 접미사·사용자 콘텐츠 서비스는 거부", all(norm_fails(x) for x in ("*.com", "*.github.io", "*.s3.amazonaws.com", "*.x.cloudfront.net", "*.pages.dev")))
check("와일드카드: 정상 도메인·정확한 호스트는 허용", egress.norm("*.example.com") == "*.example.com:443" and egress.norm("bucket.s3.amazonaws.com:443") == "bucket.s3.amazonaws.com:443")
check("허용 항목: 비 ASCII·공백 거부", norm_fails("é.example.com") and norm_fails("a b.com"))
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
    px = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, resolver=local_resolver)
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
    px2 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=False, resolver=local_resolver)
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
    px3 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, tls_upstream_port=eport, resolver=local_resolver)
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
    px4 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=False, tls_upstream_port=eport, resolver=local_resolver)
    srv4 = await asyncio.start_server(px4.handle_tls, "127.0.0.1", 0, limit=32768)
    r, w = await asyncio.open_connection("127.0.0.1", srv4.sockets[0].getsockname()[1])
    w.write(hello); await w.drain()
    check("투명: 사설로 해석되면 끊김", await asyncio.wait_for(r.read(4096), 5) == b"")
    w.close()
    # 투명 평문 HTTP(80): 이름:80 이 명시된 이름만, Host 로 판단
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": [f"localhost:{eport}"]}}})
    px5 = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, http_upstream_port=eport, resolver=local_resolver)
    srv5 = await asyncio.start_server(px5.handle_http, "127.0.0.1", 0, limit=9000)
    p5 = srv5.sockets[0].getsockname()[1]
    req = b"GET /x HTTP/1.1\r\nHost: localhost:80\r\n\r\n"
    want = b"GET /x HTTP/1.1\r\nHost: localhost:80\r\nConnection: close\r\n\r\n"   # 요청 하나만 전달 — Connection: close 가 붙는다
    r, w = await asyncio.open_connection("127.0.0.1", p5)
    w.write(req); await w.drain()
    check("투명 HTTP: 허용 Host 는 전달(에코, Connection: close 추가)", await asyncio.wait_for(r.readexactly(len(want)), 5) == want)
    w.close()
    # 에코 서버는 받은 만큼 돌려준다 — 겹쳐 보낸 두 번째 요청(Host 위장)·keep-alive 헤더는 전달되지 않아야 한다
    r, w = await asyncio.open_connection("127.0.0.1", p5)
    w.write(b"GET /a HTTP/1.1\r\nHost: localhost:80\r\nConnection: keep-alive\r\nUpgrade: websocket\r\n\r\nGET /b HTTP/1.1\r\nHost: evil.example\r\n\r\n"); await w.drain()
    got = await asyncio.wait_for(r.readexactly(len(b"GET /a HTTP/1.1\r\nHost: localhost:80\r\nConnection: close\r\n\r\n")), 5)
    w.write(b"GET /c HTTP/1.1\r\nHost: evil.example\r\n\r\n"); await w.drain()
    try:                                   # 에코 서버는 전달된 바이트를 그대로 돌려준다 — 겹친 요청·이어 보낸 요청이 전달됐다면 evil 이 되돌아온다
        extra = await asyncio.wait_for(r.read(4096), 1.5)
    except asyncio.TimeoutError:
        extra = b""
    check("투명 HTTP: keep-alive·Upgrade 제거, 겹친·이어 보낸 요청은 전달 안 함", got == b"GET /a HTTP/1.1\r\nHost: localhost:80\r\nConnection: close\r\n\r\n" and b"evil" not in got and b"evil" not in extra, extra)
    w.close()
    for bad in (b"GET http://evil.example/ HTTP/1.1\r\nHost: localhost:80\r\n\r\n",           # 절대 URI
                b"GET / HTTP/1.1\r\nHost: localhost:80\r\nHost: evil.example\r\n\r\n",       # 중복 Host
                b"POST / HTTP/1.1\r\nHost: localhost:80\r\nContent-Length: 5\r\n\r\nhello",   # 본문 있는 메서드
                b"GET / HTTP/1.1\r\nHost: localhost:80\r\nX: a\nHost: evil.example\r\n\r\n",  # 낱개 줄바꿈으로 숨긴 헤더
                b"GET / HTTP/1.1\r\nHost: localhost:80\r\nTransfer-Encoding: chunked\r\n\r\n"):
        r, w = await asyncio.open_connection("127.0.0.1", p5)
        w.write(bad); await w.drain()
        check("투명 HTTP: 모호·본문 요청은 거부 " + repr(bad[:24]), await asyncio.wait_for(r.read(4096), 15) == b"")
        w.close()
    for bad in (b"GET / HTTP/1.1\r\nHost: evil.example\r\n\r\n", b"GET / HTTP/1.1\r\n\r\n", b"junk"):
        r, w = await asyncio.open_connection("127.0.0.1", p5)
        w.write(bad); await w.drain()
        if bad == b"junk":
            w.write_eof()
        check("투명 HTTP: 허용 밖·Host 없음·깨진 요청은 끊김 " + repr(bad[:12]), await asyncio.wait_for(r.read(4096), 15) == b"")
        w.close()
    srv5.close()
    # 연결 슬롯: 한 클라이언트가 상한을 넘으면 즉시 거부, 다른 클라이언트는 영향 없음, 해제하면 다시 가능(pilot §29-45)
    old_pc = bp.PER_CLIENT_CONNS; bp.PER_CLIENT_CONNS = 2
    pxs = bp.Proxy(bp.Config(cfgfile))
    a1, a2 = pxs.slot("10.0.0.1"), pxs.slot("10.0.0.1")
    await a1.__aenter__(); await a2.__aenter__()
    try:
        await pxs.slot("10.0.0.1").__aenter__(); over = False
    except bp.BusyError:
        over = True
    other = pxs.slot("10.0.0.2"); await other.__aenter__()
    check("슬롯: 클라이언트별 상한 초과는 거부", over)
    check("슬롯: 다른 클라이언트는 영향 없음", pxs.per_client.get("10.0.0.2") == 1)
    await a1.__aexit__(); await other.__aexit__()
    again = pxs.slot("10.0.0.1"); await again.__aenter__()
    check("슬롯: 해제하면 다시 가능·정리됨", pxs.per_client == {"10.0.0.1": 2})
    await again.__aexit__(); await a2.__aexit__()
    check("슬롯: 전부 해제되면 표가 비고 세마포어 복구", pxs.per_client == {} and pxs.sem._value == bp.MAX_CONNS)
    bp.PER_CLIENT_CONNS = old_pc
    # DNS 스텁 UDP 왕복
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["registry.npmjs.org:443", "*.github.com:443", "db.x:5432"]}}})
    loop = asyncio.get_running_loop()
    calls = []
    fake = {"registry.npmjs.org": ["104.16.1.1"], "api.github.com": ["140.82.112.5"], "deb.debian.org": ["151.101.2.132"], "priv.example": ["10.1.2.3"]}

    async def fake_resolver(name):
        calls.append(name)
        if name == "slow.example":
            await asyncio.sleep(0.5); return ["151.101.9.9"]
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
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["priv.example:443", "boom.example:443", "empty.example:443", "registry.npmjs.org:443", "slow.example:443"]}}})
    n0 = calls.count("registry.npmjs.org")
    await ask("registry.npmjs.org"); await ask("registry.npmjs.org")
    check("dns: 같은 이름 반복 질의는 캐시(조회 1회 이하)", calls.count("registry.npmjs.org") - n0 == 0)
    ra = await asyncio.gather(ask("slow.example"), ask("slow.example"), ask("slow.example"))
    check("dns: 같은 이름 동시 질의는 조회 1번을 같이 기다림", calls.count("slow.example") == 1 and all(x.endswith(bytes([151, 101, 9, 9])) for x in ra), calls)
    check("dns: 사설로 해석되는 이름은 SERVFAIL(재바인딩 방지)", (await ask("priv.example"))[3] & 0xF == 2)
    check("dns: 조회 실패는 SERVFAIL", (await ask("boom.example"))[3] & 0xF == 2 and (await ask("empty.example"))[3] & 0xF == 2)
    check("dns: 허용 이름 AAAA 는 빈 답", (await ask("registry.npmjs.org", 28))[6:8] == b"\0\0" and (await ask("registry.npmjs.org", 28))[3] & 0xF == 0)
    write({"default_allow": [], "clients": {"127.0.0.1": {"name": "t1", "allow": ["deb.debian.org:80"]}}})
    check("dns: 80 만 허용된 이름도 진짜 주소", (await ask("deb.debian.org")).endswith(bytes([151, 101, 2, 132])))
    tr.close()
    # 상위 DNS 동시 질의(resolve_a): 한 곳이 죽어 있어도 다른 곳의 응답을 쓴다, NXDOMAIN 은 [], 전부 죽으면 OSError
    class Up(asyncio.DatagramProtocol):
        def __init__(self, mode): self.mode = mode
        def connection_made(self, t): self.t = t
        def datagram_received(self, d, a):
            if self.mode == "dead":
                return
            qp = bp.parse_question(d)
            qid, name, qtype, question = qp
            if self.mode == "nx":
                self.t.sendto(bp.build_answer(qid, question, qtype, 3), a)
            elif self.mode == "bad-id":
                self.t.sendto(bp.build_answer((qid + 1) & 0xFFFF, question, qtype, 0, ["6.6.6.6"]), a)
            else:
                self.t.sendto(bp.build_answer(qid, question, qtype, 0, ["93.184.216.34", "93.184.216.35"]), a)
    ups = {}
    for m in ("dead", "ok", "nx", "bad-id"):
        t_, _ = await loop.create_datagram_endpoint(lambda m=m: Up(m), local_addr=("127.0.0.1", 0))
        ups[m] = t_
    # resolve_a 는 서버 포트가 53 고정이라 시험에서는 포트를 바꿔 쓸 수 있게 (host, port) 도 받는다 — 여기서는 함수의 응답 파서만 직접 확인한다
    pkt = dns_query("a.example")
    rsp = bp.build_answer(0x1234, pkt[12:], 1, 0, ["1.2.3.4", "5.6.7.8"])
    check("A 응답 파서: 주소 둘", bp.parse_a_answers(rsp, 0x1234) == (0, ["1.2.3.4", "5.6.7.8"]), bp.parse_a_answers(rsp, 0x1234))
    check("A 응답 파서: id 다르면 무시", bp.parse_a_answers(rsp, 0x1235) is None)
    check("A 응답 파서: NXDOMAIN", bp.parse_a_answers(bp.build_answer(0x1234, pkt[12:], 1, 3), 0x1234) == (3, []))
    check("A 응답 파서: 잘린 것·질의 패킷은 None", bp.parse_a_answers(rsp[:20], 0x1234) is None and bp.parse_a_answers(pkt, 0x1234) is None)
    tc = bytearray(rsp); tc[2] |= 0x02
    check("A 응답 파서: TC(잘림) 표시는 None", bp.parse_a_answers(bytes(tc), 0x1234) is None)
    sv = {m: ("127.0.0.1", t_.get_extra_info("sockname")[1]) for m, t_ in ups.items()}
    # TCP 만 되는 상위(UDP 는 무응답): 같은 포트에 TCP 서버를 따로 열어 응답
    async def tcp_dns(r, w):
        n = int.from_bytes(await r.readexactly(2), "big")
        d = await r.readexactly(n)
        qid_, name_, qt_, qq_ = bp.parse_question(d)
        resp = bp.build_answer(qid_, qq_, qt_, 0, ["198.51.100.7"])
        w.write(len(resp).to_bytes(2, "big") + resp); await w.drain(); w.close()
    tsrv = await asyncio.start_server(tcp_dns, "127.0.0.1", sv["dead"][1])
    r_tcp = await bp.resolve_a("only-tcp.example", [sv["dead"]], timeout=3)
    check("resolve_a: UDP 가 막혀도 TCP 로 해석", r_tcp == ["198.51.100.7"], r_tcp)
    tsrv.close()
    t0 = loop.time()
    r1 = await bp.resolve_a("a.example", [sv["dead"], sv["ok"]], timeout=3)
    check("resolve_a: 죽은 서버가 있어도 산 서버 응답을 바로 씀", r1 == ["93.184.216.34", "93.184.216.35"] and loop.time() - t0 < 1.5, (r1, loop.time() - t0))
    check("resolve_a: NXDOMAIN 은 []", await bp.resolve_a("a.example", [sv["dead"], sv["nx"]], timeout=3) == [])
    check("resolve_a: id 가 틀린 응답은 무시하고 정상 응답 채택", await bp.resolve_a("a.example", [sv["bad-id"], sv["ok"]], timeout=3) == ["93.184.216.34", "93.184.216.35"])
    try:
        await bp.resolve_a("a.example", [sv["dead"], sv["bad-id"]], timeout=1); check("resolve_a: 전부 무응답이면 OSError", False)
    except OSError:
        check("resolve_a: 전부 무응답이면 OSError", True)
    check("resolve_a: 잘못된 이름은 []", await bp.resolve_a("a..example", [sv["ok"]], timeout=1) == [])
    for t_ in ups.values():
        t_.close()
    # 연결 경쟁: 첫 주소가 죽어 있어도(응답 없음 — 시험에서는 닫힌 포트의 다른 주소) 두 번째가 바로 쓰인다
    t0 = asyncio.get_running_loop().time()
    rr, ww = await bp.connect_race(["198.51.100.1", "127.0.0.1"], eport, stagger=0.2, timeout=3)
    check("연결 경쟁: 죽은 주소 뒤의 살아 있는 주소로 연결(빠르게)", ww is not None and asyncio.get_running_loop().time() - t0 < 2.5, (ww, asyncio.get_running_loop().time() - t0))
    if ww:
        ww.close()
    check("연결 경쟁: 전부 실패하면 (None, None)", await bp.connect_race(["127.0.0.1"], 1, stagger=0.1, timeout=2) == (None, None))
    check("연결 경쟁: 빈 목록", await bp.connect_race([], 80) == (None, None))
    for s in (srv, srv2, srv3, srv4, es):
        s.close()


asyncio.run(run())
print(f"{n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
