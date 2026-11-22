#!/usr/bin/env python3
"""sbox 프로젝트 의존성 감시(plan sbox-depwatch, 체크리스트 S56).

프로젝트 저장소의 **선언**(락 파일·설치 스크립트 표시)을 읽어 위험 신호를 「발견 사항 파일」에 기록한다. 설치를 막거나 프로젝트 파일을 바꾸지 않는다(읽기 전용).
팀과 결과물을 공유하는 프로젝트에서 sbox 가 설치 동작을 바꾸면 팀과 결과가 어긋나므로(사용자 결정 2026-11-22) 이 도구는 감지·기록·보고만 한다.
등급(tier): general(기본, 경고만) / critical(사전 차단 — 단계 5, 아직 미구현). 정본은 매니페스트 `[project] tier`.

**이 파일은 nix 스토어 사본(waybar 타이머의 `tools.py periodic`)에서도 import 된다** — 표준 라이브러리만 쓰고 저장소 바깥 경로를 import 하지 않는다.
ctl 공통 봉투(`ctlkit`)는 `--json` 출력 때만 지연 import 한다(저장소 안 `sboxctl` 경로에서만 동작).

  scan                         매니페스트의 모든 프로젝트를 훑어 발견 사항 파일을 갱신(타이머가 매일 호출)
  list [--project P] [--json]  발견 사항 목록
  report [--project P]         팀 제안서 자료(신호별 건수·근거·저장소에 넣을 만한 규칙)
  tier NAME general|critical   매니페스트 [project] 의 tier 줄만 수정(파일을 되쓰지 않음)

한계: 스캔 대상은 호스트 쪽 저장소의 정적 상태(커밋된 락·선언)이며, ct 안에서 방금 설치된 의존성이 아니다. npm 만 지원(락 파일 존재·package-lock.json 의 hasInstallScript).
"""
import json
import os
import sys
import time
import tomllib

MANIFESTS = os.path.expanduser(os.environ.get("SBOX_MANIFESTS", "~/.config/sbox/manifests"))
STATE = os.path.expanduser(os.environ.get("SBOX_DEPWATCH_STATE", "~/.local/state/sbox/depwatch.json"))
TIERS = ("general", "critical")
LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
SKIP_DIRS = {"node_modules"}
NAME_CAP = 20


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def _pkg_dirs(repo):
    """package.json 이 있는 디렉터리: 저장소 루트 + 한 단계 아래(node_modules·숨김 폴더 제외)."""
    out = []
    if os.path.isfile(os.path.join(repo, "package.json")):
        out.append("")
    try:
        names = sorted(os.listdir(repo))
    except OSError:
        return out
    for n in names:
        if n in SKIP_DIRS or n.startswith("."):
            continue
        if os.path.isfile(os.path.join(repo, n, "package.json")):
            out.append(n)
    return out


def npm_findings(repo):
    """repo 아래 npm 위험 신호. 프로젝트 파일은 읽기만 한다."""
    found = []
    for rel in _pkg_dirs(repo):
        d = os.path.join(repo, rel) if rel else repo
        label = rel or "."
        locks = [n for n in LOCKS if os.path.isfile(os.path.join(d, n))]
        if not locks:
            found.append({"id": f"npm.no-lock:{label}", "kind": "no-lock", "severity": "warn",
                          "msg": f"{label}: package.json 이 있는데 락 파일이 없음 — 설치할 때마다 버전이 달라질 수 있음",
                          "evidence": "package.json 만 있음 (package-lock.json·npm-shrinkwrap.json·yarn.lock·pnpm-lock.yaml 없음)"})
            continue
        pl = os.path.join(d, "package-lock.json")
        if not os.path.isfile(pl):
            continue  # yarn·pnpm 락은 설치 스크립트 표시를 읽지 않는다(한계)
        try:
            with open(pl, encoding="utf-8") as f:
                lock = json.load(f)
        except (OSError, ValueError) as e:
            found.append({"id": f"npm.bad-lock:{label}", "kind": "bad-lock", "severity": "warn",
                          "msg": f"{label}: package-lock.json 을 읽지 못함", "evidence": str(e)[:200]})
            continue
        names = sorted({(p.split("node_modules/")[-1] if p else "(root)") for p, v in (lock.get("packages") or {}).items()
                        if p and isinstance(v, dict) and v.get("hasInstallScript")})
        if names:
            shown = ", ".join(names[:NAME_CAP]) + (f" 외 {len(names) - NAME_CAP}개" if len(names) > NAME_CAP else "")
            found.append({"id": f"npm.install-script:{label}", "kind": "install-script", "severity": "warn",
                          "msg": f"{label}: 설치 중 스크립트를 실행하는 패키지 {len(names)}개",
                          "evidence": shown})
    return found


def _manifest_list():
    try:
        files = sorted(f for f in os.listdir(MANIFESTS) if f.endswith(".toml"))
    except FileNotFoundError:
        return []
    out = []
    for f in files:
        try:
            with open(os.path.join(MANIFESTS, f), "rb") as fh:
                m = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as e:
            out.append((f[:-5], None, "general", f"매니페스트를 읽지 못함: {e}"))
            continue
        p = m.get("project") or {}
        tier = p.get("tier", "general")
        err = None
        if tier not in TIERS:
            err = f"tier 값이 잘못됨({tier!r}) — general 로 처리"
            tier = "general"
        out.append((p.get("name") or f[:-5], p.get("repo") or None, tier, err))
    return out


def scan():
    """모든 프로젝트를 훑어 발견 사항 파일을 갱신. 반환: {project: 발견 수}."""
    st = load_state()
    prev = st.get("projects", {})
    projects = {}
    for name, repo, tier, err in _manifest_list():
        findings = []
        notes = []
        if err:
            notes.append(err)
        if not repo or not os.path.isdir(repo):
            notes.append("저장소 경로가 없거나 디렉터리가 아님 — 스캔 건너뜀")
        else:
            findings = npm_findings(repo)
        old = {f["id"]: f.get("first_seen") for f in (prev.get(name, {}).get("findings") or [])}
        t = now()
        for f in findings:
            f["first_seen"] = old.get(f["id"]) or t
        projects[name] = {"tier": tier, "repo": repo, "scanned_at": t, "findings": findings, "notes": notes}
    st = {"version": 1, "scanned_at": now(), "projects": projects, "overrides": st.get("overrides", [])}
    save_state(st)
    return {n: len(p["findings"]) for n, p in projects.items()}


def listing(project=None):
    st = load_state()
    ps = st.get("projects", {})
    if project:
        if project not in ps:
            raise KeyError(project)
        ps = {project: ps[project]}
    return {"scanned_at": st.get("scanned_at"), "projects": ps, "overrides": st.get("overrides", [])}


RULES = {
    "no-lock": "락 파일을 저장소에 커밋하고 CI·설치는 락 기준(`npm ci`)으로 한다",
    "install-script": "설치 스크립트가 꼭 필요한 패키지만 허용 목록에 두고 나머지는 `ignore-scripts=true`(프로젝트 .npmrc)로 막는다",
    "bad-lock": "깨진 락 파일을 다시 만든다",
}


def report(project=None):
    data = listing(project)
    lines = []
    for name, p in data["projects"].items():
        lines.append(f"## {name}  (등급 {p['tier']}, 마지막 스캔 {p['scanned_at']})")
        for n in p.get("notes", []):
            lines.append(f"  ※ {n}")
        if not p["findings"]:
            lines.append("  발견 사항 없음")
            continue
        kinds = {}
        for f in p["findings"]:
            kinds.setdefault(f["kind"], []).append(f)
        for kind, fs in kinds.items():
            lines.append(f"  - {kind} {len(fs)}건 → 팀에 제안할 규칙: {RULES.get(kind, '(정해진 문구 없음)')}")
            for f in fs:
                lines.append(f"      · {f['msg']}  [{f['evidence']}]  (처음 {f['first_seen'][:10]})")
    return "\n".join(lines) if lines else "프로젝트가 없습니다(매니페스트 없음 — `sboxctl tools --from-repo DIR` 로 등록)"


def set_tier(name, tier):
    """매니페스트 [project] 구역 안의 tier 줄만 텍스트로 고친다(되쓰기 금지 — 주석·다른 구역 보존)."""
    if tier not in TIERS:
        raise ValueError(f"tier 는 {'|'.join(TIERS)} 중 하나여야 합니다: {tier}")
    path = os.path.join(MANIFESTS, f"{name}.toml")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == "[project]"), None)
    if start is None:
        raise ValueError("매니페스트에 [project] 구역이 없습니다")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    new = f'tier = "{tier}"'
    for i in range(start + 1, end):
        if lines[i].split("=")[0].strip() == "tier":
            lines[i] = new
            break
    else:
        ins = end
        while ins > start + 1 and not lines[ins - 1].strip():
            ins -= 1
        lines.insert(ins, new)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)
    return path


def _emit(cmd, ok, **kw):
    """ctl 공통 봉투. ctlkit 은 저장소 안(sboxctl 경로)에서만 import 된다."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.join(here, "..", "..", "mods", "_tools", "_lib", "ctlkit"))
    import ctlkit  # noqa: PLC0415 — 지연 import(스토어 사본의 scan 은 이 경로를 타지 않는다)
    ctlkit.emit_json(cmd, ok, **kw)


def main(a):
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]
    proj = a[a.index("--project") + 1] if "--project" in a else None
    cmd = a[0] if a else ""
    try:
        if cmd == "scan":
            res = scan()
            if as_json:
                _emit("depwatch scan", True, data={"findings": res})
            else:
                print(json.dumps(res, ensure_ascii=False))
        elif cmd == "list":
            data = listing(proj)
            if as_json:
                _emit("depwatch list", True, data=data)
            else:
                for n, p in data["projects"].items():
                    print(f"{n}\t{p['tier']}\t{len(p['findings'])}건\t{p['scanned_at']}")
                    for f in p["findings"]:
                        print(f"    [{f['severity']}] {f['msg']}  ({f['evidence']})")
        elif cmd == "report":
            txt = report(proj)
            if as_json:
                _emit("depwatch report", True, text=txt)
            else:
                print(txt)
        elif cmd == "tier" and len(a) == 3:
            p = set_tier(a[1], a[2])
            if as_json:
                _emit("depwatch tier", True, data={"manifest": p, "tier": a[2]})
            else:
                print(f"{p}: tier = {a[2]}")
        else:
            print(__doc__, file=sys.stderr)
            sys.exit(2)
    except (KeyError, ValueError, FileNotFoundError) as e:
        msg = f"depwatch: {e}"
        if as_json:
            _emit(f"depwatch {cmd}", False, error=msg, code=1)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
