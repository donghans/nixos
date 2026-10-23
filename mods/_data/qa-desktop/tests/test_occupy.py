#!/usr/bin/env python3
"""occupy.py 의 점유 판정(공유/배타·낡은 기록·chrome) 단위 시험 — ssh 를 대체해 VM 없이 돈다. 실행: python3 test_occupy.py"""
import contextlib
import io
import json
import os
import sys
import time

SRC = open(os.path.join(os.path.dirname(__file__), "../../claude-skills/donghans-qa-desktop/scripts/occupy.py")).read().rsplit("\nmain()", 1)[0]


def run(records, chrome, argv):
    g = {}
    exec(SRC, g)
    store = {r["project"]: r for r in records}

    def ssh(script, stdin=None):
        if "cat >" in script:
            r = json.loads(stdin)
            store[r["project"]] = r
        elif script.startswith("rm -f"):
            store.pop(script.split("/")[-1].replace(".json", ""), None)
        return ""

    g["ssh"] = ssh
    g["entries"] = lambda: (list(store.values()), chrome)
    sys.argv = ["occupy.py"] + argv
    rc = 0
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            g["main"]()
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, sorted(store)


now = time.time()
rec = lambda mode, age=0, eta=30: {"project": "a", "started": now - age, "eta_min": eta, "mode": mode}
CASES = [
    ("공유 vs 공유 → 허용", [rec("shared")], "4", ["start", "b", "5", "--shared"], 0),
    ("공유 vs 배타 → 양보", [rec("exclusive")], "4", ["start", "b", "5", "--shared"], 1),
    ("배타 vs 공유 → 양보", [rec("shared")], "4", ["start", "b", "5"], 1),
    ("배타 vs 배타 → 양보", [rec("exclusive")], "4", ["start", "b", "5"], 1),
    ("기록 없고 chrome 만 → 양보", [], "3", ["start", "b", "5", "--shared"], 1),
    ("기록 없고 chrome 0 → 허용", [], "0", ["start", "b", "5"], 0),
    ("낡은 기록 + chrome 0 → 정리 후 허용", [rec("exclusive", 5 * 3600, 5)], "0", ["start", "b", "5"], 0),
    ("낡은 기록 + chrome 있음 → 양보", [rec("exclusive", 5 * 3600, 5)], "2", ["start", "b", "5"], 1),
]
bad = 0
for name, records, chrome, argv, want in CASES:
    rc, keys = run(records, chrome, argv)
    ok = rc == want
    bad += not ok
    print("OK  " if ok else "FAIL", name, "rc=", rc, keys)
sys.exit(1 if bad else 0)
