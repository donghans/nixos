"""Chromium 계열 브라우저(Vivaldi)의 탭별 CPU 를 읽기 전용으로 잰다 — 원격 디버깅 포트(127.0.0.1)의 CDP 를 쓰되 **Performance.getMetrics 와 탭 목록만** 읽는다.
탭 열기·이동·클릭·쿠키·페이지 내용은 건드리지 않고, **창 제목과 전체 주소는 저장하지 않는다**(호스트 이름과 대상 종류·확장 ID 만).
표준 라이브러리만 쓴다(WebSocket 은 아래 최소 구현)."""
import base64, hashlib, json, os, re, socket, struct, sys, time, urllib.parse, urllib.request

PORT = int(os.environ.get("OBSERVE_BROWSER_PORT", "9222"))
HOST = "127.0.0.1"


class BrowserError(Exception):
    pass


def _http(path, timeout=2.0):
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}{path}", timeout=timeout) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise BrowserError(str(e))


def available():
    try:
        _http("/json/version", 0.7)
        return True
    except BrowserError:
        return False


class WS:
    """최소 WebSocket 클라이언트(텍스트 프레임, 마스킹, 조각 합치기). CDP 한 연결용."""

    def __init__(self, url, timeout=3.0):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise BrowserError("핸드셰이크 실패")
            buf += chunk
        head, _, self._rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise BrowserError("WebSocket 거부: " + head.split(b"\r\n")[0].decode(errors="replace"))
        self._id = 0

    def _read(self, n):
        while len(self._rest) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise BrowserError("연결 끊김")
            self._rest += chunk
        out, self._rest = self._rest[:n], self._rest[n:]
        return out

    def _frame(self):
        msg = b""
        while True:
            b0, b1 = self._read(2)
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read(8))[0]
            data = self._read(ln)
            op = b0 & 0x0F
            if op == 0x9:                     # ping → pong
                self._send(0xA, data)
                continue
            if op == 0x8:
                raise BrowserError("서버가 연결을 닫음")
            msg += data
            if b0 & 0x80:
                return msg

    def _send(self, op, data):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | op])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def call(self, method, params=None):
        self._id += 1
        mid = self._id
        self._send(0x1, json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        while True:
            m = json.loads(self._frame())
            if m.get("id") == mid:
                if "error" in m:
                    raise BrowserError(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def _host(url):
    """주소 → 보여 줄 이름. 호스트만(경로·쿼리·제목은 버림). 확장은 확장 ID, 내부 페이지는 스킴."""
    u = urllib.parse.urlparse(url or "")
    if u.scheme in ("chrome-extension", "vivaldi-webui"):
        return f"{u.scheme}:{(u.hostname or '')[:32]}"
    if u.scheme in ("http", "https"):
        return u.hostname or "?"
    return u.scheme or "?"


def targets():
    """열린 대상 목록(탭·확장 백그라운드·서비스 워커 등). [{"id","type","host","ws"}] — 제목·전체 주소는 담지 않는다."""
    out = []
    for t in _http("/json/list"):
        out.append({"id": t["id"], "type": t.get("type", "?"), "host": _host(t.get("url")), "ws": t.get("webSocketDebuggerUrl")})
    return out


def _metrics(ws):
    m = {x["name"]: x["value"] for x in ws.call("Performance.getMetrics")["metrics"]}
    return m


def cpu_by_target(seconds=5.0):
    """대상마다 `seconds` 초 동안의 메인 스레드 작업 시간 비율(코어 1개=100%, TaskDuration 증가분) — 반환 [(host, type, cpu%, script%)] CPU 큰 순.
    탭이 같은 호스트면 합산하지 않고 각각(같은 사이트 탭이 여러 개일 수 있으므로) 낸다."""
    ts = [t for t in targets() if t["ws"] and t["type"] in ("page", "background_page")]     # 워커 계열은 Performance 도메인이 없어 응답이 없다
    conns = []
    for t in ts:
        try:
            ws = WS(t["ws"])
            ws.call("Performance.enable")
            conns.append((t, ws, _metrics(ws), time.time()))
        except (BrowserError, OSError):
            continue
    time.sleep(seconds)
    out = []
    for t, ws, m0, t0 in conns:
        try:
            m1 = _metrics(ws)
            dt = time.time() - t0
            out.append((t["host"], t["type"], 100 * (m1.get("TaskDuration", 0) - m0.get("TaskDuration", 0)) / dt,
                        100 * (m1.get("ScriptDuration", 0) - m0.get("ScriptDuration", 0)) / dt))
        except (BrowserError, OSError):
            pass
        ws.close()
    return sorted(out, key=lambda x: -x[2])


# ------------------------------------------------------------------ 폭주 감시(두 단계)
PROC_NAME = "vivaldi-bin"          # 브라우저 실행 파일 이름(프로세스 그룹)
HZ = os.sysconf("SC_CLK_TCK")


def proc_cpu_ticks(proc_root="/proc"):
    """브라우저 프로세스 전체의 (utime+stime) 틱 합과 프로세스 종류별 틱. 반환 (총 틱, {종류: 틱}).
    종류 = 명령줄의 --type= 값(renderer·gpu-process·utility…), 없으면 browser. 명령줄의 나머지(주소 등)는 읽지도 저장하지도 않는다."""
    total, by = 0, {}
    for d in os.listdir(proc_root):
        if not d.isdigit():
            continue
        try:
            with open(f"{proc_root}/{d}/comm") as f:
                if f.read().strip() != PROC_NAME:
                    continue
            with open(f"{proc_root}/{d}/stat") as f:
                st = f.read()
            with open(f"{proc_root}/{d}/cmdline", "rb") as f:
                args = f.read()
        except OSError:
            continue
        rest = st[st.rindex(")") + 2:].split()
        ticks = int(rest[11]) + int(rest[12])
        m = re.search(rb"--type=([a-z\-]+)", args)       # 크로미움은 프로세스 제목을 덮어써서 NUL 대신 공백으로 이어져 있다 — 종류 이름만 뽑고 나머지는 버린다
        kind = m.group(1).decode() if m else "browser"
        total += ticks
        by[kind] = by.get(kind, 0) + ticks
    return total, by


class BurstDetector:
    """폭주 판정 상태 기계(시계·파일 없이 시험 가능): 합계 CPU(코어 1개=100%)가 threshold 이상인 폴이 need 번 연속이면 True(한 번 알린 뒤 cooldown 초 동안은 False)."""

    def __init__(self, threshold=30.0, need=2, cooldown=180.0):
        self.threshold, self.need, self.cooldown = threshold, need, cooldown
        self.run, self.last = 0, -1e18

    def update(self, cpu_pct, now):
        self.run = self.run + 1 if cpu_pct >= self.threshold else 0
        if self.run >= self.need and now - self.last >= self.cooldown:
            self.last = now
            return True
        return False


def watch(poll=15.0, threshold=30.0, once=False):
    """감시 루프. 평소엔 /proc 만 읽고, 폭주가 감지되면 CDP 로 탭별 CPU 를 5초 재서 이벤트(browser.burst)로 남긴다.
    이벤트에는 호스트 이름·대상 종류·CPU 만 있다(제목·주소·내용 없음)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe_events import Events
    ev = Events("browser")
    det = BurstDetector(threshold)
    t_prev, (tk_prev, _) = time.monotonic(), proc_cpu_ticks()
    while True:
        time.sleep(poll)
        now = time.monotonic()
        tk, by = proc_cpu_ticks()
        dt = now - t_prev
        pct = 100 * (tk - tk_prev) / HZ / dt if dt > 0 else 0.0
        t_prev, tk_prev = now, tk
        if det.update(pct, now):
            top, err = [], None
            try:
                top = [r for r in cpu_by_target(5.0) if r[2] >= 3.0][:4]
            except (BrowserError, OSError) as e:
                err = str(e)[:80]
            ev.emit("info", "browser.burst", cpu_pct=round(pct, 1),
                    top=[{"host": h, "type": t, "cpu": round(c, 1), "script": round(s, 1)} for h, t, c, s in top],
                    **({"cdp_error": err} if err else {}))
        if once:
            return


if __name__ == "__main__":
    watch(poll=float(os.environ.get("OBSERVE_BROWSER_POLL", "15")), threshold=float(os.environ.get("OBSERVE_BROWSER_THRESHOLD", "30")))
