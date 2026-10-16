#!/usr/bin/env python3
"""가짜 systemd-run: --on-active=Ns 가 지나면 명령을 실행하는 분리된 프로세스를 띄운다(부모가 죽어도 살아 있음 — 실제 타이머처럼).
유닛 이름별로 pid 를 기록해 가짜 systemctl stop 이 취소할 수 있게 한다."""
import os, subprocess, sys
args = sys.argv[1:]
unit = delay = None
i = 0
while i < len(args):
    a = args[i]
    if a.startswith("--unit="): unit = a.split("=", 1)[1]
    elif a.startswith("--on-active="): delay = int(a.split("=", 1)[1].rstrip("s"))
    elif not a.startswith("--"): break
    i += 1
cmd = args[i:]
d = os.environ["FAKE_UNITS"]; os.makedirs(d, exist_ok=True)
p = subprocess.Popen(["sh", "-c", 'sleep "$0"; exec "$@"', str(delay)] + cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
open(os.path.join(d, unit), "w").write(str(p.pid))
