#!/usr/bin/env python3
"""ctx_docqueue — 읽기 뷰 호스트(노트북)의 작업 문서 쓰기 대기열(DB 표 doc_proposals).

왜: 노트북에는 동기화 담당이 없어 `propose` 가 `~/ctx/_inbox` 에 쌓이기만 하고 처리되지 않았다(2026-11-02 제안이 9일 방치).
어떻게: 읽기 뷰 호스트의 제출은 DB 행으로 넣고, 정본 호스트의 동기화 담당(ctx-doc-sync)이 그 행을 **기존 제안 파일 형식으로 풀어**
기존 `process_inbox()` 에 그대로 태운다 — 검사(읽은 판·머리말·비밀)·커밋 논리는 `ctx_store.process_proposal` 한 곳에만 있고 여기서는 전달만 한다.
계획: ctx 문서 `plan/ctx-doc-db-queue`.

공개 함수:
  use_queue()                       이 프로세스의 제출이 DB 대기열로 가는가(정본 호스트·CTX_SYNC_INLINE 이면 아니오 — 파일 인박스 그대로)
  submit(...)                       제출 지점(propose·delete·import-docs·llmui 카드가 모두 이걸 쓴다)
  wait_row / sync_view              결과 기다리기 / 반영 뒤 읽기 뷰 맞추기(거짓 충돌 방지)
  status_summary                    이 세션의 대기·충돌·거부와 최근 알림
  flush_outbox / import_inbox       서버 불가 중 보관분 재전송 / 옛 방식 제안 파일을 대기열로 옮기기
  pull_queue / collect_results / record_results / maintenance   (동기화 담당이 쓴다)
"""
import json
import os
import time

import ctx_store as st

# 상수(계획 §7 O-1 — 한 곳에 모아 둔다)
WAIT_DEFAULT = 15.0            # 노트북 제출 대기(초). CTX_PROPOSE_WAIT 로 바꾼다
VIEW_SYNC_DEADLINE = 20.0      # 반영 뒤 읽기 뷰 맞추기 마감(초)
VIEW_SYNC_STEP = 3.0           # 〃 재시도 간격(초)
FETCHED_RECOVER_SEC = 30 * 60  # 가져간 뒤 파일도 결과도 없이 이 시간이 지나면 queued 로 되돌린다
CONFLICT_BODY_KEEP_DAYS = 7    # 충돌 행 본문 보관 일수
OUTBOX_WARN_DAYS = 7           # outbox 에 이만큼 묵으면 status 가 경고한다
OPEN_STATUSES = ("queued", "fetched")
OK_STATUSES = ("applied", "same")


def use_queue() -> bool:
    """읽기 뷰 호스트(동기화 담당이 없는 호스트)에서만 DB 대기열을 쓴다. CTX_SYNC_INLINE(이 프로세스가 직접 처리) 이면 파일 인박스 그대로."""
    return not (os.environ.get("CTX_SYNC_INLINE") or st.is_writer_host())


def safe_component(s: str | None) -> bool:
    """DB 에서 온 값이 경로 성분이 되기 전의 검사 — 빈 값·`/`·NUL·`.` 로 시작·너무 긴 것을 거부한다(한글 이름은 허용)."""
    return bool(s) and "/" not in s and "\x00" not in s and not s.startswith(".") and len(s.encode()) <= 200


# ---------------------------------------------------------------- outbox(서버 불가 중 보관)
def outbox_dir(store: str) -> str:
    return os.path.join(store, "_outbox")


def outbox_put(store: str, session: str, pid: str, text: str) -> str:
    d = os.path.join(outbox_dir(store), session)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{pid}.tmp")
    open(tmp, "w").write(text)
    path = os.path.join(d, pid + ".proposal.md")
    os.replace(tmp, path)
    return path


def outbox_files(store: str) -> list[str]:
    out = []
    try:
        sessions = sorted(d for d in os.listdir(outbox_dir(store)) if not d.startswith("_"))
    except OSError:
        return out
    for sid in sessions:
        d = os.path.join(outbox_dir(store), sid)
        try:
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".proposal.md")]
        except OSError:
            pass
    return out


def outbox_old(store: str, days: float = OUTBOX_WARN_DAYS, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    return [p for p in outbox_files(store) if now - os.path.getmtime(p) > days * 86400]


# ---------------------------------------------------------------- 표 쓰기·읽기(클라이언트)
def enqueue(conn, pid: str, session: str, host: str, target: str, op: str, base_hash: str | None, body: str) -> bool:
    """행을 넣는다. 같은 id 가 이미 있으면 넣지 않고 False(멱등 — outbox 재전송·import-inbox 재실행)."""
    cur = conn.execute("INSERT INTO doc_proposals (id, session_id, host, target, op, base_hash, body, status) VALUES (%s,%s,%s,%s,%s,%s,%s,'queued') ON CONFLICT (id) DO NOTHING",
                       (pid, session, host, target, op, base_hash or "none", body))
    return cur.rowcount == 1


def has_open(conn, session: str, target: str) -> bool:
    return conn.execute("SELECT 1 FROM doc_proposals WHERE session_id=%s AND target=%s AND status IN ('queued','fetched') LIMIT 1", (session, target)).fetchone() is not None


def submit(store: str, session: str, host: str, project: str, kind: str, name: str, body: str, base_hash: str | None, op: str, connect, load_masker) -> tuple[int, str, str | None]:
    """제출 지점. (결과코드, 메시지, 토큰). 토큰: 파일 인박스면 제안 id, DB 대기열이면 행 id, outbox 보관이면 `outbox:<id>`.
    정본 호스트·CTX_SYNC_INLINE 이면 지금까지처럼 `st.propose()`(파일 인박스)."""
    if not use_queue():
        return st.propose(store, session, host, project, kind, name, body, base_hash, op)
    why = st.check_proposal(store, session, project, kind, name, body, base_hash, op)
    if why:
        return 1, why, None
    target = f"{project}/{kind}/{name}"
    pid = st.proposal_id(project, kind, name)
    text = st.render_proposal(target, op, base_hash, session, host, body)
    masker = None
    try:
        with connect(timeout=3, readonly=True) as c:
            masker = load_masker(c)
    except Exception:
        masker = None
    if op == "write" and masker is not None and masker.text(body) != body:      # 등록된 비밀은 DB 에 넣지 않는다(서버도 한 번 더 검사한다)
        return 1, f"{target}: 본문에 등록된 비밀 값이 들어 있어 올리지 않는다 — 비밀은 `donghans secret` 으로 두고 문서에는 이름만 적는다", None
    try:
        with connect(timeout=3) as c:
            if has_open(c, session, target):
                return 1, f"{target}: 이 세션의 이전 제안이 아직 처리 중이다 — 기다리거나 `donghans ctx doc status` 로 확인한다", None
            enqueue(c, pid, session, host, target, op, base_hash, body)
            c.commit()
    except Exception as e:
        outbox_put(store, session, pid, text)
        return 0, f"{target}: 서버에 접속하지 못해 **보관만 했다**(아직 반영되지 않았다, {type(e).__name__}) — 다음 `donghans ctx doc` 실행 때 다시 보낸다", "outbox:" + pid
    return 0, f"{target}: 제안을 대기열에 넣었다", pid


def wait_row(connect, pid: str, timeout: float, sleep=time.sleep, poll: float = 0.5) -> dict | None:
    """행이 끝날 때까지(또는 timeout) 기다려 마지막으로 본 행을 돌려준다. 행을 못 읽으면 None. 끝나지 않았으면 status 가 queued|fetched."""
    end = time.time() + timeout
    last = None
    while True:
        try:
            with connect(timeout=3, readonly=True) as c:
                r = c.execute("SELECT status, msg, commit_sha, doc_hash FROM doc_proposals WHERE id=%s", (pid,)).fetchone()
            if r:
                last = {"status": r[0], "msg": r[1] or "", "commit": r[2], "doc_hash": r[3]}
                if last["status"] not in OPEN_STATUSES:
                    return last
        except Exception:
            pass
        if time.time() >= end:
            return last
        sleep(poll)


def can_pull(store: str, project: str) -> bool:
    """`refresh_project` 가 실제로 pull 할 수 있는 조건(정본 호스트·origin 없음·CTX_NO_PULL=1 이면 기다려도 소용없다)."""
    if os.environ.get("CTX_NO_PULL") == "1" or st.is_writer_host():
        return False
    pd = os.path.join(store, project)
    return os.path.isdir(os.path.join(pd, ".git")) and st._git(pd, "remote", "get-url", "origin", check=False).returncode == 0


def view_in_sync(store: str, project: str, kind: str, name: str, op: str, row: dict) -> bool:
    """로컬 저장소가 서버의 반영분을 받았는가. write 는 문서 해시, delete 는 커밋 도착으로 본다."""
    if op == "delete":
        sha = row.get("commit")
        return bool(sha) and st._git(os.path.join(store, project), "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0
    d = st.read_doc(store, project, kind, name)
    return d is not None and bool(row.get("doc_hash")) and d["hash"] == row["doc_hash"]


def sync_view(store: str, project: str, kind: str, name: str, op: str, row: dict, deadline: float = VIEW_SYNC_DEADLINE, step: float = VIEW_SYNC_STEP,
              refresh=None, sleep=time.sleep) -> bool:
    """반영 뒤 로컬 읽기 뷰를 서버 판에 맞춘다(마감 시각 기준 루프). 맞췄으면 True. 못 맞췄거나 pull 할 수 없으면 False — 이때 읽은 판은 갱신하지 않는다
    (낡은 판으로 다음 제안을 하면 서버가 충돌로 거부한다 — 덮어쓰지 않으므로 안전)."""
    refresh = refresh or (lambda: st.refresh_project(store, project, force=True))
    if view_in_sync(store, project, kind, name, op, row):
        return True
    if not can_pull(store, project):
        return False
    end = time.time() + deadline
    while time.time() < end:
        refresh()
        if view_in_sync(store, project, kind, name, op, row):
            return True
        sleep(step)
    return False


def status_summary(connect, session: str) -> dict:
    """이 세션의 대기·충돌·거부 수와 최근 알림(충돌·거부 행 최근 10건의 msg 를 한 줄로)."""
    with connect(timeout=3, readonly=True) as c:
        cnt = dict(c.execute("SELECT status, count(*) FROM doc_proposals WHERE session_id=%s GROUP BY status", (session,)).fetchall())
        notes = c.execute("SELECT resolved_at, status, msg FROM doc_proposals WHERE session_id=%s AND status IN ('conflict','rejected') ORDER BY resolved_at DESC NULLS LAST LIMIT 10", (session,)).fetchall()
    return {"pending": cnt.get("queued", 0) + cnt.get("fetched", 0), "conflict": cnt.get("conflict", 0), "rejected": cnt.get("rejected", 0),
            "notices": [f"{t:%F %T} {s}: {m}" for t, s, m in reversed(notes)]}


def _parse_file(path: str) -> tuple[dict | None, str, str]:
    text, _why = st.read_text(path)
    meta, body = st.parse_proposal(text or "")
    return meta, body, os.path.basename(path)[:-len(".proposal.md")]


def _enqueue_file(conn, path: str, masker) -> str:
    """제안 파일 하나를 행으로. 결과: new | dup | bad:<이유> | secret."""
    meta, body, pid = _parse_file(path)
    if not meta or "target" not in meta:
        return "bad:제안 머리말이 없다"
    sid = meta.get("session", "")
    parts = meta["target"].split("/", 2)
    if len(parts) != 3 or st.check_target(*parts) or not safe_component(pid) or not safe_component(sid):
        return "bad:target·id·세션이 올바르지 않다"
    op = meta.get("op", "write")
    if op not in ("write", "delete"):
        return "bad:op"
    if op == "write" and masker is not None and masker.text(body) != body:
        return "secret"
    return "new" if enqueue(conn, pid, sid, meta.get("host", ""), meta["target"], op, None if meta.get("base_hash", "none") == "none" else meta["base_hash"], body) else "dup"


def flush_outbox(store: str, connect, load_masker) -> tuple[int, int]:
    """outbox 의 보관분을 DB 대기열로 보낸다. (보낸 수, 남은 수). 성공한 파일만 지운다. outbox 가 비어 있으면 DB 에 접속하지 않는다."""
    files = outbox_files(store)
    if not files:
        return 0, 0
    try:
        with connect(timeout=3, readonly=True) as c:
            masker = load_masker(c)
        conn = connect(timeout=3)
    except Exception:
        return 0, len(files)
    sent = 0
    try:
        for path in files:
            res = _enqueue_file(conn, path, masker)
            if res in ("new", "dup"):
                conn.commit()
                os.remove(path)
                sent += res == "new"
            elif res == "secret" or res.startswith("bad:"):      # 보낼 수 없는 파일은 옆으로 치운다(영원히 재시도하지 않게)
                aside = os.path.join(outbox_dir(store), "_rejected", os.path.basename(os.path.dirname(path)))
                os.makedirs(aside, exist_ok=True)
                os.replace(path, os.path.join(aside, os.path.basename(path)))
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return sent, len(outbox_files(store))


def import_inbox(connect, load_masker, folder: str) -> dict:
    """옛 방식의 `_inbox/<세션>/*.proposal.md` 파일들을 DB 대기열에 넣는다(재실행 안전 — 같은 id 는 건너뜀). 원본 파일은 건드리지 않는다."""
    paths = []
    for root, _dirs, files in os.walk(folder):
        paths += [os.path.join(root, f) for f in sorted(files) if f.endswith(".proposal.md")]
    out = {"new": 0, "dup": 0, "secret": 0, "bad": []}
    with connect(timeout=3, readonly=True) as c:
        masker = load_masker(c)
    with connect(timeout=5) as conn:
        for p in sorted(paths):
            r = _enqueue_file(conn, p, masker)
            if r.startswith("bad:"):
                out["bad"].append((p, r[4:]))
            else:
                out[r] += 1
        conn.commit()
    return out


# ---------------------------------------------------------------- 동기화 담당(정본 호스트)
def queue_has_work(connect) -> bool:
    """가벼운 선검사. 표가 없거나(옛 스키마) DB 를 못 읽으면 False — 파일 인박스 경로를 막지 않는다."""
    try:
        with connect(timeout=3, readonly=True) as c:
            return c.execute("SELECT 1 FROM doc_proposals WHERE status IN ('queued','fetched') LIMIT 1").fetchone() is not None
    except Exception:
        return False


def _result_path(store: str, pid: str) -> str:
    return os.path.join(st.inbox_dir(store), "_results", pid + ".json")


def pull_queue(store: str, connect) -> list[str]:
    """queued 행을 가져와(fetched) 기존 파일 형식 제안으로 풀어 놓는다. 쓰기 가능한 연결이 필요하다. 가져온 id 목록을 돌려준다."""
    out = []
    with connect(timeout=5) as c:
        rows = c.execute("SELECT id, session_id, host, target, op, base_hash, body, created_at FROM doc_proposals WHERE status='queued' ORDER BY created_at, id FOR UPDATE SKIP LOCKED").fetchall()
        for pid, sid, host, target, op, base, body, created in rows:
            parts = (target or "").split("/", 2)
            why = None
            if not safe_component(pid) or not safe_component(sid):
                why = "제안 id·세션 id 가 경로로 쓸 수 없는 값이다"
            elif len(parts) != 3 or st.check_target(*parts):
                why = f"target 이 올바르지 않다: {target}"
            elif op not in ("write", "delete") or (op == "write" and not (body or "").strip()):
                why = "op 또는 본문이 올바르지 않다"
            if why:
                c.execute("UPDATE doc_proposals SET status='rejected', msg=%s, body=NULL, resolved_at=now() WHERE id=%s", (why, pid))
                continue
            d = os.path.join(st.inbox_dir(store), sid)
            path = os.path.join(d, pid + ".proposal.md")
            if not os.path.exists(path) and not os.path.exists(_result_path(store, pid)):   # 이미 풀어 놓았거나 이미 처리된 것은 다시 만들지 않는다(재시작 안전)
                os.makedirs(d, exist_ok=True)
                tmp = os.path.join(d, f".{pid}.tmp")
                open(tmp, "w").write(st.render_proposal(target, op, None if base == "none" else base, sid, host or "", body or "", created.strftime("%Y-%m-%dT%H:%M:%SZ")))
                os.replace(tmp, path)
            c.execute("UPDATE doc_proposals SET status='fetched', fetched_at=now() WHERE id=%s", (pid,))
            out.append(pid)
        c.commit()
    return out


def collect_results(store: str, connect) -> list[tuple[str, str, dict]]:
    """fetched 행 중 `_results/<id>.json` 이 생긴 것을 [(id, op, 결과)] 로. 행은 아직 바꾸지 않는다(push 뒤에 기록하려고)."""
    out = []
    with connect(timeout=3, readonly=True) as c:
        rows = c.execute("SELECT id, op FROM doc_proposals WHERE status='fetched'").fetchall()
    for pid, op in rows:
        try:
            out.append((pid, op, json.load(open(_result_path(store, pid)))))
        except (OSError, ValueError):
            pass
    return out


def record_results(store: str, connect, results: list[tuple[str, str, dict]]) -> None:
    """결과를 행에 기록한다. applied·same(write)이면 문서 해시를 doc_hash 로 남기고, 본문은 applied·same·rejected 면 비운다(충돌만 보관)."""
    if not results:
        return
    with connect(timeout=5) as c:
        for pid, op, r in results:
            doc_hash = None
            if r["status"] in OK_STATUSES and op == "write":
                row = c.execute("SELECT target FROM doc_proposals WHERE id=%s", (pid,)).fetchone()
                if row:
                    project, kind, name = row[0].split("/", 2)
                    d = st.read_doc(store, project, kind, name)
                    doc_hash = d["hash"] if d else None
            keep_body = r["status"] == "conflict"
            c.execute("UPDATE doc_proposals SET status=%s, msg=%s, commit_sha=%s, doc_hash=%s, resolved_at=now(), body=CASE WHEN %s THEN body ELSE NULL END WHERE id=%s",
                      (r["status"], r.get("msg", ""), r.get("commit"), doc_hash, keep_body, pid))
        c.commit()


def maintenance(store: str, connect, now: float | None = None) -> dict:
    """① 가져간 지 FETCHED_RECOVER_SEC 이 넘었는데 파일도 결과도 없는 행을 queued 로 되돌린다 ② 충돌 행의 본문을 보관 기간 뒤에 비운다."""
    now = time.time() if now is None else now
    out = {"requeued": 0, "body_cleared": 0}
    with connect(timeout=5) as c:
        rows = c.execute("SELECT id, session_id FROM doc_proposals WHERE status='fetched' AND fetched_at < to_timestamp(%s)", (now - FETCHED_RECOVER_SEC,)).fetchall()
        for pid, sid in rows:
            if safe_component(pid) and safe_component(sid) and not os.path.exists(os.path.join(st.inbox_dir(store), sid, pid + ".proposal.md")) and not os.path.exists(_result_path(store, pid)):
                c.execute("UPDATE doc_proposals SET status='queued', fetched_at=NULL WHERE id=%s", (pid,))
                out["requeued"] += 1
        out["body_cleared"] = c.execute("UPDATE doc_proposals SET body=NULL WHERE status='conflict' AND body IS NOT NULL AND resolved_at < to_timestamp(%s)", (now - CONFLICT_BODY_KEEP_DAYS * 86400,)).rowcount
        c.commit()
    return out
