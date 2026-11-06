"""ctxcards — 결정 카드(ctx `note` 문서 `cards/<uuid>`)의 형식·파서·검사·조회·이력. 순수 함수 중심이라 DB·psycopg 를 모른다
(근거 메시지는 호출하는 쪽이 넘기는 `fetch` 콜백으로 읽는다). 설계·결정: `donghans ctx doc read --project nixos plan llm-trust/02-card-skill-ui`.

카드 한 장 = ctx 문서 하나. 머리말(`<!-- ctx … -->`: status·scope·state …)은 저장소가 관리하고, 본문 맨 앞의 자체 머리말(`---` … `---`)과
`## 내용` · `## 근거 원문` · `## 반례·한계` · `## 이력` 절이 카드의 내용이다(형식 설명은 llm-ctx/README.md 「결정 카드」).
"""
import os
import re
import subprocess

import ctx_store as st

KINDS = ("대전제", "습관", "한정 결정", "희망사항", "관점")
PROPOSERS = ("agent", "user")
REQUIRED = ("id", "title", "kind", "proposer")
CARD_PREFIX = "cards/"
SECTIONS = ("내용", "근거 원문", "반례·한계", "이력")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX_REF = re.compile(r"^[0-9a-f]{8,36}$")             # 카드·메시지 uuid 앞자리(8자 이상)
_EVID = re.compile(r"^\s*-\s*\[msg:([0-9a-fA-F-]{8,36})\]\s*(.*)$")
_QUOTES = {'"': '"', "“": "”", "「": "」"}
_FM = re.compile(r"\A\s*---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)


# ---------------------------------------------------------------- 파싱
def _value(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip() for x in v[1:-1].split(",") if x.strip()]
    return v


def parse_frontmatter(body: str) -> tuple[dict, str]:
    """(자체 머리말 dict, 나머지 본문). 머리말이 없으면 ({}, body). 값은 `키: 값` 한 줄, `[a, b]` 는 목록, 줄 끝의 `  # 설명` 은 뗀다."""
    m = _FM.match(body or "")
    if not m:
        return {}, body or ""
    meta = {}
    for line in m.group(1).split("\n"):
        line = line.split("  #")[0] if "  #" in line else line
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        if k.strip():
            meta[k.strip()] = _value(v)
    return meta, (body or "")[m.end():]


def _split_sections(rest: str) -> dict:
    out, cur = {}, None
    for line in rest.split("\n"):
        if line.startswith("## "):
            head = line[3:].strip()
            cur = next((s for s in SECTIONS if head.startswith(s)), None)
            if cur:
                out[cur] = []
            continue
        if cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def parse_evidence_line(line: str):
    """근거 한 줄 → {uuid, quote|None, pointer, note} 또는 None(근거 형식이 아님).
    `- [msg:<uuid8…>] "인용"  (설명)` / `- [msg:<uuid8…>] (포인터 — 읽을 때 채움)` / 인용·포인터 표기 없음(quote=None, pointer=False)."""
    m = _EVID.match(line)
    if not m:
        return None
    uid, rest = m.group(1).lower(), m.group(2).strip()
    if rest[:1] in _QUOTES:
        close = _QUOTES[rest[0]]
        j = rest.rfind(close)
        if j > 0:
            return {"uuid": uid, "quote": rest[1:j], "pointer": False, "note": rest[j + 1:].strip()}
    if rest.startswith("(포인터") or rest.startswith("（포인터"):
        return {"uuid": uid, "quote": None, "pointer": True, "note": rest}
    return {"uuid": uid, "quote": None, "pointer": False, "note": rest}


def parse_card(body: str) -> dict:
    """문서 본문 → {meta, sections, evidence, bad_evidence}. 형식이 틀려도 예외 없이 담고, 판단은 validate 가 한다."""
    meta, rest = parse_frontmatter(body)
    sec = _split_sections(rest)
    evid, bad = [], []
    for line in sec.get("근거 원문", "").split("\n"):
        if not line.strip().startswith("-"):
            continue
        e = parse_evidence_line(line)
        (evid if e else bad).append(e or line.strip())
    return {"meta": meta, "sections": sec, "evidence": evid, "bad_evidence": bad}


def validate(card: dict) -> list[str]:
    """형식 문제 목록(비어 있으면 통과). 필수: id·title·kind·proposer, 근거 1건 이상, 반례 1건 이상."""
    meta, p = card["meta"], []
    for k in REQUIRED:
        if not str(meta.get(k, "")).strip():
            p.append(f"필수 칸 `{k}` 가 비었다")
    if meta.get("id") and not UUID_RE.match(str(meta["id"])):
        p.append("`id` 는 uuid4 전체 형식이어야 한다")
    if meta.get("kind") and meta["kind"] not in KINDS:
        p.append(f"`kind` 는 {' | '.join(KINDS)} 중 하나")
    if meta.get("proposer") and meta["proposer"] not in PROPOSERS:
        p.append(f"`proposer` 는 {' | '.join(PROPOSERS)} 중 하나")
    if not card["evidence"]:
        p.append("`## 근거 원문` 에 `- [msg:<uuid8>]` 줄이 1건 이상 있어야 한다")
    for line in card["bad_evidence"]:
        p.append(f"근거 줄에 `[msg:<uuid8 이상>]` 가 없다: {line[:60]}")
    if not any(l.strip().startswith("-") and len(l.strip().lstrip("-").strip()) > 0 for l in card["sections"].get("반례·한계", "").split("\n")):
        p.append("`## 반례·한계` 에 반례가 1건 이상(`- …`) 있어야 한다")
    return p


# ---------------------------------------------------------------- 인용 일치 검사
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def quote_matches(quote: str, full_text: str) -> bool:
    """인용이 원문의 부분 문자열인가(공백 정규화 뒤). 인용 안의 `…`·`...` 는 생략 표시라 조각마다 따로 검사한다(조각이 2자 미만이면 무시)."""
    hay = _norm(full_text)
    parts = [p for p in (_norm(x) for x in re.split(r"…|\.\.\.", quote or "")) if len(p) >= 2]
    return bool(parts) and all(p in hay for p in parts)


def check_evidence(card: dict, fetch) -> list[dict]:
    """근거마다 {uuid, status, text, meta}. fetch(uuid앞자리) → ("ok", 전체본문, 부가정보) | ("none",) | ("ambiguous", [uuid…]).
    status: 일치 · 미일치 · 메시지 없음 · 모호 · 포인터 · 인용 없음. 포인터·인용 없음은 text(전체 본문)를 같이 돌려 읽는 쪽이 채워 보인다."""
    out = []
    for e in card["evidence"]:
        r = fetch(e["uuid"])
        if r[0] == "none":
            out.append({"uuid": e["uuid"], "status": "메시지 없음", "text": None, "meta": None})
        elif r[0] == "ambiguous":
            out.append({"uuid": e["uuid"], "status": "모호", "text": None, "meta": r[1]})
        else:
            if e["quote"] is not None:
                status = "일치" if quote_matches(e["quote"], r[1]) else "미일치"
            else:
                status = "포인터" if e["pointer"] else "인용 없음"
            out.append({"uuid": e["uuid"], "status": status, "text": r[1], "meta": r[2] if len(r) > 2 else None})
    return out


# ---------------------------------------------------------------- 조회
def card_id(name: str) -> str:
    return name[len(CARD_PREFIX):] if name.startswith(CARD_PREFIX) else name


def parse_ref(ref: str) -> tuple[str | None, str]:
    """`프로젝트:uuid8` → (프로젝트, uuid앞자리), `uuid8` → (None, uuid앞자리). 앞자리는 16진 8자 이상이어야 한다(ValueError)."""
    proj, _, pre = ref.rpartition(":")
    pre = pre.strip().lower()
    if not HEX_REF.match(pre.replace("-", "")) or len(pre.replace("-", "")) < 8:
        raise ValueError(f"카드 참조 `{ref}` — `프로젝트:uuid8`(uuid 앞 8자 이상, 16진)이어야 한다")
    return (proj.strip() or None), pre


def find_cards(store: str, ref: str | None = None, projects=None) -> tuple[list[dict], list[str]]:
    """(카드 목록, 이 머신에 저장소가 없어 건너뛴 프로젝트). ref 가 없으면 전부. 카드 행: project·name·id·path·meta(저장소 머리말)·body·card(파싱)·problems."""
    man = st.load_manifest(store)
    want_proj, pre = parse_ref(ref) if ref else (None, None)
    names = [want_proj] if want_proj else list(projects or man)
    rows, skipped = [], []
    for p in names:
        if p not in man:
            raise ValueError(f"프로젝트 {p!r} 가 매니페스트에 없다(등록된 것: {', '.join(sorted(man)) or '없음'})")
        if not os.path.isdir(os.path.join(store, p)):
            skipped.append(p)
            continue
        for k, name, path in st.iter_docs(store, p, "note"):
            if not name.startswith(CARD_PREFIX) or "/" in name[len(CARD_PREFIX):]:
                continue
            cid = card_id(name)
            if pre and not cid.replace("-", "").startswith(pre.replace("-", "")):
                continue
            d = st.read_doc(store, p, "note", name)
            if not d:
                continue
            card = parse_card(d["body"])
            rows.append({"project": p, "name": name, "id": cid, "path": path, "meta": d["meta"], "hash": d["hash"], "body": d["body"], "card": card, "problems": validate(card)})
    return rows, skipped


def ref_of(row: dict) -> str:
    return f"{row['project']}:{row['id'][:8]}"


# ---------------------------------------------------------------- 이력 (읽기 전용 git)
def _git(store: str, project: str, *args) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C.UTF-8")
    r = subprocess.run(["git", "-C", os.path.join(store, project), "-c", "core.quotepath=false", *args], capture_output=True, text=True, env=env, timeout=30)
    return r.stdout if r.returncode == 0 else ""


def history(store: str, project: str, name: str) -> list[dict]:
    """카드 문서의 판 이력(최신이 위). 항목: hash·short·date·subject(`ctx: ` 접두를 뗌)·state·demoted(앞 판이 reviewed/adopted 였는데 draft 가 됨).
    저장소를 바꾸지 않는다. **`--follow` 를 쓰지 않는다** — 카드는 같은 틀로 만들어져 서로 비슷해서 내용 유사도로 이름 변경을 추정하면 다른 카드의 이력을 끌어온다(카드 이름은 바뀌지 않는다). 「강등」 표시는 커밋 메시지가 아니라 연속한 두 판의 state 머리말을 비교해 계산한다."""
    out = _git(store, project, "log", "--no-renames", "--format=%x1e%H%x1f%h%x1f%cI%x1f%s", "--name-only", "--", f"note/{name}.md")
    revs = []
    for chunk in out.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, files = chunk.partition("\n")
        h, short, date, subject = (head.split("\x1f") + ["", "", "", ""])[:4]
        path = next((f for f in files.split("\n") if f.strip()), f"note/{name}.md")
        text = _git(store, project, "show", f"{h}:{path}")
        meta, _body = st.split_header(text) if text else (None, "")
        revs.append({"hash": h, "short": short, "date": date, "subject": subject[5:] if subject.startswith("ctx: ") else subject,
                     "state": (meta or {}).get("state", "unknown"), "path": path})
    for i, r in enumerate(revs):               # revs 는 최신이 앞 — i+1 이 직전 판
        prev = revs[i + 1] if i + 1 < len(revs) else None
        r["demoted"] = bool(prev) and prev["state"] in ("reviewed", "adopted") and r["state"] == "draft"
    return revs


def revision_diff(store: str, project: str, rev: dict, prev: dict | None) -> str:
    """한 판의 diff(직전 판 대비, 첫 판이면 전체 추가). 읽기 전용."""
    if prev:
        return _git(store, project, "diff", prev["hash"], rev["hash"], "--", rev["path"] if rev["path"] == prev["path"] else ".")
    return _git(store, project, "show", "--format=", rev["hash"], "--", rev["path"])


# ---------------------------------------------------------------- 쓰기 가드 (S2) — `ctx doc propose` 가 카드 문서에 대해 부른다
def is_card_name(kind: str, name: str) -> bool:
    return kind == "note" and name.startswith(CARD_PREFIX) and "/" not in name[len(CARD_PREFIX):] and len(name) > len(CARD_PREFIX)


def _canon(t: str) -> str:
    return "\n".join(l.rstrip() for l in (t or "").strip().split("\n"))


def _blank_last_confirmed(text: str) -> str:
    return re.sub(r"(?m)^(last_confirmed:)[^\n]*$", r"\1", text, count=1)


def append_history(text: str, line: str) -> str:
    """`## 이력` 절의 끝에 한 줄을 더한다(절이 없으면 문서 끝에 새 절)."""
    lines = text.rstrip("\n").split("\n")
    for i, l in enumerate(lines):
        if l.startswith("## ") and l[3:].strip().startswith("이력"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            lines.insert(j, line)
            return "\n".join(lines) + "\n"
    return "\n".join(lines) + f"\n\n## 이력\n{line}\n"


def guard_proposal(body: str, cur: dict | None, *, human: bool, project: str, name: str, manifest: dict, evidence_project,
                   session: str = "", host: str = "", today: str = "") -> tuple[str, list[str], list[str]]:
    """카드 문서 제안 검사·보정 → (새 본문, 오류, 경고). 오류가 있으면 제안하지 않는다.
    모두에게: 형식 검증(필수 칸·근거·반례), `id` = 문서 이름, **remote 가 있는 저장소의 카드에는 remote 없는 프로젝트 대화의 원문 인용 금지(포인터만)**.
    사람(TTY)이 아닌 경로: 새 카드는 state draft 로 채우고(없으면) draft 밖이면 거부 · `proposer: user` 거부 · reviewed/adopted 로 올리는 제안 거부 ·
    **이미 reviewed/adopted 인 카드의 내용을 고치면 draft 로 강등**(last_confirmed 를 비우고 이력에 한 줄). evidence_project(uuid앞자리) → (프로젝트|None, 메시지 있음)
    — 조회에 실패하면 예외를 던진다(원문 인용이 있을 때 안전하게 거부한다). 한계: 우발적 위반만 막는다(환경변수를 지우고 TTY 를 흉내 내거나 파일을 직접 쓰는 우회는 못 막음)."""
    errors, warns, notes = [], [], []
    hdr, text = st.split_header(body)
    card = parse_card(text)
    errors += validate(card)
    cid = str(card["meta"].get("id", ""))
    if cid and card_id(name) != cid:
        errors.append(f"`id`({cid[:8]}…)가 문서 이름({name})의 uuid 와 다르다")

    def remote_of(p):
        return (manifest.get(p) or {}).get("remote", "")
    if remote_of(project):
        for e in card["evidence"]:
            if e["quote"] is None:
                continue
            try:
                ep, found = evidence_project(e["uuid"])
            except Exception as ex:                                     # DB 접속 실패 등 — 인용 출처를 모르면 remote 가 있는 저장소에는 못 올린다
                errors.append(f"[msg:{e['uuid']}] 의 출처 프로젝트를 확인하지 못했다({type(ex).__name__}) — 원문 인용을 거부한다(포인터로 적거나 DB 접속을 확인)")
                continue
            if not found:
                warns.append(f"[msg:{e['uuid']}] 메시지를 DB 에서 찾지 못해 인용 출처 검사를 건너뛴다")
            elif ep is None:
                warns.append(f"[msg:{e['uuid']}] 의 세션이 매니페스트의 어느 프로젝트인지 알 수 없어 인용 출처 검사를 건너뛴다")
            elif ep != project and not remote_of(ep):
                errors.append(f"[msg:{e['uuid']}] 는 remote 가 없는 프로젝트({ep})의 대화다 — {project} 저장소는 GitHub 로 올라가므로 원문 인용 대신 포인터 `- [msg:{e['uuid']}] (포인터 — 읽을 때 채움)` 로 적는다")

    new_hdr = dict(hdr) if hdr is not None else (dict(cur["meta"]) if cur else st.default_meta())
    new_text = text
    changed_hdr = False
    if not human:
        req = (hdr or {}).get("state")
        if str(card["meta"].get("proposer", "")) == "user":
            errors.append("`proposer: user` 카드는 사람이 터미널에서 직접 만든 제안에만 허용한다(에이전트가 사용자 카드를 만들지 않는다)")
        if cur is None:
            if req not in (None, "unknown", "draft"):
                errors.append(f"새 카드의 state 는 draft 여야 한다(제안은 {req}) — reviewed·adopted 로 올리는 것은 사람(llmui)이 한다")
            elif new_hdr.get("state") != "draft":
                new_hdr["state"] = "draft"; changed_hdr = True
                notes.append("새 카드의 state 를 draft 로 채웠다")
        else:
            cur_state = cur["meta"].get("state", "unknown")
            if req in ("reviewed", "adopted") and req != cur_state:
                errors.append(f"state 를 {cur_state} → {req} 로 올리는 제안은 에이전트가 할 수 없다 — 사람(llmui)이 확인해 올린다")
            elif cur_state in ("reviewed", "adopted") and _canon(text) != _canon(cur["body"]):
                new_hdr["state"] = "draft"; changed_hdr = True
                new_text = append_history(_blank_last_confirmed(text), f"- {today or '(날짜 미상)'} · 에이전트 수정으로 강등({cur_state} → draft, last_confirmed 비움) · {(session or '?')[:8]}@{host or '?'}")
                notes.append(f"확인된 카드({cur_state})의 내용이 바뀌어 draft 로 강등했다 — 사용자가 다시 확인해야 한다")
    if errors:
        return body, errors, warns
    out = body
    if hdr is None and (cur is None or changed_hdr):
        out = st.render_header(new_hdr) + new_text
    elif hdr is not None and changed_hdr:
        out = st.render_header(new_hdr) + new_text
    elif new_text != text:
        out = body.replace(text, new_text, 1)
    return out, [], warns + [f"[알림] {n}" for n in notes]
