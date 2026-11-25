#!/usr/bin/env python3
"""sbox broker 키 주입 어댑터 시험(plan dev-sandbox-pilot §29-56·57·58, S64). 네트워크 없음 — 로컬 소켓의 가짜 업스트림만 쓴다.
지키는 것(토큰이 새거나 다른 클라이언트·조작된 요청이 진짜 토큰을 얻는 일을 막는다):
 ① 자리표시자가 그 클라이언트의 것과 정확히 같을 때만 진짜 값으로 바뀌고 업스트림은 자리표시자를 보지 못한다 ② 다르거나 모르는 클라이언트·중복 Authorization 은 거부(교체 안 함)
 ③ 인증 헤더가 없는 요청은 값을 붙이지 않고 그대로 ④ 진짜 값과 자리표시자는 기록에 남지 않는다 ⑤ 청크 본문·`x-api-key`·절대 URI 는 거부
 ⑥ 요청 하나만 전달(겹쳐 보낸 두 번째 요청·남는 본문은 전달 안 함) ⑦ 업스트림은 시작 때 고정한 곳뿐(요청의 Host 로 바꿀 수 없음) ⑧ 응답은 조각 단위로 되돌림(스트리밍)
실행: python3 -I core/sbox/tests/test_broker_inject.py  (mods/_tools/run-tests.sh 의 sbox-broker-inject)"""
import asyncio, io, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import broker_proxy as bp  # noqa: E402

n = {"ok": 0, "bad": 0}
REAL, PH = "sk-ant-oat01-REAL-SECRET-VALUE", "sk-ant-oat01-sbox-placeholder-t-AAAA"


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


async def local_resolver(name):
    return ["127.0.0.1"] if name == "localhost" else []


async def run():
    seen = []                                   # 가짜 업스트림이 받은 요청들: (요청 줄, 헤더 dict, 본문)

    async def upstream(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except Exception:
            writer.close(); return
        lines = head.split(b"\r\n")[:-2]
        hd = {k.lower(): v.strip() for k, _, v in (ln.decode().partition(":") for ln in lines[1:])}
        body = b""
        cl = int(hd.get("content-length", "0"))
        if cl:
            body = await reader.readexactly(cl)
        seen.append((lines[0].decode(), hd, body))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: 1\n\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(b"data: 2\n\n")             # 두 번째 조각 — 스트리밍으로 이어서 와야 한다
        await writer.drain()
        writer.close()

    up = await asyncio.start_server(upstream, "127.0.0.1", 0)
    uport = up.sockets[0].getsockname()[1]
    d = tempfile.mkdtemp()
    secret = os.path.join(d, "secret"); open(secret, "w").write(REAL + "\n")
    cfgfile = os.path.join(d, "clients.json")
    json.dump({"default_allow": [], "clients": {"127.0.0.1": {"name": "t", "allow": [], "inject": {"anthropic": {"placeholder": PH}}}}}, open(cfgfile, "w"))
    px = bp.Proxy(bp.Config(cfgfile), allow_private_targets=True, resolver=local_resolver)
    px.adapters["anthropic"] = {"upstream": "localhost", "port": uport, "secret": secret, "tls": False}
    srv = await asyncio.start_server(lambda r, w: px.handle_inject("anthropic", r, w), "127.0.0.1", 0, limit=bp.INJECT_MAX_HEAD + 1024)
    port = srv.sockets[0].getsockname()[1]
    bp._logf = io.StringIO()

    async def ask(raw, wait=0.4):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(raw)
        await w.drain()
        out = b""
        try:
            while True:
                chunk = await asyncio.wait_for(r.read(65536), wait + 1)
                if not chunk:
                    break
                out += chunk
        except asyncio.TimeoutError:
            pass
        w.close()
        return out

    def req(method="POST", path="/v1/messages?beta=true", auth=f"Bearer {PH}", body=b'{"x":1}', extra=b"", host="evil.example"):
        h = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\n".encode()
        if auth is not None:
            h += f"Authorization: {auth}\r\n".encode()
        if body is not None:
            h += f"Content-Length: {len(body)}\r\n".encode()
        return h + extra + b"\r\n" + (body or b"")

    # ① ⑦ ⑧ 정상: 자리표시자 → 진짜 값, 업스트림 호스트는 고정, 응답 두 조각이 이어서 옴
    seen.clear()
    out = await ask(req())
    check("정상 요청은 200 과 두 조각 응답", out.startswith(b"HTTP/1.1 200") and b"data: 1" in out and b"data: 2" in out, out[:120])
    check("업스트림이 진짜 값을 받음", seen and seen[0][1].get("authorization") == f"Bearer {REAL}", seen)
    check("업스트림은 자리표시자를 보지 못함", seen and PH not in json.dumps(seen[0][1]), seen)
    check("Host 는 요청이 아니라 고정 업스트림", seen and seen[0][1].get("host") == "localhost", seen)
    check("본문은 그대로", seen and seen[0][2] == b'{"x":1}', seen)
    check("연결을 Connection: close 로 바꿔 전달", seen and seen[0][1].get("connection") == "close", seen)
    # ③ 인증 없는 요청(예: HEAD /api/hello)은 값을 붙이지 않음
    seen.clear()
    out = await ask(req(method="HEAD", path="/api/hello", auth=None, body=None))
    check("인증 없는 요청은 그대로 전달·값 안 붙임", seen and "authorization" not in seen[0][1], seen)
    # ② 거부
    seen.clear()
    for label, raw, why in [
        ("다른 값", req(auth="Bearer sk-ant-oat01-other"), "placeholder-mismatch"),
        ("진짜처럼 보이는 값", req(auth=f"Bearer {REAL}"), "placeholder-mismatch"),
        ("Bearer 아님", req(auth=f"Basic {PH}"), "placeholder-mismatch"),
        ("중복 Authorization", req(extra=f"Authorization: Bearer {PH}\r\n".encode()), "dup-auth"),
    ]:
        out = await ask(raw)
        check(f"거부: {label}", out.startswith(b"HTTP/1.1 4") and why in bp._logf.getvalue(), (out[:60], why))
    check("거부된 요청은 업스트림에 가지 않음", not seen, seen)
    # ⑤ 청크·x-api-key·절대 URI·본문 길이 없음
    for label, raw in [
        ("청크 본문(Content-Length 도 함께 있어 다른 거부와 겹치지 않게)", req(extra=b"Transfer-Encoding: chunked\r\n")),
        ("x-api-key", req(extra=b"x-api-key: sk-ant-api03-abc\r\n")),
        ("절대 URI", b"POST http://evil.example/ HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n"),
        ("POST 인데 Content-Length 없음", req(body=None)),
    ]:
        out = await ask(raw)
        check(f"거부: {label}", out.startswith(b"HTTP/1.1 4") or out.startswith(b"HTTP/1.1 501"), out[:60])
    check("그 요청들도 업스트림에 가지 않음", not seen, seen)
    # ⑥ 겹친 두 번째 요청은 전달 안 함
    seen.clear()
    await ask(req() + req(path="/v1/second"))
    check("요청 하나만 전달(두 번째는 안 감)", len(seen) == 1 and seen[0][0].startswith("POST /v1/messages"), seen)
    # ④ 기록에 값이 없음
    logtxt = bp._logf.getvalue()
    check("기록에 진짜 값·자리표시자·본문 없음", REAL not in logtxt and PH not in logtxt and '{"x":1}' not in logtxt and "sk-ant-oat01-other" not in logtxt, logtxt[-300:])
    check("기록에 메서드·경로(쿼리 제외)·상태가 있음", '"path": "/v1/messages"' in logtxt and '"status": 200' in logtxt, logtxt[-300:])
    # 비밀 파일이 없으면 503 (값을 붙이지 못하므로 요청을 보내지 않음)
    seen.clear(); os.unlink(secret)
    px._secret_cache.clear()
    out = await ask(req())
    check("비밀 파일 없음 → 503·업스트림에 안 감", out.startswith(b"HTTP/1.1 503") and not seen, (out[:40], seen))
    # 비밀을 바꾸면 다음 요청부터 새 값(파일 mtime)
    open(secret, "w").write("sk-ant-oat01-NEW\n")
    px._secret_cache.clear()
    seen.clear()
    await ask(req())
    check("바뀐 비밀을 다시 읽음", seen and seen[0][1].get("authorization") == "Bearer sk-ant-oat01-NEW", seen)
    # 모르는 클라이언트(설정에서 지움)
    json.dump({"default_allow": [], "clients": {}}, open(cfgfile, "w")); os.utime(cfgfile, (1, 1))
    seen.clear()
    out = await ask(req())
    check("모르는 클라이언트는 403", out.startswith(b"HTTP/1.1 403") and not seen, out[:40])
    srv.close(); up.close()


asyncio.run(run())
print(f"sbox-broker-inject {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
