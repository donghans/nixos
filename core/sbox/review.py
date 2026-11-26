#!/usr/bin/env python3
"""sbox 승인 화면(plan sbox-project-policy A12·§4-2d, 로드맵 ㉑ S2) — `sboxctl taskd` 가 호스트에서 부른다. 표준 라이브러리만.

사람이 「의도한 변경이 맞는가」를 **10초 안에** 판단하게 하는 화면이다(코드·패키지의 취약점 판정이 아니다 — 사용자 결정 2026-11-26).
  ① 호스트가 계산한 사실만 위에 둔다: 작업 정의(argv·cwd·kind·timeout·env), 정의 파일 해시, **실행될 스크립트 본문(주석 포함)**, 지난 승인본과의 diff, 위험 신호, 보호 경로 요약
  ② 매니페스트 `note`(설명)는 사실 **아래에** 「검증되지 않음」으로 따로 둔다(설명이 사실을 가리지 않게)
  ③ 고정 고지: 「의도하신 변경이 맞는지만 확인해 주세요. 취약점 검토는 다른 도구를 사용해 주세요.」
  ④ 지난 승인과 같은 것은 한 줄, 바뀐 것만 자세히. 초기에 한꺼번에 들어오는 보호 경로는 디렉터리 단위로 접고 위험 신호 파일만 펼친다.

  show   --manifest M --digests D --pins DIR --protected P --state DIR   화면을 출력한다(승인 여부와 무관, 읽기 전용). 끝 줄에 `[요약] 새 N 바뀜 N 그대로 N 위험 N` 한 줄.
  commit --manifest M --digests D --pins DIR --protected P --state DIR   승인이 끝난 뒤 승인본 사본(작업 정의·정의 파일 본문·보호 경로 목록)을 호스트에 보관(다음 승인의 diff 기준).
"""
import argparse, difflib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks  # noqa: E402

NOTICE = "의도하신 변경이 맞는지만 확인해 주세요. 취약점 검토는 다른 도구를 사용해 주세요."
PIN_MAX = 64 * 1024            # 정의 파일 본문을 읽어 오는 상한(바이트) — 넘으면 앞부분만 보이고 그 사실을 밝힌다
BODY_LINES = 80               # 스크립트 본문 최대 줄
DIFF_LINES = 60               # diff 최대 줄
FOLD_MIN = 6                  # 한 폴더의 보호 경로가 이만큼 이상이면 접는다
INSTALL_HOOKS = ("preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly")

# 위험 신호: (이름, 정규식). 「나쁘다」는 판정이 아니라 사람이 눈여겨볼 곳 표시다.
RISKS = [
    ("내려받아 바로 실행(curl|sh)", re.compile(r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b")),
    ("rm -rf", re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b")),
    ("sudo", re.compile(r"\bsudo\b")),
    ("chmod 777", re.compile(r"\bchmod\s+(-R\s+)?[0-7]*777\b")),
    ("base64 해독 실행", re.compile(r"\bbase64\s+(-d|--decode)\b")),
    ("eval", re.compile(r"\beval\b")),
    ("원시 네트워크(nc·/dev/tcp)", re.compile(r"/dev/tcp/|\bnc\s+-|\bncat\b")),
]
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")


# ------------------------------------------------------------------ 보관(승인본 사본)
def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def load_snapshot(state):
    """(작업 정의 {이름: {...}}, 정의 파일 {상대경로: 본문}, 보호 경로 목록). 없으면 빈 값."""
    t = _read(os.path.join(state, "tasks.json"))
    p = _read(os.path.join(state, "protected.json"))
    pins = {}
    root = os.path.join(state, "pins")
    for d, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(d, f)
            pins[os.path.relpath(full, root).replace(os.sep, "/")] = _read(full, "")
    return (json.loads(t) if t else None), pins, (json.loads(p) if p else None)


def save_snapshot(state, task_defs, pin_texts, protected):
    os.makedirs(os.path.join(state, "pins"), exist_ok=True)
    for d, _dirs, files in os.walk(os.path.join(state, "pins")):
        for f in files:
            os.remove(os.path.join(d, f))
    for rel, text in pin_texts.items():
        path = os.path.join(state, "pins", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    for name, obj in (("tasks.json", task_defs), ("protected.json", sorted(protected))):
        tmp = os.path.join(state, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(state, name))


def task_def(t):
    """승인 대상이 되는 작업 정의 필드(note 는 설명이라 승인 대상이 아니다)."""
    return {"argv": t["argv"], "cwd": t["cwd"], "kind": t["kind"], "timeout": t["timeout"], "env": t["env"], "pins": sorted(t["pins"])}


# ------------------------------------------------------------------ 실행될 스크립트 본문
def npm_script_names(argv):
    """argv 가 npm·yarn·pnpm 의 스크립트 실행이면 (이름 목록, 설치 훅 여부). 특정할 수 없으면 ([], False)."""
    if not argv or os.path.basename(argv[0]) not in ("npm", "yarn", "pnpm"):
        return [], False
    rest = [a for a in argv[1:] if not a.startswith("-")]
    if not rest:
        return [], False
    if rest[0] in ("run", "run-script") and len(rest) > 1:
        return [rest[1]], False
    if rest[0] in ("test", "start", "stop", "restart"):
        return [rest[0]], False
    if rest[0] in ("install", "i", "ci", "add"):
        return [], True
    if os.path.basename(argv[0]) in ("yarn", "pnpm") and rest[0] not in ("install", "add", "exec", "dlx"):
        return [rest[0]], False
    return [], False


def script_view(argv, rel, text):
    """(제목, 줄 목록, 설치 훅 이름 목록). 실행될 스크립트 본문을 사람이 읽을 줄로 만든다 — 스크립트 안의 주석도 그대로 보인다."""
    lines = []
    hooks = []
    if rel.endswith("package.json"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
            names, install = npm_script_names(argv)
            show = []
            for n in names:
                show += [k for k in (f"pre{n}", n, f"post{n}") if k in scripts]
            hooks = [k for k in INSTALL_HOOKS if k in scripts]
            if install:
                show += [k for k in hooks if k not in show]
            title = f"{rel} 의 scripts — 이 작업이 실행하는 항목"
            if not show:
                show = list(scripts)
                title = f"{rel} 의 scripts 전체 — 작업이 쓰는 항목을 특정하지 못했다"
            for k in show:
                lines.append(f"{k} = {json.dumps(scripts[k], ensure_ascii=False)}")
            if hooks and not install:
                lines.append(f"(설치 훅 있음: {', '.join(hooks)} — 이 작업이 아니라 의존성 설치 때 실행됨)")
            return title, lines, hooks
    body = text.splitlines()
    lines = body[:BODY_LINES]
    if len(body) > BODY_LINES:
        lines.append(f"… ({len(body) - BODY_LINES}줄 더 — 호스트에서 직접 확인)")
    return f"{rel} 본문", lines, hooks


def risk_signals(argv, texts):
    """[(신호, 근거 한 줄)]. argv 와 보여 준 본문 줄에서 찾는다."""
    found = []
    joined = " ".join(argv)
    if len(argv) >= 3 and os.path.basename(argv[0]) in ("sh", "bash", "zsh", "dash") and argv[1] == "-c":
        found.append(("셸 문자열 실행(sh -c)", joined[:120]))
    for blob in [joined] + list(texts):
        for line in blob.splitlines() or [blob]:
            for name, rx in RISKS:
                if rx.search(line) and (name, line.strip()[:120]) not in found:
                    found.append((name, line.strip()[:120]))
    return found


def hosts_in(texts):
    return sorted({m.group(1) for t in texts for m in URL_RE.finditer(t)})


# ------------------------------------------------------------------ 보호 경로 요약
def category(rel):
    """보호 경로의 종류 라벨(내용을 못 읽으니 경로로만 판단) — 사람이 눈여겨볼 만한 것은 ⚠ 로."""
    base = rel.rsplit("/", 1)[-1]
    if rel.startswith(".github/workflows/") or rel == ".github":
        return "CI 워크플로 — push·PR 때 실행됨", True
    if rel.startswith(".githooks"):
        return "git 훅 — 커밋·푸시 때 실행됨", True
    if rel.startswith(".claude"):
        return "에이전트 구성(.claude) — 지침·훅·스킬", True
    if base.startswith("Dockerfile"):
        return "Dockerfile — 빌드 때 RUN 실행", True
    if base.startswith("docker-compose"):
        return "compose — 컨테이너·볼륨·포트 정의", True
    if base in ("CLAUDE.md", ".mcp.json"):
        return "에이전트 지침·MCP 설정", True
    if base == "package.json" or base == "pubspec.yaml":
        return "의존성·스크립트 정의", False
    return "의존성 락 파일", False


def protected_lines(protected, prev, dirinfo=None):
    """보호 경로를 접어서 보인다: 폴더(.claude 등)는 개수만, 눈여겨볼 개별 파일(Dockerfile·compose·package.json 등)은 한 줄씩. 지난 승인 대비 새로 생긴 것은 따로."""
    out = []
    new = sorted(set(protected) - set(prev or []))
    if prev is not None:
        out.append(f"보호 경로(작업 사본에서 읽기 전용으로 고정): {len(protected)}개 — 지난 승인 대비 새로 생긴 것 {len(new)}개")
    else:
        out.append(f"보호 경로(작업 사본에서 읽기 전용으로 고정): {len(protected)}개 — 승인본 목록이 없어 전부 새것으로 본다")
        new = sorted(protected)
    dirinfo = dirinfo or {}
    dirs, singles = {}, []
    for r in new:
        top = r.split("/", 1)[0]
        if r in dirinfo:                  # 폴더째 보호된 경로: 안쪽 파일 수·스크립트 수로 접어 보인다
            info = dirinfo[r]
            label, flag = category(r)
            tops = ", ".join(f"{k} {v}" for k, v in info.get("top", {}).items())
            out.append(f"  {'⚠ ' if flag else '  '}{r}/ — {label} · 파일 {info['files']}{'+' if info.get('truncated') else ''}개 (스크립트 {info['scripts']}개; {tops}) (접음 — 내용은 호스트에서 직접)")
        elif "/" in r or r in (".claude", ".githooks", ".github"):
            dirs.setdefault(top, []).append(r)
        else:
            singles.append(r)
    for r in singles:
        label, flag = category(r)
        out.append(f"  {'⚠ ' if flag else '  '}{r} — {label}")
    for top, items in sorted(dirs.items()):
        label, flag = category(top if top.startswith(".") else items[0])
        if len(items) >= FOLD_MIN:
            out.append(f"  {'⚠ ' if flag else '  '}{top}/ 아래 {len(items)}개 — {label} (접음)")
        else:
            for r in items:
                label, flag = category(r)
                out.append(f"  {'⚠ ' if flag else '  '}{r} — {label}")
    return out


# ------------------------------------------------------------------ 화면
def _pretty(text):
    """JSON 이면 들여쓰기로 펼친다(한 줄로 압축된 package.json 의 diff 가 「줄 전체가 바뀜」이 되지 않게). JSON 이 아니면 그대로."""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def diff_lines(old, new):
    old, new = _pretty(old), _pretty(new)
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "승인본", "지금", lineterm="", n=2))
    if len(d) > DIFF_LINES:
        d = d[:DIFF_LINES] + [f"… (diff {len(d) - DIFF_LINES}줄 더)"]
    return d


def render(manifest, digests, pin_texts, protected, state, ct="", dirinfo=None):
    """(화면 텍스트, 요약 {new, changed, same, risks}). 매니페스트·현재 다이제스트·정의 파일 본문·보호 경로·승인본(state)을 비교한다."""
    cur = tasks.load(manifest)
    snap_tasks, snap_pins, snap_prot = load_snapshot(state)
    out, stat = [], {"new": 0, "changed": 0, "same": 0, "risks": 0}
    body = []
    for name in sorted(cur):
        t = cur[name]
        digs = {rel: digests.get(rel) for rel in t["pins"]}
        approved_hash = t["pinned"]
        prev_def = (snap_tasks or {}).get(name)
        if not t["pinned"] and prev_def is None:
            state_tag = "새"
        elif prev_def is None and all(approved_hash.get(r) == digs[r] for r in t["pins"]):
            state_tag = "그대로"           # 옛 승인(사본 없음)과 해시가 같다
        elif prev_def == task_def(t) and all(approved_hash.get(r) == digs[r] for r in t["pins"]):
            state_tag = "그대로"
        else:
            state_tag = "바뀜"
        argv_txt = " ".join(t["argv"])
        if state_tag == "그대로":
            stat["same"] += 1
            body.append(f"[그대로] {name} — `{argv_txt}` 지난 승인과 같음")
            continue
        stat["new" if state_tag == "새" else "changed"] += 1
        body.append(f"[{state_tag}] {name}")
        body.append(f"  실행: {argv_txt}   (cwd={t['cwd']}, kind={t['kind']}, timeout={t['timeout']}s" + (f", env={t['env']}" if t["env"] else "") + ")")
        if prev_def and prev_def != task_def(t):
            for k in ("argv", "cwd", "kind", "timeout", "env", "pins"):
                if prev_def.get(k) != task_def(t)[k]:
                    body.append(f"  ↳ 바뀐 항목 {k}: {prev_def.get(k)!r} → {task_def(t)[k]!r}")
        shown = []
        for rel in t["pins"]:
            h = digs.get(rel)
            text = pin_texts.get(rel)
            ap = approved_hash.get(rel)
            status = "승인 없음(새 정의 파일)" if ap is None else ("승인 때와 같음" if ap == h else "승인 때와 다름")
            body.append(f"  정의 파일 {rel}  sha256 {h[:12] + '…' if h else '읽지 못함'}  — {status}")
            if text is None:
                body.append("    (본문을 읽어 오지 못했다 — 호스트에서 직접 확인)")
                continue
            truncated = len(text.encode("utf-8", "ignore")) > PIN_MAX
            title, lines, _hooks = script_view(t["argv"], rel, text[:PIN_MAX])
            body.append(f"  실행될 내용 — {title}:" + (" [앞 64KB 만]" if truncated else ""))
            body += [f"      {ln}" for ln in lines]
            shown += lines
            old = snap_pins.get(rel)
            if old is not None and old != text:
                body.append("  승인본 대비 diff:")
                body += [f"      {ln}" for ln in diff_lines(old, text)]
            elif old is None and ap is not None:
                body.append("  (승인본 사본이 없어 diff 를 못 보인다 — 이번 승인부터 보관한다)")
        risks = risk_signals(t["argv"], shown)
        if state_tag == "새":
            risks.insert(0, ("새 작업", name))
        for rel in t["pins"]:
            if approved_hash.get(rel) is None:
                risks.insert(0, ("새 정의 파일 추가", rel)) if ("새 정의 파일 추가", rel) not in risks else None
        hosts = hosts_in(shown + [argv_txt])
        for n, ev in risks:
            body.append(f"  ⚠ 눈여겨볼 곳 — {n}: {ev}")
        stat["risks"] += len(risks)
        if hosts:
            body.append(f"  참고: 본문에 나오는 외부 호스트 {', '.join(hosts)} (실제 접속은 송신 허용 목록이 따로 막는다)")
        if t.get("note"):
            body.append(f"  설명(매니페스트의 note — 사람이 쓴 설명, 검증되지 않음): {t['note']}")
    head = f"== 승인 검토{(': ' + ct) if ct else ''} — 작업 {len(cur)}개 (새 {stat['new']} · 바뀜 {stat['changed']} · 그대로 {stat['same']}) =="
    out += [head, NOTICE, ""] + body + [""]
    out += protected_lines(protected, snap_prot, dirinfo)
    out += ["", NOTICE, f"[요약] 새 {stat['new']} 바뀜 {stat['changed']} 그대로 {stat['same']} 눈여겨볼 곳 {stat['risks']}"]
    return "\n".join(out) + "\n", stat


def _load_inputs(a):
    digests = json.load(open(a.digests))
    pins = {}
    if a.pins and os.path.isdir(a.pins):
        for d, _dirs, files in os.walk(a.pins):
            for f in files:
                full = os.path.join(d, f)
                with open(full, "rb") as fh:
                    pins[os.path.relpath(full, a.pins).replace(os.sep, "/")] = fh.read().decode("utf-8", "replace")
    protected = json.load(open(a.protected)) if a.protected else []
    return digests, pins, protected


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "commit"])
    ap.add_argument("--manifest", required=True); ap.add_argument("--digests", required=True)
    ap.add_argument("--pins"); ap.add_argument("--dirinfo"); ap.add_argument("--protected"); ap.add_argument("--state", required=True); ap.add_argument("--ct", default="")
    ap.add_argument("--protected-only", action="store_true", help="commit 때 보호 경로 목록만 갱신(작업 정의·정의 파일 승인본은 그대로 — --approve 없이 설치한 경우)")
    a = ap.parse_args(argv)
    digests, pins, protected = _load_inputs(a)
    if a.cmd == "show":
        dirinfo = json.load(open(a.dirinfo)) if a.dirinfo and os.path.exists(a.dirinfo) else None
        text, _stat = render(a.manifest, digests, pins, protected, a.state, a.ct, dirinfo)
        sys.stdout.write(text)
        return 0
    if a.protected_only:
        os.makedirs(a.state, exist_ok=True)
        tmp = os.path.join(a.state, "protected.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(protected), f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(a.state, "protected.json"))
        return 0
    cur = tasks.load(a.manifest)
    save_snapshot(a.state, {n: task_def(t) for n, t in cur.items()}, {r: pins[r] for r in sorted({p for t in cur.values() for p in t["pins"]}) if r in pins}, protected)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
