"""procactions — 보호 판정 · 종료 계획 · 신호 전송(PID 재사용 방어) · 기록. 되돌릴 수 없는 동작이 있는 유일한 모듈이다.

원칙
- **보호는 그룹 뷰와 독립**: 프로세스 속성(PID·조상·UID·이름)에서 직접 판정한다. 뷰 규칙이 틀려도 보호는 풀리지 않는다.
- 하드 보호(PID 1·procui 자신과 조상·커널 스레드·다른 사용자 소유)는 어떤 override 로도 풀 수 없다. 소프트 보호는 사용자가 이름을 다시 입력해 개별로만 푼다.
- 신호는 **pidfd 로만** 보낸다(`os.kill(pid)` 로 대체하지 않는다). 순서: ①`pidfd_open` ②시작 시각이 계획 때 저장한 값과 같은지 검증 ③조상·보호를 **신호 직전의 새 스냅샷**으로 다시 계산 ④`pidfd_send_signal`.
  핸들을 먼저 얻은 뒤 검증하므로 확인과 신호 사이에 PID 가 재사용돼도 다른 프로세스에 가지 않는다. pidfd 를 못 쓰는 환경이면 종료 기능을 끈다(`supported()`).
- 자동화·무확인 모드는 없다(확인은 호출부 UI 의 몫). 기록에는 시각·이름·PID·신호·결과만 남기고 명령 인자는 남기지 않는다.
"""
from __future__ import annotations

import datetime
import json
import os
import select
import signal
import time

import procgroups as pg
import procscan as ps

# (코드, 이름 글롭 리스트, 설명) — 소프트 보호. 이름은 comm·exe·app 중 하나라도 일치하면 해당.
SOFT = [
    ("desktop", pg.DESKTOP, "데스크톱 환경(소유 뷰의 「내 환경」과 같은 목록)"),
    ("vm-container", pg.VM_CONTAINER, "VM·컨테이너 데몬"),
    ("nix", ["nix", "nix-*", "nixos-rebuild*", "nixup*", "rnixup*", "nom", "home-manager*"], "nix 빌드·배포"),
    ("infra", ["sshd*", "systemd*", "(sd-pam)", "dbus-*", "pipewire*", "wireplumber", "observe*", "usageui", "procui"], "세션 인프라·관측 수집기"),
]
HARD = {"pid1", "self", "kernel", "other-uid"}


def supported():
    return hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")


class PCtx:
    """보호 판정에 쓰는 상태: 내 UID, 자기 자신과 조상 pid, 사용자 보호 이름. 신호 직전에 **새로** 만든다."""

    def __init__(self, procs, extra=None, self_pid=None, me=None):
        self.me = os.getuid() if me is None else me
        self.bp = ps.by_pid(procs)
        self.self_pid = os.getpid() if self_pid is None else self_pid
        self.anc = ps.ancestors(self.self_pid, self.bp) | {self.self_pid}
        self.extra = extra or {"app": [], "comm": []}


def protect_reasons(p, pc):
    """[(코드, 설명)] — 비어 있으면 보호되지 않음. 뷰와 무관하게 프로세스 속성에서만 계산."""
    out = []
    if p["pid"] == 1:
        out.append(("pid1", "PID 1(init)"))
    if p["pid"] in pc.anc:
        out.append(("self", "procui 자신 또는 그 조상(실행 중인 터미널·쉘)"))
    if p["kernel"]:
        out.append(("kernel", "커널 스레드"))
    if pc.me != 0 and p["uid"] != pc.me:
        out.append(("other-uid", "다른 사용자 소유(권한 없음)"))
    if p["comm"] in pg.SESSION_COMMS:
        out.append(("llm-session", "LLM 세션 프로세스"))
    for code, globs, text in SOFT:
        if pg.glob_any(p, globs):
            out.append((code, text))
    user = list(pc.extra.get("app", [])) + list(pc.extra.get("comm", []))
    if user and pg.glob_any(p, user):
        out.append(("user", "사용자 보호 규칙([protect])"))
    return out


def is_hard(reasons):
    return any(c in HARD for c, _ in reasons)


def key(p):
    return (p["pid"], p["start"])


def build_plan(procs, selected, override, pc):
    """selected·override = {(pid, start)}. → dict(targets, excluded[(proc, reasons)], children_separate, rss, pss_kib)
    targets: 선택됐고 (보호가 없거나 소프트 보호를 override 한) 프로세스. 하드 보호는 override 여도 제외."""
    targets, excluded = [], []
    for p in procs:
        k = key(p)
        if k not in selected:
            continue
        r = protect_reasons(p, pc)
        if r and (is_hard(r) or k not in override):
            excluded.append((p, r))
        else:
            targets.append(p)
    tset = {p["pid"] for p in targets}
    kids = set()
    for p in targets:
        kids |= ps.descendants(p["pid"], procs)
    pss = [ps.pss_kib(p["pid"]) for p in targets]
    return dict(targets=targets, excluded=excluded, children_separate=len(kids - tset),
                rss=sum(p["rss"] for p in targets), pss_kib=sum(x for x in pss if x), pss_unknown=sum(1 for x in pss if x is None))


def _start_of(pid):
    st = ps.parse_stat(ps.read(f"/proc/{pid}/stat") or "")
    try:
        return int(st[1][19]) if st else None
    except (ValueError, IndexError):
        return None


def send(items, sig, override=frozenset(), extra=None, wait=0.0):
    """items(계획의 대상 프로세스 dict 리스트)에 sig 를 보낸다. → (결과 dict 리스트, 아직 살아 있는 items).
    결과: {pid, comm, sig, status: sent|gone|mismatch|protected|denied|error, detail}. wait>0 이면 그 초만큼 종료를 기다린다."""
    if not supported():
        return [dict(pid=p["pid"], comm=p["comm"], sig=int(sig), status="error", detail="이 환경은 pidfd 를 지원하지 않음") for p in items], list(items)
    fds, results = {}, []
    for p in items:                                                  # ① 핸들을 먼저 모두 얻는다
        try:
            fds[key(p)] = os.pidfd_open(p["pid"])
        except ProcessLookupError:
            results.append(dict(pid=p["pid"], comm=p["comm"], sig=int(sig), status="gone", detail="이미 종료됨"))
        except OSError as e:
            results.append(dict(pid=p["pid"], comm=p["comm"], sig=int(sig), status="error", detail=f"pidfd_open 실패: {e}"))
    fresh = ps.scan()                                                # ③ 신호 직전의 새 스냅샷으로 보호 재계산
    pc = PCtx(fresh, extra)
    bp = ps.by_pid(fresh)
    sent = []
    try:
        for p in items:
            fd = fds.get(key(p))
            if fd is None:
                continue
            base = dict(pid=p["pid"], comm=p["comm"], sig=int(sig))
            if _start_of(p["pid"]) != p["start"]:                    # ② 핸들을 얻은 뒤 시작 시각 검증
                results.append(dict(base, status="mismatch", detail="시작 시각 불일치(PID 재사용) — 신호를 보내지 않음"))
                continue
            now = bp.get(p["pid"])
            r = protect_reasons(now, pc) if now else []
            if now and r and (is_hard(r) or key(p) not in override):
                results.append(dict(base, status="protected", detail="신호 직전 재계산에서 보호됨: " + ", ".join(t for _, t in r)))
                continue
            try:
                signal.pidfd_send_signal(fd, sig)                    # ④ 핸들로 신호
                results.append(dict(base, status="sent", detail=""))
                sent.append(p)
            except ProcessLookupError:
                results.append(dict(base, status="gone", detail="이미 종료됨"))
            except PermissionError:
                results.append(dict(base, status="denied", detail="권한 없음"))
            except OSError as e:
                results.append(dict(base, status="error", detail=str(e)))
        alive = _wait_exit(sent, fds, wait)
    finally:
        for fd in fds.values():
            os.close(fd)
    return results, alive


def _wait_exit(sent, fds, wait):
    """보낸 프로세스들이 wait 초 안에 끝났는지 pidfd(종료 시 읽기 가능)로 기다리고, 아직 살아 있는 것을 돌려준다."""
    if not sent:
        return []
    po = select.poll()
    fdmap = {fds[key(p)]: p for p in sent}
    for fd in fdmap:
        po.register(fd, select.POLLIN)
    left, end = dict(fdmap), time.monotonic() + wait
    while left:
        for fd, _ev in po.poll(max(0.0, end - time.monotonic()) * 1000 if wait > 0 else 0):
            left.pop(fd, None)
            po.unregister(fd)
        if time.monotonic() >= end:
            break
    return list(left.values())


def log(path, results, group=""):
    """결과를 jsonl 로 덧붙인다(시각·그룹·이름·PID·신호·결과만). 실패하면 예외 대신 False."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for r in results:
                f.write(json.dumps(dict(t=datetime.datetime.now().isoformat(timespec="seconds"), group=group, **r), ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False
