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
    def __init__(self, cfg, allow_private_targets=False):
        self.cfg, self.allow_private, self.sem = cfg, allow_private_targets, asyncio.Semaphore(MAX_CONNS)

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
        # 이름 해석은 이 프록시가 한다 — 사설 대역이면 거부
        try:
            infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, OSError):
            rec["reason"] = "resolve-failed"
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        addrs = [i[4][0] for i in infos]
        if not self.allow_private and any(is_private(a) for a in addrs):
            rec["reason"] = "resolved-private"
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        up_r = up_w = None
        for a in addrs:
            try:
                up_r, up_w = await asyncio.wait_for(asyncio.open_connection(a, port), CONNECT_TIMEOUT)
                break
            except (asyncio.TimeoutError, OSError):
                continue
        if up_w is None:
            rec["reason"] = "connect-failed"
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
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


async def main_async(listen, port, cfg_path, allow_private):
    proxy = Proxy(Config(cfg_path), allow_private)
    server = await asyncio.start_server(proxy.handle, listen, port, limit=MAX_HEAD + 1024)
    log({"event": "start", "listen": f"{listen}:{port}", "config": cfg_path})
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
    a = ap.parse_args(argv)
    if a.log != "-":
        os.makedirs(os.path.dirname(a.log), exist_ok=True)
        _logf = open(a.log, "a", buffering=1)
    asyncio.run(main_async(a.listen, a.port, a.config, a.allow_private_targets))


if __name__ == "__main__":
    main(sys.argv[1:])
