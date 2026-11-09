#!/usr/bin/env python3
"""protocolcheck — 출력 규약 파일럿의 검사기(LLM 바깥의 코드). 규약 산출물 폴더가 규약대로인지 확인하고 `.check/result.json`·`.check/CHECK.md` 에 쓴다.
설계: ctx 문서 plan llm-trust/10-p5prime-1-protocol-pilot, 검사 규칙 동결 명세: note llm-trust/wf-10-s1-frozen-protocol §3 (이 파일의 정규식·판정이 그 구현이다).
훅(protocolhook.py)과 수동 실행이 같은 `run_checks` 를 부른다.

  protocolcheck run <폴더> [--final] [--json]   검사. 상태 `작업중` 이면 부분 검사, 아니면 마감 시도 검사. --final(종료 후 수동): 전부(C6 포함)·상태 작업중은 C1 FAIL
  protocolcheck facts <폴더> [--no-quotes]       facts/diff-stat.txt·facts/quotes.txt 를 만들고 sha 를 등록한다
  protocolcheck hook prompt|stop                 Claude Code 훅(UserPromptSubmit·Stop). 게이트 `LLM_PROTOCOL_PILOT=1` 이 없으면 아무것도 하지 않고 종료 코드 0

판정: FAIL(미충족)·WARN(경고)·INFO(정보). 되돌림(F 팔)은 FAIL 중 REWIND_IDS 만 근거로 한다. 이 검사는 형식·문자열 존재만 본다 — 읽히는지·의미가 맞는지는 못 본다(검사 통과 ≠ 읽힘).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # -I 로 실행돼도 형제 모듈(ctxcards·ctx_secrets·protocol_text…)을 찾는다

CLASSES = ("결정", "계획", "검증·QA", "구현 결과", "모름")
MODULES_BY_CLASS = {"결정": ["10-glossary.md", "11-options.md", "12-evidence.md"], "계획": ["20-remaining.md"],
                    "검증·QA": ["40-why-tested.md"], "구현 결과": ["50-before-after.md"], "모름": []}
ALL_MODULE_FILES = sorted({f for v in MODULES_BY_CLASS.values() for f in v})
MODULE_VALUES = ("index", "cover", "unknown", "glossary", "options", "evidence", "remaining", "whytested", "beforeafter")
FACTS_MODULE = "facts"   # 사실분(도구 파일)의 모듈 값 — S1 열거값에 없어 보정(wf-10-s2 deviations)
FIXED = ("00-cover.md", "01-unknown.md")
SECTIONS = {   # 파일 → 필수 절 제목(`## ` 줄)
    "00-cover.md": ("결정할 것", "한 줄 그림", "최종사용자 영향"),
    "01-unknown.md": ("못 쟀음·미확인", "빠진 것"),
    "20-remaining.md": ("열린 결정", "재방문 조건"),
    "40-why-tested.md": ("왜 이 시험인가", "추정 확인표"),
    "50-before-after.md": ("바뀐 파일", "전후", "사용 가능 수준"),
}
INDEX_COLS = ("파일", "한 줄 요약", "언제 읽나", "근거 대화 범위", "종류", "검사")
HEAD_KEYS = ("종류", "모듈", "작성", "근거")
REWIND_IDS = ("C1", "C2", "C3", "C4", "C4b", "C5", "C8", "C9")   # 되돌림 근거가 되는 FAIL 의 ID(순서가 (c) 사유 정렬 순서)
LEN_WARN = 2000
LEN_TOTAL_WARN = 12000
FACTS_MAX_BYTES = 20 * 1024
MAX_INTERPRETIVE_FILES = 6
C6_ONE_TIMEOUT = 15
C6_TOTAL_TIMEOUT = 90
PLACEHOLDER_OK = "(포인터 — 읽을 때 채움)"

BANNED = [re.compile(p, re.I) for p in (r"\bTODO\b", r"\bTBD\b", r"\bFIXME\b", r"\bXXX\b", r"추후", r"작성 예정", r"내용 없음", r"여기에 (?:작성|입력)", r"lorem ipsum")]
PLACEHOLDER_RE = re.compile(r"<[^<>\n`]{1,40}>")
UUID_PRE = r"[0-9a-f]{8}(?:-?[0-9a-f]){0,28}"   # uuid 앞 8자 이상(전체 uuid 도 허용 — 카드·`ctx msg` 머리줄이 전체를 쓴다: 과거 카드 8건 그림자 적용에서 확인한 보정)
QUOTE_LINE = re.compile(r'^- \[msg:(' + UUID_PRE + r')\] "(.+)" \((.+)\)$')
POINTER_LINE = re.compile(r"^- \[msg:(" + UUID_PRE + r")\] \(포인터")
MSG_LINE = re.compile(r"^- \[msg:")


# ---------------------------------------------------------------- 공통 유틸
def norm_text(t: str) -> str:
    return unicodedata.normalize("NFC", (t or "").replace("\r\n", "\n"))


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return norm_text(f.read())
    except OSError:
        return None


def sha256_file(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def write_tool_file(path: str, text: str, mode: int = 0o400) -> None:
    """도구가 만드는 파일: 임시 파일에 쓴 뒤 교체(기존 0400 파일도 덮어쓴다)하고 권한을 건다."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".tmp-{os.getpid()}-{os.path.basename(path)}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def parse_head(text: str):
    """`---` 머리. (필드 dict, 본문) 또는 (None, text)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            meta = {}
            for ln in lines[1:i]:
                m = re.match(r"^([^:：\s]+)\s*:\s*(.*)$", ln)
                if m:
                    meta[m.group(1)] = re.split(r"\s+#", m.group(2))[0].strip()
            return meta, "\n".join(lines[i + 1:])
    return None, text


def strip_code(text: str) -> str:
    """코드펜스(~~~·```)와 인라인 백틱 구간을 뺀 나머지('코드 밖')."""
    out, fence = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\s*(`{3,}|~{3,})", ln)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append(re.sub(r"`[^`\n]*`", " ", ln))
    return "\n".join(out)


def section(body: str, title: str):
    """`## 제목` 아래(다음 `## ` 전까지)의 줄들. 없으면 None."""
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^##\s+" + re.escape(title) + r"\s*$", ln):
            j = i + 1
            while j < len(lines) and not re.match(r"^##\s", lines[j]):
                j += 1
            return lines[i + 1:j]
    return None


def nonblank(lines) -> list:
    return [l for l in lines if l.strip()]


def split_items(lines) -> list:
    """절 안의 최상위 항목(`^- ` 또는 `^\\d+[.)] ` 로 시작하는 줄과 그 아래 이어지는 줄) 블록 목록."""
    items, cur = [], None
    for ln in lines:
        if re.match(r"^(- |\d+[.)]\s)", ln):
            cur = [ln]
            items.append(cur)
        elif cur is not None:
            cur.append(ln)
    return ["\n".join(x) for x in items]


def item_label(block: str, idx: int) -> str:
    m = re.search(r"\b([A-Z]\d+)\b", block.split("\n")[0])
    return m.group(1) if m else str(idx)


def is_split(name: str) -> bool:
    return bool(re.match(r"^\d\d-[a-z-]+?-\d+\.md$", name))


def base_name(name: str) -> str:
    return re.sub(r"-\d+\.md$", ".md", name) if is_split(name) else name


def table_rows(lines) -> list:
    """`|` 로 시작하는 줄 → 칸 목록."""
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("|"):
            cells = s.strip("|").split("|") if s.endswith("|") else s[1:].split("|")
            out.append([c.strip() for c in cells])
    return out


def is_sep_row(cells) -> bool:
    return all(re.fullmatch(r":?-{1,}:?", c.replace(" ", "")) for c in cells if c != "") and any(c for c in cells)


def clean_cell_file(c: str) -> str:
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    return c.replace("`", "").strip()


# ---------------------------------------------------------------- 산출물 폴더 읽기
class Folder:
    """산출물 폴더의 읽기 뷰(한 번 읽어 둔다)."""

    def __init__(self, d: str):
        self.dir = d
        self.md = {}      # 이름 → 정규화 본문 (루트의 *.md, FORMAT.md 제외)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(d, n)
            if n.endswith(".md") and n != "FORMAT.md" and os.path.isfile(p):
                self.md[n] = read(p) or ""
        self.facts = {}   # 'facts/x' → 본문
        fd = os.path.join(d, "facts")
        if os.path.isdir(fd):
            for n in sorted(os.listdir(fd)):
                if os.path.isfile(os.path.join(fd, n)):
                    self.facts["facts/" + n] = read(os.path.join(fd, n)) or ""
        self.index = self.md.get("INDEX.md")
        self.sha = {}
        s = read(os.path.join(d, ".check", "facts.sha"))
        for ln in (s or "").split("\n"):
            m = re.match(r"^([0-9a-f]{64})\s+(\S.*)$", ln)
            if m:
                self.sha[m.group(2).strip()] = m.group(1)

    def index_lines(self) -> dict:
        """INDEX 의 `- 키: 값` 줄."""
        out = {}
        if self.index is None:
            return out
        _m, body = parse_head(self.index)
        for ln in (body if _m is not None else self.index).split("\n"):
            m = re.match(r"^- (분류|켜진 모듈|세션|상태):\s*(.*?)\s*$", ln)
            if m and m.group(1) not in out:
                out[m.group(1)] = m.group(2)
        return out

    def state(self):
        v = self.index_lines().get("상태", "")
        m = re.match(r"^(작업중|완료)", v)
        return m.group(1) if m else None

    def klass(self):
        v = self.index_lines().get("분류", "")
        return v if v in CLASSES else None

    def interpretive(self) -> dict:
        return dict(self.md)


def item(id_, level, file, reason):
    return {"id": id_, "level": level, "file": file, "reason": reason}


# ---------------------------------------------------------------- 개별 검사
def check_c1(fo: Folder, final: bool) -> list:
    out = []
    if fo.index is None:
        return [item("C1", "FAIL", "INDEX.md", "INDEX.md 없음")]
    meta, body = parse_head(fo.index)
    if meta is None or any(k not in meta for k in HEAD_KEYS):
        out.append(item("C1", "FAIL", "INDEX.md", "머리 4필드 부족"))
    lines = fo.index_lines()
    raw = fo.index
    if "분류" not in lines:
        out.append(item("C1", "FAIL", "INDEX.md", "`- 분류` 줄 없음"))
    elif lines["분류"] not in CLASSES:
        out.append(item("C1", "FAIL", "INDEX.md", "분류 값 오류"))
    if "켜진 모듈" not in lines:
        out.append(item("C1", "FAIL", "INDEX.md", "`- 켜진 모듈` 줄 없음"))
    if "세션" not in lines:
        out.append(item("C1", "FAIL", "INDEX.md", "`- 세션` 줄 없음"))
    if not re.search(r"^- 상태: (작업중|완료)", raw, re.M):
        out.append(item("C1", "FAIL", "INDEX.md", "상태 줄 없음"))
    elif final and fo.state() == "작업중":
        out.append(item("C1", "FAIL", "INDEX.md", "미완료(상태가 작업중)"))
    ibody = body if meta is not None else raw
    if section(ibody, "지금 결정할 것") is None:
        out.append(item("C1", "FAIL", "INDEX.md", "`## 지금 결정할 것` 절 없음"))
    sec = section(ibody, "파일")
    if sec is None:
        out.append(item("C1", "FAIL", "INDEX.md", "`## 파일` 절 없음"))
    else:
        rows = table_rows(sec)
        if not rows:
            out.append(item("C1", "FAIL", "INDEX.md", "표 열이 6개가 아님"))
        else:
            hdr = [re.sub(r"\s+", "", c) for c in rows[0]]
            if hdr != [re.sub(r"\s+", "", c) for c in INDEX_COLS]:
                out.append(item("C1", "FAIL", "INDEX.md", "표 열이 6개가 아님"))
            else:
                bad = [r for r in rows[1:] if not is_sep_row(r) and len(r) != 6]
                if bad:
                    out.append(item("C1", "FAIL", "INDEX.md", "표 열이 6개가 아님"))
    return out


def index_files(fo: Folder) -> list:
    sec = section(parse_head(fo.index or "")[1] if parse_head(fo.index or "")[0] is not None else (fo.index or ""), "파일")
    out = []
    for r in table_rows(sec or [])[1:]:
        if is_sep_row(r) or not r:
            continue
        f = clean_cell_file(r[0])
        if f:
            out.append(f)
    return out


def check_c2(fo: Folder) -> list:
    """표↔파일 일치. 표에 없는 `*.md`·표의 파일 중 없는 것 FAIL. facts/* 는 표에 올린 것만 존재를 본다(올리지 않은 facts 는 FAIL 아님 — S1 명세 보정, 훅이 만드는 파일을 모델이 알 수 없다)."""
    if fo.index is None:
        return []
    listed = set(index_files(fo)) - {"INDEX.md", "FORMAT.md"}   # 표에 INDEX 자신·FORMAT.md 를 올려도 오류가 아니다(실제 스모크에서 모델이 INDEX 를 표에 올렸다)
    out = []
    actual_md = {n for n in fo.md if n != "INDEX.md"}
    for n in sorted(actual_md - listed):
        out.append(item("C2", "FAIL", "INDEX.md", f"표에 없는 파일 {n}"))
    for n in sorted(listed - actual_md - set(fo.facts)):
        out.append(item("C2", "FAIL", "INDEX.md", f"표의 {n} 파일 없음"))
    return out


def body_len(text: str) -> int:
    meta, body = parse_head(text)
    b = body if meta is not None else text
    lines = [l for l in b.split("\n") if not re.match(r"^#\s", l)]
    return len(re.sub(r"\s+", "", "\n".join(lines)))


def check_c3(fo: Folder, working: bool) -> list:
    out = []
    names = list(FIXED)
    if not working:
        for n in FIXED:
            if n not in fo.md:
                out.append(item("C3", "FAIL", n, f"{n} 없음"))
    pool = [n for n in fo.md if n != "INDEX.md" and (n in FIXED if working else True)]
    for n in sorted(pool):
        if body_len(fo.md[n]) < 20:
            out.append(item("C3", "FAIL", n, "본문이 20자 미만"))
    return out


def check_c4(fo: Folder) -> list:
    out = []
    kl = fo.klass()
    if kl:
        for n in MODULES_BY_CLASS[kl]:
            if n not in fo.md:
                out.append(item("C4", "FAIL", n, f"모듈 파일 {n} 없음"))
        for n in sorted(fo.md):
            if is_split(n):
                continue
            if n in ALL_MODULE_FILES and n not in MODULES_BY_CLASS[kl]:
                out.append(item("C4", "WARN", n, "분류에 속하지 않는 모듈 파일"))
    for n, text in sorted(fo.md.items()):
        if n == "INDEX.md" or is_split(n):
            continue
        meta, body = parse_head(text)
        body = body if meta is not None else text
        for title in SECTIONS.get(n, ()):
            sec = section(body, title)
            if sec is None or not nonblank(sec):
                out.append(item("C4", "FAIL", n, f"`## {title}` 절 없음/빔"))
        dec = None
        if n == "00-cover.md":
            dec = section(body, "결정할 것")
        elif n == "20-remaining.md":
            dec = section(body, "열린 결정")
        if dec is not None and nonblank(dec):
            nb = nonblank(dec)
            if not (len(nb) == 1 and "없음" in nb[0]):
                blocks = split_items(dec) or ["\n".join(dec)]
                for i, b in enumerate(blocks, 1):
                    if "추천" not in b or "되돌" not in b:
                        out.append(item("C4", "FAIL", n, f"결정 {item_label(b, i)}에 추천·되돌리기 없음"))
        if n == "11-options.md":
            blocks = split_items(body.split("\n"))
            if not blocks:
                out.append(item("C4", "FAIL", n, "선택지 항목 없음/빔"))
            for i, b in enumerate(blocks, 1):
                miss = [k for k in ("전:", "후:", "엮이는 곳:") if k not in b]
                if miss:
                    out.append(item("C4", "FAIL", n, f"선택지 {item_label(b, i)}에 {'·'.join(miss)} 없음"))
        if n == "12-evidence.md" and not any(MSG_LINE.match(l) for l in body.split("\n")):
            out.append(item("C4", "FAIL", n, "`- [msg:` 근거 줄 없음"))
        if n == "10-glossary.md":
            rows = [r for r in table_rows(body.split("\n")) if not is_sep_row(r)]
            if len(rows) < 2:
                out.append(item("C4", "FAIL", n, "용어 표 데이터 행 없음"))
        if n == "40-why-tested.md":
            sec = section(body, "추정 확인표")
            if sec is not None and nonblank(sec) and not any(k in l for l in sec for k in ("확인", "추정", "못 쟀음")):
                out.append(item("C4", "FAIL", n, "추정 확인표에 확인·추정·못 쟀음 줄 없음"))
        if n == "50-before-after.md":
            sec = section(body, "바뀐 파일")
            if sec is not None and nonblank(sec) and not re.search(r"`[^`\n]+`", "\n".join(sec)):
                out.append(item("C4", "FAIL", n, "`## 바뀐 파일` 에 백틱 경로 없음"))
    return out


def check_c4b(fo: Folder) -> list:
    out = []
    for n, text in sorted(fo.md.items()):
        keep = "\n".join(l for l in strip_code(text).split("\n") if PLACEHOLDER_OK not in l)
        seen = set()
        for rx in BANNED:
            m = rx.search(keep)
            if m and m.group(0).lower() not in seen:
                seen.add(m.group(0).lower())
                out.append(item("C4b", "FAIL", n, f"금지 문구 `{m.group(0)}`"))
        m = PLACEHOLDER_RE.search(keep)
        if m:
            out.append(item("C4b", "FAIL", n, f"금지 문구 `{m.group(0)[:20]}`"))
    return out


def facts_meta_ok(text: str) -> bool:
    meta, _b = parse_head(text)
    return bool(meta) and meta.get("종류") == "사실" and meta.get("작성", "").startswith("tool:") and all(k in meta for k in HEAD_KEYS)


def check_c5(fo: Folder) -> list:
    out = []
    for n, text in sorted(fo.md.items()):
        meta, _b = parse_head(text)
        if meta is None or any(k not in meta for k in HEAD_KEYS):
            out.append(item("C5", "FAIL", n, "머리 필드 값 오류(4필드 부족)"))
            continue
        if meta["종류"] not in ("해석", "사실") or meta["모듈"] not in MODULE_VALUES:
            out.append(item("C5", "FAIL", n, "머리 필드 값 오류"))
        elif meta["종류"] == "사실" or meta["작성"].startswith("tool:"):
            out.append(item("C5", "FAIL", n, "머리 필드 값 오류(해석분이 사실분 표지)"))
    for req in ("facts/request-items.txt", "facts/base.txt"):
        if req not in fo.facts:
            out.append(item("C5", "FAIL", req, f"facts 파일 {os.path.basename(req)} 없음"))
    for n, text in sorted(fo.facts.items()):
        if not facts_meta_ok(text):
            out.append(item("C5", "FAIL", n, "머리 필드 값 오류(사실분 표지)"))
        want = fo.sha.get(n)
        have = sha256_file(os.path.join(fo.dir, n))
        if want is None:
            out.append(item("C5", "FAIL", n, "facts 파일이 바뀜(등록 해시 없음)"))
        elif want != have:
            out.append(item("C5", "FAIL", n, "facts 파일이 바뀜"))
    return out


# --- C6 인용 일치 (--final 에서만)
def default_fetch(uuid8: str):
    """`donghans ctx msg <uuid8> --all` → ("ok", 본문, 세션ID) | ("none",) | ("ambiguous",) | ("error", 사유). DB 접속 실패·시간 초과는 error."""
    exe = os.environ.get("LLM_PROTOCOL_DONGHANS", "donghans")
    try:
        r = subprocess.run([exe, "ctx", "msg", uuid8, "--all"], capture_output=True, text=True, timeout=C6_ONE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ("error", type(e).__name__)
    out = r.stdout or ""
    if r.returncode != 0 and not out.startswith("일치하는 메시지 없음") and "건에 일치한다" not in out:
        return ("error", f"종료 코드 {r.returncode}")
    if out.startswith("일치하는 메시지 없음"):
        return ("none",)
    if "건에 일치한다" in out.split("\n", 1)[0]:
        return ("ambiguous",)
    m = re.match(r"^# (\S+)\s+세션 (\S+)\s", out)
    if not m:
        return ("error", "머리줄 형식 불명")
    body = out.split("\n", 1)[1] if "\n" in out else ""
    body = "\n".join(l for l in body.split("\n") if not l.startswith("# "))   # 안내(notes) 줄 제거
    return ("ok", norm_text(body), m.group(2))


def default_repo_of(session_id: str):
    """세션의 repo_url. 모르면 None, 조회 실패는 ("error", 사유)."""
    exe = os.environ.get("LLM_PROTOCOL_DONGHANS", "donghans")
    if not re.fullmatch(r"[0-9a-fA-F-]{8,40}", session_id or ""):
        return ("error", "세션 ID 형식")
    try:
        r = subprocess.run([exe, "ctx", "sql", f"select repo_url from sessions where session_id = '{session_id}'"], capture_output=True, text=True, timeout=C6_ONE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ("error", type(e).__name__)
    if r.returncode != 0:
        return ("error", f"종료 코드 {r.returncode}")
    rows = [l for l in r.stdout.split("\n")[1:] if l.strip()]
    return rows[0].strip() if rows else None


def collect_quotes(fo: Folder, fetch=default_fetch, repo_of=default_repo_of, now=time.monotonic) -> tuple:
    """모든 해석분의 인용 줄 → (판정 항목들, 기록들). 기록: {uuid, status}. status: 일치·미일치·메시지 없음·모호·미실시·형식오류·nixos 아님."""
    import ctxcards as cx
    out, recs, cache, repos = [], [], {}, {}
    t0, dead = now(), None
    for n, text in sorted(fo.md.items()):
        for ln in text.split("\n"):
            if POINTER_LINE.match(ln):
                recs.append({"uuid": POINTER_LINE.match(ln).group(1), "status": "포인터", "file": n})
                continue
            m = QUOTE_LINE.match(ln)
            if not m:
                if n == "12-evidence.md" and MSG_LINE.match(ln):
                    out.append(item("C6", "FAIL", n, f"근거 줄 형식 오류: {ln[:30]}"))
                    recs.append({"uuid": (re.match(r"^- \[msg:([^\]]*)", ln).group(1))[:36], "status": "형식오류", "file": n})
                continue
            uid, quote, paren = m.groups()
            parts = [p.strip() for p in paren.split("·")]
            if len(parts) < 2 or not re.match(r"\d{4}-\d{2}-\d{2}(?!\d)", parts[0]) or not "·".join(parts[1:]).strip():
                out.append(item("C6", "FAIL", n, f"[msg:{uid}] 날짜·한정 표기 없음"))
                recs.append({"uuid": uid, "status": "형식오류", "file": n})
                continue
            if dead is not None and uid not in cache or now() - t0 > C6_TOTAL_TIMEOUT:
                why = "전체 시간 초과" if dead is None else "앞선 조회 실패"
                out.append(item("C6", "INFO", n, f"C6 미실시 [msg:{uid}] ({why})"))
                recs.append({"uuid": uid, "status": "미실시", "file": n})
                continue
            r = cache.get(uid)
            if r is None:
                r = cache[uid] = fetch(uid)
            if r[0] == "error":
                dead = r[1]   # 접속 실패면 나머지도 곧 실패한다 — 90초를 쓰지 않고 곧장 미실시로
                out.append(item("C6", "INFO", n, f"C6 미실시 [msg:{uid}] ({r[1]})"))
                recs.append({"uuid": uid, "status": "미실시", "file": n})
            elif r[0] == "none":
                out.append(item("C6", "FAIL", n, f"[msg:{uid}] 메시지 없음"))
                recs.append({"uuid": uid, "status": "메시지 없음", "file": n})
            elif r[0] == "ambiguous":
                out.append(item("C6", "INFO", n, f"[msg:{uid}] 중복 접두"))
                recs.append({"uuid": uid, "status": "모호", "file": n})
            else:
                ok = cx.quote_matches(quote, r[1])
                sid = r[2] if len(r) > 2 else None
                if sid and sid not in repos:
                    repos[sid] = repo_of(sid)
                repo = repos.get(sid)
                if not ok:
                    out.append(item("C6", "FAIL", n, f"[msg:{uid}] 인용 불일치"))
                    recs.append({"uuid": uid, "status": "미일치", "file": n})
                else:
                    recs.append({"uuid": uid, "status": "일치", "file": n})
                if isinstance(repo, tuple):
                    out.append(item("C6", "INFO", n, f"C6 미실시 [msg:{uid}] 저장소 확인({repo[1]})"))
                elif not (repo or "").rstrip("/").endswith("/nixos"):
                    out.append(item("C6", "FAIL", n, f"[msg:{uid}] nixos 대화가 아님"))
                    recs[-1]["status"] = "nixos 아님"
    npt = sum(1 for r in recs if r["status"] == "포인터")
    if npt:
        out.append(item("C6", "INFO", "12-evidence.md", f"포인터 줄 {npt}건(인용 검사 대상 아님)"))
    return out, recs


def quotes_text(recs: list) -> str:
    return head_text("quotes") + "\n".join(f"{r['uuid']}\t{r['status']}\t{r['file']}" for r in recs) + ("\n" if recs else "(인용 줄 없음)\n")


def head_text(module_note: str = "facts") -> str:
    return f"---\n종류: 사실\n모듈: {FACTS_MODULE}\n작성: tool:protocolcheck\n근거: 없음\n---\n"


def check_c7(fo: Folder) -> list:
    out = []
    names = [n for n in sorted(fo.md)]
    tot = 0
    for n in names:
        L = len(fo.md[n])
        tot += L
        if L > LEN_WARN:
            out.append(item("C7", "WARN", n, f"2,000자 초과({L}자)"))
    nonsplit = [n for n in names if not is_split(n)]
    if len(nonsplit) > MAX_INTERPRETIVE_FILES:
        out.append(item("C7", "WARN", "INDEX.md", f"해석분 파일 {len(nonsplit)}개(6개 초과)"))
    if tot > LEN_TOTAL_WARN:
        out.append(item("C7", "WARN", "INDEX.md", f"해석분 합 {tot}자(12,000자 초과)"))
    for n in sorted(fo.facts):
        try:
            sz = os.path.getsize(os.path.join(fo.dir, n))
        except OSError:
            continue
        if sz > FACTS_MAX_BYTES:
            out.append(item("C7", "WARN", n, f"사실분 20KB 초과({sz}B)"))
    return out


def parse_base(fo: Folder) -> dict:
    t = fo.facts.get("facts/base.txt") or ""
    d = {"head": None, "cwd": None, "status": [], "hashes": {}}
    for ln in t.split("\n"):
        m = re.match(r"^저장소 HEAD: (\S+)", ln)
        if m:
            d["head"] = None if m.group(1) == "없음" else m.group(1)
        m = re.match(r"^작업 폴더: (.+)$", ln)
        if m:
            d["cwd"] = m.group(1).strip()
        m = re.match(r"^상태: (.+)$", ln)
        if m:
            d["status"].append(m.group(1))
        m = re.match(r"^해시: ([0-9a-f]{64}) (.+)$", ln)
        if m:
            d["hashes"][m.group(2)] = m.group(1)
    return d


def norm_path(p: str, root: str | None) -> str:
    p = p.strip()
    while p.startswith("./"):
        p = p[2:]
    if root and p.startswith(root.rstrip("/") + "/"):
        p = p[len(root.rstrip("/")) + 1:]
    return p


def check_c8(fo: Folder) -> list:
    if fo.klass() != "구현 결과" or "50-before-after.md" not in fo.md:
        return []
    ds = fo.facts.get("facts/diff-stat.txt")
    if ds is None:
        return [item("C8", "INFO", "50-before-after.md", "C8 미실시(facts/diff-stat.txt 없음)")]
    root = parse_base(fo)["cwd"]
    actual = {norm_path(m.group(1), root) for m in (re.match(r"^파일: (.+)$", l) for l in ds.split("\n")) if m}
    meta, body = parse_head(fo.md["50-before-after.md"])
    sec = section(body if meta is not None else fo.md["50-before-after.md"], "바뀐 파일") or []
    doc = set()
    for c in re.findall(r"`([^`\n]+)`", "\n".join(sec)):
        if "/" in c or re.search(r"\.\w+$", c):
            doc.add(norm_path(c, root))
    out = []

    def matched(p: str) -> bool:
        return any(a.startswith(p) for a in actual) if p.endswith("/") else p in actual

    for p in sorted(doc):
        if not matched(p):
            out.append(item("C8", "FAIL", "50-before-after.md", f"안 바뀐 파일 {p}"))
    extra = sorted(a for a in actual if not any((a.startswith(p) if p.endswith("/") else a == p) for p in doc))
    if extra:
        out.append(item("C8", "WARN", "50-before-after.md", f"문서에 없는 변경 파일 {len(extra)}건: " + ", ".join(extra[:8])))
    return out


def check_c9(fo: Folder) -> list:
    import ctx_secrets as cs
    import ctx_store as st
    out = []
    for n, text in sorted(fo.md.items()):
        if cs.find_candidates(text) or st.SECRET_PATTERNS.search(text):
            out.append(item("C9", "FAIL", n, "비밀 패턴이 걸림"))
    return out


def check_c10(fo: Folder) -> list:
    t = fo.facts.get("facts/request-items.txt")
    if t is None:
        return []
    nums = []
    for ln in t.split("\n"):
        m = re.match(r"^\s*(\d+)[.)]", ln)
        if m and m.group(1) not in nums:
            nums.append(m.group(1))
    if not nums:
        return [item("C10", "INFO", "facts/request-items.txt", "번호 항목 없는 프롬프트")]
    hay = (fo.md.get("01-unknown.md") or "") + "\n" + (fo.md.get("00-cover.md") or "")
    out = []
    for N in nums:
        if not (re.search(r"요청\s*" + N + r"(?!\d)", hay) or re.search(r"(?<![\d.])" + N + r"\s*번", hay)):
            out.append(item("C10", "WARN", "01-unknown.md", f"요청 {N} 언급 없음"))
    return out


def check_c11(fo: Folder) -> list:
    """용어 풀이(판정 없음 — INFO 로 기록만, 정확도 측정용)."""
    gl = fo.md.get("10-glossary.md") or ""
    out = []
    seen = set()
    for n, text in sorted(fo.md.items()):
        if n == "10-glossary.md":
            continue
        lines = strip_code(text).split("\n")
        for i, ln in enumerate(lines):
            cands = re.findall(r"\b[A-Z][A-Z0-9-]{1,}\b", ln) + [m.group(1) for m in re.finditer(r"([가-힣A-Za-z0-9·_-]{2,20})(?:이|가)?란", ln)]
            for c in cands:
                if c in seen:
                    continue
                seen.add(c)
                ctx = "\n".join(lines[max(0, i - 1):i + 2])
                glossed = c in gl or bool(re.search(r"[:—(]", ctx))
                if not glossed:
                    out.append(item("C11", "INFO", n, f"용어 후보 {c} 풀이 없음"))
                if len(out) >= 30:
                    return out
    return out


# ---------------------------------------------------------------- 실행
def run_checks(d: str, mode: str, quote_records=None, quote_items=None) -> dict:
    """mode: working(작업중 Stop: C1·C3·C9) · attempt(마감 시도: C6 제외 전부) · final(수동 마감: 전부). 결과 dict(items·counts…). 내부 오류는 INFO C0 로 기록하고 던지지 않는다."""
    fo = Folder(d)
    items = []

    def guarded(fn, *a):
        try:
            return fn(*a)
        except Exception as e:   # 검사기 오류는 FAIL 도 통과도 아님 — INFO C0
            return [item("C0", "INFO", "-", f"내부오류 {fn.__name__}: {type(e).__name__}: {str(e)[:60]}")]

    final = mode == "final"
    if mode == "working":
        items += guarded(check_c1, fo, False)
        items += guarded(check_c3, fo, True)
        items += guarded(check_c9, fo)
    else:
        c1 = guarded(check_c1, fo, final)
        items += c1
        if fo.index is None:
            pass   # INDEX 없음: C1 FAIL 하나만(다른 규칙은 파일이 없어 무의미)
        else:
            items += guarded(check_c2, fo)
            items += guarded(check_c3, fo, False)
            items += guarded(check_c4, fo)
            items += guarded(check_c4b, fo)
            items += guarded(check_c5, fo)
            if final:
                if quote_items is not None:
                    items += quote_items
            items += guarded(check_c7, fo)
            items += guarded(check_c8, fo)
            items += guarded(check_c9, fo)
            items += guarded(check_c10, fo)
            items += guarded(check_c11, fo)
    counts = {lv: sum(1 for i in items if i["level"] == lv) for lv in ("FAIL", "WARN", "INFO")}
    return {"mode": mode, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "dir": d, "state": fo.state(), "class": fo.klass(), "counts": counts, "items": items}


def write_result(d: str, res: dict) -> None:
    cd = os.path.join(d, ".check")
    os.makedirs(cd, mode=0o700, exist_ok=True)
    write_tool_file(os.path.join(cd, "result.json"), json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    write_tool_file(os.path.join(cd, "CHECK.md"), render_check_md(res))


def render_check_md(res: dict) -> str:
    c = res["counts"]
    out = [f"# 규약 검사 결과 — {res['mode']} · {res['ts']}", "",
           f"- 상태: {res.get('state') or '없음'} · 분류: {res.get('class') or '없음'}",
           f"- FAIL {c['FAIL']} · WARN {c['WARN']} · INFO {c['INFO']}",
           "- 이 검사는 형식·문자열 존재만 본다. 읽히는지·의미가 맞는지는 못 본다(통과 ≠ 읽힘).", "",
           "| 판정 | ID | 파일 | 사유 |", "|---|---|---|---|"]
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    for i in sorted(res["items"], key=lambda x: (order[x["level"]], x["id"], x["file"])):
        out.append(f"| {i['level']} | {i['id']} | {i['file']} | {i['reason'].replace('|', '/')} |")
    return "\n".join(out) + "\n"


def fails(res: dict) -> list:
    return [i for i in res["items"] if i["level"] == "FAIL"]


def rewindable(res: dict) -> list:
    return sorted((i for i in fails(res) if i["id"] in REWIND_IDS), key=lambda i: (REWIND_IDS.index(i["id"]), i["file"]))


def block_reason(res: dict) -> str:
    """(c) 되돌림 사유 — 동결 문구(protocol_text)에 FAIL 항목(최대 5개, 줄마다 44자 이내)을 끼운다."""
    import protocol_text as T
    its = rewindable(res)
    lines = []
    for i in its[:5]:
        ln = f"- {i['id']} {i['file']}: {i['reason']}"
        lines.append(ln if len(ln) <= 44 else ln[:43] + "…")
    if len(its) > 5:
        lines.append(f"(외 {len(its) - 5}건은 .check/CHECK.md 에 있다)")
    return T.C_HEAD + "\n" + "\n".join(lines) + "\n" + T.C_TAIL


# ---------------------------------------------------------------- facts
def git(cwd: str, *args, timeout: int = 10) -> str | None:
    try:
        r = subprocess.run(["git", "-C", cwd, "-c", "core.quotepath=false", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def register_sha(d: str, rels) -> None:
    """facts.sha 에 도구가 쓴 facts 파일의 해시를 등록한다(기존 항목은 유지, 도구가 쓴 파일만)."""
    p = os.path.join(d, ".check", "facts.sha")
    cur = {}
    for ln in (read(p) or "").split("\n"):
        m = re.match(r"^([0-9a-f]{64})\s+(\S.*)$", ln)
        if m:
            cur[m.group(2).strip()] = m.group(1)
    for r in rels:
        h = sha256_file(os.path.join(d, r))
        if h:
            cur[r] = h
    os.makedirs(os.path.join(d, ".check"), mode=0o700, exist_ok=True)
    write_tool_file(p, "".join(f"{h}  {r}\n" for r, h in sorted(cur.items())))


def refresh_diff_stat(d: str) -> bool:
    """facts/diff-stat.txt: `git diff --stat <시작 HEAD>` + 변경·미추적 파일 목록(`파일: <경로>`). 시작 때 이미 변경돼 있던 파일은 내용 해시가 달라졌을 때만 넣는다."""
    fo = Folder(d)
    b = parse_base(fo)
    cwd = b["cwd"]
    if not cwd or not os.path.isdir(cwd):
        return False
    head = b["head"]
    lines = [head_text(), f"시작 HEAD: {head or '없음'}", f"작업 폴더: {cwd}", "--- git diff --stat ---"]
    files = []
    if head:
        stat = git(cwd, "diff", "--stat", head)
        lines.append((stat or "").rstrip() or "(변경 없음)")
        names = git(cwd, "diff", "--name-only", head) or ""
        files += [x for x in names.split("\n") if x.strip()]
    else:
        lines.append("(git 저장소가 아니거나 HEAD 가 없다)")
    others = git(cwd, "ls-files", "--others", "--exclude-standard") or ""
    files += [x for x in others.split("\n") if x.strip()]
    dirty_at_start = {s[3:].strip() if len(s) > 3 else s for s in b["status"]}
    top = (git(cwd, "rev-parse", "--show-toplevel") or cwd).strip()
    keep = []
    for f in sorted(set(files)):
        if f in dirty_at_start:
            old = b["hashes"].get(f)
            cur = sha256_file(os.path.join(top, f))
            if old is not None and old == cur:
                continue
        keep.append(f)
    lines.append("--- 변경·미추적 파일 ---")
    lines += [f"파일: {f}" for f in keep] or ["(없음)"]
    write_tool_file(os.path.join(d, "facts", "diff-stat.txt"), "\n".join(lines) + "\n")
    register_sha(d, ["facts/diff-stat.txt"])
    return True


def cmd_facts(a) -> int:
    d = os.path.abspath(a.dir)
    ok = refresh_diff_stat(d)
    print("facts/diff-stat.txt " + ("갱신" if ok else "못 만듦(base.txt 의 작업 폴더 없음)"))
    if not a.no_quotes:
        _items, recs = collect_quotes(Folder(d))
        write_tool_file(os.path.join(d, "facts", "quotes.txt"), quotes_text(recs))
        register_sha(d, ["facts/quotes.txt"])
        print(f"facts/quotes.txt {len(recs)}건")
    return 0


def cmd_run(a) -> int:
    d = os.path.abspath(a.dir)
    fo = Folder(d)
    if not os.path.isdir(d):
        print(f"폴더 없음: {d}", file=sys.stderr)
        return 2
    mode = "final" if a.final else ("working" if fo.state() == "작업중" else "attempt")
    qi = qr = None
    if mode != "working":
        if fo.index is not None or a.final:
            try:
                refresh_diff_stat(d)
            except Exception:
                pass
    if mode == "final" and fo.index is not None:
        qi, qr = collect_quotes(Folder(d))
        write_tool_file(os.path.join(d, "facts", "quotes.txt"), quotes_text(qr))
        register_sha(d, ["facts/quotes.txt"])
    res = run_checks(d, mode, quote_items=qi)
    write_result(d, res)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        c = res["counts"]
        print(f"[{mode}] FAIL {c['FAIL']} · WARN {c['WARN']} · INFO {c['INFO']}  → {os.path.join(d, '.check', 'CHECK.md')}")
        for i in res["items"]:
            if i["level"] != "INFO":
                print(f"  {i['level']} {i['id']} {i['file']}: {i['reason']}")
    return 1 if res["counts"]["FAIL"] else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        if os.environ.get("LLM_PROTOCOL_PILOT") != "1":   # 게이트: 무동작·무지연(무거운 import 전에 끝낸다)
            return 0
        import protocolhook
        return protocolhook.main(argv[1:])
    p = argparse.ArgumentParser(prog="protocolcheck", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("dir"); r.add_argument("--final", action="store_true"); r.add_argument("--json", action="store_true"); r.set_defaults(f=cmd_run)
    f = sub.add_parser("facts"); f.add_argument("dir"); f.add_argument("--no-quotes", action="store_true"); f.set_defaults(f=cmd_facts)
    h = sub.add_parser("hook"); h.add_argument("which", choices=["prompt", "stop"])
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
