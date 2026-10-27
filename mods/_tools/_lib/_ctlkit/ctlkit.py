"""ctlkit — LLM·스크립트용 ctl 도구(observectl · procctl …)가 공유하는 `--json` 봉투와 실행 틀.

사람은 TUI 를 보고 LLM 세션이 ctl 을 쓴다 → ctl 출력은 미려한 표보다 **같은 모양의 구조**가 중요하다. 모든 ctl 이 한 봉투를 쓰게 해 LLM 이 도구마다 다른 형식을 익히지 않게 한다.

봉투(JSON 한 덩어리):
  {"command": 명령, "ok": true|false, "structured": true|false, "exit_code": 정수,
   "data": 구조화 데이터(structured 일 때), "text": 사람용 출력 그대로(structured=false 일 때),
   "notes": 참고 문구 리스트(표 위에 괄호로 찍던 말), "error": 실패 사유(ok=false)}
- ok=false 여도 data 가 함께 올 수 있다(예: procctl plan 이 대상 0개일 때 제외 목록).
- 종료 코드는 봉투의 exit_code 와 프로세스 종료 코드가 같다(도구별 의미는 그 도구의 스킬 문서).
- NaN·Infinity 는 JSON 이 표현하지 못하므로 None 으로 바꾼다.
이 파일은 표준 라이브러리만 쓴다. 여러 도구가 같은 디렉터리로 복사해 import 한다(정본: mods/_tools/_lib/_ctlkit/ctlkit.py).
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import sys


class Out:
    """명령이 구조화 데이터를 내놓는 통로. json 이면 data/notes 를 모아 한 번에 JSON 으로, 아니면 기존처럼 바로 찍는다."""

    def __init__(self, a=None, as_json=None):
        self.json = bool(getattr(a, "json", False)) if as_json is None else as_json
        self.notes, self.data = [], None

    def note(self, text):
        if self.json:
            self.notes.append(text)
        else:
            print(text)

    def done(self, data):
        self.data = data


def clean(v):
    """NaN·Infinity → None(재귀)."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def emit_json(cmd, ok, *, data=None, text=None, notes=(), error=None, code=0):
    obj = {"command": cmd, "ok": ok, "structured": data is not None, "exit_code": code}
    if data is not None:
        obj["data"] = clean(data)
    if text is not None:
        obj["text"] = text
    if notes:
        obj["notes"] = list(notes)
    if error:
        obj["error"] = error
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def run_json(a, cmd, fn):
    """fn(a) 를 실행해 봉투로 낸다. a.out 에 Out 을 달아 주므로 fn 은 a.out.done(data)·a.out.note(문구)로 구조화 결과를 낼 수 있다.
    done 이 안 불리면 fn 이 찍은 출력(stdout)을 text 로 담는다. 실패(sys.exit(문구|코드))는 ok=false 봉투 + 같은 종료 코드."""
    a.out = Out(a, True)
    buf = io.StringIO()
    code, err = 0, None
    try:
        with contextlib.redirect_stdout(buf):
            fn(a)
    except SystemExit as e:
        if e.code in (None, 0):
            code = 0
        elif isinstance(e.code, int):
            code = e.code
        else:
            code, err = 1, str(e.code)
    if err or code:
        emit_json(cmd, False, text=buf.getvalue() or None, notes=a.out.notes, error=err or f"종료 코드 {code}", code=code)
        sys.exit(code)
    if a.out.data is not None:
        emit_json(cmd, True, data=a.out.data, notes=a.out.notes)
    else:
        emit_json(cmd, True, text=buf.getvalue(), notes=a.out.notes)
