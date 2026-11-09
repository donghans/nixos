"""llmhost_artifacts — llmui 9 「호스트」 탭 S3: 세션이 만든 산출물(색인 INDEX.md → 파일)을 읽어 보이는 순수 함수. 화면·호스트·DB 와 무관하다(표준 라이브러리만).

설계: ctx 문서 plan llm-trust/13-p5prime-3-llmui-host-tab §4 S3, 색인 형식은 plan llm-trust/09 §5-3(표 6열: 파일·한 줄 요약·언제 읽나·근거 대화 범위·종류·검사).
- parse_index: INDEX.md → 머리(`- 키: 값`)·「지금 결정할 것」·파일 표. 열 순서가 아니라 머리글 이름으로 칸을 찾는다(없으면 앞 6칸 순서).
- resolve_path / read_file: 색인에 적힌 경로를 **산출물 폴더 밖으로 못 나가게** 검사해 읽는다(절대 경로·`..`·밖을 가리키는 심볼릭 링크·일반 파일이 아닌 것은 거부).
- load_check / row_status: `.check/result.json`(검사기 protocolcheck 가 쓴 것)을 읽어 파일별 검사 상태를 낸다. 검사기 결과가 LLM 이 쓴 색인의 「검사」 칸보다 우선한다.
- render: 접힌/펼친 항목을 [(스타일, 글)] 로 그린다. 비밀 치환은 호출자(llmui)가 모든 줄에 마스커를 씌운다 — 이 모듈은 치환을 모른다.
이 화면의 검사 상태는 형식·문자열 존재만 본 결과다(검사 통과 ≠ 읽힘 — plan 09 §7).
"""
from __future__ import annotations

import json
import os
import re

STYLES = ("head", "meta", "decide", "row", "row_sel", "ok", "warn", "fail", "fact", "interp", "body", "dim", "err")

FILE_MAX_BYTES = 200_000     # 한 파일을 읽는 상한(넘으면 앞부분만)
SHOW_MAX_CHARS = 12_000      # 한 파일을 화면에 보이는 상한
INDEX_NAME = "INDEX.md"
COLS = ("파일", "한 줄 요약", "언제 읽나", "근거 대화 범위", "종류", "검사")
NOTE_NOT_READ = "검사 통과는 읽힘·의미 보장이 아니다(형식·문자열 존재만 본 결과)."


# ---------------------------------------------------------------- 경로 검사
def within(base: str, path: str) -> bool:
    """realpath 로 풀었을 때 path 가 base(자기 자신 포함) 안인가."""
    try:
        b, p = os.path.realpath(base), os.path.realpath(path)
        return os.path.commonpath([b, p]) == b
    except (ValueError, OSError):
        return False


def clean_cell_file(c: str) -> str:
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    return c.replace("`", "").strip()


def resolve_path(root: str, rel: str):
    """(절대경로, None) 또는 (None, 이유). root 는 산출물 폴더."""
    rel = (rel or "").strip()
    if not rel:
        return None, "파일 이름이 비어 있다"
    if "\x00" in rel:
        return None, "경로에 NUL 이 있다"
    if os.path.isabs(rel) or rel.startswith("~"):
        return None, "절대 경로는 열지 않는다(산출물 폴더 안의 상대 경로만)"
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts:
        return None, "`..` 이 있는 경로는 열지 않는다"
    p = os.path.join(root, *[x for x in parts if x not in ("", ".")])
    if not within(root, p):
        return None, "산출물 폴더 밖을 가리키는 경로(심볼릭 링크 포함)라 열지 않는다"
    if not os.path.exists(p):
        return None, "파일이 없다"
    if not os.path.isfile(os.path.realpath(p)):
        return None, "일반 파일이 아니다"
    return p, None


def read_file(root: str, rel: str):
    """(글, 안내 또는 None, 오류 또는 None). 안내는 잘림·인코딩 대체 같은 것."""
    p, err = resolve_path(root, rel)
    if err:
        return None, None, err
    try:
        with open(p, "rb") as f:
            raw = f.read(FILE_MAX_BYTES + 1)
    except OSError as e:
        return None, None, f"읽지 못함: {e.strerror or e}"
    note = None
    if len(raw) > FILE_MAX_BYTES:
        raw = raw[:FILE_MAX_BYTES]
        note = f"앞 {FILE_MAX_BYTES:,}바이트만 읽었다"
    if b"\x00" in raw[:4096]:
        return None, None, "텍스트 파일이 아니다(바이너리)"
    text = raw.decode("utf-8", errors="replace")
    if "�" in text:
        note = ((note + " · ") if note else "") + "UTF-8 이 아닌 바이트가 있어 일부를 대체했다"
    return text, note, None


# ---------------------------------------------------------------- 색인 파싱
def _cells(line: str):
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(cells) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", c.replace(" ", "")) for c in cells if c != "") and any(cells)


def parse_index(text: str) -> dict:
    """INDEX.md → {title, meta{키:값}, decide[줄], rows[{file, summary, when, range, kind, check}], warnings[]}. 못 읽는 줄은 건너뛰고 warnings 에 적는다."""
    out = {"title": "", "meta": {}, "decide": [], "rows": [], "warnings": []}
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":                       # 머리(---) 건너뜀
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    section = None
    header: list | None = None
    in_code = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^#\s+(.*)$", ln)
        if m and not out["title"]:
            out["title"] = m.group(1).strip()
            continue
        m = re.match(r"^##\s+(.*)$", ln)
        if m:
            section = m.group(1).strip()
            header = None
            continue
        m = re.match(r"^- (분류|켜진 모듈|세션|상태|만든 시각)\s*[:：]\s*(.*?)\s*$", ln)      # protocolcheck.Folder.index_lines 와 같은 키(위치 불문)
        if m and m.group(1) not in out["meta"]:
            out["meta"][m.group(1)] = m.group(2)
            continue
        if section and section.startswith("지금 결정할 것") and ln.strip() and not ln.strip().startswith("|"):
            out["decide"].append(ln.rstrip())
            continue
        cells = _cells(ln)
        if cells is None:
            continue
        if _is_sep(cells):
            continue
        if header is None:
            if "파일" in cells:
                header = cells
                continue
            continue                                              # 머리글 없는 표는 파일 표로 보지 않는다
        if not any(cells):
            continue

        def col(name, default_idx):
            if name in header:
                i = header.index(name)
            else:
                i = default_idx
            return cells[i].strip() if i < len(cells) else ""
        f = clean_cell_file(col("파일", 0))
        if not f:
            out["warnings"].append("파일 칸이 빈 줄을 건너뜀")
            continue
        out["rows"].append({"file": f, "summary": col("한 줄 요약", 1), "when": col("언제 읽나", 2), "range": col("근거 대화 범위", 3),
                            "kind": col("종류", 4), "check": col("검사", 5)})
    return out


# ---------------------------------------------------------------- 검사 상태
def load_check(root: str) -> dict | None:
    """`.check/result.json`(protocolcheck) → dict. 없거나 못 읽으면 None."""
    p = os.path.join(root, ".check", "result.json")
    if not within(root, p) or not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else None
    except (OSError, ValueError):
        return None


def row_status(row: dict, check: dict | None):
    """(라벨, 스타일 ok|warn|fail|dim, 출처). 검사기 결과(.check)가 있으면 그것을 우선한다."""
    name = row["file"]
    idx = (row.get("check") or "").strip()
    if check is not None:
        mine = [i for i in check["items"] if isinstance(i, dict) and i.get("file") == name]
        fails = [i for i in mine if i.get("level") == "FAIL"]
        warns = [i for i in mine if i.get("level") == "WARN"]
        if fails:
            return "미충족 " + ", ".join(sorted({str(i.get("id")) for i in fails})), "fail", "검사기"
        if warns:
            return "경고 " + ", ".join(sorted({str(i.get("id")) for i in warns})), "warn", "검사기"
        return "통과", "ok", "검사기"
    if not idx:
        return "검사 안 됨", "dim", "색인"
    if idx.startswith("통과"):
        return idx, "ok", "색인"
    if idx.startswith("미충족") or idx.startswith("FAIL"):
        return idx, "fail", "색인"
    return idx, "warn", "색인"


def check_summary(check: dict | None) -> str:
    if check is None:
        return "검사기 결과(.check/result.json) 없음 — 색인의 「검사」 칸만 보인다(LLM 이 쓴 값이라 검사기 결과가 아니다)"
    c = check.get("counts") or {}
    return f"검사기 결과: FAIL {c.get('FAIL', 0)} · WARN {c.get('WARN', 0)} · INFO {c.get('INFO', 0)}  ({check.get('mode', '?')} · {check.get('ts', '?')})"


# ---------------------------------------------------------------- 불러오기
def load(root: str, base: str | None = None) -> dict:
    """산출물 폴더를 한 번 읽는다 → {root, ok, err, index, check}. base 가 있으면 root 가 그 안(세션 작업 폴더 안)이어야 한다."""
    root = os.path.abspath(os.path.expanduser(root))
    res = {"root": root, "ok": False, "err": None, "index": None, "check": None}
    if base is not None and not within(base, root):
        res["err"] = f"세션 작업 폴더({base}) 밖의 폴더는 열지 않는다"
        return res
    if not os.path.isdir(root):
        res["err"] = f"폴더가 없다: {root}"
        return res
    text, _note, err = read_file(root, INDEX_NAME)
    if err:
        res["err"] = f"{INDEX_NAME} 를 읽지 못함: {err}"
        return res
    res["index"] = parse_index(text)
    res["check"] = load_check(root)
    res["ok"] = True
    return res


def find_candidates(base: str, limit: int = 20) -> list:
    """base 와 그 아래 한 단계에서 INDEX.md 가 있는 폴더(심볼릭 링크로 밖을 가리키는 것은 제외)."""
    out = []
    try:
        if os.path.isfile(os.path.join(base, INDEX_NAME)):
            out.append(base)
        for n in sorted(os.listdir(base)):
            d = os.path.join(base, n)
            if os.path.isdir(d) and within(base, d) and os.path.isfile(os.path.join(d, INDEX_NAME)):
                out.append(d)
            if len(out) >= limit:
                break
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 그리기
def render(data: dict, expanded: set, cursor: int = 0, contents: dict | None = None):
    """data=load() 결과. expanded=펼친 행 번호 집합, cursor=선택한 행. 반환 ([(스타일, 글)], 행→시작 줄 번호 목록).
    contents: 행 번호 → (글, 안내, 오류) 캐시(없으면 그때 읽는다; 호출자가 dict 를 넘기면 채워 넣는다)."""
    out: list = []
    starts: list = []
    if not data.get("ok"):
        return [("err", data.get("err") or "열지 못함")], starts
    idx, check, root = data["index"], data["check"], data["root"]
    out.append(("head", f"산출물 — {idx['title'] or root}"))
    out.append(("dim", root))
    for k in ("분류", "상태", "세션", "켜진 모듈"):
        if k in idx["meta"]:
            out.append(("meta", f"{k}: {idx['meta'][k]}"))
    out.append(("dim", check_summary(check)))
    out.append(("dim", NOTE_NOT_READ))
    if idx["decide"]:
        out.append(("head", "지금 결정할 것 (LLM 의 해석)"))
        out.extend(("decide", "  " + ln.strip()) for ln in idx["decide"][:12])
    for w in idx["warnings"]:
        out.append(("warn", f"색인 경고: {w}"))
    if not idx["rows"]:
        out.append(("warn", "색인에 파일 표가 없다(머리글에 「파일」 칸이 있는 표)."))
    out.append(("head", f"파일 {len(idx['rows'])}개 — ↑↓ 이동 · Enter/Space 접기·펴기 · ←→ 접기/펴기 · F2 모두 펴기 · F3 모두 접기"))
    for i, row in enumerate(idx["rows"]):
        starts.append(len(out))
        label, st, src = row_status(row, check)
        sel = i == cursor
        mark = "▼" if i in expanded else "▶"
        kind = row["kind"] or "?"
        out.append(("row_sel" if sel else "row", f"{'>' if sel else ' '} {mark} {row['file']}  — {row['summary'] or '(요약 없음)'}"))
        out.append(("fact" if kind.startswith("사실") else "interp" if kind.startswith("해석") else "dim",
                    f"      종류: {kind + ('  (도구가 모은 사실분)' if kind.startswith('사실') else '  (LLM 의 해석 — 사실처럼 읽지 말 것)' if kind.startswith('해석') else '')}"
                    f"   언제 읽나: {row['when'] or '-'}   근거: {row['range'] or '-'}"))
        out.append((st, f"      검사: {label}  [{src}]"))
        if i in expanded:
            if contents is not None and i in contents:
                got = contents[i]
            else:
                got = read_file(root, row["file"])
                if contents is not None:
                    contents[i] = got
            text, note, err = got
            if err:
                out.append(("err", f"      ✗ {err}"))
            else:
                if note:
                    out.append(("warn", f"      ({note})"))
                body = text if len(text) <= SHOW_MAX_CHARS else text[:SHOW_MAX_CHARS]
                out.append(("dim", "      ┌" + "─" * 40))
                out.extend(("body", "      │ " + ln) for ln in body.replace("\r\n", "\n").split("\n"))
                if len(text) > SHOW_MAX_CHARS:
                    out.append(("warn", f"      │ … (화면에는 앞 {SHOW_MAX_CHARS:,}자만 — {len(text) - SHOW_MAX_CHARS:,}자 더 있음)"))
                out.append(("dim", "      └" + "─" * 40))
    return out, starts


def to_text(lines) -> str:
    return "\n".join(t for _s, t in lines)
