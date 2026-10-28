#!/usr/bin/env python3
"""ctx_store — 작업 문서(계획·QA·메모)의 파일 저장소 `~/ctx`, 세션별 읽기 뷰, 쓰기 제안(인박스), 동기화 담당. `donghans ctx doc` 의 본체.

용어(고정): 문서(doc) · 저장소(store, `~/ctx/<프로젝트>/` — 프로젝트마다 독립 git 저장소가 원천) · 뷰(view, 읽기용 복사본 `~/.cache/ctx-views/<세션ID>/`) ·
제안(proposal, 쓰기 요청 — 인박스 `~/ctx/_inbox/<세션ID>/`) · 동기화 담당(sync worker, 제안을 검증해 커밋하는 세션 밖 프로세스).
LLM 은 저장소에 직접 쓰지 않는다: 뷰를 읽고 `propose` 로 제안만 남기며, 동기화 담당이 ① 읽은 판과 같은 판인지(base_hash) ② 등록된 비밀이 없는지
③ 머리말이 올바른지 검사해 통과한 것만 커밋한다. 충돌은 자동으로 합치지 않고 멈추고 알린다.

문서 파일 = ctx 머리말 + 본문. 머리말은 맨 앞의 HTML 주석 한 덩어리(`<!-- ctx` … `-->`)라서 본문(자기 `---` 머리말 포함)을 한 바이트도 바꾸지 않는다.
머리말 칸: status(active|done|dropped|unknown) · scope · state · adopted_to · provenance · env_dependent · source_of_truth · origin_path · updated_host · updated_at.
값이 없으면 unknown. base_hash 는 머리말을 포함한 파일 전체의 sha256 이다.

순수 함수와 파일 함수는 DB 없이 시험한다. 비밀 검사기(masker)는 호출자가 넣는다(`ctx_secrets.load_masker(conn)`) — 이 모듈은 DB 를 모른다.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import tomllib

KINDS = ("plan", "qa", "note")
STATUSES = ("active", "done", "dropped", "unknown")
CHOICES = {
    "status": STATUSES,
    "scope": ("personal", "project", "unknown"),
    "state": ("draft", "reviewed", "adopted", "unknown"),
    "env_dependent": ("unknown", "yes", "no"),
    "source_of_truth": ("file", "db-generated", "unknown"),
}
FREE_FIELDS = ("adopted_to", "provenance", "origin_path", "updated_host", "updated_at")
FIELD_ORDER = ("status", "scope", "state", "adopted_to", "provenance", "env_dependent", "source_of_truth", "origin_path", "updated_host", "updated_at")
MAX_BYTES = 2_000_000
HDR_OPEN, HDR_CLOSE = "<!-- ctx\n", "-->\n"
PROP_OPEN = "<!-- ctx-proposal\n"
BASE_FILE, ENDED_FILE, PID_FILE, WATCH_PID_FILE, REJECTED_DIR = ".ctx-base.json", ".ctx-ended", ".ctx-pid", ".ctx-watch.pid", ".ctx-rejected"
EXCLUDE_TOP = ("_inbox", ".git")


# ---------------------------------------------------------------- 경로·설정
def store_dir() -> str:
    return os.environ.get("CTX_STORE_DIR") or os.path.join(os.path.expanduser("~"), "ctx")


def views_dir() -> str:
    return os.environ.get("CTX_VIEWS_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "ctx-views")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_hash(path: str) -> str | None:
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def valid_name(name: str) -> str | None:
    """이름이 올바르면 None, 아니면 이유. 경로꼴(`a/b`)을 허용하고 `..`·절대 경로·`.md` 접미·숨김 칸은 거부한다."""
    if not name or not name.strip():
        return "이름이 비었다"
    if name.startswith("/") or "\x00" in name or any(p in ("", "..", ".") for p in name.split("/")):
        return "이름은 `..`·절대 경로·빈 칸을 쓸 수 없다"
    if len(name) > 300:
        return "이름이 너무 길다(300자 이하)"
    if name.endswith(".md"):
        return "이름에 `.md` 를 붙이지 않는다(저장할 때 붙는다)"
    if any(p.startswith(".") for p in name.split("/")):
        return "`.` 로 시작하는 칸은 쓸 수 없다"
    return None


def valid_project(project: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}", project or ""):
        return "프로젝트 이름은 영문·숫자·`.`·`_`·`-` 만(61자 이하)"
    if project.startswith("_"):
        return "`_` 로 시작하는 이름은 예약돼 있다"
    return None


def doc_rel(project: str, kind: str, name: str) -> str:
    return f"{project}/{kind}/{name}.md"


def doc_path(store: str, project: str, kind: str, name: str) -> str:
    return os.path.join(store, doc_rel(project, kind, name))


def check_target(project: str, kind: str, name: str) -> str | None:
    return valid_project(project) or (None if kind in KINDS else f"kind 는 {' | '.join(KINDS)} 중 하나") or valid_name(name)


# ---------------------------------------------------------------- 매니페스트
def load_manifest(store: str) -> dict:
    """`<store>/manifest.toml` 의 `[projects.<이름>]` 표. 없으면 빈 표."""
    p = os.path.join(store, "manifest.toml")
    try:
        with open(p, "rb") as f:
            d = tomllib.load(f)
    except FileNotFoundError:
        return {}
    return d.get("projects", {})


def resolve_project(manifest: dict, project: str | None = None, repo_url: str | None = None) -> tuple[str | None, str | None]:
    """(프로젝트, 오류). 명시한 이름 → 없으면 repo_url 과 일치하는 매니페스트 항목. 추측하지 않는다."""
    if project:
        if project in manifest:
            return project, None
        return None, f"프로젝트 {project!r} 가 매니페스트에 없다(등록된 것: {', '.join(sorted(manifest)) or '없음'})"
    if repo_url:
        for name, m in manifest.items():
            if m.get("repo_url") == repo_url:
                return name, None
    return None, f"프로젝트를 알 수 없다 — `--project <이름>` 을 준다(등록된 것: {', '.join(sorted(manifest)) or '없음'})"


# ---------------------------------------------------------------- 머리말
def default_meta() -> dict:
    return {"status": "active", "scope": "unknown", "state": "unknown", "adopted_to": "", "provenance": "", "env_dependent": "unknown",
            "source_of_truth": "file", "origin_path": "", "updated_host": "", "updated_at": ""}


def split_header(text: str) -> tuple[dict | None, str]:
    """(머리말 dict 또는 None, 본문). 머리말이 없으면 None 과 전체 본문."""
    if not text.startswith(HDR_OPEN):
        return None, text
    end = text.find("\n" + HDR_CLOSE, len(HDR_OPEN) - 1)
    if end < 0:
        return None, text
    meta = {}
    for line in text[len(HDR_OPEN):end + 1].splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            meta[k.strip()] = v.strip()
        elif line.endswith(":"):
            meta[line[:-1].strip()] = ""
    return meta, text[end + 1 + len(HDR_CLOSE):]


def render_header(meta: dict) -> str:
    m = {**default_meta(), **{k: v for k, v in meta.items() if k in FIELD_ORDER}}
    return HDR_OPEN + "".join(f"{k}: {str(m[k]).replace(chr(10), ' ')}\n" for k in FIELD_ORDER) + HDR_CLOSE


def validate_meta(meta: dict) -> list[str]:
    bad = []
    for k, allowed in CHOICES.items():
        if k in meta and meta[k] not in allowed:
            bad.append(f"{k}: {meta[k]!r} (가능한 값: {' | '.join(allowed)})")
    for k in meta:
        if k not in FIELD_ORDER:
            bad.append(f"알 수 없는 칸: {k}")
    return bad


def compose(meta: dict | None, body: str) -> str:
    return render_header(meta or {}) + body


# ---------------------------------------------------------------- 문서 읽기
def read_text(path: str, max_bytes: int = MAX_BYTES) -> tuple[str | None, str | None]:
    """(본문, None) 또는 (None, 건너뛴 이유). 이진·너무 큰·빈 파일은 문서로 보지 않는다."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return None, f"읽을 수 없음({e.strerror})"
    if size == 0:
        return None, "빈 파일"
    if size > max_bytes:
        return None, f"{size:,}바이트 > 한도 {max_bytes:,}"
    raw = open(path, "rb").read()
    if b"\x00" in raw:
        return None, "이진 파일"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "UTF-8 이 아님(이진 파일)"


def read_doc(store: str, project: str, kind: str, name: str) -> dict | None:
    p = doc_path(store, project, kind, name)
    text, _ = read_text(p)
    if text is None:
        return None
    meta, body = split_header(text)
    return {"path": p, "text": text, "meta": meta or default_meta(), "has_header": meta is not None, "body": body, "hash": sha(text)}


def iter_docs(store: str, project: str, kind: str | None = None):
    """(kind, name, 경로) — 정렬된 순서. 숨김 폴더·_inbox 는 건너뛴다."""
    for k in ([kind] if kind else KINDS):
        base = os.path.join(store, project, k)
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for f in sorted(files):
                if f.endswith(".md") and not f.startswith("."):
                    rel = os.path.relpath(os.path.join(root, f), base).replace(os.sep, "/")[:-3]
                    yield k, rel, os.path.join(root, f)


def list_docs(store: str, project: str, kind: str | None = None, status: str | None = None, prefix: str | None = None) -> list[dict]:
    rows = []
    for k, name, p in iter_docs(store, project, kind):
        if prefix and not name.startswith(prefix):
            continue
        text, _ = read_text(p)
        if text is None:
            continue
        meta, body = split_header(text)
        meta = meta or default_meta()
        if status and meta.get("status") != status:
            continue
        rows.append({"project": project, "kind": k, "name": name, "status": meta.get("status", "unknown"), "chars": len(body),
                     "state": meta.get("state", "unknown"), "hash": sha(text), "path": p})
    return rows


def snippet(body: str, term: str, width: int = 60) -> str:
    i = body.lower().find(term.lower())
    if i < 0:
        return ""
    a, b = max(0, i - width), min(len(body), i + len(term) + width)
    return ("…" if a else "") + body[a:b].replace("\n", " ") + ("…" if b < len(body) else "")


def find_docs(store: str, project: str, term: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    out = []
    t = term.lower()
    for k, name, p in iter_docs(store, project, kind):
        text, _ = read_text(p)
        if text is None:
            continue
        meta, body = split_header(text)
        if t in body.lower() or t in name.lower():
            out.append({"project": project, "kind": k, "name": name, "status": (meta or {}).get("status", "unknown"), "snippet": snippet(body, term)})
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------- 읽기 뷰
def view_root(views: str, session: str) -> str:
    return os.path.join(views, session)


def _load_base(root: str) -> dict:
    try:
        return json.load(open(os.path.join(root, BASE_FILE)))
    except (OSError, ValueError):
        return {}


def _save_base(root: str, base: dict) -> None:
    os.makedirs(root, exist_ok=True)
    tmp = os.path.join(root, BASE_FILE + ".tmp")
    json.dump(base, open(tmp, "w"), ensure_ascii=False, sort_keys=True, indent=0)
    os.replace(tmp, os.path.join(root, BASE_FILE))


def _copy_in(src: str, dst: str) -> None:
    """원본 → 뷰 복사: 임시 이름으로 복사해 0444 로 만들고 rename(블록 공유가 되면 reflink, 아니면 일반 복사로 폴백)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".ctx-tmp"
    r = subprocess.run(["cp", "--reflink=auto", "--", src, tmp], capture_output=True)
    if r.returncode != 0:
        shutil.copyfile(src, tmp)
    os.chmod(tmp, 0o444)
    os.replace(tmp, dst)


def modified_in_view(root: str) -> list[tuple[str, str]]:
    """[(뷰 상대 경로, 'modified'|'deleted')] — 기준 해시와 다른 파일."""
    out = []
    for rel, h in sorted(_load_base(root).items()):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            out.append((rel, "deleted"))
        elif file_hash(p) != h:
            out.append((rel, "modified"))
    return out


def _preserve_modified(root: str, rel: str) -> str:
    """직접 고친 뷰 파일은 덮어쓰기 전에 `.ctx-rejected/` 로 옮겨 잃지 않게 한다."""
    p = os.path.join(root, rel)
    dst = os.path.join(root, REJECTED_DIR, f"{rel}.{time.strftime('%Y%m%dT%H%M%S')}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copyfile(p, dst)
        os.chmod(dst, 0o644)
    except OSError:
        pass
    return dst


def build_view(store: str, views: str, session: str, project: str, kind: str | None = None, names: list[str] | None = None, pid: int | None = None) -> dict:
    """세션의 뷰를 만들거나 갱신한다(멱등). 새 해시를 `.ctx-base.json` 에 **먼저** 기록한 뒤 파일을 교체해 감시가 자기 갱신을 직접 수정으로 오인하지 않게 한다.
    직접 수정된 뷰 파일은 `.ctx-rejected/` 로 보관한 뒤 원본으로 되돌린다. 돌려주는 값: root·copied·kept(되돌린 직접 수정)·docs."""
    root = view_root(views, session)
    os.makedirs(root, exist_ok=True)
    base = _load_base(root)
    copied, restored, docs = [], [], []
    for k, name, src in iter_docs(store, project, kind):
        if names and name not in names:
            continue
        rel = doc_rel(project, k, name)
        sh = file_hash(src)
        dst = os.path.join(root, rel)
        cur = file_hash(dst)
        docs.append(rel)
        if cur == sh and base.get(rel) == sh:
            continue
        if cur is not None and base.get(rel) is not None and cur != base.get(rel):
            _preserve_modified(root, rel)
            restored.append(rel)
        base[rel] = sh
        _save_base(root, base)
        _copy_in(src, dst)
        copied.append(rel)
    _save_base(root, base)
    index = ["# ctx 문서 뷰 (읽기 전용 — 고치려면 `donghans ctx doc propose`)", f"프로젝트 {project} · 세션 {session}", ""]
    for rel in sorted(base):
        if rel.startswith(project + "/"):
            index.append(f"- {rel}")
    tmp = os.path.join(root, "INDEX.md.ctx-tmp")
    open(tmp, "w").write("\n".join(index) + "\n")
    os.replace(tmp, os.path.join(root, "INDEX.md"))
    if pid:
        open(os.path.join(root, PID_FILE), "w").write(str(pid))
    clear_ended(views, session)
    return {"root": root, "copied": copied, "restored": restored, "docs": docs}


def ensure_in_view(store: str, views: str, session: str, project: str, kind: str, name: str) -> str | None:
    """문서 하나를 뷰에 넣고(이미 있으면 갱신) 기준 해시를 돌려준다 — `read` 가 쓴다(읽은 판을 기록해야 propose 가 충돌을 잡는다)."""
    r = build_view(store, views, session, project, kind, [name])
    return _load_base(r["root"]).get(doc_rel(project, kind, name))


def base_hash_for(views: str, session: str, project: str, kind: str, name: str) -> str | None:
    return _load_base(view_root(views, session)).get(doc_rel(project, kind, name))


def mark_ended(views: str, session: str) -> None:
    root = view_root(views, session)
    if os.path.isdir(root):
        open(os.path.join(root, ENDED_FILE), "w").write(str(int(time.time())))


def clear_ended(views: str, session: str) -> None:
    try:
        os.remove(os.path.join(view_root(views, session), ENDED_FILE))
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cleanup_views(views: str, now: float | None = None, max_age_days: float = 7.0) -> list[str]:
    """끝난 세션(종료 표식)의 뷰, 또는 마지막 접근이 오래됐고 세션 프로세스가 죽은 뷰를 지운다. 지운 세션 ID 목록."""
    now = now or time.time()
    gone = []
    try:
        sessions = sorted(os.listdir(views))
    except OSError:
        return gone
    for sid in sessions:
        root = os.path.join(views, sid)
        if not os.path.isdir(root):
            continue
        ended = os.path.exists(os.path.join(root, ENDED_FILE))
        try:
            pid = int(open(os.path.join(root, PID_FILE)).read().strip())
        except (OSError, ValueError):
            pid = 0
        alive = bool(pid) and _pid_alive(pid)
        try:
            age = now - os.path.getmtime(os.path.join(root, BASE_FILE))
        except OSError:
            age = now - os.path.getmtime(root)
        if (ended and not alive) or (age > max_age_days * 86400 and not alive):
            for r, d, f in os.walk(root):
                for x in d:
                    os.chmod(os.path.join(r, x), 0o755)
            shutil.rmtree(root, ignore_errors=True)
            gone.append(sid)
    return gone


# ---------------------------------------------------------------- 제안(인박스)
def inbox_dir(store: str) -> str:
    return os.path.join(store, "_inbox")


def _stamp() -> str:
    t = time.time()
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)) + f"{int((t % 1) * 1000):03d}Z"


def parse_proposal(text: str) -> tuple[dict | None, str]:
    if not text.startswith(PROP_OPEN):
        return None, text
    end = text.find("\n" + HDR_CLOSE, len(PROP_OPEN) - 1)
    if end < 0:
        return None, text
    meta = {}
    for line in text[len(PROP_OPEN):end + 1].splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            meta[k.strip()] = v.strip()
    return meta, text[end + 1 + len(HDR_CLOSE):]


def pending_proposals(store: str, session: str | None = None, target: str | None = None, include_invalid: bool = False) -> list[dict]:
    """대기 중인 제안. include_invalid 면 머리말이 깨진 파일도 담는다(동기화 담당이 거부 처리할 수 있게)."""
    out = []
    ib = inbox_dir(store)
    try:
        sessions = [session] if session else sorted(d for d in os.listdir(ib) if not d.startswith("_"))
    except OSError:
        return out
    for sid in sessions:
        d = os.path.join(ib, sid)
        try:
            files = sorted(f for f in os.listdir(d) if f.endswith(".proposal.md"))
        except OSError:
            continue
        for f in files:
            text, _ = read_text(os.path.join(d, f))
            meta, _b = parse_proposal(text or "")
            if meta and (not target or meta.get("target") == target):
                out.append({"id": f[:-len(".proposal.md")], "path": os.path.join(d, f), "session": sid, **meta})
            elif not meta and include_invalid and not target:
                out.append({"id": f[:-len(".proposal.md")], "path": os.path.join(d, f), "session": sid})
    return out


def propose(store: str, session: str, host: str, project: str, kind: str, name: str, body: str, base_hash: str | None) -> tuple[int, str, str | None]:
    """제안을 인박스에 남긴다. (결과코드, 메시지, 제안 id). 저장소 문서는 건드리지 않는다.
    base_hash: 에이전트가 읽은 판의 해시(뷰의 .ctx-base.json), 새 문서면 None. 문서가 이미 있는데 base 가 없으면 거부한다(먼저 읽어야 한다)."""
    why = check_target(project, kind, name)
    if why:
        return 1, why, None
    if not body.strip():
        return 1, "빈 본문은 제안하지 않는다", None
    if len(body.encode()) > MAX_BYTES:
        return 1, f"본문이 한도({MAX_BYTES:,}바이트)를 넘는다", None
    exists = os.path.exists(doc_path(store, project, kind, name))
    if exists and not base_hash:
        return 1, f"{kind}/{name}: 이미 있는 문서다 — 먼저 `donghans ctx doc read|path` 로 읽어 판을 기록한다(읽지 않은 판에 덮어쓰지 않는다)", None
    if not exists and base_hash:
        return 1, f"{kind}/{name}: 읽은 뒤 문서가 사라졌다 — 새 문서면 base 없이 제안한다", None
    target = f"{project}/{kind}/{name}"
    if pending_proposals(store, session, target):
        return 1, f"{target}: 이 세션의 이전 제안이 아직 처리 중이다 — 기다리거나 `donghans ctx doc status` 로 확인한다", None
    pid = f"{_stamp()}-{project}-{kind}-{name.replace('/', '__')}"
    d = os.path.join(inbox_dir(store), session)
    os.makedirs(d, exist_ok=True)
    head = PROP_OPEN + f"target: {target}\nbase_hash: {base_hash or 'none'}\nsession: {session}\nhost: {host}\ncreated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n" + HDR_CLOSE
    tmp = os.path.join(d, f".{pid}.tmp")
    open(tmp, "w").write(head + body)
    os.replace(tmp, os.path.join(d, pid + ".proposal.md"))   # 완성된 파일만 보이게(감시가 반쯤 쓴 파일을 읽지 않게)
    return 0, f"{target}: 제안을 남겼다(대기 중)", pid


def _notice(store: str, session: str, line: str) -> None:
    d = os.path.join(inbox_dir(store), "_notices")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, session + ".log"), "a").write(f"{time.strftime('%F %T')} {line}\n")


def _result(store: str, pid: str, status: str, msg: str, commit: str | None = None) -> None:
    d = os.path.join(inbox_dir(store), "_results")
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{pid}.tmp")
    json.dump({"status": status, "msg": msg, "commit": commit}, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, os.path.join(d, pid + ".json"))


def wait_result(store: str, pid: str, timeout: float = 10.0) -> dict | None:
    p = os.path.join(inbox_dir(store), "_results", pid + ".json")
    end = time.time() + timeout
    while time.time() < end:
        try:
            return json.load(open(p))
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


def session_status(store: str, session: str) -> dict:
    """세션의 대기·충돌·거부 제안 수와 알림 줄."""
    ib = inbox_dir(store)
    cnt = {"pending": len(pending_proposals(store, session)), "conflict": 0, "rejected": 0}
    for key, sub in (("conflict", "_conflicts"), ("rejected", "_rejected")):
        try:
            cnt[key] = len([f for f in os.listdir(os.path.join(ib, sub, session)) if f.endswith(".proposal.md")])
        except OSError:
            pass
    try:
        notes = open(os.path.join(ib, "_notices", session + ".log")).read().splitlines()[-10:]
    except OSError:
        notes = []
    return {**cnt, "notices": notes}


# ---------------------------------------------------------------- 동기화 담당
def _git(proj_dir: str, *args: str, check: bool = True):
    return subprocess.run(["git", "-C", proj_dir, "-c", "user.name=ctx-sync", "-c", "user.email=ctx-sync@localhost", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=check)


def ensure_repo(proj_dir: str) -> None:
    os.makedirs(proj_dir, exist_ok=True)
    if not os.path.isdir(os.path.join(proj_dir, ".git")):
        _git(proj_dir, "init", "-q", "-b", "main")


def commit_file(store: str, project: str, rel_in_project: str, msg: str) -> str | None:
    pd = os.path.join(store, project)
    ensure_repo(pd)
    _git(pd, "add", "--", rel_in_project)
    r = _git(pd, "commit", "-q", "-m", msg, "--", rel_in_project, check=False)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        raise RuntimeError(f"git commit 실패: {r.stderr.strip() or r.stdout.strip()}")
    return _git(pd, "rev-parse", "--short", "HEAD").stdout.strip() or None


class _Lock:
    """저장소 쓰기 직렬화(커밋까지만 — push 는 락 밖)."""
    def __init__(self, store: str):
        os.makedirs(store, exist_ok=True)
        self.f = open(os.path.join(store, ".sync.lock"), "w")

    def __enter__(self):
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _move_aside(store: str, path: str, sub: str, session: str, reason: str) -> None:
    d = os.path.join(inbox_dir(store), sub, session)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(path))
    os.replace(path, dst)
    open(dst + ".reason", "w").write(reason + "\n")


def process_proposal(store: str, path: str, masker=None, manifest: dict | None = None) -> tuple[str, str, str | None]:
    """제안 파일 하나를 검사해 적용한다. (결과, 메시지, 커밋) — 결과: applied · same · conflict · rejected.
    검사 순서: 형식 → 프로젝트 → 읽은 판(base_hash) → 머리말 → 비밀. 통과하면 쓰고 커밋한다."""
    pid = os.path.basename(path)[:-len(".proposal.md")]
    session = os.path.basename(os.path.dirname(path))

    def done(status, msg, commit=None, aside=None):
        if aside:
            _move_aside(store, path, aside, session, msg)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
        _result(store, pid, status, msg, commit)
        if status in ("conflict", "rejected"):
            _notice(store, session, f"{status}: {msg}")
        return status, msg, commit

    text, why = read_text(path)
    if text is None:
        return done("rejected", f"제안을 읽을 수 없다: {why}", aside="_rejected")
    meta, body = parse_proposal(text)
    if not meta or "target" not in meta:
        return done("rejected", "제안 머리말이 없거나 target 이 없다", aside="_rejected")
    parts = meta["target"].split("/", 2)
    if len(parts) != 3:
        return done("rejected", f"target 형식이 올바르지 않다: {meta['target']}", aside="_rejected")
    project, kind, name = parts
    why = check_target(project, kind, name)
    if why:
        return done("rejected", f"{meta['target']}: {why}", aside="_rejected")
    manifest = load_manifest(store) if manifest is None else manifest
    if project not in manifest:
        return done("rejected", f"프로젝트 {project!r} 가 매니페스트에 없다", aside="_rejected")
    with _Lock(store):
        p = doc_path(store, project, kind, name)
        cur = read_doc(store, project, kind, name)
        base = meta.get("base_hash", "none")
        if cur is None and os.path.exists(p):
            return done("rejected", f"{meta['target']}: 현재 문서를 읽을 수 없다(이진·빈 파일)", aside="_rejected")
        if (cur is None) != (base == "none") or (cur is not None and cur["hash"] != base):
            return done("conflict", f"{meta['target']}: 읽은 뒤 문서가 바뀌었다(읽은 판 {base[:8]}, 지금 {(cur or {}).get('hash', '없음')[:8]}) — 최신본을 다시 읽고 고친다", aside="_conflicts")
        new_meta, new_body = split_header(body)
        if new_meta is None:
            new_meta = dict(cur["meta"]) if cur else default_meta()
            new_body = body
        else:
            problems = validate_meta(new_meta)
            if problems:
                return done("rejected", f"{meta['target']}: 머리말이 올바르지 않다 — " + "; ".join(problems), aside="_rejected")
        if not new_body.strip():
            return done("rejected", f"{meta['target']}: 빈 본문", aside="_rejected")
        new_meta = {**default_meta(), **new_meta, "updated_host": meta.get("host", ""), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if cur is None and not new_meta.get("provenance"):
            new_meta["provenance"] = f"제안 {meta.get('session', '')[:8]}@{meta.get('host', '')}"
        full = compose(new_meta, new_body)
        if masker is not None and masker.text(full) != full:
            return done("rejected", f"{meta['target']}: 본문에 등록된 비밀 값이 들어 있어 올리지 않는다 — 비밀은 `donghans secret` 으로 두고 문서에는 이름만 적는다", aside="_rejected")
        if cur is not None and new_body == cur["body"] and {k: v for k, v in new_meta.items() if k not in ("updated_host", "updated_at")} == {k: v for k, v in cur["meta"].items() if k not in ("updated_host", "updated_at")}:
            return done("same", f"{meta['target']}: 이미 같은 내용")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".ctx-tmp"
        open(tmp, "w").write(full)
        os.replace(tmp, p)
        try:
            sha1 = commit_file(store, project, f"{kind}/{name}.md", f"ctx: {meta['target']} ({session[:8]}@{meta.get('host', '')})")
        except Exception as e:  # 커밋 실패 — 쓴 파일을 되돌려 저장소와 이력이 어긋나지 않게 한다
            if cur is not None:
                open(p, "w").write(cur["text"])
            else:
                os.remove(p)
            return done("rejected", f"{meta['target']}: 커밋 실패 — {e}", aside="_rejected")
    return done("applied", f"{meta['target']}: 반영했다", sha1)


def process_inbox(store: str, masker=None, manifest: dict | None = None) -> list[tuple[str, str, str, str | None]]:
    """인박스의 모든 제안을 타임스탬프 순으로 처리한다. [(제안 id, 결과, 메시지, 커밋)]."""
    items = pending_proposals(store, include_invalid=True)
    items.sort(key=lambda m: m["id"])
    manifest = load_manifest(store) if manifest is None else manifest
    out = []
    for m in items:
        st, msg, c = process_proposal(store, m["path"], masker, manifest)
        out.append((m["id"], st, msg, c))
    return out


def push_project(store: str, project: str, masker=None, manifest: dict | None = None) -> tuple[bool, str]:
    """매니페스트에 remote 가 있을 때만 push. push 직전에 추적 파일 전체에 비밀 검사를 하고, 걸리면 push 하지 않는다(이력에 들어간 비밀은 되돌릴 수 없다).
    비밀 검사기가 없으면(DB 에 못 붙음) fail-closed 로 거부한다. 락 밖에서 부른다."""
    manifest = load_manifest(store) if manifest is None else manifest
    remote = (manifest.get(project) or {}).get("remote", "")
    if not remote:
        return False, "remote 가 없어 push 하지 않는다"
    if masker is None:
        return False, "비밀 검사기를 못 써서(DB 연결 실패 등) push 하지 않는다"
    pd = os.path.join(store, project)
    files = _git(pd, "ls-files", check=False).stdout.splitlines()
    for rel in files:
        text, why = read_text(os.path.join(pd, rel))
        if text is None:
            if why != "빈 파일":   # 이진·너무 큰·UTF-8 이 아닌 파일은 검사할 수 없다 — 통과시키지 않는다(fail-closed)
                return False, f"{project}/{rel}: 비밀 검사를 할 수 없는 파일이라({why}) push 하지 않는다"
            continue
        if masker.text(text) != text:
            return False, f"{project}/{rel}: 등록된 비밀 값이 들어 있어 push 하지 않는다"
    if _git(pd, "remote", "get-url", "origin", check=False).returncode != 0:
        _git(pd, "remote", "add", "origin", remote)
    r = _git(pd, "push", "-q", "origin", "HEAD", check=False)
    return (r.returncode == 0), (r.stderr.strip() or "push 했다")


# ---------------------------------------------------------------- 자료 영역(files) — 문서(.md)가 아닌 증거·데이터
# `<store>/<프로젝트>/files/` 는 **별도 git 저장소**(중첩)다. 바깥 저장소는 `/files/` 를 무시하므로 바깥 저장소의 push(예: nixos → GitHub)가 자료를 보낼 수 없다.
# files 저장소에는 remote 를 두지 않는다. 문서 흐름(제안·동기화 담당)과 무관하게 서버 호스트에서 `import-files` 로만 들어온다.
FILES_DIR = "files"
FILE_MAX_BYTES = 5_000_000
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico")
TEXT_EXTS = (".md", ".txt", ".json", ".jsonl", ".log", ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".mts", ".tsx", ".jsx", ".py", ".sh",
             ".tsv", ".csv", ".yml", ".yaml", ".toml", ".xml", ".svg", ".out", ".b64", ".diff", ".patch", ".sql", ".ini", ".conf")
# 이름으로 거부(비밀·키·세션 상태) — 내용은 열지 않는다.
DENY_NAME = re.compile(r"(^\.env($|\.)|\.har$|^storageState\.json$|\.jks$|\.pem$|\.key$|\.p12$|\.keystore$|^\.npmrc$|^\.netrc$|\.sqlite3?$|\.db$|^oidc_client_secret$|"
                       r"^conversation\.log$|^client_secret.*\.json$|^id_(rsa|ed25519)|\.age$|^secrets?\.(json|ya?ml|toml)$|^key\.properties$)", re.I)
# 재생성물·도구 관리 폴더 — 이관·탐지 대상이 아니다.
REGEN_DIRS = frozenset({"node_modules", "build", "dist", ".dart_tool", ".gradle", ".next", ".nuxt", "target", ".venv", "venv", "__pycache__", "coverage", ".turbo", ".idea",
                        ".cache", ".astro", "model-cache", ".cxx", ".build", "worktrees", ".git", ".pytest_cache", ".mypy_cache", "dist-server", "ephemeral", "Pods", "DerivedData", ".symlinks", ".fvm"})
CACHE_NAMES = frozenset({"gradlew", "gradlew.bat", "gradle-wrapper.jar", "local.properties", "Generated.xcconfig", "GeneratedPluginRegistrant.h", "GeneratedPluginRegistrant.m",
                         "GeneratedPluginRegistrant.java", "flutter_export_environment.sh", ".flutter-plugins-dependencies", ".flutter-plugins",   # 도구가 만드는 파일
                         "handoffs", "donghans-instructions.md", "donghans-override.md", ".donghans-instr-state.json", "settings.local.json", "scheduled_tasks.lock",
                         "qa-extra", "resume-extra"})
SECRET_PATTERNS = re.compile(r"(ghp_[A-Za-z0-9]{20}|AKIA[0-9A-Z]{12}|BEGIN [A-Z ]*PRIVATE|xox[bp]-|\bsk-[A-Za-z0-9]{20}|AIza[0-9A-Za-z_-]{20}|Bearer\s+[A-Za-z0-9._-]{12}|"
                             r"eyJ[A-Za-z0-9_-]{10}|://[^/\s:@]+:[^@\s/]+@|(password|passwd|token|secret|api[_-]?key)[\x22']?\s*[:=]\s*[\x22']?\S{6}|(비밀번호|비번)\s*[:=]\s*\S|(비밀번호|비번)\s*[`'\x22]\S)", re.I)


def files_dir(store: str, project: str) -> str:
    return os.path.join(store, project, FILES_DIR)


def ensure_files_repo(store: str, project: str) -> str:
    """files 저장소를 만들고 바깥 저장소가 무시하게 한다. 경로를 돌려준다."""
    fd = files_dir(store, project)
    os.makedirs(fd, exist_ok=True)
    if not os.path.isdir(os.path.join(fd, ".git")):
        _git(fd, "init", "-q", "-b", "main")
    pd = os.path.join(store, project)
    ensure_repo(pd)
    gi = os.path.join(pd, ".gitignore")
    cur = open(gi).read() if os.path.exists(gi) else ""
    if "/files/" not in cur.splitlines():
        open(gi, "w").write(cur + ("" if not cur or cur.endswith("\n") else "\n") + "/files/\n")
        commit_file(store, project, ".gitignore", "ctx: files/ 는 별도 저장소(바깥 저장소가 무시)")
    return fd


def scan_text(text: str, masker=None) -> str | None:
    """텍스트에서 비밀 후보를 찾는다. 없으면 None, 있으면 이유."""
    if masker is not None and masker.text(text) != text:
        return "등록된 비밀 값이 들어 있다"
    m = SECRET_PATTERNS.search(text)
    if m:
        return f"비밀 패턴({m.group(0)[:3]}…)"
    return None


def classify_file(path: str, masker=None, max_bytes: int = FILE_MAX_BYTES) -> tuple[str, str]:
    """('ok'|'image'|'held', 이유). image 는 저장하지 않는 스크린샷, held 는 사람이 봐야 해서 건드리지 않는 파일."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if os.path.islink(path):
        return "held", "심볼릭 링크"
    if DENY_NAME.search(name):
        return "held", "비밀·키 이름"
    if ext in IMAGE_EXTS:
        return "image", "스크린샷(저장하지 않는다)"
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return "held", f"읽을 수 없음({e.strerror})"
    if size > max_bytes:
        return "held", f"{size:,}바이트 > 한도 {max_bytes:,}"
    if ext not in TEXT_EXTS:
        return "held", f"검사할 수 없는 형식({ext or '확장자 없음'})"
    raw = open(path, "rb").read()
    if b"\x00" in raw:
        return "held", "이진 내용"
    why = scan_text(raw.decode("utf-8", "replace"), masker)
    return ("held", why) if why else ("ok", "")


def walk_files(src: str):
    """src 아래 일반 파일의 (절대 경로, 상대 경로). 재생성 폴더·.git 은 들어가지 않는다."""
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in REGEN_DIRS)
        for f in sorted(files):
            p = os.path.join(root, f)
            yield p, os.path.relpath(p, src).replace(os.sep, "/")


def import_files(store: str, project: str, src: str, dest: str = "", masker=None, dry_run: bool = False, max_bytes: int = FILE_MAX_BYTES) -> dict:
    """src 폴더의 파일을 `<project>/files/<dest>/<상대경로>` 로 복사하고 files 저장소에 한 번 커밋한다. 원본은 건드리지 않는다.
    반환: imported · same · images · held(각 [(상대경로, 이유)]) · commit. dry_run 이면 쓰지 않는다."""
    if dest and (dest.startswith("/") or any(p in ("", "..", ".") for p in dest.split("/"))):
        raise ValueError("dest 는 `..`·절대 경로·빈 칸을 쓸 수 없다")
    rep = {"imported": [], "same": [], "images": [], "held": [], "commit": None}
    fd = files_dir(store, project)
    plan = []
    for p, rel in walk_files(src):
        kind, why = classify_file(p, masker, max_bytes)
        if kind == "image":
            rep["images"].append((rel, why)); continue
        if kind == "held":
            rep["held"].append((rel, why)); continue
        tgt = os.path.join(fd, dest, rel) if dest else os.path.join(fd, rel)
        if os.path.exists(tgt) and file_hash(tgt) == file_hash(p):
            rep["same"].append((rel, "")); continue
        rep["imported"].append((rel, "")); plan.append((p, tgt))
    if dry_run or not plan:
        return rep
    with _Lock(store):
        ensure_files_repo(store, project)
        for p, tgt in plan:
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            shutil.copyfile(p, tgt)
        _git(fd, "add", "-A")
        r = _git(fd, "commit", "-q", "-m", f"ctx files: {dest or '.'} 에서 {len(plan)}개 가져옴", check=False)
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            raise RuntimeError(f"git commit 실패: {r.stderr.strip() or r.stdout.strip()}")
        rep["commit"] = _git(fd, "rev-parse", "--short", "HEAD").stdout.strip() or None
    return rep


def list_files(store: str, project: str, prefix: str = "") -> list[tuple[str, int]]:
    fd = files_dir(store, project)
    out = []
    for p, rel in walk_files(fd):
        if rel.startswith(prefix):
            out.append((rel, os.path.getsize(p)))
    return out


def ctx_body_hashes(store: str, project: str) -> set[str]:
    """ctx 문서(모든 종류)의 본문 해시(머리말 제외) — 원본 파일이 이미 ctx 에 있는지 대조하는 열쇠."""
    out = set()
    for _k, _n, p in iter_docs(store, project):
        text, _ = read_text(p)
        if text is not None:
            out.add(sha(split_header(text)[1]))
    return out


def audit_project(store: str, project: str, root: str, extra: tuple[str, ...] = (), skip: tuple[str, ...] = ()) -> dict:
    """프로젝트 폴더(root)의 **git 이 무시하는 비재생성 파일** 중 ctx 에 없는 것을 찾는다(읽기 전용).
    md 는 본문 해시가 ctx 문서에 있으면, 그 밖은 `files/<root 기준 경로>` 가 같은 바이트로 있으면 「있음」. 스크린샷(이미지)은 따로 센다."""
    bodies = ctx_body_hashes(store, project)
    fd = files_dir(store, project)
    r = subprocess.run(["git", "-C", root, "status", "--ignored=traditional", "--porcelain", "-z"], capture_output=True, text=True)
    cands = []
    for rec in r.stdout.split("\0"):
        if rec.startswith("!! "):
            cands.append(rec[3:])
    res = {"present": 0, "missing": [], "images": 0, "held": [], "skipped": 0}

    def visit(abs_p: str, rel: str):
        name = os.path.basename(rel.rstrip("/"))
        if name in REGEN_DIRS or name in CACHE_NAMES or any(rel.rstrip("/") == sk or rel.startswith(sk.rstrip("/") + "/") for sk in skip):
            res["skipped"] += 1; return
        if os.path.isdir(abs_p) and not os.path.islink(abs_p):
            try:
                entries = sorted(os.listdir(abs_p))
            except OSError:   # 권한이 없는 폴더(예: 컨테이너 데이터)는 건너뛴다
                res["skipped"] += 1; return
            for e in entries:
                visit(os.path.join(abs_p, e), rel.rstrip("/") + "/" + e)
            return
        try:
            kind, why = classify_file(abs_p, None)
        except OSError:
            res["skipped"] += 1; return
        if kind == "image":
            res["images"] += 1; return
        if kind == "held" and (DENY_NAME.search(name) or why == "심볼릭 링크"):
            res["skipped"] += 1; return
        if name.endswith(".md"):
            text, _ = read_text(abs_p)
            if text is not None and sha(text) in bodies:
                res["present"] += 1; return
        else:
            tgt = os.path.join(fd, rel)
            if os.path.exists(tgt) and file_hash(tgt) == file_hash(abs_p):
                res["present"] += 1; return
        (res["held"] if kind == "held" else res["missing"]).append(rel if kind != "held" else f"{rel} ({why})")

    for c in cands:
        visit(os.path.join(root, c), c)
    for e in extra:
        if os.path.exists(e):
            visit(e, os.path.relpath(e, root) if e.startswith(root) else e)
    return res


# ---------------------------------------------------------------- inotify (ctypes — 외부 의존성 없이)
IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE = 0x2, 0x4, 0x8, 0x40, 0x80, 0x100, 0x200
IN_ISDIR = 0x40000000


class Inotify:
    def __init__(self):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 실패")
        self.wd: dict[int, str] = {}

    def add(self, path: str, mask: int) -> bool:
        w = self.libc.inotify_add_watch(self.fd, path.encode(), mask)
        if w < 0:
            return False
        self.wd[w] = path
        return True

    def read(self, timeout: float) -> list[tuple[str, int]]:
        """[(경로, 마스크)] — 시간 초과면 빈 목록."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return []
        out, i = [], 0
        while i + 16 <= len(data):
            wd, mask, _cookie, ln = struct.unpack_from("iIII", data, i)
            name = data[i + 16:i + 16 + ln].split(b"\0", 1)[0].decode(errors="replace")
            base = self.wd.get(wd)
            if base is not None:
                out.append((os.path.join(base, name) if name else base, mask))
            i += 16 + ln
        return out

    def close(self):
        os.close(self.fd)


def _view_dirs(root: str):
    for r, dirs, _f in os.walk(root):
        dirs[:] = [d for d in dirs if d != REJECTED_DIR]
        yield r


def watch_view(root: str, emit, pid: int | None = None, stop=None, poll: float = 1.0, debounce: float = 0.3) -> int:
    """세션 뷰를 inotify 로 지켜보다 직접 수정(기준 해시와 다름)이 생기면 emit(줄)을 부른다. 끝나는 때: 종료 표식·세션 프로세스(pid) 사망·stop() 참.
    같은 파일을 연달아 알리지 않는다(내용이 바뀐 해시가 이미 알린 것과 같으면 건너뜀)."""
    ino = Inotify()
    mask = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_ATTRIB | IN_MODIFY
    for d in _view_dirs(root):
        ino.add(d, mask)
    told: dict[str, str | None] = {}
    last_check = 0.0
    dirty = False
    try:
        while True:
            if stop and stop():
                return 0
            if os.path.exists(os.path.join(root, ENDED_FILE)):
                return 0
            if pid and not _pid_alive(pid):
                return 0
            for path, m in ino.read(poll):
                if m & IN_ISDIR and m & IN_CREATE:
                    for d in _view_dirs(path):
                        ino.add(d, mask)
                if REJECTED_DIR in path.split(os.sep) or path.endswith((".ctx-tmp", ".tmp")):
                    continue
                dirty = True
                last_check = time.time()
            if dirty and time.time() - last_check >= debounce:
                dirty = False
                for rel, kind in modified_in_view(root):
                    cur = file_hash(os.path.join(root, rel))
                    if told.get(rel) == (cur or "deleted"):
                        continue
                    told[rel] = cur or "deleted"
                    emit(f"[ctx 뷰] {rel} 이(가) {'직접 수정됨' if kind == 'modified' else '삭제됨'} — 뷰는 읽기 전용이다. 고치려면 `donghans ctx doc propose` 를 쓴다(뷰를 다시 만들면 원본으로 되돌아간다)")
    finally:
        ino.close()


def watch_inbox(store: str, handle, stop=None, poll: float = 30.0) -> None:
    """동기화 담당의 본체 반복: 인박스를 inotify 로 지켜보다(+주기 점검) 제안이 오면 handle() 을 부른다."""
    ib = inbox_dir(store)
    os.makedirs(ib, exist_ok=True)
    ino = Inotify()
    mask = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
    ino.add(ib, mask)
    for d in os.listdir(ib):
        if not d.startswith("_") and os.path.isdir(os.path.join(ib, d)):
            ino.add(os.path.join(ib, d), mask)
    handle()
    try:
        while not (stop and stop()):
            evs = ino.read(poll)
            for path, m in evs:
                if m & IN_ISDIR and m & IN_CREATE and not os.path.basename(path).startswith("_"):
                    ino.add(path, mask)
            handle()
    finally:
        ino.close()
