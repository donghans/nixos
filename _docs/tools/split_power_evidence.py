#!/usr/bin/env python3
"""split_power_evidence.py — 전력 근거 장부(`_docs/content/explanation/power-evidence.md`, 한 행이 표의 한 줄)를 행마다 파일로 나눠
`_docs/content/explanation/power-evidence-ledger/` 에 쓴다. 목적: git diff 가 행 단위·문장 단위로 보이게 하고 한 줄이 1000자를 넘는 가독성 문제를 푼다.

사용: split_power_evidence.py build   — 원본 장부에서 index.md 와 rows/NNN.md 를 (다시) 만든다. 원본은 건드리지 않는다.
      split_power_evidence.py check   — 검사(종료 코드 0=통과). 원본 장부에 있는 행: ① 행 파일 전체가 원본에서 다시 만든 것과 글자 단위로 같다(결론·제목·안내문 포함)
                                       ② 상세 줄을 한 칸 공백으로 이으면 원문과 같다 ③ 색인 줄이 같다. 원본에 없는 번호(새 행): 모양(제목·소제목·결론)과 색인 등재만 본다(결론 300자 초과는 경고).
규칙(내용 보존): 열 내용은 바꾸지 않는다. 상세 칸은 문장 끝(`. ` 앞이 한글·닫는 괄호·강조 기호·역따옴표, 역따옴표 밖)에서 줄바꿈만 하며, 줄을 한 칸 공백으로 이으면 원문과 정확히 같다.
정본: 2026-10-26 이후 새 행은 이 폴더(rows/N.md + index.md 한 줄)에만 쓴다. 기존 장부의 표는 그때까지의 행으로 동결한다(비교용)."""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(os.path.dirname(HERE), "content", "explanation")
OLD = os.path.join(CONTENT, "power-evidence.md")
NEW = os.path.join(CONTENT, "power-evidence-ledger")      # 기존 `power-evidence.md` 와 사이트 경로가 겹치지 않도록 다른 이름
ROWS = os.path.join(NEW, "rows")
COLS = {2: "수준", 3: "근거(조건)", 4: "수준을 올리려면"}      # 셀 번호(0부터, 0=번호 1=주장) → 소제목. 3열 행은 수준만 있다
ROW_RE = re.compile(r"^\| (\d+) \| ")
LEAD_MAX = 300           # 새 행 결론 길이 권고


def split_cells(line):
    """`| a | b | c |` → [a, b, c]. 역따옴표 안의 ` | ` 는 구분자로 보지 않는다. 왕복이 안 되면 예외."""
    assert line.startswith("| ") and line.endswith(" |"), line[:40]
    body, cells, cur, tick, i = line[2:-2], [], [], False, 0
    while i < len(body):
        ch = body[i]
        if ch == "`":
            tick = not tick
        if not tick and body.startswith(" | ", i):
            cells.append("".join(cur)); cur = []; i += 3; continue
        cur.append(ch); i += 1
    cells.append("".join(cur))
    assert "| " + " | ".join(cells) + " |" == line, "셀 분해 왕복 실패: " + line[:60]
    return cells


def sentence_lines(text):
    """문장 끝에서만 줄바꿈(역따옴표 안은 제외). 줄을 ' ' 로 이으면 원문과 같다."""
    out, cur, tick, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        cur.append(ch)
        if ch == "`":
            tick = not tick
        if (ch == "." and not tick and i + 2 < len(text) and text[i + 1] == " " and text[i + 2] != " "
                and i > 0 and re.match(r"[가-힣\)\]\*`]", text[i - 1])):
            out.append("".join(cur)); cur = []
            i += 2                       # 문장 끝 점 다음의 공백 한 칸은 줄바꿈이 대신한다(이으면 복원)
            continue
        i += 1
    out.append("".join(cur))
    return out


def trim(t, n):
    """n 자를 넘으면 마지막 공백에서 자르되 열린 괄호 이후는 버리고 …를 붙인다."""
    if len(t) <= n:
        return t
    t = t[:n]
    t = t[:t.rfind(" ")] if " " in t else t
    for o, c in ("()", "[]", "〔〕", "「」"):
        if t.count(o) > t.count(c):
            t = t[:t.rfind(o)].rstrip()
    return t.rstrip(" ,;·—-") + "…"


def plain(t):
    """색인·제목용: 강조 기호·역따옴표·큰따옴표·역슬래시 제거, 표 구분자는 /. 열린 채 끝나는 마크업과 YAML 제목 깨짐을 막는다."""
    return re.sub(r"[*`\"\\]", "", t).replace("|", "/")


def short(s, n):
    s = plain(s)
    return s if len(s) <= n else trim(s, n)


def lead_of(cell):
    """행의 결론: 맨 앞 굵은 문장, 없으면 첫 문장(최대 240자, 괄호가 열린 채 끝나지 않게 다듬음)."""
    m = re.match(r"\*\*(.+?)\*\*", cell)
    if m:
        return m.group(1)
    return trim(sentence_lines(cell)[0], 240)


def parse_old():
    rows = []
    for line in open(OLD, encoding="utf-8").read().split("\n"):
        m = ROW_RE.match(line)
        if m:
            rows.append((int(m.group(1)), line))
    return rows


def render_row(n, line):
    cells = split_cells(line)
    assert int(cells[0]) == n
    lead = lead_of(cells[1])
    parts = [f"# 장부 #{n} — {short(lead, 100)}", "",
             f"> 장부 #{n} 행. 원본 `power-evidence.md` 표의 한 줄을 열 단위로 나눈 것이다(내용 변경 없음, 문장 단위로 줄만 바꿈). 새 행은 이 모양으로 쓴다.", "",
             "## 결론", "", lead, "", "## 상세", ""] + sentence_lines(cells[1]) + [""]
    for idx in range(2, len(cells)):
        parts += [f"## {COLS.get(idx, f'열 {idx + 1}')}", "", cells[idx], ""]
    return "\n".join(parts).rstrip("\n") + "\n"


def index_line(n, line):
    cells = split_cells(line)
    grade = cells[2] if len(cells) > 2 else ""
    return f"| {n} | {short(lead_of(cells[1]), 240)} | {short(grade, 120)} | [행](rows/{n:03d}.md) |"


INDEX_HEAD = """# 전력·입력 조사 근거 장부 — 행 단위 색인

**정본은 이 폴더다.** 2026-10-26 이후 새 행은 `rows/N.md` 와 아래 표의 한 줄로만 쓴다. 기존 장부 [`power-evidence`](../power-evidence) 의 표는 그때까지의 행을 담은 **동결 사본**(비교·diff 용)이고, 용어·단위 정정표와 남은 계측 목록만 아직 거기에 있다.

왜 나눴나: 기존 장부는 측정 하나가 표의 한 줄이라 1000자를 넘는 행이 있었고(최대 약 1,600자) 한 글자만 고쳐도 git 이 행 전체를 바뀐 것으로 보였다. 이 폴더는 **행마다 파일**로 나누고 상세는 **문장마다 줄**을 바꿔 diff 가 문장 단위로 보인다.

**행 파일의 모양**: `# 장부 #N — 결론` → `## 결론`(첫 굵은 문장 한 개) → `## 상세`(원문, 문장마다 줄) → `## 수준`(등급·근거 수준) → 필요하면 `## 근거(조건)`·`## 수준을 올리려면`. 정정은 상세 맨 끝에 날짜와 함께 덧붙인다. 문장 줄바꿈은 코드 스팬(`` ` ``) 밖의 「한글·닫는 괄호·강조 기호 뒤의 마침표 + 공백」에서만 한다(소수점·영문 약어 뒤는 자르지 않는다).

**검사**: `python3 _docs/tools/split_power_evidence.py check` — 기존 장부의 행은 원본에서 다시 만든 것과 글자 단위로 같은지(결론·제목 포함), 새 행은 모양과 색인 등재를 본다. 결론이 300자를 넘는 새 행은 경고한다.

**새 행 쓰는 법**: ① `rows/N.md` 를 위 모양으로 만든다 ② 이 표에 `| N | 결론 | 수준 | [행](rows/NNN.md) |` 한 줄을 더한다(위쪽, 번호 내림차순) ③ 검사를 돌린다.

| # | 결론 | 수준 | 상세 |
|---|---|---|---|"""


def build():
    os.makedirs(ROWS, exist_ok=True)
    rows = parse_old()
    old_nums = {n for n, _ in rows}
    existing_new = []                     # 이미 있는 새 행(원본에 없는 번호)의 색인 줄은 보존
    ip = os.path.join(NEW, "index.md")
    if os.path.exists(ip):
        for ln in open(ip, encoding="utf-8").read().split("\n"):
            m = re.match(r"^\| (\d+) \| ", ln)
            if m and int(m.group(1)) not in old_nums:
                existing_new.append((int(m.group(1)), ln))
    lines = [(n, index_line(n, line)) for n, line in rows] + existing_new
    for n, line in rows:
        with open(os.path.join(ROWS, f"{n:03d}.md"), "w", encoding="utf-8") as f:
            f.write(render_row(n, line))
    with open(ip, "w", encoding="utf-8") as f:
        f.write(INDEX_HEAD + "\n" + "\n".join(l for _, l in sorted(lines, key=lambda x: -x[0])) + "\n")
    print(f"행 {len(rows)}개(+새 행 {len(existing_new)}개 색인 보존) → {ROWS}")


def reassemble(text):
    """행 파일 본문 → 원래 표의 한 줄(상세는 줄을 공백으로 이음)."""
    t = text.split("\n")
    n = int(re.match(r"# 장부 #(\d+) ", t[0]).group(1))
    sec, cur = None, {}
    for ln in t[1:]:
        if ln.startswith("## "):
            sec = ln[3:]; cur[sec] = []; continue
        if sec is not None:
            cur[sec].append(ln)

    def body(name):
        v = cur[name]
        while v and v[0] == "": v = v[1:]
        while v and v[-1] == "": v = v[:-1]
        return v
    cells = [str(n), " ".join(body("상세"))]
    for idx in range(2, 10):
        name = COLS.get(idx, f"열 {idx + 1}")
        if name in cur: cells.append("\n".join(body(name)))
    return "| " + " | ".join(cells) + " |"


def check():
    rows = dict(parse_old())
    bad, warn = [], []
    idx_text = open(os.path.join(NEW, "index.md"), encoding="utf-8").read()
    idx_lines = {int(m.group(1)): ln for ln in idx_text.split("\n") for m in [re.match(r"^\| (\d+) \| ", ln)] if m}
    if not idx_text.startswith(INDEX_HEAD):
        bad.append("index.md 머리글이 도구의 INDEX_HEAD 와 다름")
    files = sorted(f for f in os.listdir(ROWS) if re.fullmatch(r"\d{3}\.md", f)) if os.path.isdir(ROWS) else []
    nums = {int(f[:-3]) for f in files}
    for n, line in rows.items():
        p = os.path.join(ROWS, f"{n:03d}.md")
        if n not in nums:
            bad.append(f"#{n}: 행 파일 없음"); continue
        text = open(p, encoding="utf-8").read()
        try:
            got = reassemble(text)
        except Exception as e:
            bad.append(f"#{n}: 조립 실패 {e}"); continue
        if got != line:
            k = next((i for i, (a, b) in enumerate(zip(got, line)) if a != b), min(len(got), len(line)))
            bad.append(f"#{n}: 상세·열이 원본과 다름(첫 차이 {k}번째 글자: 새 「{got[k:k+30]}」 원 「{line[k:k+30]}」)")
        if text != render_row(n, line):
            bad.append(f"#{n}: 결론·제목·안내문이 원본에서 다시 만든 것과 다름")
        if idx_lines.get(n) != index_line(n, line):
            bad.append(f"#{n}: 색인 줄이 다름")
    for n in sorted(nums - set(rows)):          # 새 행: 모양과 색인 등재만
        text = open(os.path.join(ROWS, f"{n:03d}.md"), encoding="utf-8").read()
        t = text.split("\n")
        if not re.match(rf"# 장부 #{n} — \S", t[0]):
            bad.append(f"새 행 #{n}: 첫 줄이 「# 장부 #{n} — 결론」 모양이 아님")
        heads = [ln for ln in t if ln.startswith("## ")]
        if heads[:3] != ["## 결론", "## 상세", "## 수준"]:
            bad.append(f"새 행 #{n}: 소제목 순서가 결론·상세·수준이 아님({heads[:3]})")
        else:
            lead = [x for x in text.split("## 결론")[1].split("## 상세")[0].split("\n") if x.strip()]
            if len(lead) != 1:
                bad.append(f"새 행 #{n}: 결론이 한 문장(한 줄)이 아님")
            elif len(lead[0]) > LEAD_MAX:
                warn.append(f"새 행 #{n}: 결론 {len(lead[0])}자(권고 {LEAD_MAX}자)")
        if n not in idx_lines or f"(rows/{n:03d}.md)" not in idx_lines[n]:
            bad.append(f"새 행 #{n}: 색인에 없음")
    extra_idx = sorted(set(idx_lines) - nums)
    if extra_idx: bad.append(f"행 파일이 없는 색인 줄: {extra_idx}")
    links = re.findall(r"\(rows/(\d+)\.md\)", idx_text)
    dup = sorted({l for l in links if links.count(l) > 1})
    if dup: bad.append(f"색인 링크 중복: {dup}")
    print(f"원본 행 {len(rows)}개 · 행 파일 {len(files)}개(새 행 {len(nums - set(rows))}개) · 색인 링크 {len(links)}개")
    for w in warn: print("⚠", w)
    for b in bad: print("✗", b)
    print("통과" if not bad else f"실패 {len(bad)}건")
    return 0 if not bad else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("build", "check"):
        sys.exit(__doc__)
    if sys.argv[1] == "build":
        build()
    sys.exit(check() if sys.argv[1] == "check" else 0)
