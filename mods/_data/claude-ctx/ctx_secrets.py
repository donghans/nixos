#!/usr/bin/env python3
"""ctx_secrets — 공유 컨텍스트(ctx)의 비밀번호 등록표 · 출력 치환 · 후보 탐지 · 주입 래퍼 · 로컬 파일 치환.

설계(사용자 결정):
  - 등록표(secrets 표)는 ctx DB 에 **평문**으로 둔다(ctx DB 는 허용된 tailnet 기기만 접속하는 설계). 원문(messages/hook_events)도 DB 에 그대로 보존한다.
  - 치환은 **내보낼 때만** 한다: `donghans ctx search|recent|session|sql|handoff` 출력과 `donghans secret run` 하위 프로세스의 출력.
    DB 원문은 바꾸지 않는다. 사람이 TTY 에서 `--raw` 를 줄 때만 풀린다(Claude 의 Bash 도구는 TTY 가 아니라 못 푼다).
  - 이미 DB 에 적재된 로컬 사본(~/.claude/projects/**/*.jsonl)은 `scrub` 으로 [protected] 로 바꿀 수 있다(원문은 DB 에 있다).
  - 비밀번호를 대화에 남기지 않는 길: `donghans secret run -- cmd {{secret:이름}}` — 값은 실행 직전에만 끼워 넣고, 출력은 다시 치환한다.
이 모듈은 DB 없이도 시험할 수 있게 치환·탐지·파일 치환 핵심을 순수 함수로 둔다(DB 를 쓰는 부분은 conn 을 받는다).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

MASK = "[protected]"
LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")   # 환경변수 이름이기도 하다
MIN_LEN = 4                                              # 이보다 짧은 값을 치환하면 일반 단어까지 지워진다

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS secrets (
  id         bigserial PRIMARY KEY,
  label      text NOT NULL UNIQUE,
  kind       text NOT NULL DEFAULT 'literal' CHECK (kind IN ('literal','regex')),
  value      text NOT NULL,
  enabled    boolean NOT NULL DEFAULT true,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
)""",
    """CREATE TABLE IF NOT EXISTS secret_ignores (
  fp         text PRIMARY KEY,
  pattern    text,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
)""",
]


# ---------------------------------------------------------------- 값 표현
def fingerprint(value: str) -> str:
    """값을 드러내지 않고 같은 값인지 가리키는 짧은 식별자(후보 승인·무시에 쓴다)."""
    return hashlib.sha1(value.encode("utf-8", "surrogatepass")).hexdigest()[:10]


def preview(value: str) -> str:
    """사람에게 보여 주는 흐린 미리보기: 앞 2~3자 + 길이. 전체 값은 절대 포함하지 않는다."""
    n = len(value)
    head = value[: 3 if n >= 12 else (2 if n >= 6 else 1)]
    return f"{head}…({n}자)"


def value_forms(value: str) -> set[str]:
    """같은 비밀이 파일·JSON 안에서 보일 수 있는 표기: 원형, JSON 이스케이프(비ASCII 그대로/\\uXXXX)."""
    forms = {value}
    for ascii_only in (False, True):
        forms.add(json.dumps(value, ensure_ascii=ascii_only)[1:-1])
    return {f for f in forms if f}


# ---------------------------------------------------------------- 치환 엔진
class Masker:
    """등록된 비밀(literal: 값 그대로, regex: 패턴)을 [protected] 로 바꾼다. secrets = [{label, kind, value}]"""

    def __init__(self, secrets=()):
        self.secrets = [dict(s) for s in secrets]
        lits = [s["value"] for s in self.secrets if s.get("kind", "literal") == "literal" and s["value"]]
        forms = sorted({f for v in lits for f in value_forms(v)}, key=len, reverse=True)  # 긴 것 먼저(부분 일치로 끝이 남지 않게)
        self._lit = re.compile("|".join(re.escape(f) for f in forms)) if forms else None
        self._regs = [re.compile(s["value"]) for s in self.secrets if s.get("kind") == "regex"]

    def __bool__(self):
        return bool(self._lit or self._regs)

    def text(self, s):
        if not s or not isinstance(s, str):
            return s
        if self._lit:
            s = self._lit.sub(MASK, s)
        for r in self._regs:
            s = r.sub(MASK, s)
        return s

    def obj(self, v):
        """문자열·리스트·딕트를 재귀로 치환한 새 값(튜플은 튜플로)."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {k: self.obj(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(self.obj(x) for x in v)
        return v

    def hits(self, s) -> bool:
        return bool(s) and self.text(s) != s

    def labels_in(self, s: str) -> list[str]:
        """s 에 나타나는 비밀의 label 들(값은 돌려주지 않는다)."""
        out = []
        for sec in self.secrets:
            if sec.get("kind", "literal") == "regex":
                if re.search(sec["value"], s):
                    out.append(sec["label"])
            elif any(f in s for f in value_forms(sec["value"])):
                out.append(sec["label"])
        return out


IDENTITY = Masker()


def validate(label: str, kind: str, value: str, force=False):
    """등록 전 검사. 문제가 있으면 ValueError(한국어 메시지)."""
    if not LABEL_RE.match(label or ""):
        raise ValueError("이름은 영문으로 시작하고 영문·숫자·_ 만 쓸 수 있다(환경변수 이름이 된다)")
    if kind not in ("literal", "regex"):
        raise ValueError("kind 는 literal 또는 regex")
    if not value:
        raise ValueError("값이 비어 있다")
    if kind == "regex":
        try:
            r = re.compile(value)
        except re.error as e:
            raise ValueError(f"정규식 오류: {e}")
        if r.search(""):
            raise ValueError("빈 문자열에 일치하는 정규식은 모든 곳을 지우므로 등록할 수 없다")
    elif len(value) < MIN_LEN and not force:
        raise ValueError(f"값이 {MIN_LEN}자보다 짧으면 일반 단어까지 치환된다(그래도 등록하려면 --force)")


# ---------------------------------------------------------------- DB: 등록표
def ensure_schema(conn):
    for st in SCHEMA_STATEMENTS:
        conn.execute(st)
    conn.commit()


def load_secrets(conn, only_enabled=True):
    """등록표를 읽는다. 표가 아직 없으면(마이그레이션 전) 빈 목록."""
    import psycopg.errors as pe
    try:
        rows = conn.execute("SELECT label, kind, value, enabled FROM secrets" + (" WHERE enabled" if only_enabled else "") + " ORDER BY label").fetchall()
    except pe.UndefinedTable:
        conn.rollback()
        return []
    return [dict(label=r[0], kind=r[1], value=r[2], enabled=r[3]) for r in rows]


def load_masker(conn) -> Masker:
    return Masker(load_secrets(conn))


def add_secret(conn, label, kind, value, note=None, replace=False, force=False):
    validate(label, kind, value, force)
    ensure_schema(conn)
    if replace:
        conn.execute("""INSERT INTO secrets (label, kind, value, note) VALUES (%s,%s,%s,%s)
                        ON CONFLICT (label) DO UPDATE SET kind=excluded.kind, value=excluded.value, note=coalesce(excluded.note, secrets.note),
                          enabled=true, updated_at=now()""", (label, kind, value, note))
    else:
        import psycopg.errors as pe
        try:
            conn.execute("INSERT INTO secrets (label, kind, value, note) VALUES (%s,%s,%s,%s)", (label, kind, value, note))
        except pe.UniqueViolation:
            conn.rollback()
            raise ValueError(f"'{label}' 은(는) 이미 있다(값을 바꾸려면 --replace)")
    conn.commit()


# ---------------------------------------------------------------- 후보 탐지
# (이름, 정규식, 비밀로 볼 그룹 번호). 후보는 사람이 승인해야 등록된다 — 오탐은 `ignore` 로 숨긴다.
PATTERNS = [
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{20,}", 0),
    ("openai_key", r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", 0),
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{30,}", 0),
    ("github_pat", r"github_pat_[A-Za-z0-9_]{40,}", 0),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", 0),
    ("slack_token", r"xox[baprs]-[A-Za-z0-9\-]{10,}", 0),
    ("google_api_key", r"AIza[0-9A-Za-z_\-]{35}", 0),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----", 0),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b", 0),
    ("url_credentials", r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s@/]{4,})@", 1),
    ("assigned_secret", r"(?i)(?<![A-Za-z])(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)(?![A-Za-z])[\"']?\s*[:=]\s*[\"']?([^\s\"'<>,;)}\]]{6,})", 1),
    ("korean_password", r"(?:비밀번호|패스워드|암호)\s*(?:는|은|가|이)?\s*[:=]?\s*[\"']?([A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:,.?~]{6,})", 1),
]
_COMPILED = [(n, re.compile(p), g) for n, p, g in PATTERNS]
# 값 패턴이 닫는 괄호 앞에서 끊기므로(`${X}` → `${X`, `[protected]` → `[protected`) 여는 쪽만 보고 거른다
_PLACEHOLDER = re.compile(r"(?i)^(?:x{3,}|\*{3,}|\.{3,}|<.*|\$\{.*|\$\(.*|\$[A-Z_]+|\{\{.*|\[?protected\]?|your[_-]?.*|example.*|changeme|password|secret|token|null|none|true|false)$")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    c = {}
    for ch in s:
        c[ch] = c.get(ch, 0) + 1
    return -sum(n / len(s) * math.log2(n / len(s)) for n in c.values())


def plausible(value: str, strict: bool) -> bool:
    """키워드형 패턴(assigned_secret/korean_password)의 오탐을 거른다: 자리표시자·평범한 단어·한 종류 문자만으로 된 값 제외."""
    if _PLACEHOLDER.match(value) or MASK in value:
        return False
    if not strict:
        return True
    # 키워드(password= 등) 뒤에 오는 값이 비밀이 아니라 경로·코드·식별자인 경우를 거른다(실제 데이터에서 가장 많은 오탐 모양)
    if value.startswith(("/", "~", "./", "../", "$", "`")) or "://" in value or "(" in value or ")" in value:
        return False
    if re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+", value):   # process.env.X · os.environ.get 같은 코드 참조
        return False
    # `_`·`-` 는 식별자(snake_case)에도 흔해서 문자 종류로 세지 않는다: 소문자/대문자/숫자/그 밖의 기호 중 2종류 이상이어야 한다
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9_\-]"))
    return classes >= 2 and _entropy(value) >= 2.2 and not re.fullmatch(r"[가-힣]+", value)


def find_candidates(text: str):
    """한 텍스트의 (패턴 이름, 비밀로 추정되는 값) 들. 같은 구간은 먼저 일치한 패턴이 가진다."""
    seen_spans, out = [], []
    for name, rx, g in _COMPILED:
        for m in rx.finditer(text):
            val = m.group(g)
            if not val:
                continue
            span = m.span(g)
            if any(not (span[1] <= a or span[0] >= b) for a, b in seen_spans):
                continue
            if not plausible(val, strict=name in ("assigned_secret", "korean_password")):
                continue
            seen_spans.append(span)
            out.append((name, val))
    return out


def scan_messages(rows, masker=IDENTITY, ignored=frozenset()):
    """rows: (session_id, repo_url, ts, text) 이터레이터 → {fp: {...}} (등록·무시된 값 제외, 값은 value 키에 담되 출력은 호출자가 가린다)."""
    found = {}
    for sid, repo, ts, text in rows:
        if not text:
            continue
        for name, val in find_candidates(text):
            if masker.hits(val) or fingerprint(val) in ignored:
                continue
            fp = fingerprint(val)
            d = found.setdefault(fp, dict(fp=fp, pattern=name, value=val, count=0, sessions=set(), repos=set(), first=ts, last=ts))
            d["count"] += 1
            d["sessions"].add(sid)
            if repo:
                d["repos"].add(repo)
            if ts and (d["first"] is None or ts < d["first"]):
                d["first"] = ts
            if ts and (d["last"] is None or ts > d["last"]):
                d["last"] = ts
    return found


# ---------------------------------------------------------------- 주입 래퍼
_REF = re.compile(r"\{\{secret(-file)?:([A-Za-z][A-Za-z0-9_]*)\}\}")


def referenced_labels(argv):
    return {m.group(2) for a in argv for m in _REF.finditer(a)}


def build_command(argv, secrets, env_labels=()):
    """argv 의 {{secret:이름}} 은 값으로, {{secret-file:이름}} 은 0600 임시 파일 경로로 바꾼다(직접 대화에 값이 남지 않게).
    환경변수로는 env_labels 에 적은 것만 준다(최소 권한). 반환: (argv, env 추가분, 정리할 파일들). 모르는 이름이면 KeyError(이름 목록만 담음)."""
    lit = {s["label"]: s["value"] for s in secrets if s.get("kind", "literal") == "literal"}
    need = referenced_labels(argv) | set(env_labels)
    missing = sorted(need - set(lit))
    if missing:
        raise KeyError(f"등록되지 않았거나 literal 이 아닌 이름: {', '.join(missing)} (등록된 이름: {', '.join(sorted(lit)) or '없음'})")
    files = []

    def sub(m):
        label = m.group(2)
        if m.group(1):  # -file
            d = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
            fd, p = tempfile.mkstemp(prefix=f"secret-{label}-", dir=d)
            os.write(fd, lit[label].encode())
            os.close(fd)
            os.chmod(p, 0o600)
            files.append(p)
            return p
        return lit[label]

    out = [_REF.sub(sub, a) for a in argv]
    return out, {l: lit[l] for l in env_labels}, files


def run_masked(argv, secrets, env_labels=(), out=None, err=None, stdin=None):
    """argv 를 비밀을 끼워 실행하고, 표준출력·오류를 줄 단위로 치환해 내보낸다. 반환: 종료 코드."""
    masker = Masker(secrets)
    out = out or sys.stdout
    err = err or sys.stderr
    cmd, env_add, files = build_command(argv, secrets, env_labels)
    try:
        p = subprocess.Popen(cmd, env={**os.environ, **env_add}, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        for f in files:
            os.unlink(f)
        err.write(f"명령을 찾을 수 없다: {argv[0]}\n")
        return 127

    def pump(src, dst):
        for line in iter(src.readline, b""):
            dst.write(masker.text(line.decode("utf-8", "replace")))
            dst.flush()

    ts = [threading.Thread(target=pump, args=(p.stdout, out)), threading.Thread(target=pump, args=(p.stderr, err))]
    for t in ts:
        t.start()
    try:
        rc = p.wait()
    except KeyboardInterrupt:
        p.terminate()
        rc = p.wait()
    for t in ts:
        t.join()
    for f in files:
        try:
            os.unlink(f)
        except OSError:
            pass
    return rc


# ---------------------------------------------------------------- 로컬 파일 치환(.claude 의 jsonl)
def scrub_bytes(data: bytes, secrets):
    """jsonl 바이트에서 비밀을 [protected] 로 바꾼다. 줄마다 JSON 으로 다시 읽혀야만 적용한다(안 읽히면 그 줄은 그대로 두고 skipped 로 센다).
    반환: (새 바이트, {label: 횟수}, skipped 줄 수)."""
    lits = [s for s in secrets if s.get("kind", "literal") == "literal" and s["value"]]
    regs = [s for s in secrets if s.get("kind") == "regex"]
    form_map = [(s["label"], [f.encode("utf-8") for f in sorted(value_forms(s["value"]), key=len, reverse=True)]) for s in lits]
    all_forms = sorted({f for _, fs in form_map for f in fs}, key=len, reverse=True)
    lit_rx = re.compile(b"|".join(re.escape(f) for f in all_forms)) if all_forms else None
    reg_rx = [(s["label"], re.compile(s["value"])) for s in regs]
    hits, skipped, out = {}, 0, []
    for line in data.split(b"\n"):
        new = line
        line_hits = {}
        if lit_rx and lit_rx.search(line):
            for label, fs in form_map:
                n = sum(line.count(f) for f in fs)
                if n:
                    line_hits[label] = n
            new = lit_rx.sub(MASK.encode(), new)
        if reg_rx and line:
            txt = new.decode("utf-8", "surrogateescape")
            for label, rx in reg_rx:
                n = len(rx.findall(txt))
                if n:
                    line_hits[label] = line_hits.get(label, 0) + n
                    txt = rx.sub(MASK, txt)
            new = txt.encode("utf-8", "surrogateescape")
        if new != line:
            try:
                if line.strip():
                    json.loads(line)          # 원래 JSON 이었다면
                json.loads(new)               # 바뀐 뒤에도 JSON 이어야 한다
            except Exception:
                skipped += 1
                out.append(line)
                continue
            for k, v in line_hits.items():
                hits[k] = hits.get(k, 0) + v
        out.append(new)
    return b"\n".join(out), hits, skipped


def registry_hash(secrets) -> str:
    """등록표의 내용 해시(값은 담기지 않음). 점검 캐시가 「그때와 같은 등록표로 이미 본 파일」인지 가리는 데 쓴다."""
    h = hashlib.sha1()
    for sec in sorted(secrets, key=lambda x: (x["label"], x.get("kind", "literal"))):
        h.update(f"{sec['label']}\0{sec.get('kind', 'literal')}\0{sec['value']}\0".encode("utf-8", "surrogatepass"))
    return h.hexdigest()[:16]


def transcript_files(home):
    import glob
    return (sorted(glob.glob(os.path.join(home, ".claude/projects/*/*.jsonl")))
            + sorted(glob.glob(os.path.join(home, ".claude/projects/*/*/subagents/*.jsonl"))))


def scrub_local(cc, conn, files, secrets, apply=False, idle_secs=3600, log=print, state=None):
    """적재가 끝난(오프셋 == 파일 크기) 한가한 트랜스크립트의 비밀을 치환한다.
    - 적용 전에 그 파일을 먼저 적재해 원문이 DB 에 있게 하고, ingest_state 오프셋을 새 크기로 맞춘다(길이가 바뀌므로).
    - 열려 있을 수 있는 파일(최근 idle_secs 안에 수정됨)은 건드리지 않는다. 쓰는 사이 파일이 바뀌면 포기한다.
    - state(dict, 호출자가 파일로 저장)가 있으면 「수정 시각·크기·등록표 해시가 지난번 점검과 같은 파일」은 읽지 않고 건너뛴다(트랜스크립트가 GB 단위라서).
    cc = claude_ctx 모듈(ingest_transcript · lock_key · INGEST_HOST 를 쓴다). 반환: 요약 dict."""
    summary = dict(files=0, hit_files=0, changed=0, skipped_active=0, skipped_unsynced=0, skipped_changed=0, skipped_lines=0, cached=0, hits={})
    now = time.time()
    rh = registry_hash(secrets)
    for path in files:
        summary["files"] += 1
        try:
            st = os.stat(path)
        except OSError:
            continue
        key = [st.st_mtime_ns, st.st_size, rh]
        if state is not None and state.get(path) == key:
            summary["cached"] += 1
            continue
        try:
            data = open(path, "rb").read()
        except OSError:
            continue
        new, hits, skipped = scrub_bytes(data, secrets)
        if not hits:
            if state is not None:
                state[path] = key   # 이 등록표로는 비밀이 없는 파일 — 파일이 바뀌기 전에는 다시 읽지 않는다
            continue
        summary["hit_files"] += 1
        summary["skipped_lines"] += skipped
        if now - st.st_mtime < idle_secs:
            summary["skipped_active"] += 1
            log(f"  (진행 중으로 보임, 건너뜀) {path}  {_fmt_hits(hits)}")
            continue
        if not apply:
            log(f"  [dry-run] {path}  {_fmt_hits(hits)}" + (f"  ※JSON 이 깨져 건너뛸 줄 {skipped}" if skipped else ""))
            for k, v in hits.items():
                summary["hits"][k] = summary["hits"].get(k, 0) + v
            continue
        cc.ingest_transcript(conn, path)  # 원문이 DB 에 있게 한다(멱등)
        conn.commit()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (cc.lock_key(path),))
            if not cur.fetchone()[0]:
                summary["skipped_changed"] += 1
                continue
            st2 = os.stat(path)
            if (st2.st_mtime_ns, st2.st_size) != (st.st_mtime_ns, st.st_size):
                summary["skipped_changed"] += 1
                log(f"  (읽는 사이 파일이 바뀜, 건너뜀) {path}")
                continue
            cur.execute("SELECT byte_offset FROM ingest_state WHERE host=%s AND path=%s", (cc.INGEST_HOST, path))
            row = cur.fetchone()
            if not row or row[0] != st.st_size:
                summary["skipped_unsynced"] += 1
                log(f"  (DB 에 다 적재되지 않아 건너뜀) {path}")
                continue
            tmp = path + ".scrub.tmp"
            with open(tmp, "wb") as f:
                f.write(new)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, st.st_mode & 0o7777)
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))  # 수정 시각 보존(--days 선별과 순서가 달라지지 않게)
            cur.execute("UPDATE ingest_state SET byte_offset=%s, updated_at=now() WHERE host=%s AND path=%s", (len(new), cc.INGEST_HOST, path))
            os.replace(tmp, path)
        summary["changed"] += 1
        if state is not None:
            st3 = os.stat(path)
            state[path] = [st3.st_mtime_ns, st3.st_size, rh]
        for k, v in hits.items():
            summary["hits"][k] = summary["hits"].get(k, 0) + v
        log(f"  치환 {path}  {_fmt_hits(hits)}")
    return summary


def _fmt_hits(hits):
    return ", ".join(f"{k}×{v}" for k, v in sorted(hits.items()))
