#!/usr/bin/env python3
"""가짜 posture CLI: `posture get <키>` 를 $FAKE_POSTURE(JSON {"mode","rotation"}) 에서 읽음"""
import json, os, sys
d = {"mode": "laptop", "rotation": 0}
try: d.update(json.load(open(os.environ["FAKE_POSTURE"])))
except Exception: pass
print(d.get(sys.argv[2], ""))
