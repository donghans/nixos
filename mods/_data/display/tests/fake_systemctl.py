#!/usr/bin/env python3
"""가짜 systemctl: `--user stop <유닛>.timer ...` 만 지원 — 가짜 systemd-run 이 띄운 대기 프로세스를 죽인다"""
import os, signal, sys
d = os.environ["FAKE_UNITS"]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args and args[0] == "stop":
    for u in args[1:]:
        name = u.rsplit(".", 1)[0]
        f = os.path.join(d, name)
        try:
            pid = int(open(f).read()); os.killpg(pid, signal.SIGKILL); os.remove(f)
        except (OSError, ValueError):
            pass
