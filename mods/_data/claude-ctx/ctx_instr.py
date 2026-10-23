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

명령 경유(사용자 결정 2026-10-23 — 읽을 때도 최신본이어야 해서 파일 직접 읽기·쓰기를 줄인다):
  - **읽기**는 `donghans instr show [--section 절]` — 먼저 동기화(최신화)하고 보여 준다. 접속 실패면 로컬 캐시를 「낡았을 수 있음」 표시와 함께 보인다.
  - **쓰기**는 `donghans instr edit|set` — DB 에 낙관적 잠금(rev)으로 먼저 쓰고 캐시를 맞춘다. 캐시 파일은 읽기 전용(0444)이라 직접 고치면 막힌다
    (우회하면 위의 `ahead`·`conflict` 로 잡힌다 — 그 판정표는 안전망으로 남는다. `push`/`pull` 도 이전 방식·복구용으로 남긴다).
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
    """캐시를 쓴다(읽기 전용으로 — 직접 편집 대신 `donghans instr edit|set`). 기존 읽기 전용 파일도 교체된다."""
    p = local_path(main, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o444)
    os.replace(tmp, p)


def lock_local(main, name):
    """DB 와 같아진 캐시 파일을 읽기 전용으로 잠근다(이미 잠겼으면 아무것도 안 한다)."""
    p = local_path(main, name)
    try:
        if os.path.isfile(p) and os.stat(p).st_mode & 0o222:
            os.chmod(p, 0o444)
    except OSError:
        pass


ROLE = {"instructions": "추가 지침 — 기본 절차에 더해 적용", "override": "오버라이드 — 충돌하는 기본 절차보다 우선"}


def split_sections(body):
    """본문을 (머리말, [절 본문…]) 으로 나눈다. 절 = `## ` 로 시작하는 줄부터 다음 `## ` 앞까지(`###` 은 절이 아님)."""
    pre, secs = [], []
    for line in body.splitlines(keepends=True):
        if line.startswith("## "):
            secs.append([line])
        elif secs:
            secs[-1].append(line)
        else:
            pre.append(line)
    return "".join(pre), ["".join(s) for s in secs]


def select_sections(body, wanted):
    """제목에 wanted 중 하나가 들어간 절만 고른다(머리말은 늘 포함, wanted 가 비면 전체). (본문, 생략한 절 제목 목록)"""
    if not wanted:
        return body, []
    pre, secs = split_sections(body)
    keep, omitted = [pre], []
    for s in secs:
        title = s.split("\n", 1)[0][3:].strip()
        if any(w in title for w in wanted):
            keep.append(s)
        else:
            omitted.append(title)
    return "".join(keep), omitted


def render(main, name, wanted, status, db=None):
    """`instr show` 가 보이는 한 파일 분량. 파일이 없으면 None. override 는 짧고 우선하므로 절을 고르지 않고 전체를 보인다.
    main 이 None 이면 로컬 캐시 없이 `db`({"rev", "body"} — `db_rows` 의 값)를 보인다(`--repo` 경로)."""
    if main is None:
        if db is None:
            return None
        local, rev = db["body"], db["rev"]
    else:
        local = read_local(main, name)
        if local is None:
            return None
        rev = (load_state(main).get(name) or {}).get("rev", "?")
    body, omitted = select_sections(local, wanted) if name == "instructions" else (local, [])
    out = f"## 프로젝트 지침: .claude/{NAMES[name]} ({ROLE[name]} · rev {rev} · {status})\n{body.rstrip(chr(10))}\n"
    if omitted:
        out += f"(생략된 절 {len(omitted)}개: " + " · ".join(omitted) + " — 전체는 `donghans instr show`)\n"
    return out


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
        if act == "noop" and local is not None and db is not None:
            lock_local(main, name)
        if act == "write":
            write_local(main, name, db["body"]); state[name] = {"rev": db["rev"], "sha": sha(db["body"])}; touched = True
            notices.append((name, "updated", f"{NAMES[name]} 를 공유 저장소 rev {db['rev']} 로 갱신했다"))
        elif act == "record":
            state[name] = {"rev": db["rev"], "sha": sha(local)}; touched = True; lock_local(main, name)
        elif act == "adopt" and adopt:
            _insert(conn, repo_url, name, local, host); state[name] = {"rev": 1, "sha": sha(local)}; touched = True; lock_local(main, name)
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
        state[name] = {"rev": db["rev"], "sha": sha(local)}; save_state(main, state); lock_local(main, name)
        return 0, f"{name}: 이미 공유 저장소와 같다(rev {db['rev']})"
    else:
        st = state.get(name)
        if not force and not (st and st.get("rev") == db["rev"]):
            return 1, f"{name}: 공유 저장소(rev {db['rev']})가 마지막 동기화 이후 바뀌었다 — `donghans instr diff {name}` 확인 뒤 --force"
        rev = _update(conn, repo_url, name, local, host, db["rev"])
        if rev is None:
            return 1, f"{name}: 올리는 사이에 다른 기기가 먼저 바꿨다 — 다시 시도"
    state[name] = {"rev": rev, "sha": sha(local)}; save_state(main, state); lock_local(main, name)
    return 0, f"{name}: 공유 저장소에 올렸다(rev {rev})"


def set_body(conn, repo_url, main, name, body, host, masker=None, expect_rev=None):
    """새 본문을 DB 에 먼저 쓰고(낙관적 잠금) 캐시를 맞춘다 — `instr edit|set` 의 본체. (결과코드, 메시지). main=None 이면 DB 만 쓴다(캐시·상태 건너뜀).
    expect_rev 를 주면 DB 가 그 rev 일 때만 쓴다(읽은 뒤 다른 기기가 바꿨으면 거부). 주지 않으면 지금 DB 의 rev 기준(마지막에 쓴 쪽이 이긴다)."""
    if not body.strip():
        return 1, f"{name}: 빈 본문은 올리지 않는다"
    if masker is not None and masker.text(body) != body:
        return 1, "본문에 등록된 비밀 값이 들어 있어 올리지 않는다 — 비밀은 `donghans secret` 으로 두고 지침에는 이름만 적는다"
    db = db_rows(conn, repo_url).get(name)
    if db is not None and expect_rev is not None and db["rev"] != expect_rev:
        return 1, f"{name}: 읽은 뒤 공유 저장소가 rev {db['rev']} 로 바뀌었다(기대 rev {expect_rev}) — 최신본(`donghans instr get {name}`)에서 다시 고친다"
    if db is None:
        try:
            rev = _insert(conn, repo_url, name, body, host)
        except Exception:
            return 1, f"{name}: 올리는 사이에 다른 기기가 먼저 만들었다 — 다시 시도"
    elif sha(body) == sha(db["body"]):
        rev = db["rev"]
    else:
        rev = _update(conn, repo_url, name, body, host, db["rev"])
        if rev is None:
            return 1, f"{name}: 올리는 사이에 다른 기기가 먼저 바꿨다 — 다시 시도"
    if main is not None:      # main=None 이면 로컬 캐시·상태는 건드리지 않는다(ctxui·`--repo` 경로 — 다음 `instr show`·세션 시작 동기화가 캐시를 맞춘다)
        write_local(main, name, body)
        state = load_state(main); state[name] = {"rev": rev, "sha": sha(body)}; save_state(main, state)
    return 0, f"{name}: 공유 저장소에 올렸다(rev {rev})" + ("" if db is None or sha(body) != sha(db["body"]) else " — 이미 같은 내용")


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
