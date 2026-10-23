#!/usr/bin/env python3
"""ctx_instr — 프로젝트별 지침(`.claude/donghans-instructions.md`·`donghans-override.md`)을 ctx DB 로 공유한다.

설계(사용자 결정 2026-10-23 · 동기): 지침 파일은 추적 제외라 **그 컴퓨터 디스크에만** 있었다. DB(`project_instructions`)를 정본으로 두고
로컬 파일은 **캐시**로 만든다 — `claude` 래퍼의 SessionStart 훅이 `sync` 를 돌려 파일이 없거나 낡았으면 DB 본문으로 채우고
`.git/info/exclude` 도 맞춘다. 그래서 읽는 쪽(`donghans-resume`·`donghans-qa` 스킬)은 **바뀐 것이 없다** — 늘 같은 경로의 파일을 읽는다.

규칙(어긋나는 것을 막는 핵심):
  - 동기화는 마지막 동기화 상태(rev·sha, `.claude/.donghans-instr-state.json`)와 비교한다. **로컬이 손대지 않았으면** DB 가 이긴다(덮어씀).
  - **로컬을 고쳤고 DB 는 그대로면** `ahead` — 훅은 절대 DB 로 밀어 올리지 않는다(`donghans instr push` 로 사람이·에이전트가 명시적으로).
  - **둘 다 바뀌었거나 상태 기록이 없는 기존 파일이 DB 와 다르면** `conflict` — 어느 쪽도 덮지 않는다. `diff` → `push --force`/`pull --force`.
  - **DB 에 행이 없고 로컬 파일이 있으면** 첫 채택(`adopt`)으로 올린다(덮을 것이 없다).
  - 올릴 때 본문에 **등록된 비밀 값**이 들어 있으면 거부한다.
  - 실행 파일(`qa-extra`·`resume-extra`)은 동기화하지 않는다 — DB 에서 받은 코드를 실행하는 구조가 되기 때문이다.
순수 판정(`plan`)은 DB 없이 시험한다.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess

NAMES = {"instructions": "donghans-instructions.md", "override": "donghans-override.md"}
STATE_FILE = ".donghans-instr-state.json"
EXCLUDE = [f".claude/{n}" for n in NAMES.values()] + [f".claude/{STATE_FILE}"]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def plan(local: str | None, st: dict | None, db: dict | None) -> str:
    """local: 로컬 본문 | None, st: 마지막 동기화 {'rev','sha'} | None, db: {'rev','body'} | None → 행동.
    noop · adopt(DB 에 올림) · write(DB→로컬) · record(같다 — 상태만 갱신) · ahead(로컬이 앞섬) · conflict(양쪽 변경)"""
    if db is None:
        return "noop" if local is None else "adopt"
    if local is None:
        return "write"
    if sha(local) == sha(db["body"]):
        return "record" if not st or st.get("rev") != db["rev"] or st.get("sha") != sha(local) else "noop"
    if st and sha(local) == st.get("sha"):
        return "write"            # 로컬은 손대지 않았고 DB 가 달라졌다
    if st and st.get("rev") == db["rev"]:
        return "ahead"            # 로컬만 고쳤다
    return "conflict"


def _git(cwd, *a):
    try:
        r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def roots(cwd):
    """(메인 체크아웃 루트, 공통 .git 디렉터리) — 추적 제외 파일은 메인 체크아웃에만 둔다(워크트리 공통). git 저장소가 아니면 None."""
    if not cwd or not os.path.isdir(cwd):
        return None
    top = _git(cwd, "rev-parse", "--show-toplevel")
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not top or not common:
        return None
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else top
    return main, common


def ensure_excluded(common: str) -> bool:
    """`.git/info/exclude` 에 지침 파일·상태 파일을 없는 것만 추가한다. 바꿨으면 True."""
    path = os.path.join(common, "info", "exclude")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    have = open(path).read() if os.path.exists(path) else ""
    missing = [l for l in EXCLUDE if l not in have.splitlines()]
    if not missing:
        return False
    with open(path, "a") as f:
        f.write(("" if have.endswith("\n") or not have else "\n") + "\n".join(missing) + "\n")
    return True


def _state_path(main):
    return os.path.join(main, ".claude", STATE_FILE)


def load_state(main) -> dict:
    try:
        return json.load(open(_state_path(main)))
    except Exception:
        return {}


def save_state(main, state):
    os.makedirs(os.path.join(main, ".claude"), exist_ok=True)
    tmp = _state_path(main) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, _state_path(main))


def local_path(main, name):
    return os.path.join(main, ".claude", NAMES[name])


def read_local(main, name):
    p = local_path(main, name)
    return open(p, errors="ignore").read() if os.path.isfile(p) else None


def write_local(main, name, text):
    p = local_path(main, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, p)


def db_rows(conn, repo_url) -> dict:
    cur = conn.execute("SELECT name, rev, body FROM project_instructions WHERE repo_url=%s", (repo_url,))
    return {n: {"rev": r, "body": b} for n, r, b in cur.fetchall()}


def _insert(conn, repo_url, name, body, host):
    conn.execute("INSERT INTO project_instructions (repo_url, name, body, rev, updated_host) VALUES (%s,%s,%s,1,%s)", (repo_url, name, body, host))
    return 1


def _update(conn, repo_url, name, body, host, expect_rev):
    cur = conn.execute("UPDATE project_instructions SET body=%s, rev=rev+1, updated_host=%s, updated_at=now() WHERE repo_url=%s AND name=%s AND rev=%s RETURNING rev",
                       (body, host, repo_url, name, expect_rev))
    row = cur.fetchone()
    return row[0] if row else None


def sync(conn, repo_url, main, common, host, adopt=True):
    """SessionStart 훅·`instr sync` 가 쓰는 한 번의 동기화. 알릴 것(앞섬·충돌)을 [(name, kind, 메시지)] 로 돌려준다. 절대 DB 를 덮어쓰지 않는다(adopt 는 빈 자리에만)."""
    notices = []
    rows = db_rows(conn, repo_url)
    state = load_state(main)
    touched = False
    for name in NAMES:
        local, st, db = read_local(main, name), state.get(name), rows.get(name)
        act = plan(local, st, db)
        if act == "write":
            write_local(main, name, db["body"]); state[name] = {"rev": db["rev"], "sha": sha(db["body"])}; touched = True
            notices.append((name, "updated", f"{NAMES[name]} 를 공유 저장소 rev {db['rev']} 로 갱신했다"))
        elif act == "record":
            state[name] = {"rev": db["rev"], "sha": sha(local)}; touched = True
        elif act == "adopt" and adopt:
            _insert(conn, repo_url, name, local, host); state[name] = {"rev": 1, "sha": sha(local)}; touched = True
            notices.append((name, "adopted", f"{NAMES[name]} 를 공유 저장소에 처음 올렸다(rev 1)"))
        elif act == "ahead":
            notices.append((name, "ahead", f"{NAMES[name]} 가 공유 저장소보다 새롭다 — `donghans instr push {name}` 로 올려야 다른 기기에 반영된다"))
        elif act == "conflict":
            notices.append((name, "conflict", f"{NAMES[name]} 가 공유 저장소와 다르고 어느 쪽이 최신인지 알 수 없다 — `donghans instr diff {name}` 로 확인 뒤 `push --force`/`pull --force`"))
    if any(n for n in NAMES if read_local(main, n) is not None):
        ensure_excluded(common)
    if touched:
        save_state(main, state)
    return notices


def push(conn, repo_url, main, name, host, force=False, masker=None):
    """로컬 → DB. (결과코드, 메시지). 0=올림/이미 같음, 1=거부."""
    local = read_local(main, name)
    if local is None:
        return 1, f"로컬 {NAMES[name]} 가 없다"
    if masker is not None and masker.text(local) != local:
        return 1, "본문에 등록된 비밀 값이 들어 있어 올리지 않는다 — 비밀은 `donghans secret` 으로 두고 지침에는 이름만 적는다"
    state = load_state(main)
    db = db_rows(conn, repo_url).get(name)
    if db is None:
        rev = _insert(conn, repo_url, name, local, host)
    elif sha(local) == sha(db["body"]):
        state[name] = {"rev": db["rev"], "sha": sha(local)}; save_state(main, state)
        return 0, f"{name}: 이미 공유 저장소와 같다(rev {db['rev']})"
    else:
        st = state.get(name)
        if not force and not (st and st.get("rev") == db["rev"]):
            return 1, f"{name}: 공유 저장소(rev {db['rev']})가 마지막 동기화 이후 바뀌었다 — `donghans instr diff {name}` 확인 뒤 --force"
        rev = _update(conn, repo_url, name, local, host, db["rev"])
        if rev is None:
            return 1, f"{name}: 올리는 사이에 다른 기기가 먼저 바꿨다 — 다시 시도"
    state[name] = {"rev": rev, "sha": sha(local)}; save_state(main, state)
    return 0, f"{name}: 공유 저장소에 올렸다(rev {rev})"


def pull(conn, repo_url, main, name, force=False):
    db = db_rows(conn, repo_url).get(name)
    if db is None:
        return 1, f"{name}: 공유 저장소에 없다"
    local = read_local(main, name)
    state = load_state(main)
    if local is not None and sha(local) != sha(db["body"]) and not force:
        st = state.get(name)
        if not (st and sha(local) == st.get("sha")):
            return 1, f"{name}: 로컬을 고친 흔적이 있어 덮지 않는다 — `donghans instr diff {name}` 확인 뒤 --force"
    write_local(main, name, db["body"]); state[name] = {"rev": db["rev"], "sha": sha(db["body"])}; save_state(main, state)
    ensure_excluded(roots(main)[1]) if roots(main) else None
    return 0, f"{name}: 공유 저장소 rev {db['rev']} 로 갱신"


def diff_text(conn, repo_url, main, name):
    db = db_rows(conn, repo_url).get(name)
    local = read_local(main, name)
    a = (db["body"] if db else "").splitlines(keepends=True)
    b = (local or "").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, f"공유 저장소 rev {db['rev'] if db else '-'}", "로컬", n=2))
