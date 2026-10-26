#!/usr/bin/env python3
"""procctl — procui 와 같은 코어(procscan·procgroups·procactions)를 명령줄로 여는 **비대화형 프로세스 정리 도구**. LLM 에이전트와 사람이 쓴다.

pkill·kill·killall 대신 쓴다: 이름 글롭이 의도보다 넓게 맞는 일, 자기 자신·조상(터미널·tmux)이나 다른 세션을 죽이는 일, PID 재사용, 기록 없음을 막는다.

  procctl groups [--view V] [--filter F] [--json]          그룹·합계(읽기 전용)
  procctl show <pid|그룹> [--view V] [--json]               세부 사용량·보호 사유(읽기 전용)
  procctl plan  --group G | --pid N… | --filter F [--view V] [--with-children] [--scope session|user] [--ttl 초] [--json]
                                                            아무것도 죽이지 않고 계획을 만든다(ID·대상·보호로 제외·범위 밖·예상 확보 메모리)
  procctl apply <계획 ID> [--term-wait 3] [--json]          그 계획의 대상에만 SIGTERM, 대기 후 살아남은 것을 알린다
  procctl escalate <계획 ID> [--json]                       apply 뒤 살아남은 대상에만 SIGKILL(별도 호출)
  procctl log [--tail N]                                    ~/.local/state/procui/actions.jsonl 조회

종료 코드: 0 성공 · 2 대상 없음/인자 오류 · 3 거부(만료·변조·상태·호출자 권한) · 4 대상이 전부 보호로 제외 · 5 일부 실패
소프트 보호(컴포지터·VM·nix·세션 인프라·LLM 세션 등)와 하드 보호(PID 1·자신과 조상·커널 스레드·다른 UID)는 이 도구에서 풀 수 없다 — 사람이 procui 에서만.
에이전트(조상에 LLM 세션이 있는 호출자)는 기본 범위가 **자기 세션의 자식 트리**이고, 자기가 만든 계획만 적용하며, 대상은 최대 20개다.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "observe")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)
import procactions as pa
import procgroups as pg
import procplan as pp
import procscan as ps

try:
    import observe_apps
except ImportError:
    observe_apps = None

CONFIG_PATH = os.environ.get("PROCUI_CONFIG") or os.path.expanduser("~/.config/procui/groups.toml")
LOG_PATH = os.path.join(pp.STATE_DIR, "actions.jsonl")


def snapshot():
    """0.5초 간격 두 번 스캔해 CPU% 까지 채운 프로세스 목록."""
    resolver = observe_apps.AppResolver() if observe_apps else None
    a = ps.scan()
    t0 = time.monotonic()
    prev = ps.with_cpu(a, {}, 0)
    time.sleep(0.5)
    procs = ps.annotate(ps.scan(), resolver)
    ps.with_cpu(procs, prev, time.monotonic() - t0)
    return procs


def load_views():
    extra, protect, warns = pg.load_config(CONFIG_PATH)
    return pg.merge_views(pg.BUILTIN_VIEWS, extra), protect, warns


def pick_view(views, name):
    if name is None:
        return views[1]                     # 기본 뷰: 앱
    v = next((x for x in views if x["name"] == name), None)
    if v is None:
        die(pp.NO_TARGET, f"뷰 '{name}' 없음 — 가능: {', '.join(x['name'] for x in views)}")
    return v


def die(code, msg, as_json=False):
    if as_json:
        print(json.dumps(dict(error=msg, code=code), ensure_ascii=False))
    else:
        print(f"procctl: {msg}", file=sys.stderr)
    sys.exit(code)


def emit(obj, as_json, text):
    print(json.dumps(obj, ensure_ascii=False, indent=1) if as_json else text)


def gib(x):
    return f"{x / ps.GIB:.1f} GiB" if x >= ps.GIB else f"{x / ps.MIB:.0f} MiB"


def short_reasons(r):
    return ", ".join(t for _, t in r)


# ---------- 읽기 전용 ----------
def cmd_groups(a):
    procs = snapshot()
    views, protect, warns = load_views()
    view = pick_view(views, a.view)
    ctx = pg.Ctx(procs)
    pred, fw = pg.parse_filter(a.filter)
    pc = pa.PCtx(procs, protect)
    groups = pg.build_groups(procs, view, ctx, pred, a.sort)
    rows = [dict(group=g["name"], n=g["n"], cpu=round(g["cpu"], 1), rss_mib=round(g["rss"] / ps.MIB), protected=sum(1 for p in g["procs"] if pa.protect_reasons(p, pc))) for g in groups]
    text = f"뷰 {view['name']} · 그룹 {len(rows)}개 · 프로세스 {sum(r['n'] for r in rows)}/{len(procs)}개\n" + "\n".join(
        f"  {ps.fit(r['group'], 34)} {r['n']:>4}개  CPU {r['cpu']:>6.1f}%  RSS {r['rss_mib']:>6} MiB" + (f"  잠금 {r['protected']}" if r["protected"] else "") for r in rows)
    emit(dict(view=view["name"], groups=rows, warnings=warns + fw), a.json, text + ("\n경고: " + " / ".join(warns + fw) if warns + fw and not a.json else ""))


def cmd_show(a):
    procs = snapshot()
    views, protect, warns = load_views()
    ctx = pg.Ctx(procs)
    pc = pa.PCtx(procs, protect)
    if a.target.isdigit():
        p = next((x for x in procs if x["pid"] == int(a.target)), None)
        if not p:
            die(pp.NO_TARGET, f"pid {a.target} 없음", a.json)
        labels = {v["name"]: pg.classify(v, p, ctx) for v in views}
        r = pa.protect_reasons(p, pc)
        lines = ps.detail(p, procs, labels)
        emit(dict(pid=p["pid"], comm=p["comm"], app=p["app"], cpu=round(p["cpu"], 1), rss_mib=round(p["rss"] / ps.MIB), threads=p["threads"], groups=labels,
                  protection=[dict(code=c, text=t) for c, t in r], detail=lines), a.json, "\n".join(lines) + "\n보호  " + (short_reasons(r) if r else "없음"))
        return
    view = pick_view(views, a.view)
    g = next((x for x in pg.build_groups(procs, view, ctx) if x["name"] == a.target), None)
    if not g:
        names = [x["name"] for x in pg.build_groups(procs, view, ctx)][:15]
        die(pp.NO_TARGET, f"뷰 '{view['name']}' 에 그룹 '{a.target}' 없음 — 예: {', '.join(names)}", a.json)
    mem = [dict(pid=p["pid"], comm=p["comm"], cpu=round(p["cpu"], 1), rss_mib=round(p["rss"] / ps.MIB), protection=[t for _, t in pa.protect_reasons(p, pc)]) for p in g["procs"]]
    emit(dict(group=g["name"], n=g["n"], members=mem), a.json, f"그룹 {g['name']} — {g['n']}개, CPU {g['cpu']:.1f}%, RSS {gib(g['rss'])}\n" + "\n".join(
        f"  pid {m['pid']:<8} {ps.fit(m['comm'], 24)} CPU {m['cpu']:>5.1f}%  RSS {m['rss_mib']:>6} MiB" + (f"  잠금: {', '.join(m['protection'])}" if m["protection"] else "") for m in mem[:40]))


# ---------- plan ----------
def cmd_plan(a):
    pp.purge()
    if not (a.group or a.pid or a.filter):
        die(pp.NO_TARGET, "대상을 지정해야 한다: --group 이름 | --pid N | --filter 식 (전체 선택은 없다)", a.json)
    procs = snapshot()
    views, protect, warns = load_views()
    view = pick_view(views, a.view)
    caller = pp.caller_identity(procs)
    ctx = pg.Ctx(procs)
    pred, fw = pg.parse_filter(a.filter)
    groups = pg.build_groups(procs, view, ctx, pred, "cpu")
    chosen = {}
    if a.group:
        gs = [g for g in groups if g["name"] == a.group]
        if not gs:
            die(pp.NO_TARGET, f"뷰 '{view['name']}' 에 그룹 '{a.group}' 없음(필터 결과 포함) — 예: {', '.join(g['name'] for g in groups[:12])}", a.json)
        for p in gs[0]["procs"]:
            chosen[p["pid"]] = p
    if a.pid:
        bp = ps.by_pid(procs)
        for n in a.pid:
            if n in bp:
                chosen[n] = bp[n]
    if a.filter and not a.group and not a.pid:
        for g in groups:
            for p in g["procs"]:
                chosen[p["pid"]] = p
    if a.with_children:
        for pid in list(chosen):
            for c in ps.descendants(pid, procs):
                chosen.setdefault(c, ps.by_pid(procs)[c])
    scope = a.scope or ("session" if caller["agent"] else "user")
    out_of_scope = []
    if scope == "session":
        if not caller["agent"]:
            die(pp.NO_TARGET, "--scope session 은 LLM 세션 안에서만 의미가 있다(사람은 --scope user)", a.json)
        allowed = pp.session_scope(procs, caller["root"]["pid"])
        for pid in list(chosen):
            if pid not in allowed:
                out_of_scope.append(dict(pid=pid, comm=chosen[pid]["comm"]))
                del chosen[pid]
    pc = pa.PCtx(procs, protect)
    sel = {(p["pid"], p["start"]) for p in chosen.values()}
    plan_raw = pa.build_plan(procs, sel, set(), pc)
    targets = [dict(pid=p["pid"], start=p["start"], comm=p["comm"], app=p["app"], group=pg.classify(view, p, ctx), rss=p["rss"]) for p in plan_raw["targets"]]
    excluded = [dict(pid=p["pid"], comm=p["comm"], reasons=[t for _, t in r]) for p, r in plan_raw["excluded"]]
    if caller["agent"] and len(targets) > pp.MAX_AGENT_TARGETS:
        die(pp.NO_TARGET, f"대상 {len(targets)}개 > 에이전트 상한 {pp.MAX_AGENT_TARGETS}개 — 범위를 좁힐 것(그룹·필터 조정)", a.json)
    selection = dict(view=view["name"], group=a.group, filter=a.filter, pids=a.pid or [], with_children=bool(a.with_children), scope=scope)
    if not targets:
        code = pp.ALL_PROTECTED if excluded and not out_of_scope else pp.NO_TARGET
        why = "대상이 전부 보호로 제외됐다" if code == pp.ALL_PROTECTED else "대상이 없다(범위 밖이거나 이미 없음)"
        emit(dict(error=why, code=code, excluded=excluded, out_of_scope=out_of_scope), a.json,
             f"procctl: {why}\n" + "\n".join(f"  제외 {e['comm']}({e['pid']}): {', '.join(e['reasons'])}" for e in excluded[:10]) +
             ("\n" + "\n".join(f"  범위 밖 {o['comm']}({o['pid']})" for o in out_of_scope[:10]) if out_of_scope else ""))
        sys.exit(code)
    plan = pp.new_plan(targets, excluded, out_of_scope, plan_raw["children_separate"], plan_raw["rss"], plan_raw["pss_kib"], selection, caller, a.ttl)
    pp.save(plan)
    mem = plan["pss_kib"] * 1024 if plan["pss_kib"] else plan["rss"]
    t = [f"계획 {plan['id']} — {'에이전트' if caller['agent'] else '사람'} 모드 · 만료 {time.strftime('%H:%M:%S', time.localtime(plan['expires']))} · 뷰 {view['name']} · 범위 {scope}",
         f"대상 {len(targets)}개 (예상 확보 {gib(mem)}" + (" PSS" if plan["pss_kib"] else " RSS, 공유 포함이라 과대") + "):"]
    t += [f"  pid {x['pid']:<8} {ps.fit(x['comm'], 24)} {ps.fit(x['group'], 20)} RSS {x['rss'] // ps.MIB:>6} MiB" for x in targets[:30]]
    if excluded:
        t.append(f"보호로 제외 {len(excluded)}개:")
        t += [f"  {e['comm']}({e['pid']}) — {', '.join(e['reasons'])}" for e in excluded[:10]]
    if out_of_scope:
        t.append(f"범위 밖으로 제외 {len(out_of_scope)}개(에이전트 기본 범위 = 자기 세션의 자식 트리, 넓히려면 --scope user): " + ", ".join(f"{o['comm']}({o['pid']})" for o in out_of_scope[:8]))
    if plan["children_separate"]:
        t.append(f"선택하지 않은 자식 {plan['children_separate']}개가 남는다(함께 정리하려면 --with-children)")
    t.append(f"다음: procctl apply {plan['id']}")
    emit(dict(plan, warnings=warns + fw), a.json, "\n".join(t))


# ---------- apply / escalate ----------
def run_signal(a, stage):
    procs = ps.scan()
    plan = pp.load(a.plan_id) if a.plan_id.isalnum() else None
    caller = pp.caller_identity(procs)
    ok, code, msg = pp.check_for_apply(plan, caller, procs, stage=stage)
    if not ok:
        die(code, msg, a.json)
    views, protect, warns = load_views()
    items = [dict(pid=t["pid"], start=t["start"], comm=t["comm"]) for t in plan["targets"]]
    if stage == "escalate":
        items = [i for i in items if i["pid"] in set(plan["survivors"])]
        if not items:
            die(pp.NO_TARGET, "살아남은 대상이 없다", a.json)
    pre = []
    if caller["agent"] and plan["selection"]["scope"] == "session":      # 적용 시점에도 자기 세션의 자식 트리 안인지 다시 확인(부모가 바뀐 것 제외)
        allowed = pp.session_scope(procs, caller["root"]["pid"])
        keep = []
        for i in items:
            (keep if i["pid"] in allowed else pre).append(i)
        items = keep
        pre = [dict(pid=i["pid"], comm=i["comm"], sig=0, status="out-of-scope", detail="적용 시점에 자기 세션의 자식 트리 밖") for i in pre]
    sig = signal.SIGTERM if stage == "apply" else signal.SIGKILL
    wait = a.term_wait if stage == "apply" else 2.0
    res, alive = pa.send(items, sig, frozenset(), protect, wait) if items else ([], [])
    res = pre + res
    pa.log(LOG_PATH, res, f"procctl:{plan['selection']['view']}/{plan['selection']['group'] or plan['selection']['filter'] or 'pid'}")
    plan["state"] = "applied"
    plan["survivors"] = [x["pid"] for x in alive]
    plan["applied_at" if stage == "apply" else "escalated_at"] = time.time()
    pp.save(plan)
    sent = sum(1 for r in res if r["status"] == "sent")
    gone = sum(1 for r in res if r["status"] == "gone")
    bad = [r for r in res if r["status"] not in ("sent", "gone")]
    out = dict(plan=plan["id"], signal="SIGTERM" if stage == "apply" else "SIGKILL", sent=sent, gone=gone, refused=bad, survivors=[dict(pid=x["pid"], comm=x["comm"]) for x in alive], results=res)
    t = [f"{out['signal']} 전송 {sent}개 · 이미 없음 {gone}개 · 거부·실패 {len(bad)}개 · 살아남음 {len(alive)}개"]
    t += [f"  거부 {r['comm']}({r['pid']}): {r['status']} — {r['detail']}" for r in bad[:10]]
    if alive:
        t.append("살아남은 프로세스: " + ", ".join(f"{x['comm']}({x['pid']})" for x in alive[:10]))
        if stage == "apply":
            t.append(f"강제 종료는 별도로: procctl escalate {plan['id']}")
    emit(out, a.json, "\n".join(t))
    if bad and sent + gone == 0:
        sys.exit(pp.ALL_PROTECTED)
    if bad:
        sys.exit(pp.PARTIAL)


def cmd_apply(a):
    run_signal(a, "apply")


def cmd_escalate(a):
    run_signal(a, "escalate")


def cmd_log(a):
    try:
        lines = open(LOG_PATH).read().splitlines()[-a.tail:]
    except OSError:
        lines = []
    print("\n".join(lines) if lines else "기록 없음")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="procctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("groups")
    g.add_argument("--view"); g.add_argument("--filter", default=""); g.add_argument("--sort", default="cpu", choices=list(pg.SORTS)); g.add_argument("--json", action="store_true")
    g.set_defaults(fn=cmd_groups)
    s = sub.add_parser("show")
    s.add_argument("target"); s.add_argument("--view"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_show)
    p = sub.add_parser("plan")
    p.add_argument("--view"); p.add_argument("--group"); p.add_argument("--pid", type=int, action="append"); p.add_argument("--filter", default="")
    p.add_argument("--with-children", action="store_true"); p.add_argument("--scope", choices=["session", "user"]); p.add_argument("--ttl", type=int, default=pp.DEFAULT_TTL)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan)
    for name, fn in (("apply", cmd_apply), ("escalate", cmd_escalate)):
        x = sub.add_parser(name)
        x.add_argument("plan_id"); x.add_argument("--term-wait", type=float, default=3.0); x.add_argument("--json", action="store_true")
        x.set_defaults(fn=fn)
    l = sub.add_parser("log")
    l.add_argument("--tail", type=int, default=20)
    l.set_defaults(fn=cmd_log)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
