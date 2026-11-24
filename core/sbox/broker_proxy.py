#!/usr/bin/env python3
"""broker 의 송신 프록시 (plan dev-sandbox-pilot §29-25, 로드맵 S61·S64 최소 구현).

프로젝트 ct 의 모든 외부 연결은 이 프록시(HTTP CONNECT)만 거친다. 표준 라이브러리만 쓴다(ct 안에 python3 만 있으면 됨).

하는 일 — 그리고 일부러 하지 않는 일:
  - 파싱하는 것은 CONNECT 요청 한 줄·헤더 상한(8KiB)과, 포트 443 터널의 첫 TLS ClientHello 의 SNI 뿐이다.
    터널 안의 바이트는 해석·검사·변조하지 않고 그대로 전달한다(내용 검사·TLS 가로채기를 넣지 않는 것 자체가 방어 — §29-25).
  - 허용 판단: 출발지 IP → 클라이언트 항목의 allow 목록(`호스트:포트`, 호스트는 정확히 또는 `*.접미사`) + 전체 기본 허용(default_allow).
  - 이름은 이 프록시가 직접 해석한다(클라이언트가 IP 를 고를 수 없다). 해석 결과가 사설·루프백·링크로컬·CGNAT 대역이면 거부한다(DNS 재바인딩·LAN 도달 방지).
  - 포트 443 은 TLS ClientHello 의 SNI 가 요청한 호스트와 같아야 한다(다르면 도메인 위장으로 보고 끊음). 다른 포트는 SNI 검사를 하지 않는다.
  - 일반 HTTP 프록시 요청(GET http://…)은 지원하지 않는다(403) — CONNECT 만. http:// 저장소는 https 로 바꿔 쓴다.
  - 요청마다 한 줄 JSON 기록(시각·클라이언트·호스트·포트·판정·사유·바이트·초). 차단 없이 전수 기록(사용자 승인 2026-11-23 ⑤).
투명 경로(S70-b-lite, 프록시 설정을 모르는 프로그램용 — pilot §29-31):
  - DNS 스텁: ct 의 resolver 로 지정된다. 그 ct 의 허용목록에 `이름:443`(또는 `:80`)이 있는 이름만 **진짜 공인 IPv4**(broker 가 직접 조회, 사설이면 거부)로 답하고, 나머지는 NXDOMAIN. ct 의 기본 게이트웨이가 broker 이고 broker 의 nft 가 그 연결의 443·80 을 아래 수신기로 돌린다(pilot §29-37).
    AAAA·그 밖의 유형은 「없음」(빈 답)으로 답해 IPv4 로만 가게 한다. 질의는 한 줄 JSON 으로 기록.
  - TLS 443 수신: 연결한 프로그램이 broker 주소로 오면 첫 ClientHello 의 SNI 를 읽어 같은 허용 판단·사설 대역 거부로 처리한다.
    목적지는 SNI 이름을 broker 가 직접 해석해서 정한다(클라이언트가 준 주소는 쓰지 않는다). SNI 가 없으면 끊는다.
  - 평문 HTTP(80): 허용목록에 `이름:80` 이 **명시된** 이름만, 첫 요청의 Host 헤더로 판단(apt 저장소 같은 서명된 평문). 나머지 평문은 거부.
  - 비 443·비 80·비 TLS 연결, 터널 안 내용은 이 경로의 범위 밖이다(CONNECT 프록시 또는 S72 어댑터).
설정 파일(JSON, 요청마다 mtime 이 바뀌었는지 보고 다시 읽음 — 변경에 재시작 불필요):
  {"default_allow": ["host:port", ...], "clients": {"10.100.1.57": {"name": "sbox-ct-…", "allow": ["github.com:443", "*.npmjs.org:443"]}}}
"""
import asyncio
import ipaddress
import json
import os
import socket
import sys
import time

MAX_HEAD = 8192
HEAD_TIMEOUT = 10
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 600
MAX_CONNS = 512
SNI_PORTS = {443}   # 이 포트의 터널은 첫 TLS 레코드의 SNI 가 요청 호스트와 같아야 한다

_PRIVATE_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
    "::1/128", "fc00::/7", "fe80::/10", "::/128", "ff00::/8")]


def is_private(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return any(a in n for n in _PRIVATE_NETS)


def host_matches(pattern, host):
    pattern, host = pattern.lower(), host.lower()
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return pattern == host


def rule_matches(rule, host, port):
    h, _, p = rule.rpartition(":")
    return bool(h) and p == str(port) and host_matches(h, host)


def parse_sni(data):
    """TLS ClientHello 에서 server_name 을 꺼낸다. 아니면 None. 길이를 모두 검사한다(잘린 입력은 None)."""
    try:
        if len(data) < 5 or data[0] != 0x16:
            return None
        rec_len = int.from_bytes(data[3:5], "big")
        body = data[5:5 + rec_len]
        if not body or body[0] != 0x01:
            return None
        pos = 4 + 2 + 32                       # 핸드셰이크 헤더 + 버전 + 랜덤
        sid = body[pos]; pos += 1 + sid
        cs = int.from_bytes(body[pos:pos + 2], "big"); pos += 2 + cs
        cm = body[pos]; pos += 1 + cm
        ext_total = int.from_bytes(body[pos:pos + 2], "big"); pos += 2
        end = min(pos + ext_total, len(body))
        while pos + 4 <= end:
            etype = int.from_bytes(body[pos:pos + 2], "big")
            elen = int.from_bytes(body[pos + 2:pos + 4], "big")
            pos += 4
            if etype == 0 and elen >= 5:
                lst = body[pos + 2:pos + elen]
                if lst and lst[0] == 0:
                    n = int.from_bytes(lst[1:3], "big")
                    return lst[3:3 + n].decode("ascii", "strict").lower()
            pos += elen
    except (IndexError, UnicodeDecodeError, ValueError):
        return None
    return None


async def connect_race(addrs, port, stagger=0.3, timeout=CONNECT_TIMEOUT):
    """주소 여러 개를 시차(stagger 초)를 두고 동시에 시도해 먼저 연결되는 것을 쓴다(happy eyeballs 식). CDN 이 돌려준 주소 중 하나가 죽어 있어도
    그 주소의 연결 시한(10초)을 줄줄이 기다리지 않는다 — 순서대로 시도하던 때 pypi.org 가 37초 만에 실패해 pip 이 읽기 시간 초과로 빌드가 깨졌다(2026-11-24, 핫스팟 망)."""
    addrs = list(dict.fromkeys(addrs))[:6]
    if not addrs:
        return None, None
    done = asyncio.Queue()

    async def one(i, a):
        try:
            await asyncio.sleep(i * stagger)
            await done.put(await asyncio.wait_for(asyncio.open_connection(a, port), timeout))
        except (asyncio.TimeoutError, OSError):
            await done.put(None)
    tasks = [asyncio.ensure_future(one(i, a)) for i, a in enumerate(addrs)]
    winner, fails = None, 0
    try:
        while fails < len(tasks):
            res = await done.get()
            if res is None:
                fails += 1
                continue
            winner = res
            break
    finally:
        for t in tasks:
            t.cancel()
        # 이미 연결에 성공했는데 우리가 안 쓰게 된 것은 닫는다
        while not done.empty():
            extra = done.get_nowait()
            if extra is not None and extra is not winner:
                try:
                    extra[1].close()
                except OSError:
                    pass
    return winner if winner else (None, None)


class Config:
    def __init__(self, path):
        self.path, self.mtime, self.data = path, -1, {"default_allow": [], "clients": {}}

    def get(self):
        try:
            m = os.stat(self.path).st_mtime_ns
            if m != self.mtime:
                with open(self.path) as f:
                    self.data = json.load(f)
                self.mtime = m
        except (OSError, ValueError) as e:       # 읽지 못하면 마지막 정상 설정을 유지(없으면 전부 거부)
            log({"event": "config-error", "error": str(e)[:200]})
        return self.data


_logf = None


def log(rec):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **rec}
    line = json.dumps(rec, ensure_ascii=False)
    if _logf:
        _logf.write(line + "\n"); _logf.flush()
    else:
        print(line, flush=True)


async def pipe(r, w, counter, key):
    try:
        while True:
            chunk = await asyncio.wait_for(r.read(65536), IDLE_TIMEOUT)
            if not chunk:
                break
            counter[key] += len(chunk)
            w.write(chunk)
            await w.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            w.close()
        except OSError:
            pass


class Proxy:
    def __init__(self, cfg, allow_private_targets=False, tls_upstream_port=443, http_upstream_port=80):
        self.cfg, self.allow_private, self.sem = cfg, allow_private_targets, asyncio.Semaphore(MAX_CONNS)
        self.tls_upstream_port = tls_upstream_port   # 시험에서만 바꾼다
        self.http_upstream_port = http_upstream_port

    def decide(self, client_ip, host, port):
        data = self.cfg.get()
        c = data.get("clients", {}).get(client_ip)
        if c is None:
            return False, "unknown-client", ""
        rules = list(data.get("default_allow", [])) + list(c.get("allow", []))
        if any(rule_matches(r, host, port) for r in rules):
            return True, "allowed", c.get("name", "")
        return False, "not-in-allowlist", c.get("name", "")

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername") or ("?", 0)
        rec = {"client": peer[0], "host": "", "port": 0, "verdict": "deny", "reason": "", "up": 0, "down": 0}
        t0 = time.monotonic()
        try:
            async with self.sem:
                await self._serve(reader, writer, rec)
        except Exception as e:                    # 한 연결의 예외가 프록시를 죽이지 않게
            rec["reason"] = rec["reason"] or "error:" + type(e).__name__
        finally:
            rec["secs"] = round(time.monotonic() - t0, 2)
            log(rec)
            try:
                writer.close()
            except OSError:
                pass

    async def open_upstream(self, host, port):
        """이름 해석은 이 프록시가 한다 — 사설 대역이면 거부. (reader, writer, 사유) — 실패하면 writer 가 None."""
        try:
            infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, OSError):
            return None, None, "resolve-failed"
        addrs = [i[4][0] for i in infos]
        if not self.allow_private and any(is_private(a) for a in addrs):
            return None, None, "resolved-private"
        r, w = await connect_race(addrs, port)
        if w is not None:
            return r, w, ""
        return None, None, "connect-failed"

    async def handle_tls(self, reader, writer):
        """투명 TLS 수신(S70-b-lite): ct 가 허용된 이름을 DNS 스텁에서 broker IP 로 받아 그대로 접속해 온다."""
        peer = writer.get_extra_info("peername") or ("?", 0)
        rec = {"client": peer[0], "host": "", "port": self.tls_upstream_port, "mode": "transparent", "verdict": "deny", "reason": "", "up": 0, "down": 0}
        t0 = time.monotonic()
        up_w = None
        try:
            async with self.sem:
                first = b""
                try:
                    async def fill():
                        nonlocal first
                        while True:
                            chunk = await reader.read(16384)
                            if not chunk:
                                return
                            first += chunk
                            if len(first) >= 5 and (first[0] != 0x16 or len(first) >= 5 + int.from_bytes(first[3:5], "big")):
                                return
                            if len(first) > 16384 + 5:
                                return
                    await asyncio.wait_for(fill(), HEAD_TIMEOUT)
                except asyncio.TimeoutError:
                    pass
                sni = parse_sni(first)
                if not sni or len(sni) > 253:
                    rec["reason"] = "no-sni"
                else:
                    rec["host"] = sni
                    ok, why, name = self.decide(rec["client"], sni, self.tls_upstream_port)
                    rec["name"], rec["reason"] = name, why
                    if ok:
                        up_r, up_w, why = await self.open_upstream(sni, self.tls_upstream_port)
                        if up_w is None:
                            rec["reason"] = why
                        else:
                            rec["verdict"] = "allow"
                            counter = {"up": len(first), "down": 0}
                            up_w.write(first); await up_w.drain()
                            await asyncio.gather(pipe(reader, up_w, counter, "up"), pipe(up_r, writer, counter, "down"))
                            rec["up"], rec["down"] = counter["up"], counter["down"]
        except Exception as e:
            rec["reason"] = rec["reason"] or "error:" + type(e).__name__
        finally:
            rec["secs"] = round(time.monotonic() - t0, 2)
            log(rec)
            for w in (writer, up_w):
                try:
                    if w:
                        w.close()
                except OSError:
                    pass

    async def handle_http(self, reader, writer):
        """투명 평문 HTTP 수신(포트 80): 첫 요청의 Host 헤더로 판단한다 — 허용목록에 `이름:80` 이 명시된 이름만(예: Debian·Ubuntu 이미지의 apt). 본문은 해석하지 않는다."""
        peer = writer.get_extra_info("peername") or ("?", 0)
        rec = {"client": peer[0], "host": "", "port": self.http_upstream_port, "mode": "transparent-http", "verdict": "deny", "reason": "", "up": 0, "down": 0}
        t0 = time.monotonic()
        up_w = None
        try:
            async with self.sem:
                try:
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                    head = b""
                host = ""
                for ln in head.split(b"\r\n")[1:]:
                    k, _, v = ln.partition(b":")
                    if k.strip().lower() == b"host":
                        host = v.strip().decode("latin-1").lower().rsplit(":", 1)[0] if v.strip().isascii() else ""
                        break
                if not head or not host or len(host) > 253:
                    rec["reason"] = "no-host"
                else:
                    rec["host"] = host
                    ok, why, name = self.decide(rec["client"], host, self.http_upstream_port)
                    rec["name"], rec["reason"] = name, why
                    if ok:
                        up_r, up_w, why = await self.open_upstream(host, self.http_upstream_port)
                        if up_w is None:
                            rec["reason"] = why
                        else:
                            rec["verdict"] = "allow"
                            counter = {"up": len(head), "down": 0}
                            up_w.write(head); await up_w.drain()
                            await asyncio.gather(pipe(reader, up_w, counter, "up"), pipe(up_r, writer, counter, "down"))
                            rec["up"], rec["down"] = counter["up"], counter["down"]
        except Exception as e:
            rec["reason"] = rec["reason"] or "error:" + type(e).__name__
        finally:
            rec["secs"] = round(time.monotonic() - t0, 2)
            log(rec)
            for w in (writer, up_w):
                try:
                    if w:
                        w.close()
                except OSError:
                    pass

    async def _serve(self, reader, writer, rec):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            rec["reason"] = "bad-head"; return
        if len(head) > MAX_HEAD:
            rec["reason"] = "head-too-large"; return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split(" ")
        if len(parts) != 3 or parts[0] != "CONNECT":
            rec["reason"] = "not-connect"
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        host, _, port_s = parts[1].rpartition(":")
        host = host.strip("[]").lower()
        if not host or not port_s.isdigit() or not (0 < int(port_s) < 65536) or len(host) > 253:
            rec["reason"] = "bad-target"
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        port = int(port_s)
        rec["host"], rec["port"] = host, port
        ok, why, name = self.decide(rec["client"], host, port)
        rec["name"], rec["reason"] = name, why
        if not ok:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        up_r, up_w, why = await self.open_upstream(host, port)
        if up_w is None:
            rec["reason"] = why
            code = b"403 Forbidden" if why == "resolved-private" else b"502 Bad Gateway"
            writer.write(b"HTTP/1.1 " + code + b"\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n"); await writer.drain()
        first = b""
        if port in SNI_PORTS:                     # 첫 TLS 레코드의 SNI 가 요청한 호스트와 같아야 한다
            try:
                first = await asyncio.wait_for(reader.read(16384), HEAD_TIMEOUT)
            except asyncio.TimeoutError:
                first = b""
            sni = parse_sni(first)
            if sni != host:
                rec["reason"] = "sni-mismatch" if sni else "no-sni"
                up_w.close(); return
        rec["verdict"] = "allow"
        counter = {"up": len(first), "down": 0}
        if first:
            up_w.write(first); await up_w.drain()
        await asyncio.gather(pipe(reader, up_w, counter, "up"), pipe(up_r, writer, counter, "down"))
        rec["up"], rec["down"] = counter["up"], counter["down"]


# ---- DNS 스텁 (S70-b-lite) ----
def parse_question(data):
    """DNS 질의 패킷 → (id, 이름, 유형, 질문 구간 바이트) 또는 None. 압축 포인터·여러 질문·응답 패킷은 거부."""
    try:
        if len(data) < 17 or len(data) > 512:
            return None
        qid = int.from_bytes(data[0:2], "big")
        flags = int.from_bytes(data[2:4], "big")
        if flags & 0x8000 or (flags >> 11) & 0xF != 0:        # 응답이거나 표준 질의가 아님
            return None
        if int.from_bytes(data[4:6], "big") != 1:
            return None
        pos, labels = 12, []
        while True:
            n = data[pos]
            if n == 0:
                pos += 1
                break
            if n & 0xC0 or n > 63:
                return None
            labels.append(data[pos + 1:pos + 1 + n].decode("ascii", "strict").lower())
            if len(labels[-1]) != n:
                return None
            pos += 1 + n
        qtype = int.from_bytes(data[pos:pos + 2], "big")
        qclass = int.from_bytes(data[pos + 2:pos + 4], "big")
        if len(data) < pos + 4 or qclass != 1:
            return None
        name = ".".join(labels)
        if not name or len(name) > 253:
            return None
        return qid, name, qtype, data[12:pos + 4]
    except (IndexError, UnicodeDecodeError):
        return None


def build_answer(qid, question, qtype, rcode, ips=None, ttl=30):
    """응답 패킷. ips(문자열 IPv4 목록 또는 단일 문자열)가 있고 qtype 이 A(1)이면 A 레코드를 붙인다."""
    if isinstance(ips, str):
        ips = [ips]
    ans = b""
    if ips and qtype == 1 and rcode == 0:
        for ip in ips:
            ans += b"\xc0\x0c" + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + ttl.to_bytes(4, "big") + (4).to_bytes(2, "big") + socket.inet_aton(ip)
    flags = 0x8180 | rcode                                      # QR·RD·RA
    an = len(ips) if ans else 0
    return qid.to_bytes(2, "big") + flags.to_bytes(2, "big") + (1).to_bytes(2, "big") + an.to_bytes(2, "big") + b"\0\0\0\0" + question + ans


class DnsStub(asyncio.DatagramProtocol):
    """허용된 이름만 **진짜 공인 IPv4** 로 답한다(방식 B, pilot §29-37) — ct 의 기본 게이트웨이가 broker 라서 그 주소로 가는 443·80 연결이 broker 의 redirect 로 프록시에 닿는다.
    사설·루프백 등으로 해석되는 이름은 거부한다(DNS 재바인딩·LAN 도달 방지 — 프록시의 사설 해석 거부와 같은 규칙). 해석은 broker 가 한다(ct 가 고를 수 없음)."""
    TTL = 30

    def __init__(self, proxy, resolver=None):
        self.proxy, self.transport = proxy, None
        self.resolver = resolver or self._resolve

    async def _resolve(self, name):
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(name, 443, family=socket.AF_INET, type=socket.SOCK_STREAM), CONNECT_TIMEOUT)
        return sorted({i[4][0] for i in infos})

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        q = parse_question(data)
        if q:
            asyncio.ensure_future(self.answer(q, addr))

    async def answer(self, q, addr):
        qid, name, qtype, question = q
        ok, why, who = self.proxy.decide(addr[0], name, 443)
        if not ok:
            ok, why, who = self.proxy.decide(addr[0], name, 80)   # 평문 80 만 허용된 이름(apt 등)도 안내
        ips, rc = [], "nxdomain"
        if ok:
            if qtype != 1:
                rc = "ok-empty"                                    # AAAA·그 밖: 「없음」(IPv4 로만 가게 함)
            else:
                try:
                    ips = [i for i in await self.resolver(name) if not is_private(i)]
                except (asyncio.TimeoutError, OSError):
                    ips = []
                rc = "ok" if ips else "servfail"
                if not ips:
                    why = "resolve-failed-or-private"
        code = {"ok": 0, "ok-empty": 0, "nxdomain": 3, "servfail": 2}[rc]
        self.transport.sendto(build_answer(qid, question, qtype, code, ips[:4] if ips else None, self.TTL), addr)
        log({"event": "dns", "client": addr[0], "name": name, "qtype": qtype, "result": rc, "reason": why, "answers": ips[:4]})


async def main_async(listen, port, cfg_path, allow_private, tls_listen=None, tls_port=0, http_port=0, dns_listen=None, dns_port=53):
    proxy = Proxy(Config(cfg_path), allow_private)
    server = await asyncio.start_server(proxy.handle, listen, port, limit=MAX_HEAD + 1024)
    log({"event": "start", "listen": f"{listen}:{port}", "config": cfg_path})
    extra = []
    if tls_port:
        extra.append(await asyncio.start_server(proxy.handle_tls, tls_listen or listen, tls_port, limit=32768))
        log({"event": "start-tls", "listen": f"{tls_listen or listen}:{tls_port}"})
    if http_port:
        extra.append(await asyncio.start_server(proxy.handle_http, tls_listen or listen, http_port, limit=MAX_HEAD + 1024))
        log({"event": "start-http", "listen": f"{tls_listen or listen}:{http_port}"})
    if dns_listen:
        await asyncio.get_running_loop().create_datagram_endpoint(lambda: DnsStub(proxy), local_addr=(dns_listen, dns_port))
        log({"event": "start-dns", "listen": f"{dns_listen}:{dns_port}"})
    async with server:
        await server.serve_forever()


def main(argv):
    global _logf
    import argparse
    ap = argparse.ArgumentParser(description="sbox broker CONNECT 프록시")
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=3128)
    ap.add_argument("--config", default="/etc/broker/clients.json")
    ap.add_argument("--log", default="/var/log/broker/access.log")
    ap.add_argument("--allow-private-targets", action="store_true", help="시험 전용 — 사설 대역 대상 허용")
    ap.add_argument("--tls-port", type=int, default=0, help="투명 TLS 수신 포트(0 = 끔, 운영은 443)")
    ap.add_argument("--http-port", type=int, default=0, help="투명 평문 HTTP 수신 포트(0 = 끔, 운영은 80 — 허용목록에 이름:80 이 있는 이름만)")
    ap.add_argument("--dns-listen", default="", help="DNS 스텁이 받을 주소(broker 자신의 IP — systemd-resolved 가 127.0.0.53 을 쓰므로 와일드카드 불가)")
    ap.add_argument("--dns-port", type=int, default=53)
    a = ap.parse_args(argv)
    if a.log != "-":
        os.makedirs(os.path.dirname(a.log), exist_ok=True)
        _logf = open(a.log, "a", buffering=1)
    asyncio.run(main_async(a.listen, a.port, a.config, a.allow_private_targets, tls_port=a.tls_port, http_port=a.http_port, dns_listen=a.dns_listen or None, dns_port=a.dns_port))


if __name__ == "__main__":
    main(sys.argv[1:])
