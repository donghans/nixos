#!/usr/bin/env python3
"""시험용 가짜 claude 백엔드. 시나리오 파일(JSONL)을 순서대로 실행한다. 사용: fake_claude.py <시나리오.jsonl> [--timeout 초]
설계: ctx 문서 plan llm-trust/11-p5prime-2-session-host §10-1. 호스트는 claude 대신 이 스크립트를 띄운다(Adapter.argv 의 spec["exe"]).
이 스크립트는 claude 의 다른 인자(-p, --input-format …)를 받으면 무시한다(시나리오 경로는 첫 번째 `.jsonl` 로 끝나는 인자).

시나리오 한 줄 = 단계 하나(위에서 아래로):
  {"emit": [<줄>, …]}         표준출력에 줄을 낸다. 줄이 dict/list 면 JSON(ensure_ascii=False, 공백 없음), 문자열이면 그대로(깨진 줄 시험용)
  {"expect": {…}}             표준입력에서 줄 하나가 올 때까지 기다려(기본 10초) 조건을 검사한다. 조건 키(모두 만족해야 함):
        stdin_type      파싱한 줄의 type 과 같다(user · control_response · control_request)
        line            줄 원문이 문자열과 **바이트 단위로** 같다(개행 제외)
        text            user 줄의 message.content 가 같다
        control_response  response.response 의 부분집합(예 {"behavior":"deny"}); request_id 는 최상위 키 "request_id" 로
        control_request   request 의 부분집합(예 {"subtype":"interrupt"})
        request_id      control_response 의 response.request_id
  {"expect": {"stdin_eof": true}}  표준입력이 닫힐 때까지 기다린다(그 전에 다른 줄이 오면 불일치)
  {"sleep": 초}               잠잔다
  {"stderr": "글"}            표준오류에 한 줄
  {"ignore_sigterm": true}    SIGTERM 을 무시한다(종료 4단계의 SIGKILL 경로 시험용)
  {"exit": 코드}              그 코드로 즉시 종료
시나리오 끝에 이르면 표준입력이 닫힐 때까지 읽고 종료 코드 0(입력 EOF 에서 스스로 끝나는 유휴 claude 와 같다).
종료 코드: 0 정상 · 2 시나리오 오류 · 3 기대 불일치 · 4 기대한 입력이 시간 안에 안 옴 · 5 기대 중 입력이 닫힘
"""
import json
import os
import select
import signal
import sys
import time

DEFAULT_TIMEOUT = 10.0


def _dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def _subset(want, got):
    if isinstance(want, dict):
        return isinstance(got, dict) and all(k in got and _subset(v, got[k]) for k, v in want.items())
    return want == got


class Stdin:
    def __init__(self):
        self.fd = sys.stdin.fileno(); self.buf = b""; self.eof = False

    def readline(self, deadline):
        """줄 하나(개행 제외, str). 닫히면 None, 시간 초과면 TimeoutError."""
        while b"\n" not in self.buf:
            if self.eof:
                break
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            r, _, _ = select.select([self.fd], [], [], left)
            if r:
                chunk = os.read(self.fd, 65536)
                if not chunk:
                    self.eof = True
                else:
                    self.buf += chunk
        if b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            return line.decode("utf-8", "replace")
        if self.buf:
            line, self.buf = self.buf, b""
            return line.decode("utf-8", "replace")
        return None


def match(cond: dict, line: str):
    """줄이 조건에 맞으면 None, 아니면 불일치 사유."""
    try:
        o = json.loads(line)
    except ValueError:
        o = None
    for k, want in cond.items():
        if k == "line":
            if line != want:
                return f"line 불일치: 기대 {want!r} 받음 {line!r}"
        elif k == "stdin_type":
            if not isinstance(o, dict) or o.get("type") != want:
                return f"stdin_type 불일치: 기대 {want!r} 받음 {line[:200]!r}"
        elif k == "text":
            c = o.get("message", {}).get("content") if isinstance(o, dict) and isinstance(o.get("message"), dict) else None
            if c != want:
                return f"text 불일치: 기대 {want!r} 받음 {c!r}"
        elif k == "control_response":
            r = o.get("response", {}).get("response") if isinstance(o, dict) and isinstance(o.get("response"), dict) else None
            if o is None or o.get("type") != "control_response" or not _subset(want, r):
                return f"control_response 불일치: 기대 {want!r} 받음 {line[:300]!r}"
        elif k == "control_request":
            r = o.get("request") if isinstance(o, dict) else None
            if o is None or o.get("type") != "control_request" or not _subset(want, r):
                return f"control_request 불일치: 기대 {want!r} 받음 {line[:300]!r}"
        elif k == "request_id":
            r = o.get("response", {}).get("request_id") if isinstance(o, dict) and isinstance(o.get("response"), dict) else None
            if r != want:
                return f"request_id 불일치: 기대 {want!r} 받음 {r!r}"
        else:
            return f"알 수 없는 조건 키 {k!r}"
    return None


def run(steps, timeout) -> int:
    sin = Stdin()
    out = sys.stdout
    for n, st in enumerate(steps, 1):
        if "emit" in st:
            for ln in st["emit"]:
                out.write((ln if isinstance(ln, str) else _dump(ln)) + "\n")
            out.flush()
        elif "sleep" in st:
            time.sleep(float(st["sleep"]))
        elif "stderr" in st:
            sys.stderr.write(str(st["stderr"]) + "\n"); sys.stderr.flush()
        elif "ignore_sigterm" in st:
            signal.signal(signal.SIGTERM, signal.SIG_IGN if st["ignore_sigterm"] else signal.SIG_DFL)
        elif "exit" in st:
            out.flush()
            return int(st["exit"])
        elif "expect" in st:
            cond = st["expect"]
            deadline = time.monotonic() + float(st.get("timeout", timeout))
            if cond.get("stdin_eof"):
                try:
                    ln = sin.readline(deadline)
                except TimeoutError:
                    sys.stderr.write(f"fake_claude: 단계 {n}: 입력이 닫히지 않음\n"); return 4
                if ln is not None:
                    sys.stderr.write(f"fake_claude: 단계 {n}: EOF 를 기대했으나 줄이 옴: {ln[:200]!r}\n"); return 3
                continue
            try:
                ln = sin.readline(deadline)
            except TimeoutError:
                sys.stderr.write(f"fake_claude: 단계 {n}: 기대한 입력이 오지 않음 {cond!r}\n"); return 4
            if ln is None:
                sys.stderr.write(f"fake_claude: 단계 {n}: 입력이 닫힘 {cond!r}\n"); return 5
            why = match(cond, ln)
            if why:
                sys.stderr.write(f"fake_claude: 단계 {n}: {why}\n"); return 3
        else:
            sys.stderr.write(f"fake_claude: 단계 {n}: 알 수 없는 단계 {st!r}\n"); return 2
    out.flush()
    while True:   # 유휴: 입력이 닫힐 때까지(들어오는 줄은 버린다)
        try:
            ln = sin.readline(time.monotonic() + 3600)
        except TimeoutError:
            continue
        if ln is None:
            return 0


def main(argv) -> int:
    path = None; timeout = DEFAULT_TIMEOUT; i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--timeout" and i + 1 < len(argv):
            timeout = float(argv[i + 1]); i += 2; continue
        if path is None and a.endswith(".jsonl"):
            path = a
        i += 1
    if not path:
        sys.stderr.write("fake_claude: 시나리오(.jsonl) 경로가 없음\n"); return 2
    try:
        steps = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except (OSError, ValueError) as e:
        sys.stderr.write(f"fake_claude: 시나리오를 읽을 수 없음: {e}\n"); return 2
    return run(steps, timeout)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
