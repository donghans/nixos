#!/usr/bin/env python3
"""observe_browser 시험: WebSocket 최소 구현(가짜 CDP 서버), 탭별 CPU 계산, 호스트만 남기는 개인정보 처리, /proc 파싱, 폭주 판정, 읽기 전용(허용 메서드만 호출)."""
import base64, hashlib, json, os, socket, struct, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="browser-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import http.server
from harness import checker
check, finish = checker()

CALLED = []
TASK = {"A": 0.0}

def ws_send(conn, text):
    b = text.encode(); n = len(b)
    head = bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n))
    conn.sendall(head + b)

def ws_recv(conn):
    h = conn.recv(2)
    if len(h) < 2: return None
    ln = h[1] & 0x7F
    if ln == 126: ln = struct.unpack(">H", conn.recv(2))[0]
    mask = conn.recv(4)
    data = b""
    while len(data) < ln: data += conn.recv(ln - len(data))
    return bytes(x ^ mask[i % 4] for i, x in enumerate(data)).decode()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/json/version": body = {"Browser": "Fake/1"}
        elif self.path == "/json/list":
            body = [{"id": "p1", "type": "page", "title": "비밀 메일 제목", "url": "https://mail.example.com/u/0/#inbox/secret-token?q=1", "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/p1"},
                    {"id": "e1", "type": "background_page", "title": "확장", "url": "chrome-extension://abcdefghijklmnop/bg.html", "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/e1"},
                    {"id": "w1", "type": "service_worker", "title": "sw", "url": "https://x.example.com/sw.js", "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/w1"}]
        elif self.path.startswith("/devtools/page/"):
            key = self.headers["Sec-WebSocket-Key"]
            acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.wfile.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode()); self.wfile.flush()
            conn = self.connection; who = self.path.rsplit("/", 1)[1]
            while True:
                m = ws_recv(conn)
                if m is None: break
                req = json.loads(m); CALLED.append(req["method"])
                if req["method"] == "Performance.getMetrics":
                    TASK["A"] += 0.5 if who == "p1" else 0.01          # 호출마다 p1 은 0.5 초, 확장은 0.01 초 증가
                    ws_send(conn, json.dumps({"id": req["id"], "result": {"metrics": [{"name": "TaskDuration", "value": TASK["A"] if who == "p1" else TASK["A"] / 50}, {"name": "ScriptDuration", "value": TASK["A"] / 2}]}}))
                else:
                    ws_send(conn, json.dumps({"id": req["id"], "result": {}}))
            return
        else:
            self.send_response(404); self.end_headers(); return
        b = json.dumps(body).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)

class TS(http.server.ThreadingHTTPServer): daemon_threads = True
srv = TS(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OBSERVE_BROWSER_PORT"] = str(srv.server_address[1])
import observe_browser as br
br.PORT = srv.server_address[1]

check("available: 응답하면 True", br.available() is True)
ts = br.targets()
check("targets: 호스트만 남김(제목·경로·쿼리 없음)", [t["host"] for t in ts] == ["mail.example.com", "chrome-extension:abcdefghijklmnop", "x.example.com"] and not any("title" in t or "url" in t for t in ts), str(ts))
check("개인정보: 직렬화 결과에 제목·토큰이 없다", "비밀" not in json.dumps(ts, ensure_ascii=False) and "secret-token" not in json.dumps(ts))
check("_host: 내부·확장·http", br._host("vivaldi://settings") == "vivaldi" and br._host("about:blank") == "about" and br._host("https://a.b.com:8443/x") == "a.b.com")
rows = br.cpu_by_target(0.2)
check("cpu_by_target: 페이지·확장 배경만(서비스 워커는 제외) — CPU 큰 순", [r[0] for r in rows] == ["mail.example.com", "chrome-extension:abcdefghijklmnop"] and rows[0][2] > rows[1][2] > 0, str(rows))
check("읽기 전용: 호출한 CDP 메서드는 Performance.enable/getMetrics 뿐", set(CALLED) == {"Performance.enable", "Performance.getMetrics"}, str(set(CALLED)))
srv.shutdown(); srv.server_close()
check("서버가 꺼지면 available False", br.available() is False)

# --- /proc 파싱(가짜 /proc)
root = os.path.join(TMP, "proc"); os.makedirs(root)
def mkproc(pid, comm, cmdline, ut, st):
    d = os.path.join(root, str(pid)); os.makedirs(d)
    open(d + "/comm", "w").write(comm + "\n")
    open(d + "/cmdline", "wb").write(cmdline)
    fields = ["S"] + ["0"] * 10 + [str(ut), str(st)] + ["0"] * 20          # state 다음 11번째(0부터)가 utime
    open(d + "/stat", "w").write(f"{pid} ({comm}) " + " ".join(fields))
mkproc(10, "vivaldi-bin", b"/opt/vivaldi/vivaldi-bin --lang=ko", 100, 20)
mkproc(11, "vivaldi-bin", b"/opt/vivaldi/vivaldi-bin --type=renderer --renderer-client-id=5 https://secret.example/path", 300, 50)     # 크로미움은 NUL 대신 공백
mkproc(12, "vivaldi-bin", b"vivaldi-bin\0--type=gpu-process\0--x", 10, 5)
mkproc(13, "bash", b"bash", 999, 999)
tk, by = br.proc_cpu_ticks(root)
check("proc_cpu_ticks: 종류별 합(browser 120, renderer 350, gpu 15), 다른 프로세스 무시", tk == 485 and by == {"browser": 120, "renderer": 350, "gpu-process": 15}, str((tk, by)))
check("개인정보: 명령줄의 주소는 읽어도 저장하지 않음(결과에 종류만)", "secret" not in json.dumps(by))

# --- 폭주 판정
d = br.BurstDetector(threshold=30, need=2, cooldown=100)
seq = [(10, 0), (40, 15), (45, 30), (50, 45), (50, 130), (50, 145), (5, 160), (60, 175), (60, 190)]
out = [d.update(c, t) for c, t in seq]
check("BurstDetector: 2번 연속 넘으면 한 번 알리고 쿨다운 동안 침묵, 조용해지면 연속 초기화", out == [False, False, True, False, True, False, False, False, False], str(out))
finish("browser")
