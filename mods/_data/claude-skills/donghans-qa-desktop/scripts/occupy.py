#!/usr/bin/env python3
"""qa-desktop VM 점유 알림 — 에이전트 종류와 무관한 기본 수단(VM 안의 작은 파일).

사용 (호스트에서 실행; VM 에는 ssh 로 접속):
  occupy.py list                              지금 점유 중인 프로젝트와 경과 시간(예상보다 오래됐으면 「낡음」 표시). 기록 없는 chrome 은 PID·경과·cwd·주인 추정과 함께 「소유 불명」 경고
  occupy.py start <프로젝트> <예상분> [메모] [--wait <분>] [--shared]
                                              점유 시작을 적는다. **다른 프로젝트가 점유 중이거나 chrome 이 떠 있으면 내 기록을 지우고 양보하며 종료 코드 1**.
                                              --wait N: 양보하는 대신 최대 N분 동안 30초마다 다시 시도해 빌 때까지 기다린다(QA 세션끼리 사람·개발 세션 중재 없이 순번을 맞추는 수단).
                                              --shared: 「보이는 화면을 쓰지 않는다」는 선언 — 전환(ws.py)·전체 화면 캡처(snap.py)·클릭 계열 입력 없이 page 기반 캡처만 한다.
                                              공유 점유끼리는 동시에 허용(각자 전용 데스크톱)되고, 배타 점유(기본)와는 서로 양보한다. 배타는 보이는 화면을 독점해야 하는 세션용.
                                              기록이 낡았는데(예상+15분 초과) chrome 도 없으면 「끝내지 못한 점유」로 보고 지운 뒤 진행한다. --force 는 사용자 지시가 있을 때만
  occupy.py end <프로젝트>                    점유 종료(자기 항목만 지운다)

설계: 엄격한 락이 아니라 **알림**이다(합의: 시작 알림 + 오래되면 `pgrep chrome` 으로 확인). 다만 `start` 는 「기록 후 확인」으로 동시 시작 때 둘 다 점유로 남지 않게 양보한다. 파일은 `/tmp/qa-desktop-occupancy/<프로젝트>.json`
(VM 의 /tmp 라 재부팅하면 사라진다). 세션 간 메시지 도구(Claude Code 의 SendMessage 등)가 있으면 상대 QA 세션에 직접 알리는 것을 같이 써도 좋지만,
이 파일은 메시지 도구가 없는 에이전트도 같은 정보를 읽고 쓰게 하는 기준 수단이다.
환경변수: QA_DESKTOP_SSH(기본 qa@10.100.0.84), QA_DESKTOP_KEY(기본 ~/.ssh/qa_desktop_ed25519).
"""
import json
import os
import random
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


def owners():
    """기록 없이도 chrome 주인을 추정할 단서: 메인 chrome 프로세스(--type= 없는 것)의 PID·경과 초·cwd. cwd 가 `flow_<프로젝트>` 면 그 프로젝트 것으로 본다."""
    out = ssh("for p in $(pgrep chrom); do tr '\\0' ' ' </proc/$p/cmdline 2>/dev/null | grep -q -- '--type=' && continue; "
              "echo \"chromeproc=$p|$(ps -o etimes= -p $p 2>/dev/null | tr -d ' ')|$(readlink /proc/$p/cwd 2>/dev/null)\"; done")
    procs = []
    for line in out.splitlines():
        if line.startswith("chromeproc="):
            pid, age, cwd = (line.split("=", 1)[1].split("|") + ["", ""])[:3]
            base = os.path.basename(cwd.rstrip("/"))
            procs.append({"pid": pid, "age_min": int(age) // 60 if age.isdigit() else None, "cwd": cwd,
                          "owner": base[len("flow_"):] if base.startswith("flow_") else None})
    return procs


def fmt_proc(c):
    age = f"{c['age_min']}분 경과" if c["age_min"] is not None else "경과 불명"
    return f"PID {c['pid']}, {age}, cwd={c['cwd'] or '?'}, 주인 추정: {c['owner'] or '불명'}"


def fmt(e, now):
    age = (now - e["started"]) / 60
    stale = age > e["eta_min"] + 15
    return f"- {e['project']}[{'공유' if e.get('mode') == 'shared' else '배타'}]: {age:.0f}분 경과 / 예상 {e['eta_min']}분{'  [낡음: 끝나지 않았거나 종료 기록을 못 남긴 듯 — pgrep chrome 으로 확인]' if stale else ''}" + (f"  — {e['note']}" if e.get("note") else "")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    now = time.time()
    if cmd == "list":
        items, chrome = entries()
        print("점유 중인 프로젝트 없음" if not items else "점유 중:\n" + "\n".join(fmt(e, now) for e in items))
        print(f"(VM 의 chrome 프로세스 {chrome}개)")
        recorded = {e["project"] for e in items}
        for c in owners():
            if c["owner"] not in recorded:
                print(f"! 소유 불명 chrome(점유 기록 없음): {fmt_proc(c)} — 주인이 `start` 를 안 했거나 종료 기록 없이 남은 것. 죽이지 말고 PID 로만 구분하고, 주인 세션에 알려라")
    elif cmd == "start":
        raw = sys.argv[2:]
        wait_min = 0
        if "--wait" in raw:
            i = raw.index("--wait")
            try:
                wait_min = int(raw[i + 1])
            except (IndexError, ValueError):
                sys.exit("사용: --wait <분>")
            del raw[i:i + 2]
        shared = "--shared" in raw
        args = [a for a in raw if a not in ("--force", "--shared")]
        force = "--force" in raw
        if len(args) < 2:
            sys.exit("사용: occupy.py start <프로젝트> <예상분> [메모] [--wait <분>] [--shared] [--force]")
        proj, eta, note = args[0], int(args[1]), " ".join(args[2:])
        deadline = now + wait_min * 60
        while True:
            now = time.time()
            rec = {"project": proj, "started": now, "eta_min": eta, "note": note, "mode": "shared" if shared else "exclusive"}
            # 먼저 기록하고 나서 다시 읽어 충돌을 판정한다(list→start 사이의 틈을 줄이는 「기록 후 확인」): 먼저 와 있던 다른 프로젝트가 있으면 내 기록을 지우고 양보한다.
            ssh(f"mkdir -p {DIR} && cat > {DIR}/{proj}.json", stdin=json.dumps(rec, ensure_ascii=False))
            items, chrome = entries()
            others = [e for e in items if e["project"] != proj]
            # 공유 점유끼리는 충돌이 아니다(둘 다 보이는 화면을 안 쓴다). 공유로 시작하면 상대 중 배타만, 배타로 시작하면 모든 상대가 충돌.
            conflicts = [e for e in others if not (shared and e.get("mode") == "shared")]
            # 기록 없이 떠 있는 chrome(추적 안 된 사용)은 기록이 하나도 없을 때만 의미가 있다 — 기록된 세션이 있으면 그들의 chrome 이다
            busy = chrome not in ("0", "?") and not others
            if busy:
                procs = owners()
                if procs and all(c["owner"] == proj for c in procs):
                    busy = False   # 전부 내 flow_<프로젝트> 에서 띄운 chrome — 양보할 상대가 아니다
                    print(f"· 떠 있는 chrome 은 내 것({proj}) 이다 — 점유를 기록하고 계속한다")
            # 끝내지 못한 점유(낡았고 chrome 도 없음)는 치운다 — 종료 기록을 못 남기고 끝난 세션 때문에 영원히 막히지 않게
            if others and chrome == "0":
                for e in [e for e in others if (now - e["started"]) / 60 > e["eta_min"] + 15]:
                    print("! 낡은 점유 기록을 정리:", fmt(e, now))
                    ssh(f"rm -f {DIR}/{e['project']}.json")
                    others.remove(e)
                    if e in conflicts:
                        conflicts.remove(e)
            if not (conflicts or busy) or force:
                break
            ssh(f"rm -f {DIR}/{proj}.json")
            if now >= deadline:
                for e in conflicts:
                    print("! 양보: 다른 프로젝트가 점유 중:", fmt(e, now))
                if busy:
                    print(f"! 양보: VM 에 chrome 프로세스 {chrome}개가 떠 있다 — 사용 중일 수 있다")
                    for c in owners():
                        print("  ·", fmt_proc(c))
                print("내 점유는 기록하지 않았다(--wait <분> 으로 기다리거나, --force 는 사용자 지시가 있을 때만).")
                sys.exit(1)
            print(f"… 점유 중({', '.join(e['project'] for e in conflicts) or 'chrome'}) — 30초 뒤 다시 시도", flush=True)
            time.sleep(30 + random.randint(0, 5))   # 동시에 깨어난 두 세션이 서로 양보만 하는 것을 줄이는 지터
        for e in conflicts:
            print("! (--force) 다른 프로젝트가 점유 중인데 기록한다:", fmt(e, now))
        print(f"점유 시작 기록: {proj} ({'공유' if shared else '배타'}, 예상 {eta}분)")
    elif cmd == "end":
        if len(sys.argv) < 3:
            sys.exit("사용: occupy.py end <프로젝트>")
        ssh(f"rm -f {DIR}/{sys.argv[2]}.json")
        print(f"점유 종료 기록: {sys.argv[2]}")
    else:
        sys.exit(__doc__)


main()
