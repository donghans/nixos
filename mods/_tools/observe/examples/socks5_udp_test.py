#!/usr/bin/env python3
# 사용: socks5_udp_test.py <SOCKS5 서버 IP> [포트=1080]  — 서버가 UDP ASSOCIATE 로 UDP(DNS)를 중계하는지 직접 시험한다(사설 대역이면 프록시 우회로 직접 연결).
# 2026-10-20: 폰 sing-box(socks 입력, 출력 direct)는 UDP 중계 정상(8.8.8.8 응답 87 ms, 1.1.1.1 첫 패킷 유실).
"""폰의 SOCKS5 서버가 UDP ASSOCIATE 로 UDP(DNS)를 중계하는지 직접 시험. 사설 대역으로 직접 연결(프록시 우회)."""
import socket, struct, sys, time
GW, PORT = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1080
def q(name=b"\x07example\x03com\x00"):
    return struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + name + struct.pack(">HH", 1, 1)
t = socket.create_connection((GW, PORT), timeout=5)
t.sendall(b"\x05\x01\x00"); r = t.recv(2); print("인증 협상:", r.hex())
t.sendall(b"\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00")           # UDP ASSOCIATE, 0.0.0.0:0
rep = t.recv(32)
if len(rep) < 10 or rep[1] != 0:
    print("UDP ASSOCIATE 거부/실패 응답:", rep.hex()); sys.exit(2)
atyp = rep[3]; bnd_addr = socket.inet_ntoa(rep[4:8]); bnd_port = struct.unpack(">H", rep[8:10])[0]
print(f"UDP ASSOCIATE 성공: 릴레이 {bnd_addr}:{bnd_port}")
if bnd_addr in ("0.0.0.0", "::"): bnd_addr = GW
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(4)
for dst in ("1.1.1.1", "8.8.8.8"):
    pkt = b"\x00\x00\x00\x01" + socket.inet_aton(dst) + struct.pack(">H", 53) + q()
    t0 = time.time(); u.sendto(pkt, (bnd_addr, bnd_port))
    try:
        data, _ = u.recvfrom(2048); print(f"  DNS via UDP → {dst}:53 응답 {len(data)}바이트, {((time.time()-t0)*1000):.0f} ms, 헤더 {data[:10].hex()}")
    except socket.timeout:
        print(f"  DNS via UDP → {dst}:53 응답 없음(4초) — UDP 중계 안 됨")
