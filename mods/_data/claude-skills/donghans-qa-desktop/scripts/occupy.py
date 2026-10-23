#!/usr/bin/env python3
"""qa-desktop VM 점유 알림 — 에이전트 종류와 무관한 기본 수단(VM 안의 작은 파일).

사용 (호스트에서 실행; VM 에는 ssh 로 접속):
  occupy.py list                              지금 점유 중인 프로젝트와 경과 시간(예상보다 오래됐으면 「낡음」 표시)
  occupy.py start <프로젝트> <예상분> [메모]   점유 시작을 적는다(이미 다른 프로젝트가 점유 중이면 알려 주고 0이 아닌 코드로 끝난다 — 강제는 아님)
  occupy.py end <프로젝트>                    점유 종료(자기 항목만 지운다)

설계: 락이 아니라 **알림**이다(합의: 락 파일은 두지 않고 시작 알림 + 오래되면 `pgrep chrome` 으로 확인). 파일은 `/tmp/qa-desktop-occupancy/<프로젝트>.json`
(VM 의 /tmp 라 재부팅하면 사라진다). 세션 간 메시지 도구(Claude Code 의 SendMessage 등)가 있으면 상대 QA 세션에 직접 알리는 것을 같이 써도 좋지만,
이 파일은 메시지 도구가 없는 에이전트도 같은 정보를 읽고 쓰게 하는 기준 수단이다.
환경변수: QA_DESKTOP_SSH(기본 qa@10.100.0.84), QA_DESKTOP_KEY(기본 ~/.ssh/qa_desktop_ed25519).
"""
import json
import os
import subprocess
import sys
import time

DIR = "/tmp/qa-desktop-occupancy"
TARGET = os.environ.get("QA_DESKTOP_SSH", "qa@10.100.0.84")
KEY = os.path.expanduser(os.environ.get("QA_DESKTOP_KEY", "~/.ssh/qa_desktop_ed25519"))


def ssh(script, stdin=None):
    r = subprocess.run(["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", TARGET, script],
                       input=stdin, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        sys.exit(f"VM 접속/명령 실패(rc={r.returncode}): {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout


def entries():
    out = ssh(f"mkdir -p {DIR}; for f in {DIR}/*.json; do [ -f \"$f\" ] && cat \"$f\" && echo; done; echo; echo chrome=$(pgrep -c chrom)")
    items, chrome = [], "?"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("chrome="):
            chrome = line.split("=", 1)[1]
        elif line.startswith("{"):
            try:
                items.append(json.loads(line))
            except ValueError:
                pass
    return items, chrome


def fmt(e, now):
    age = (now - e["started"]) / 60
    stale = age > e["eta_min"] + 15
    return f"- {e['project']}: {age:.0f}분 경과 / 예상 {e['eta_min']}분{'  [낡음: 끝나지 않았거나 종료 기록을 못 남긴 듯 — pgrep chrome 으로 확인]' if stale else ''}" + (f"  — {e['note']}" if e.get("note") else "")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    now = time.time()
    if cmd == "list":
        items, chrome = entries()
        print("점유 중인 프로젝트 없음" if not items else "점유 중:\n" + "\n".join(fmt(e, now) for e in items))
        print(f"(VM 의 chrome 프로세스 {chrome}개)")
    elif cmd == "start":
        if len(sys.argv) < 4:
            sys.exit("사용: occupy.py start <프로젝트> <예상분> [메모]")
        proj, eta, note = sys.argv[2], int(sys.argv[3]), " ".join(sys.argv[4:])
        items, chrome = entries()
        others = [e for e in items if e["project"] != proj]
        for e in others:
            print("! 다른 프로젝트가 점유 중:", fmt(e, now))
        if chrome not in ("0", "?"):
            print(f"! VM 에 chrome 프로세스 {chrome}개가 떠 있다 — 사용 중일 수 있다")
        rec = {"project": proj, "started": now, "eta_min": eta, "note": note}
        ssh(f"mkdir -p {DIR} && cat > {DIR}/{proj}.json", stdin=json.dumps(rec, ensure_ascii=False))
        print(f"점유 시작 기록: {proj} (예상 {eta}분)")
        sys.exit(1 if others or chrome not in ("0", "?") else 0)
    elif cmd == "end":
        if len(sys.argv) < 3:
            sys.exit("사용: occupy.py end <프로젝트>")
        ssh(f"rm -f {DIR}/{sys.argv[2]}.json")
        print(f"점유 종료 기록: {sys.argv[2]}")
    else:
        sys.exit(__doc__)


main()
