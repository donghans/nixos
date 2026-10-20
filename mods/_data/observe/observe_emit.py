#!/usr/bin/env python3
"""observe-emit — 셸 스크립트에서 구조화 이벤트를 남긴다:  observe-emit <컴포넌트> <수준> <이벤트> [키=값 ...]
예) observe-emit lid-policy info lid lid=closed action=screen-off
값은 숫자면 숫자로, 아니면 문자열로 기록. 개인정보(입력한 글자·URL·명령 인자)는 넘기지 말 것."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from observe_events import Events

if len(sys.argv) < 4 or sys.argv[2] not in ("trace", "debug", "info", "warn", "error"):
    sys.exit(__doc__)
kv = {}
for x in sys.argv[4:]:
    k, _, v = x.partition("=")
    try:
        kv[k] = int(v)
    except ValueError:
        try:
            kv[k] = float(v)
        except ValueError:
            kv[k] = v
Events(sys.argv[1]).emit(sys.argv[2], sys.argv[3], **kv)
