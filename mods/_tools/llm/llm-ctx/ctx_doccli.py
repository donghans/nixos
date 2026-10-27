#!/usr/bin/env python3
"""ctx_doccli — `donghans ctx doc …` 명령. 본체는 ctx_store.py, 여기는 인자·출력·세션 결정만 한다.

명령(모두 `--help` 첫 줄에 하는 일과 하지 않는 일을 적는다):
  list      문서 목록을 보인다. 읽기만 한다.
  read      문서 하나를 읽는다(읽은 판을 이 세션의 뷰에 기록 — propose 가 충돌을 잡으려면 먼저 읽어야 한다).
  path      이 세션의 읽기 뷰를 만들거나 갱신하고 경로를 알려 준다. 저장소는 건드리지 않는다.
  find      문서 본문·이름을 검색한다(대화 이력 검색은 `donghans ctx search`).
  propose   새 본문을 **제안**으로 남긴다. 저장소에 직접 쓰지 않는다 — 동기화 담당이 검사해 반영한다.
  status    이 세션의 대기·충돌·거부 제안과 동기화 담당 상태를 보인다.
  watch     이 세션의 뷰를 지켜보다 직접 수정되면 한 줄로 알린다(Monitor 로 띄운다).
  sync      (동기화 담당) 인박스의 제안을 검사해 반영한다. 세션 밖에서 서비스로 돈다.
  cleanup   끝난 세션의 낡은 뷰를 지운다.
  init      (사람만) 프로젝트를 매니페스트에 등록하고 저장소를 만든다.
  import-db 옛 DB 표(project_docs)의 문서를 파일 저장소로 내보내고 바이트를 대조한다(멱등, 로컬 파일만 만든다).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import ctx_store as st

H = None   # llm_ctx 가 넘겨 주는 도우미(norm_repo·git_meta·connect·load_masker·HOST·human_only) — 순환 import 를 피한다


def _session(a):
    return getattr(a, "session", None) or os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def _need_session(a):
    sid = _session(a)
    if not sid:
        sys.exit("세션을 알 수 없다 — 에이전트 셸이 아니면 `--session <ID>` 를 준다(환경변수 CLAUDE_CODE_SESSION_ID 가 없다)")
    return sid


def _project(a, need=True):
    store = st.store_dir()
    man = st.load_manifest(store)
    repo = H.git_meta(os.getcwd()).get("repo_url")
    proj, err = st.resolve_project(man, getattr(a, "project", None), repo)
    if err and need:
        sys.exit(err + f"\n(문서 저장소: {store})")
    return store, proj


def _masker():
    """출력 치환기. DB 에 못 붙으면 알리고(조용히 넘기지 않는다) 치환 없이 진행한다 — 문서는 쓸 때 이미 비밀 검사를 거쳤다."""
    try:
        with H.connect(timeout=3, readonly=True) as c:
            return H.load_masker(c)
    except Exception as e:
        print(f"(경고: 비밀 등록표를 못 읽어 출력 치환을 건너뛴다 — {type(e).__name__})", file=sys.stderr)
        return None


def _mask(m, text):
    return m.text(text) if m is not None else text


# ---------------------------------------------------------------- 읽기
def cmd_list(a):
    store, proj = _project(a)
    rows = st.list_docs(store, proj, a.kind, a.status, a.prefix)
    print(f"프로젝트 {proj} ({store}/{proj})")
    for r in rows:
        print(f"- {r['kind']}/{r['name']}: {r['status']} · {r['state']} · {r['chars']}자 · {r['hash'][:8]}")
    if not rows:
        print("(문서 없음)")
    return 0


def cmd_read(a):
    store, proj = _project(a)
    sid = _session(a)
    d = st.read_doc(store, proj, a.kind, a.name)
    if d is None:
        print(f"{a.kind}/{a.name}: 없다", file=sys.stderr)
        return 1
    if sid:
        st.ensure_in_view(store, st.views_dir(), sid, proj, a.kind, a.name)
    m = _masker()
    pend = st.pending_proposals(store, None, f"{proj}/{a.kind}/{a.name}")
    if not a.body_only:
        meta = d["meta"]
        print(f"# {proj}/{a.kind}/{a.name} · 상태 {meta.get('status')} · {meta.get('state')} · {meta.get('updated_host') or '-'} {meta.get('updated_at') or ''} · 판 {d['hash'][:8]}")
        if pend:
            print(f"(대기 중인 제안 {len(pend)}개 — 아래 본문은 반영 전 판이다: {', '.join(p['session'][:8] for p in pend)})")
    print(_mask(m, d["body"]), end="" if (a.body_only or d["body"].endswith("\n")) else "\n")
    return 0


def cmd_path(a):
    store, proj = _project(a)
    sid = _need_session(a)
    views = st.views_dir()
    pid = int(os.environ["CLAUDE_PID"]) if os.environ.get("CLAUDE_PID", "").isdigit() else None
    r = st.build_view(store, views, sid, proj, a.kind, pid=pid)
    gone = st.cleanup_views(views)
    print(r["root"])
    print(f"문서 {len(r['docs'])}개(이번에 복사 {len(r['copied'])}개). 읽기 전용이다 — Read·Grep 으로 읽고, 고치려면 `donghans ctx doc propose` 를 쓴다.", file=sys.stderr)
    if r["restored"]:
        print(f"(직접 고친 뷰 파일 {len(r['restored'])}개를 원본으로 되돌렸다 — 고친 내용은 {r['root']}/{st.REJECTED_DIR}/ 에 보관)", file=sys.stderr)
    if gone:
        print(f"(끝난 세션의 낡은 뷰 {len(gone)}개를 정리했다)", file=sys.stderr)
    wp = os.path.join(r["root"], st.WATCH_PID_FILE)
    alive = False
    try:
        alive = st._pid_alive(int(open(wp).read().strip()))
    except (OSError, ValueError):
        pass
    if not alive:
        print("즉시 알림이 필요하면 다음을 Monitor 로 띄운다(뷰가 직접 수정되면 바로 알려 준다): donghans ctx doc watch", file=sys.stderr)
    return 0


def cmd_find(a):
    store, proj = _project(a)
    rows = st.find_docs(store, proj, a.term, a.kind, a.limit)
    m = _masker()
    for r in rows:
        print(f"- {r['kind']}/{r['name']} ({r['status']}): {_mask(m, r['snippet'])}")
    if not rows:
        print("(일치하는 문서 없음)")
    return 0


# ---------------------------------------------------------------- 쓰기 제안
def _wake_worker():
    """동기화 담당 서비스가 있으면 깨운다(없으면 아무것도 안 함). 인박스 inotify 가 이미 알아채므로 보조 수단이다."""
    try:
        if subprocess.run(["systemctl", "--user", "cat", "ctx-doc-sync.service"], capture_output=True).returncode != 0:
            return False
        if subprocess.run(["systemctl", "--user", "is-active", "--quiet", "ctx-doc-sync.service"]).returncode != 0:
            subprocess.run(["systemctl", "--user", "start", "--no-block", "ctx-doc-sync.service"], capture_output=True)
        return True
    except OSError:
        return False


def _inline_sync(store):
    """CTX_SYNC_INLINE=1(시험·서비스 없는 호스트): 이 프로세스가 직접 처리한다. 비밀 검사기를 못 쓰면 처리하지 않는다."""
    try:
        with H.connect(timeout=3, readonly=True) as c:
            m = H.load_masker(c)
    except Exception as e:
        print(f"(비밀 검사기를 못 써서 처리하지 않고 대기시킨다 — {type(e).__name__})", file=sys.stderr)
        return
    st.process_inbox(store, m)


def cmd_propose(a):
    store, proj = _project(a)
    sid = _need_session(a)
    if bool(a.file) == bool(a.stdin):
        sys.exit("--file <경로> 또는 --stdin 중 하나를 준다")
    body = sys.stdin.read() if a.stdin else open(a.file, errors="ignore").read()
    base = st.base_hash_for(st.views_dir(), sid, proj, a.kind, a.name)
    code, msg, pid = st.propose(store, sid, H.HOST, proj, a.kind, a.name, body, base)
    if code:
        print(msg, file=sys.stderr)
        return 1
    if os.environ.get("CTX_SYNC_INLINE"):
        _inline_sync(store)
        worker = True
    else:
        worker = _wake_worker()
    r = st.wait_result(store, pid, float(os.environ.get("CTX_PROPOSE_WAIT", "10")) if worker else 0.2)
    if not r:
        print(msg + ("" if worker else " — 이 호스트에는 동기화 담당이 없어 처리되지 않는다(`systemctl --user status ctx-doc-sync`)"))
        return 0
    print(r["msg"] + (f" (커밋 {r['commit']})" if r.get("commit") else ""))
    if r["status"] in ("applied", "same"):
        st.ensure_in_view(store, st.views_dir(), sid, proj, a.kind, a.name)   # 자기 제안 반영분을 직접 수정으로 오인하지 않게 읽은 판을 새로 기록
        return 0
    return 1


def cmd_status(a):
    store, proj = _project(a, need=False)
    sid = _session(a)
    active = subprocess.run(["systemctl", "--user", "is-active", "ctx-doc-sync.service"], capture_output=True, text=True).stdout.strip() or "없음"
    print(f"문서 저장소 {store} · 프로젝트 {proj or '(알 수 없음)'} · 동기화 담당 {active}")
    if sid:
        s = st.session_status(store, sid)
        print(f"이 세션: 대기 {s['pending']} · 충돌 {s['conflict']} · 거부 {s['rejected']}")
        for n in s["notices"]:
            print("  " + n)
        root = st.view_root(st.views_dir(), sid)
        if os.path.isdir(root):
            mods = st.modified_in_view(root)
            print(f"뷰 {root}: 직접 수정 {len(mods)}개" + "".join(f"\n  {r} ({k})" for r, k in mods))
    allp = st.pending_proposals(store)
    print(f"전체 대기 제안 {len(allp)}개")
    return 0


def cmd_watch(a):
    sid = _need_session(a)
    root = st.view_root(st.views_dir(), sid)
    if not os.path.isdir(root):
        sys.exit(f"이 세션의 뷰가 없다 — 먼저 `donghans ctx doc path` 를 부른다({root})")
    pid = a.pid or (int(os.environ["CLAUDE_PID"]) if os.environ.get("CLAUDE_PID", "").isdigit() else None)
    open(os.path.join(root, st.WATCH_PID_FILE), "w").write(str(os.getpid()))
    print(f"[ctx 뷰] 감시를 시작했다({root}) — 직접 수정이 생기면 이 줄처럼 알린다", flush=True)
    return st.watch_view(root, lambda line: print(line, flush=True), pid=pid)


def cmd_cleanup(a):
    gone = st.cleanup_views(st.views_dir(), max_age_days=a.days)
    print(f"지운 뷰 {len(gone)}개" + "".join(f"\n  {g}" for g in gone))
    return 0


# ---------------------------------------------------------------- 동기화 담당
def _load_masker_or_none():
    try:
        with H.connect(timeout=3, readonly=True) as c:
            return H.load_masker(c)
    except Exception as e:
        print(f"[sync] 비밀 검사기를 못 써서 처리를 미룬다 — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


def _sync_once(store, push):
    m = _load_masker_or_none()
    if m is None:
        return 1                      # 비밀 검사 없이 반영하지 않는다(fail-closed) — 제안은 인박스에 남고 다음 점검 때 다시 시도
    for _pid, status, msg, commit in st.process_inbox(store, m):
        print(f"[sync] {status}: {msg}" + (f" ({commit})" if commit else ""), flush=True)
    if push:
        man = st.load_manifest(store)
        for proj, meta in man.items():
            if meta.get("remote"):
                ok, msg = st.push_project(store, proj, m, man)
                print(f"[sync] push {proj}: {'ok' if ok else '못 함'} — {msg}", flush=True)
    return 0


def cmd_sync(a):
    store = st.store_dir()
    if not a.watch:
        return _sync_once(store, a.push)
    print(f"[sync] 시작: {store}/_inbox 를 지켜본다", flush=True)
    st.watch_inbox(store, lambda: _sync_once(store, a.push), poll=float(a.interval))
    return 0


# ---------------------------------------------------------------- 사람 전용
def cmd_init(a):
    H.human_only("ctx doc init(매니페스트 등록)")
    store = st.store_dir()
    why = st.valid_project(a.project)
    if why:
        sys.exit(why)
    os.makedirs(store, exist_ok=True)
    man = st.load_manifest(store)
    if a.project in man:
        print(f"{a.project}: 이미 등록돼 있다")
    else:
        repo = H.norm_repo(a.repo_url) if a.repo_url else ""
        block = f'\n[projects.{a.project}]\nrepo_url = "{repo}"\nowner = "{a.owner}"\nremote = "{a.remote or ""}"\n'
        with open(os.path.join(store, "manifest.toml"), "a") as f:
            f.write(block)
        print(f"{a.project}: 매니페스트에 등록했다")
    st.ensure_repo(os.path.join(store, a.project))
    for k in st.KINDS:
        os.makedirs(os.path.join(store, a.project, k), exist_ok=True)
    return 0


def cmd_import_db(a):
    store = st.store_dir()
    man = st.load_manifest(store)
    by_repo = {m.get("repo_url"): n for n, m in man.items()}
    done = {"created": 0, "same": 0, "skipped": 0, "mismatch": 0}
    with H.connect(readonly=True) as c:
        rows = c.execute("SELECT repo_url, kind, name, body, status, rev, origin_path, updated_host, updated_at FROM project_docs ORDER BY repo_url, kind, name").fetchall()
    for repo, kind, name, body, status, rev, origin, host, at in rows:
        proj = by_repo.get(repo)
        if proj is None:
            done["skipped"] += 1
            if a.verbose:
                print(f"  건너뜀(매니페스트에 없는 저장소 {repo}): {kind}/{name}")
            continue
        p = st.doc_path(store, proj, kind, name)
        if os.path.exists(p):
            cur = st.read_doc(store, proj, kind, name)
            if cur and cur["body"] == body:
                done["same"] += 1
                continue
            print(f"  어긋남(이미 다른 내용이 있다): {proj}/{kind}/{name}", file=sys.stderr)
            done["mismatch"] += 1
            continue
        meta = {**st.default_meta(), "status": status, "origin_path": origin or "", "updated_host": host, "updated_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "provenance": f"ctx DB project_docs rev {rev} 에서 이관", "source_of_truth": "file"}
        if not a.dry_run:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(st.compose(meta, body))
        done["created"] += 1
    if not a.dry_run:
        for proj in set(by_repo.values()):
            pd = os.path.join(store, proj)
            if os.path.isdir(pd):
                st.ensure_repo(pd)
                st._git(pd, "add", "-A")
                r = st._git(pd, "commit", "-q", "-m", "ctx: DB(project_docs)에서 문서 이관", check=False)
    # 대조: 모든 행의 본문이 파일 본문과 바이트 같은지 다시 확인
    bad = 0
    for repo, kind, name, body, *_ in rows:
        proj = by_repo.get(repo)
        if proj is None:
            continue
        cur = st.read_doc(store, proj, kind, name)
        if a.dry_run:
            continue
        if cur is None or cur["body"] != body:
            bad += 1
            print(f"  대조 실패: {proj}/{kind}/{name}", file=sys.stderr)
    print(("[dry-run] " if a.dry_run else "") + " · ".join(f"{k} {v}" for k, v in done.items()) + (f" · 대조 실패 {bad}" if not a.dry_run else ""))
    return 1 if (bad or done["mismatch"]) else 0


# ---------------------------------------------------------------- 등록
def register(ctx_sub, helpers):
    """`donghans ctx doc …` 를 ctx 하위 명령에 등록한다."""
    global H
    H = helpers
    doc = ctx_sub.add_parser("doc", help="작업 문서(plan·qa·note)의 파일 저장소 — 읽기는 뷰, 쓰기는 제안으로만",
                             description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).add_subparsers(dest="docverb", required=True)
    K = lambda p, opt=False: p.add_argument("kind", nargs="?" if opt else None, choices=st.KINDS)
    P = lambda p: p.add_argument("--project", help="프로젝트 이름(기본: 현재 git 저장소의 repo_url 로 매니페스트에서 찾는다 — 못 찾으면 실패)")
    S = lambda p: p.add_argument("--session", help="세션 ID(기본: 환경변수 CLAUDE_CODE_SESSION_ID)")
    p = doc.add_parser("list", help="문서 목록을 보인다(읽기만)"); K(p, True); p.add_argument("--status", choices=st.STATUSES); p.add_argument("--prefix"); P(p); p.set_defaults(f=cmd_list)
    p = doc.add_parser("read", help="문서 하나를 읽는다(저장소는 고치지 않는다; 읽은 판을 이 세션에 기록)"); K(p); p.add_argument("name"); p.add_argument("--body-only", action="store_true"); P(p); S(p); p.set_defaults(f=cmd_read)
    p = doc.add_parser("path", help="이 세션의 읽기 뷰를 만들고 경로를 알려 준다(저장소는 고치지 않는다)"); K(p, True); P(p); S(p); p.set_defaults(f=cmd_path)
    p = doc.add_parser("find", help="문서 본문·이름을 검색한다(대화 이력은 `donghans ctx search`)"); p.add_argument("term"); K(p, True); p.add_argument("--limit", type=int, default=20); P(p); p.set_defaults(f=cmd_find)
    p = doc.add_parser("propose", help="새 본문을 제안으로 남긴다(저장소에 직접 쓰지 않는다 — 동기화 담당이 검사해 반영)"); K(p); p.add_argument("name")
    p.add_argument("--file"); p.add_argument("--stdin", action="store_true"); P(p); S(p); p.set_defaults(f=cmd_propose)
    p = doc.add_parser("status", help="이 세션의 대기·충돌·거부 제안과 동기화 담당 상태(읽기만)"); P(p); S(p); p.set_defaults(f=cmd_status)
    p = doc.add_parser("watch", help="이 세션의 뷰가 직접 수정되면 한 줄로 알린다(Monitor 로 띄운다; 저장소는 고치지 않는다)"); S(p); p.add_argument("--pid", type=int, help="이 프로세스가 죽으면 끝낸다(기본: CLAUDE_PID)"); p.set_defaults(f=cmd_watch)
    p = doc.add_parser("sync", help="(동기화 담당) 인박스의 제안을 검사해 반영한다 — 세션 안에서 부르는 명령이 아니다")
    p.add_argument("--watch", action="store_true", help="서비스로: 인박스를 지켜보며 반복"); p.add_argument("--push", action="store_true", help="remote 가 있는 프로젝트는 push(직전 비밀 검사)"); p.add_argument("--interval", type=float, default=30, help="--watch 의 주기 점검(초)"); p.set_defaults(f=cmd_sync)
    p = doc.add_parser("cleanup", help="끝난 세션의 낡은 뷰를 지운다"); p.add_argument("--days", type=float, default=7); p.set_defaults(f=cmd_cleanup)
    p = doc.add_parser("init", help="(사람만) 프로젝트를 매니페스트에 등록하고 저장소를 만든다"); p.add_argument("project"); p.add_argument("--repo-url"); p.add_argument("--owner", default="personal"); p.add_argument("--remote"); p.set_defaults(f=cmd_init)
    p = doc.add_parser("import-db", help="옛 DB 표 project_docs 의 문서를 파일로 내보내고 대조한다(멱등)"); p.add_argument("--dry-run", action="store_true"); p.add_argument("-v", "--verbose", action="store_true"); p.set_defaults(f=cmd_import_db)
