"""procplan — procctl 의 「계획」 저장·검증(UI·신호 없음). plan → apply → escalate 가 같은 계획 파일을 본다.

계획 파일 `~/.local/state/procui/plans/<id>.json`: 대상(pid·시작 시각·이름·그룹)·보호로 제외된 것·범위 밖·만료·호출자(에이전트 여부와 그 세션 루트)·서명(sig).
sig = 대상·만료·호출자·선택 조건의 sha256 이다 — **우발적 수정·잘못된 파일 감지용**이며 악의적 위조 방지는 아니다(같은 UID 가 파일과 sig 를 함께 고칠 수 있다).
실제 안전은 apply 가 신호 직전에 한다: pidfd 로 시작 시각 재검증 + 보호를 새 스냅샷으로 다시 계산(procactions.send).
에이전트(조상에 LLM 세션이 있는 호출자)는 **자기가 만든 계획만**, **자기 세션의 자식 트리 범위**(기본)에서, **상한 개수 이하**로, 소프트 보호 해제 없이 쓸 수 있다.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time

import procgroups as pg
import procscan as ps

STATE_DIR = os.environ.get("PROCUI_STATE_DIR") or os.path.expanduser("~/.local/state/procui")
PLANS = os.path.join(STATE_DIR, "plans")
DEFAULT_TTL = 600
MAX_AGENT_TARGETS = 20
SIG_SKIP = {"sig", "state", "survivors", "applied_at", "escalated_at"}

OK, NO_TARGET, REJECTED, ALL_PROTECTED, PARTIAL = 0, 2, 3, 4, 5      # 종료 코드


def caller_identity(procs, pid=None):
    """호출자 정보 {agent, root:{pid,start}|None}. 조상 사슬에 LLM 세션 프로세스가 있으면 에이전트 — 환경 변수는 믿지 않는다."""
    ctx = pg.Ctx(procs)
    root = ctx.session_root(os.getpid() if pid is None else pid)
    if root is None:
        return dict(agent=False, root=None)
    return dict(agent=True, root=dict(pid=root, start=ctx.bp[root]["start"]))


def session_scope(procs, root_pid):
    """에이전트 기본 범위: 세션 루트의 자손 pid 집합(루트 자신 제외)."""
    return ps.descendants(root_pid, procs)


def digest(plan):
    body = {k: v for k, v in plan.items() if k not in SIG_SKIP}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def new_plan(targets, excluded, out_of_scope, children_separate, rss, pss_kib, selection, caller, ttl=DEFAULT_TTL, now=None):
    now = time.time() if now is None else now
    plan = dict(id=secrets.token_hex(4), created=now, expires=now + ttl, selection=selection, caller=caller,
                targets=targets, excluded=excluded, out_of_scope=out_of_scope, children_separate=children_separate, rss=rss, pss_kib=pss_kib,
                state="planned", survivors=[])
    plan["sig"] = digest(plan)
    return plan


def path_of(plan_id):
    if not plan_id.isalnum():
        raise ValueError("계획 ID 형식이 아님")
    return os.path.join(PLANS, f"{plan_id}.json")


def save(plan):
    os.makedirs(PLANS, exist_ok=True)
    tmp = path_of(plan["id"]) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path_of(plan["id"]))


def load(plan_id):
    """계획 dict | None(없음·읽을 수 없음)."""
    try:
        with open(path_of(plan_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def purge(older_than=86400, now=None):
    """만료 후 하루 지난 계획 파일 정리. 지운 개수."""
    now = time.time() if now is None else now
    n = 0
    try:
        names = os.listdir(PLANS)
    except OSError:
        return 0
    for name in names:
        p = os.path.join(PLANS, name)
        try:
            if name.endswith(".json") and now - os.path.getmtime(p) > older_than + DEFAULT_TTL:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def check_for_apply(plan, caller, procs, now=None, stage="apply"):
    """(ok, 종료 코드, 메시지). stage = apply(planned 만) | escalate(applied 만).
    무결성(sig)·만료·상태·호출자 권한(에이전트는 자기 세션이 만든 계획만)·에이전트 상한을 본다."""
    now = time.time() if now is None else now
    if plan is None:
        return False, REJECTED, "계획을 찾을 수 없다(ID 확인, 만료 후 하루 지나면 삭제됨)"
    if plan.get("sig") != digest(plan):
        return False, REJECTED, "계획 파일이 변조됐거나 손상됨(sig 불일치) — 새로 plan 할 것"
    if now > plan["expires"]:
        return False, REJECTED, "계획이 만료됨 — 새로 plan 할 것(만료 시 대상 목록이 낡았을 수 있다)"
    want = "planned" if stage == "apply" else "applied"
    if plan.get("state") != want:
        return False, REJECTED, ("이미 적용된 계획 — 살아남은 것만 `procctl escalate <ID>` 로" if stage == "apply" else "아직 apply 하지 않은 계획 — 먼저 `procctl apply <ID>`")
    if caller["agent"]:
        pc = plan["caller"]
        if not pc["agent"] or pc["root"] != caller["root"]:
            return False, REJECTED, "에이전트는 자기 세션이 만든 계획만 적용할 수 있다(사람이 만든 계획·다른 세션의 계획은 사람이 적용)"
        if len(plan["targets"]) > MAX_AGENT_TARGETS:
            return False, REJECTED, f"에이전트 모드 대상 상한 {MAX_AGENT_TARGETS}개 초과"
    return True, OK, ""
