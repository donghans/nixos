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
  import-docs   폴더의 .md 를 문서로 반입한다(제안 경로 — 동기화 담당이 검사해 반영). 원본은 건드리지 않는다.
  import-files  폴더의 비 md 자료(json·log·html·스크립트 등)를 `files` 영역에 복사한다(서버 호스트에서만; 스크린샷·비밀은 건너뜀).
  import-held   import-files 가 「검사 불가」로 보류한 파일 중 사용자가 허용한 것만 검사 없이 받는다(하네스가 실행 전에 사용자 확인을 띄운다; 비밀 후보는 허용돼도 안 받음).
  files     `files` 영역의 목록을 보인다. 읽기만 한다.
  audit     프로젝트 폴더에서 git 이 무시하는데 ctx 에 없는 작업 자료를 찾는다. 읽기만 한다.
  init      (실행 전 사용자 확인) 프로젝트를 매니페스트에 등록하고 저장소를 만든다.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import ctx_docqueue as dq
import ctx_store as st

H = None   # llm_ctx 가 넘겨 주는 도우미(norm_repo·git_meta·connect·load_masker·HOST·human_only·is_human) — 순환 import 를 피한다


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
    if err and dq.use_queue():      # 읽기 뷰 호스트: 서버가 등록한 프로젝트를 doc_projects 에서 찾아 자동 연결한다(수동 `git remote add` 불필요)
        if dq.auto_connect(store, H.connect, getattr(a, "project", None), repo):
            man = st.load_manifest(store)
            proj, err = st.resolve_project(man, getattr(a, "project", None), repo)
    if err and need:
        sys.exit(err + f"\n(문서 저장소: {store})")
    _flush_outbox(store)
    return store, proj


def _flush_outbox(store):
    """서버에 못 보내 outbox 에 보관했던 제안을 다시 보낸다(`ctx doc` 명령이 시작할 때마다 — 비어 있으면 DB 에 접속하지 않는다)."""
    if not dq.outbox_files(store) or not dq.use_queue():
        return
    sent, _left = dq.flush_outbox(store, H.connect, H.load_masker)
    if sent:
        print(f"(서버에 못 보냈던 제안 {sent}개를 대기열로 보냈다)", file=sys.stderr)


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
def _refresh(store, proj, force=False):
    """읽기·쓰기 앞의 최신화(노트북 등 읽기 뷰 호스트만; 정본 호스트·origin 없음·최근 시도는 건너뜀). 알릴 것이 있으면 stderr 한 줄."""
    msg = dq.refresh_by_head(store, proj, H.connect, force=force) if dq.use_queue() else st.refresh_project(store, proj, force=force)
    if msg:
        print(msg, file=sys.stderr)


def cmd_list(a):
    store, proj = _project(a)
    _refresh(store, proj)
    rows = st.list_docs(store, proj, a.kind, a.status, a.prefix)
    print(f"프로젝트 {proj} ({store}/{proj})")
    for r in rows:
        print(f"- {r['kind']}/{r['name']}: {r['status']} · {r['state']} · {r['chars']}자 · {r['hash'][:8]}")
    if not rows:
        print("(문서 없음)")
    return 0


def cmd_read(a):
    store, proj = _project(a)
    _refresh(store, proj)
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
    _refresh(store, proj)
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
    _refresh(store, proj)
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


def _guard_card(store, proj, name, body, sid):
    """카드 제안을 검사·보정해 새 본문을 돌려준다. 오류가 있으면 이유를 stderr 에 보이고 종료 코드 1 로 끝낸다(제안하지 않는다)."""
    import datetime
    import ctxcards as cx
    man = st.load_manifest(store)
    conn_holder = {}

    def evidence_project(u8):
        if "c" not in conn_holder:
            conn_holder["c"] = H.connect(readonly=True)
        row = conn_holder["c"].execute("SELECT s.repo_url FROM messages m JOIN sessions s USING (session_id) WHERE m.uuid LIKE %s LIMIT 1", (u8 + "%",)).fetchone()
        if not row:
            return None, False
        url = H.norm_repo(row[0]) if row[0] else None
        for pname, m in man.items():
            if url and m.get("repo_url") and H.norm_repo(m["repo_url"]) == url:
                return pname, True
        return None, True
    try:
        new_body, errors, warns = cx.guard_proposal(body, st.read_doc(store, proj, "note", name), human=bool(H.is_human()), project=proj, name=name, manifest=man,
                                                    evidence_project=evidence_project, session=sid or "", host=H.HOST, today=datetime.date.today().isoformat())
    finally:
        if "c" in conn_holder:
            conn_holder["c"].close()
    for w in warns:
        print(f"카드 가드: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"카드 가드: {e}", file=sys.stderr)
        sys.exit(1)
    return new_body


def cmd_propose(a):
    store, proj = _project(a)
    _refresh(store, proj, force=True)
    sid = _need_session(a)
    if bool(a.file) == bool(a.stdin):
        sys.exit("--file <경로> 또는 --stdin 중 하나를 준다")
    body = sys.stdin.read() if a.stdin else open(a.file, errors="ignore").read()
    import ctxcards as cx
    if cx.is_card_name(a.kind, a.name):                           # 결정 카드: 형식 검증·상태 가드·인용 출처 검사(설계: plan llm-trust/02-card-skill-ui S2)
        body = _guard_card(store, proj, a.name, body, sid)
    base = st.base_hash_for(st.views_dir(), sid, proj, a.kind, a.name)
    code, msg, pid = dq.submit(store, sid, H.HOST, proj, a.kind, a.name, body, base, "write", H.connect, H.load_masker)
    if code:
        print(msg, file=sys.stderr)
        return 1
    return _finish_proposal(store, pid, msg, sid, proj, a.kind, a.name)


def _finish_queued(store, pid, msg, sid, proj, kind, name, op):
    """읽기 뷰 호스트: DB 대기열 행의 결과를 기다려 보이고, 반영됐으면 로컬 읽기 뷰를 서버 판에 맞춘다(맞추지 못하면 읽은 판을 갱신하지 않는다)."""
    r = dq.wait_row(H.connect, pid, float(os.environ.get("CTX_PROPOSE_WAIT", dq.WAIT_DEFAULT)))
    if not r or r["status"] in dq.OPEN_STATUSES:
        print(f"{proj}/{kind}/{name}: **아직 반영되지 않았다**(대기열에서 처리를 기다리는 중{'' if r else ' — 상태를 읽지 못했다'}) — `donghans ctx doc status` 로 확인한다. 같은 제안을 다시 올리지 않는다(종료 코드 0 이어도 반영 완료가 아니다)")
        return 0
    print(r["msg"] + (f" (커밋 {r['commit']})" if r.get("commit") else ""))
    if r["status"] in dq.OK_STATUSES:
        if dq.sync_view(store, proj, kind, name, op, r):
            if sid and op == "write":
                st.ensure_in_view(store, st.views_dir(), sid, proj, kind, name)
        else:
            print("(반영됐지만 이 호스트의 읽기 뷰는 아직 낡았다 — 잠시 뒤 `donghans ctx doc read` 로 다시 읽고 고친다. 계속 같으면 사용자에게 알린다)")
        return 0
    return 1


def _finish_proposal(store, pid, msg, sid=None, proj=None, kind=None, name=None, op="write"):
    if pid and pid.startswith("outbox:"):
        print(msg + " (종료 코드 0 이어도 반영 완료가 아니다)")
        return 0
    if dq.use_queue():
        return _finish_queued(store, pid, msg, sid, proj, kind, name, op)
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
        if sid:
            st.ensure_in_view(store, st.views_dir(), sid, proj, kind, name)   # 자기 제안 반영분을 직접 수정으로 오인하지 않게 읽은 판을 새로 기록
        return 0
    return 1


def cmd_delete(a):
    store, proj = _project(a)
    _refresh(store, proj, force=True)
    sid = _need_session(a)
    base = st.base_hash_for(st.views_dir(), sid, proj, a.kind, a.name)
    code, msg, pid = dq.submit(store, sid, H.HOST, proj, a.kind, a.name, "", base, "delete", H.connect, H.load_masker)
    if code:
        print(msg, file=sys.stderr)
        return 1
    return _finish_proposal(store, pid, msg, None, proj, a.kind, a.name, op="delete")


def _status_queue(store, sid):
    """읽기 뷰 호스트의 status — 「대기열」 줄이 이 경로(DB 대기열)의 관찰 가능한 표지다."""
    print("[대기열] 이 호스트는 동기화 담당이 없어 제안을 DB 대기열로 보낸다 — 정본 호스트의 동기화 담당이 반영한다(반영 전에는 문서가 바뀌지 않는다)")
    if sid:
        try:
            s = dq.status_summary(H.connect, sid)
            print(f"이 세션: 대기 {s['pending']} · 충돌 {s['conflict']} · 거부 {s['rejected']}")
            for n in s["notices"]:
                print("  " + n)
        except Exception as e:
            print(f"(대기열을 못 읽었다 — {type(e).__name__}: 서버에 접속할 수 없거나 스키마가 아직 대기열을 지원하지 않는다)")
    left = dq.outbox_files(store)
    if left:
        old = dq.outbox_old(store)
        print(f"[대기열] 서버에 못 보내 보관 중인 제안 {len(left)}개" + (f" — 그중 {len(old)}개는 {int(dq.OUTBOX_WARN_DAYS)}일을 넘었다(서버 접속·허용 목록을 확인한다)" if old else " (다음 `ctx doc` 실행 때 다시 보낸다)"))


def cmd_status(a):
    store, proj = _project(a, need=False)
    sid = _session(a)
    active = subprocess.run(["systemctl", "--user", "is-active", "ctx-doc-sync.service"], capture_output=True, text=True).stdout.strip() or "없음"
    print(f"문서 저장소 {store} · 프로젝트 {proj or '(알 수 없음)'} · 동기화 담당 {active}")
    if dq.use_queue():
        _status_queue(store, sid)
        return 0
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


def cmd_import_inbox(a):
    """옛 방식의 `_inbox/<세션>/*.proposal.md` 제안 파일들을 DB 대기열에 넣는다(어느 호스트에서든 — 정본 호스트에서도 이 명령만은 DB 를 쓴다). 원본은 건드리지 않는다."""
    folder = os.path.abspath(a.folder)
    if not os.path.isdir(folder):
        sys.exit(f"폴더가 아니다: {folder}")
    try:
        r = dq.import_inbox(H.connect, H.load_masker, folder)
    except Exception as e:
        sys.exit(f"대기열에 넣지 못했다(DB 접속·스키마 확인) — {type(e).__name__}: {e}")
    print(f"대기열에 넣음 {r['new']} · 이미 있음 {r['dup']} · 비밀 때문에 건너뜀 {r['secret']} · 올바르지 않음 {len(r['bad'])}")
    for p, why in r["bad"]:
        print(f"  bad: {p} — {why}")
    return 0


def cmd_cleanup(a):
    gone = st.cleanup_views(st.views_dir(), max_age_days=a.days)
    print(f"지운 뷰 {len(gone)}개" + "".join(f"\n  {g}" for g in gone))
    try:                                    # 낡은(등록표가 바뀐 뒤의) `ctx msg` 파일 — DB 를 못 읽으면 어느 것이 낡았는지 몰라 건드리지 않는다
        import ctx_secrets as cs
        with H.connect(timeout=3, readonly=True) as c:
            h = cs.registry_hash(cs.load_secrets(c))
        stale = st.sweep_stale_msgs(st.views_dir(), h)
        print(f"지운 낡은 ctx msg 파일 {len(stale)}개" + "".join(f"\n  {g}" for g in stale))
    except Exception as e:
        print(f"ctx msg 파일 훑기를 건너뜀(DB 를 못 읽음) — {type(e).__name__}: {e}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- 동기화 담당
def _load_masker_or_none():
    try:
        with H.connect(timeout=3, readonly=True) as c:
            return H.load_masker(c)
    except Exception as e:
        print(f"[sync] 비밀 검사기를 못 써서 처리를 미룬다 — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


PUSH_EVERY = 600      # 반영된 커밋이 없어도 못 보낸 것을 따라잡는 주기(초). 반영이 있으면 곧바로 보낸다.
_last_push = {}


_last_log = {}


def _log_throttled(key, line, every=600.0):
    """같은 오류를 `every` 초에 한 번만 낸다(DB 가 내려갔을 때 점검 주기마다 반복하지 않게)."""
    now = time.time()
    if now - _last_log.get(key, 0) >= every:
        _last_log[key] = now
        print(line, flush=True)


_last_sweep = {"t": 0.0}


def _sync_heads_safe(store, push_results=None):
    try:
        dq.sync_heads(store, H.connect, push_results)
    except Exception as e:           # 표가 아직 없음(옛 스키마) 등 — 파일 인박스·push 를 막지 않는다
        _log_throttled("sync_heads", f"[sync] head 를 기록하지 못했다 — {type(e).__name__}: {e}")


def _sync_once(store, push, force_push=False):
    """① 필요 판정(masker 없이): 대기열·파일 인박스에 할 일이 있는가, push 가 필요한가 — 없으면 DB 에는 선검사 1회만 쓰고 끝(단 HEAD_SWEEP_EVERY 마다 head 점검)
    ② 필요하면 비밀 검사기(못 얻으면 아무것도 하지 않는다 — fail-closed) ③ DB 대기열 → 파일 인박스(pull_queue) ④ process_inbox ⑤ push
    ⑥ 그 뒤에 대기열 행에 결과 기록 ⑦ 프로젝트별 head(실제 `git rev-parse HEAD`)를 doc_projects 에 기록 — push 가 끝난 뒤라야 pushed_sha 도 함께 남는다."""
    now = time.time()
    man = st.load_manifest(store)
    queued = dq.queue_has_work(H.connect)
    pending = bool(st.pending_proposals(store, include_invalid=True))
    push_due = bool(push) and any(meta.get("remote") and (force_push or now - _last_push.get(proj, 0) >= PUSH_EVERY) for proj, meta in man.items())
    if not (queued or pending or push_due or force_push):
        if now - _last_sweep["t"] >= dq.HEAD_SWEEP_EVERY:      # 할 일이 없어도 가끔 head 를 점검한다(직접 git 으로 고친 경우·기록 전 죽음·NULL 백필 복구)
            _last_sweep["t"] = now
            _sync_heads_safe(store)
        return 0
    m = _load_masker_or_none()
    if m is None:
        return 1                      # 비밀 검사 없이 반영·push 하지 않는다(fail-closed) — 제안은 인박스·대기열에 남고 다음 점검 때 다시 시도
    if queued:
        try:
            pulled = dq.pull_queue(store, H.connect)
            if pulled:
                print(f"[sync] 대기열에서 {len(pulled)}건을 가져왔다", flush=True)
        except Exception as e:        # 표가 아직 없음(스키마 서비스·동기화 서비스 재시작 순서) 등 — 파일 인박스 경로와 push 를 막지 않는다
            _log_throttled("pull_queue", f"[sync] 대기열을 가져오지 못했다 — {type(e).__name__}: {e}")
    applied = False
    for _pid, status, msg, commit in st.process_inbox(store, m):
        print(f"[sync] {status}: {msg}" + (f" ({commit})" if commit else ""), flush=True)
        applied = applied or status == "applied"
    results = []
    if queued:
        try:
            results = dq.collect_results(store, H.connect)
            applied = applied or any(r["status"] == "applied" for _p, _o, r in results)
        except Exception as e:
            _log_throttled("collect_results", f"[sync] 대기열 결과를 모으지 못했다 — {type(e).__name__}: {e}")
    pushed_now = {}
    if push:
        for proj, meta in man.items():
            if meta.get("remote") and (force_push or applied or now - _last_push.get(proj, 0) >= PUSH_EVERY):
                ok, msg = st.push_project(store, proj, m, man)
                _last_push[proj] = now
                if ok:
                    pushed_now[proj] = dq.local_head(os.path.join(store, proj))
                print(f"[sync] push {proj}: {'ok' if ok else '못 함'} — {msg}", flush=True)
    if queued:
        try:
            dq.record_results(store, H.connect, results)
            dq.maintenance(store, H.connect, now)
        except Exception as e:
            _log_throttled("record_results", f"[sync] 대기열 결과를 기록하지 못했다 — {type(e).__name__}: {e}")
    _last_sweep["t"] = now
    _sync_heads_safe(store, pushed_now)
    return 0


def cmd_sync(a):
    store = st.store_dir()
    if not a.watch:
        return _sync_once(store, a.push, force_push=True)
    print(f"[sync] 시작: {store}/_inbox 를 지켜본다", flush=True)
    st.watch_inbox(store, lambda: _sync_once(store, a.push), poll=float(a.interval))
    return 0


# ---------------------------------------------------------------- 반입·탐지(파편화 정리)
def _writer_host() -> bool:
    """자료 영역(files)은 서버 호스트(동기화 담당이 있는 곳)에서만 쓴다 — 노트북에서 쓰면 두 호스트의 files 저장소가 갈라진다."""
    forced = os.environ.get("CTX_ALLOW_FILES_WRITE")   # "1" 허용 · "0" 금지(시험) · 없으면 호스트 판별
    if forced in ("0", "1"):
        return forced == "1"
    return subprocess.run(["systemctl", "--user", "cat", "ctx-doc-sync.service"], capture_output=True).returncode == 0


def _need_masker():
    try:
        with H.connect(timeout=3, readonly=True) as c:
            return H.load_masker(c)
    except Exception as e:
        sys.exit(f"비밀 검사기를 못 써서(DB 연결 실패 — {type(e).__name__}) 반입하지 않는다(fail-closed)")


def _doc_name(prefix: str, rel: str) -> str | None:
    parts = [x.lstrip(".") for x in rel[:-3].split("/")]
    if any(not x for x in parts):
        return None
    return "/".join(([prefix.strip("/")] if prefix else []) + parts)


def cmd_import_docs(a):
    store, proj = _project(a)
    _refresh(store, proj, force=True)
    sid = _need_session(a)
    src = os.path.abspath(a.src)
    if not os.path.isdir(src):
        sys.exit(f"폴더가 아니다: {src}")
    masker = None if a.dry_run else _need_masker()
    bodies = st.ctx_body_hashes(store, proj)
    label = a.origin_label or os.path.basename(src)
    rows = {"same": [], "proposed": [], "held": [], "name-bad": [], "skip-nonmd": 0}
    queued = []
    for p, rel in st.walk_files(src):
        if not rel.endswith(".md"):
            rows["skip-nonmd"] += 1
            continue
        kind, why = st.classify_file(p, masker)
        if kind == "held":
            rows["held"].append((rel, why)); continue
        if kind != "ok":
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        if st.sha(text) in bodies:
            rows["same"].append((rel, "본문이 이미 ctx 에 있다")); continue
        name = _doc_name(a.prefix, rel)
        if not name or st.valid_name(name):
            rows["name-bad"].append((rel, st.valid_name(name or "") or "이름을 만들 수 없다")); continue
        kd = a.kind or ("qa" if rel.startswith("qa/") else "note")
        if os.path.exists(st.doc_path(store, proj, kd, name)):
            rows["same"].append((rel, f"{kd}/{name} 이 이미 있다")); continue
        meta = {"provenance": f"이관 {time.strftime('%F')} — {label}/{rel}", "origin_path": f"{label}/{rel}", "source_of_truth": "file"}
        queued.append((rel, kd, name, st.compose(meta, text)))
    if a.dry_run:
        rows["proposed"] = [(r, f"{k}/{n}") for r, k, n, _ in queued]
    else:
        pids = []
        for rel, kd, name, body in queued:
            code, msg, pid = dq.submit(store, sid, H.HOST, proj, kd, name, body, None, "write", H.connect, H.load_masker)
            if code:
                rows["held"].append((rel, msg)); continue
            pids.append((rel, f"{kd}/{name}", pid))
        queue_mode = dq.use_queue()
        if not queue_mode:
            if os.environ.get("CTX_SYNC_INLINE"):
                _inline_sync(store)
            else:
                _wake_worker()
        end = time.time() + float(a.wait)
        for rel, tgt, pid in pids:
            if pid.startswith("outbox:"):
                rows["held"].append((rel, f"{tgt}: **아직 반영되지 않았다**(서버에 접속하지 못해 보관만 했다) — 같은 제안을 다시 올리지 않는다, 다음 `ctx doc` 실행 때 다시 보낸다")); continue
            if queue_mode:
                r = dq.wait_row(H.connect, pid, max(0.2, end - time.time()))
                if r and r["status"] in dq.OPEN_STATUSES:
                    r = None
            else:
                r = st.wait_result(store, pid, max(0.2, end - time.time()))
            if r and r["status"] in ("applied", "same"):
                rows["proposed"].append((rel, tgt))
            else:
                rows["held"].append((rel, f"{tgt}: " + (r["msg"] if r else "**아직 반영되지 않았다**(시간 안에 처리되지 않음, 대기 중일 수 있다) — 같은 제안을 다시 올리지 않는다, `ctx doc status` 로 확인한다")))
    print(f"프로젝트 {proj} · 원본 {src}" + (" · (dry-run)" if a.dry_run else ""))
    print(f"반영{'할 것' if a.dry_run else ''} {len(rows['proposed'])} · 이미 있음 {len(rows['same'])} · 보류 {len(rows['held'])} · 이름 불가 {len(rows['name-bad'])} · md 아님(건너뜀) {rows['skip-nonmd']}")
    for k in ("held", "name-bad"):
        for rel, why in rows[k]:
            print(f"  {k}: {rel} — {why}")
    if a.manifest:
        with open(a.manifest, "w") as f:
            for k in ("proposed", "same", "held", "name-bad"):
                for rel, why in rows[k]:
                    f.write(f"{k}\t{rel}\t{why}\t{st.file_hash(os.path.join(src, rel)) or '-'}\n")
        print(f"목록: {a.manifest}")
    return 0


def cmd_import_held(a):
    """검사만 못 한 보류 파일을 사용자 허용으로 받는다. 허용 자체는 하네스의 `ask` 규칙(실행 전 사용자 확인)이 강제한다 — 이 명령은 그 확인을 대신하지 못한다."""
    if not a.files:
        sys.exit("--files 로 허용할 상대경로를 준다(import-files 의 보류 목록에서 고른다)")
    if not a.reason.strip():
        sys.exit("--reason 이 필요하다(왜 검사 없이 받는지 — files 저장소 커밋에 남는다)")
    a.allow, a.manifest, a.limit = a.files, None, 50
    return cmd_import_files(a)


def cmd_import_files(a):
    store, proj = _project(a)
    if not a.dry_run and not _writer_host():
        sys.exit("자료 영역(files)은 서버 호스트(동기화 담당이 있는 곳)에서만 쓴다 — 이 호스트에는 `ctx-doc-sync` 가 없다")
    src = os.path.abspath(a.src)
    if not os.path.isdir(src):
        sys.exit(f"폴더가 아니다: {src}")
    masker = _need_masker()
    rep = st.import_files(store, proj, src, a.dest or "", masker, a.dry_run, allow=tuple(getattr(a, "allow", ()) or ()), reason=getattr(a, "reason", "") or "")
    print(f"프로젝트 {proj} · 원본 {src} → files/{a.dest or ''}" + (" · (dry-run)" if a.dry_run else ""))
    print(f"복사{'할 것' if a.dry_run else ''} {len(rep['imported'])} · 이미 같음 {len(rep['same'])} · 스크린샷(저장 안 함) {len(rep['images'])} · 보류 {len(rep['held'])}"
          + (f" · 커밋 {rep['commit']}" if rep["commit"] else ""))
    for rel, why in rep["overridden"]:
        print(f"  사용자 허용으로 검사 없이 받음: {rel} — {why}")
    for rel, why in rep["refused"]:
        print(f"  허용 거부: {rel} — {why}")
    for rel, why in rep["held"][: a.limit]:
        print(f"  보류: {rel} — {why}")
    if len(rep["held"]) > a.limit:
        print(f"  … 보류 {len(rep['held']) - a.limit}개 더(--limit 로 늘린다)")
    if a.manifest:
        with open(a.manifest, "w") as f:
            for k in ("imported", "same", "images", "held"):
                for rel, why in rep[k]:
                    f.write(f"{k}\t{rel}\t{why}\t{st.file_hash(os.path.join(src, rel)) or '-'}\n")
        print(f"목록: {a.manifest}")
    return 0


def cmd_files(a):
    store, proj = _project(a)
    rows = st.list_files(store, proj, a.prefix or "")
    print(f"프로젝트 {proj} ({st.files_dir(store, proj)}) — 자료 {len(rows)}개 · {sum(s for _, s in rows) / 1e6:.2f}MB")
    for rel, size in rows[: a.limit]:
        print(f"- {rel} ({size:,}B)")
    if len(rows) > a.limit:
        print(f"… {len(rows) - a.limit}개 더(--limit)")
    return 0


def cmd_audit(a):
    store, proj = _project(a)
    root = a.root or H.git_meta(os.getcwd()).get("repo_root")
    if not root or not os.path.isdir(root):
        sys.exit("프로젝트 폴더를 알 수 없다 — `--root <경로>` 를 준다")
    res = st.audit_project(store, proj, root, tuple(os.path.expanduser(p) for p in (a.paths or [])), tuple(a.skip or []))
    print(f"프로젝트 {proj} · 폴더 {root}")
    print(f"ctx 에 있음 {res['present']} · **없음 {len(res['missing'])}** · 보류(비밀 후보·검사 불가) {len(res['held'])} · 스크린샷 {res['images']} · 재생성물·캐시 건너뜀 {res['skipped']}")
    for rel in res["missing"][: a.limit]:
        print(f"  없음: {rel}")
    for rel in res["held"][: a.limit]:
        print(f"  보류: {rel}")
    if len(res["missing"]) > a.limit:
        print(f"  … 없음 {len(res['missing']) - a.limit}개 더(--limit)")
    if res["missing"]:
        print("→ 문서(.md)는 `donghans ctx doc import-docs`, 자료는 `import-files` 로 ctx 에 둔다(노트북↔데스크톱 파편화 방지).")
    return 0 if not res["missing"] else 2


# ---------------------------------------------------------------- 사람 전용
def cmd_init(a):
    # 사람 확인은 하네스의 `ask` 규칙(llm-cli.nix: Bash(donghans ctx doc init:*))이 실행 전에 강제한다 — --remote 는 외부 전송 경로라 확인창에 명령이 그대로 보인다.
    store = st.store_dir()
    why = st.valid_project(a.project)
    if why:
        sys.exit(why)
    repo = H.norm_repo(a.repo_url) if a.repo_url else ""
    if dq.use_queue():       # 읽기 뷰 호스트: 로컬 매니페스트를 쓰지 않고 정본 호스트에 등록을 요청한다(로컬에만 등록되어 서버와 갈라지던 `genple-new` 사고의 원인)
        return _init_queued(a, repo)
    print(st.init_project(store, a.project, repo, a.owner, a.remote or ""))
    return 0


def _init_queued(a, repo):
    sid = _session(a) or f"cli-{H.HOST}"
    code, msg, pid = dq.submit_init(sid, H.HOST, a.project, repo, a.owner, a.remote or "", H.connect)
    if code:
        print(msg, file=sys.stderr)
        return 1
    r = dq.wait_row(H.connect, pid, float(os.environ.get("CTX_PROPOSE_WAIT", dq.WAIT_DEFAULT)))
    if not r or r["status"] in dq.OPEN_STATUSES:
        print(f"{a.project}: **아직 반영되지 않았다**(정본 호스트의 처리를 기다리는 중) — `donghans ctx doc status` 로 확인한다. 같은 `init` 을 다시 실행하지 않는다(종료 코드 0 이어도 등록 완료가 아니다)")
        return 0
    print(r["msg"] + ("" if r["status"] not in dq.OK_STATUSES else " — 다음 `donghans ctx doc` 실행 때 이 호스트에 자동으로 연결된다"))
    return 0 if r["status"] in dq.OK_STATUSES else 1


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
    p = doc.add_parser("delete", help="문서 삭제를 제안으로 남긴다(먼저 read|path 로 읽어야 한다 — 동기화 담당이 읽은 판이 같을 때만 git 에서 지운다; 이력에 남아 복구 가능)"); K(p); p.add_argument("name"); P(p); S(p); p.set_defaults(f=cmd_delete)
    p = doc.add_parser("status", help="이 세션의 대기·충돌·거부 제안과 동기화 담당 상태(읽기만)"); P(p); S(p); p.set_defaults(f=cmd_status)
    p = doc.add_parser("watch", help="이 세션의 뷰가 직접 수정되면 한 줄로 알린다(Monitor 로 띄운다; 저장소는 고치지 않는다)"); S(p); p.add_argument("--pid", type=int, help="이 프로세스가 죽으면 끝낸다(기본: CLAUDE_PID)"); p.set_defaults(f=cmd_watch)
    p = doc.add_parser("sync", help="(동기화 담당) 인박스의 제안을 검사해 반영한다 — 세션 안에서 부르는 명령이 아니다")
    p.add_argument("--watch", action="store_true", help="서비스로: 인박스를 지켜보며 반복"); p.add_argument("--push", action="store_true", help="remote 가 있는 프로젝트는 push(직전 비밀 검사)"); p.add_argument("--interval", type=float, default=5, help="--watch 의 주기 점검(초) — DB 대기열 점검 주기이기도 하다"); p.set_defaults(f=cmd_sync)
    p = doc.add_parser("import-inbox", help="옛 방식의 인박스 제안 파일을 DB 대기열에 넣는다(원본은 건드리지 않는다 — 정본 호스트의 동기화 담당이 반영)"); p.add_argument("folder"); p.set_defaults(f=cmd_import_inbox)
    p = doc.add_parser("cleanup", help="끝난 세션의 낡은 뷰를 지운다"); p.add_argument("--days", type=float, default=7); p.set_defaults(f=cmd_cleanup)
    p = doc.add_parser("init", help="프로젝트를 매니페스트에 등록하고 저장소를 만든다(하네스가 실행 전 사용자 확인을 띄운다)"); p.add_argument("project"); p.add_argument("--repo-url"); p.add_argument("--owner", default="personal"); p.add_argument("--remote"); p.set_defaults(f=cmd_init)

    p = doc.add_parser("import-docs", help="폴더의 .md 를 문서로 반입한다(제안 경로 — 동기화 담당이 검사해 반영; 원본은 건드리지 않는다)"); p.add_argument("src"); P(p); S(p)
    p.add_argument("--prefix", default="local", help="문서 이름 앞에 붙일 경로(기본 local)"); p.add_argument("--kind", choices=st.KINDS, help="종류(기본: qa/ 로 시작하면 qa, 아니면 note)")
    p.add_argument("--origin-label", help="머리말 origin_path 의 앞부분(기본: 폴더 이름)"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--wait", type=float, default=300, help="처리 결과를 기다리는 최대 초")
    p.add_argument("--manifest", help="결과 목록(상태·경로·해시)을 이 파일에 쓴다"); p.set_defaults(f=cmd_import_docs)
    p = doc.add_parser("import-files", help="폴더의 비 md 자료를 files 영역에 복사한다(서버 호스트 전용; 스크린샷·비밀·검사 불가 파일은 건너뛰고 보고)"); p.add_argument("src"); P(p)
    p.add_argument("--to", dest="dest", default="", help="files 안의 하위 경로(기본: 폴더 바로 아래)"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--limit", type=int, default=50)
    p.add_argument("--manifest", help="결과 목록(상태·경로·해시)을 이 파일에 쓴다"); p.set_defaults(f=cmd_import_files)
    p = doc.add_parser("import-held", help="import-files 가 검사 불가로 보류한 파일 중 사용자가 허용한 것만 검사 없이 받는다(하네스가 사용자 확인을 띄운다; 비밀 후보는 안 받음)"); p.add_argument("src"); P(p)
    p.add_argument("--to", dest="dest", default="", help="files 안의 하위 경로(import-files 때와 같게)"); p.add_argument("--files", nargs="+", metavar="상대경로", help="허용할 보류 파일(원본 폴더 기준 상대경로)")
    p.add_argument("--reason", default="", help="검사 없이 받는 이유(커밋에 남는다)"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(f=cmd_import_held)
    p = doc.add_parser("files", help="files 영역의 자료 목록(읽기만)"); P(p); p.add_argument("prefix", nargs="?"); p.add_argument("--limit", type=int, default=50); p.set_defaults(f=cmd_files)
    p = doc.add_parser("audit", help="프로젝트 폴더에서 git 이 무시하는데 ctx 에 없는 작업 자료를 찾는다(읽기만)"); P(p); p.add_argument("--root", help="프로젝트 폴더(기본: 현재 git 저장소)")
    p.add_argument("--paths", nargs="*", help="폴더 밖 추가 경로(예: ~/qa-shots)"); p.add_argument("--skip", nargs="*", help="세지 않을 하위 경로(예: librechat-original — 앱 실행 데이터)"); p.add_argument("--limit", type=int, default=30); p.set_defaults(f=cmd_audit)
