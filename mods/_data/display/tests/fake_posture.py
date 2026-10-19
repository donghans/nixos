#!/usr/bin/env python3
"""가짜 posture CLI: `posture get <키> [키…]` 를 $FAKE_POSTURE(JSON {"mode","rotation"}) 에서 읽음(여러 키는 공백으로 이어서 한 줄)"""
import json, os, sys
d = {"mode": "laptop", "rotation": 0}
try: d.update(json.load(open(os.environ["FAKE_POSTURE"])))
except Exception: pass
print(" ".join(str(d.get(k, "")) for k in sys.argv[2:]))
