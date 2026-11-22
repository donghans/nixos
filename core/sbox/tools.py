#!/usr/bin/env python3
"""sbox 도구 층 엔진(plan dev-sandbox-pilot §29·§29-3, 체크리스트 S5·S34·S46).

도구마다 코드를 짜지 않고 `core/sbox/tools.toml`(카탈로그)에 「어디서 받고·무엇으로 검증하고·어떻게 푸는가」를 선언한다.
엔진은 호스트에서 공식 배포 파일을 받아 **체크섬(필요하면 GPG 서명까지) 검증** 후 `~/.cache/sbox/tools/<도구>/<버전>/` 에 풀어 쓰기 권한을 뺀다.
컨테이너는 그 폴더를 읽기 전용 디스크 장치로만 `/opt/tools/<도구>/<버전>` 에 받는다(컨테이너가 직접 내려받지 않음).

역할별 버전 정책(사용자 방침 2026-11-22):
  re(실행환경)  버전 고정 — 매니페스트 [resolved] 에 처음 풀린 정확한 버전을 기록, --update 로만 다시 해석
  de(개발환경)  항상 최신 — 해석 결과를 고정하지 않고, 새 버전을 받으면 쓰이지 않는 옛 버전은 `prune` 으로 정리

서브명령(표준출력은 기계가 읽는 한 줄 또는 JSON):
  catalog                      카탈로그의 도구·역할·설명(JSON)
  resolve TOOL [SPEC]          SPEC(22, 22.11, 22.11.0, latest, stable, lts) → 정확한 버전(de 는 SPEC 생략 시 latest)
  fetch TOOL VERSION           내려받기·검증·풀기 → 풀린 폴더 경로
  links TOOL                   컨테이너 /usr/local/bin 에 만들 링크(이름 → 폴더 안 상대 경로, JSON)
  prune TOOL [--keep V]        표준입력으로 받은 「쓰이는 폴더 경로」 목록에 없는 옛 버전을 지움(--keep 은 남길 버전) → 지운 버전 목록
  infer REPO                   프로젝트 파일(.nvmrc·package.json engines·go.mod)에서 버전 추론 → JSON
  effective MANIFEST           매니페스트의 [override] 가 [inferred] 를 덮은 최종 도구 표 → JSON
  plan [--repo DIR] [--manifest FILE] [--update] [--tool T=SPEC ...]
                               매니페스트를 만들거나 갱신하고, re 도구는 정확한 버전을 [resolved] 에 고정해 JSON 으로 낸다
                               (이미 고정된 버전은 스펙이 그대로면 재사용 — 새 패치로 조용히 바뀌지 않음. --update 로만 다시 해석)

검증: 체크섬 출처(HTTPS)와 받은 파일을 대조하고, 처음 본 (도구, 버전, 파일)의 해시를 잠금 파일(`~/.config/sbox/tools.lock`)에 적는다(TOFU).
이후엔 잠금 값과 다르면 거부한다. 카탈로그에 서명(gpg-detached)이 선언돼 있으면 체크섬 문서를 gpg 로 검증하고 주 키 지문이 선언값과 같아야 통과한다.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

CACHE = os.path.expanduser(os.environ.get("SBOX_TOOLS_CACHE", "~/.cache/sbox/tools"))
LOCK = os.path.expanduser(os.environ.get("SBOX_TOOLS_LOCK", "~/.config/sbox/tools.lock"))
CATALOG = os.environ.get("SBOX_TOOLS_CATALOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.toml"))
NODE_INDEX = "https://nodejs.org/dist/index.json"
GO_JSON = "https://go.dev/dl/?mode=json&include=all"
EXACT = re.compile(r"\d+\.\d+(\.\d+)?")


def fail(msg):
    print(f"sbox-tools: {msg}", file=sys.stderr)
    sys.exit(1)


def http(url):
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 — 카탈로그가 고정한 https 주소
        return r.read()


def catalog():
    with open(CATALOG, "rb") as f:
        return tomllib.load(f)


def tool(name):
    t = catalog().get(name)
    if not isinstance(t, dict):
        fail(f"카탈로그에 없는 도구: {name} (있는 도구: {', '.join(catalog())})")
    return t


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


# ---------- 해석(resolver) ----------
def resolve(name, spec=None):
    t = tool(name)
    r = t.get("resolver") or {}
    typ = r.get("type")
    if not spec:
        spec = r.get("default") if t.get("role") == "de" else None
        if not spec:
            fail(f"{name}: 스펙이 필요합니다(re 도구는 생략할 수 없음)")
    spec = str(spec).lstrip("v")
    if typ == "node-index":
        v = _node_resolve(spec)
    elif typ == "go-json":
        v = _go_resolve(spec)
    elif typ == "channel-file" and spec in r.get("channels", []):
        v = http(r["url"].format(channel=spec)).decode().strip()
    else:
        v = spec
    if not EXACT.fullmatch(v):
        fail(f"{name}: 해석한 버전이 올바르지 않습니다: {spec} → {v!r}")
    _rollback_guard(name, spec, v, moving=(typ == "channel-file" and spec in r.get("channels", [])) or spec in ("latest", "lts"))
    mn = t.get("min_version")
    if mn and vtuple(v) < vtuple(mn):
        fail(f"{name} {v} 는 최소 버전 {mn} 보다 낮습니다(서명 없는 옛 릴리스 등) — 거부")
    return v


def _rollback_guard(name, spec, v, moving):
    """움직이는 가리킴(latest·lts·채널 이름)이 **본 적 있는 최고 버전보다 낮은 버전**을 가리키면 거부한다(롤백·다운그레이드 방어, S47).
    채널 파일은 서명이 없어 공격자가 옛 서명 릴리스를 가리키게 해도 서명 검증은 통과하기 때문이다. 공급자의 정상 롤백이면
    SBOX_TOOLS_ALLOW_DOWNGRADE=1 로 한 번 허용한다. 고정 버전(정확한 X.Y.Z 스펙)에는 적용하지 않는다."""
    if not moving:
        return
    key = f"_max/{name}/{spec}"
    lock = load_lock()
    prev = lock.get(key)
    if prev and vtuple(v) < vtuple(prev) and os.environ.get("SBOX_TOOLS_ALLOW_DOWNGRADE") != "1":
        fail(f"{name} {spec} 가 이전에 본 {prev} 보다 낮은 {v} 를 가리킵니다 — 롤백 공격이거나 공급자의 정상 롤백입니다. "
             f"확인 뒤 SBOX_TOOLS_ALLOW_DOWNGRADE=1 로 다시 실행하세요")
    # 새 최고이거나, 사용자가 낮아진 것을 허용한 경우(그 값을 새 기준선으로 — 매번 환경변수를 줄 필요가 없게)
    if not prev or vtuple(v) > vtuple(prev) or (vtuple(v) < vtuple(prev) and os.environ.get("SBOX_TOOLS_ALLOW_DOWNGRADE") == "1"):
        lock[key] = v
        save_lock(lock)


def _node_resolve(spec):
    idx = json.loads(http(NODE_INDEX))
    if spec == "lts":
        for e in idx:
            if e.get("lts"):
                return e["version"].lstrip("v")
        fail("Node LTS 를 찾지 못했습니다")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", spec):
        fail(f"node 스펙 표기가 올바르지 않습니다: {spec}")
    for e in idx:  # 최신순
        v = e["version"].lstrip("v")
        if v == spec or v.startswith(spec + "."):
            return v
    fail(f"node {spec} 에 맞는 버전이 없습니다")


def _go_entries():
    return [e for e in json.loads(http(GO_JSON)) if e.get("stable")]


def _go_resolve(spec):
    es = _go_entries()
    if spec == "latest":
        return es[0]["version"].removeprefix("go")
    for e in es:  # 최신순
        v = e["version"].removeprefix("go")
        if v == spec or v.startswith(spec + "."):
            return v
    fail(f"go {spec} 에 맞는 안정 버전이 없습니다")


# ---------- 잠금(TOFU) ----------
def load_lock():
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_lock(d):
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=True)


# ---------- 서명(gpg) ----------
def gpg_cmd():
    """gpg 가 호스트에 없으면 일회성으로 nix shell nixpkgs#gnupg 를 쓴다(전역 지침: 임의 설치 금지)."""
    if shutil.which("gpg"):
        return ["gpg"]
    if shutil.which("nix"):
        return ["nix", "shell", "nixpkgs#gnupg", "-c", "gpg"]
    fail("gpg 도 nix 도 없습니다")


def verify_gpg(doc, sig, key, fingerprint, workdir):
    """분리 서명 검증. 주 키 지문이 fingerprint 와 같아야 통과한다(VALIDSIG 의 마지막 필드)."""
    p = {n: os.path.join(workdir, n) for n in ("doc", "doc.sig", "key.asc")}
    for n, data in (("doc", doc), ("doc.sig", sig), ("key.asc", key)):
        open(p[n], "wb").write(data)
    home = os.path.join(workdir, "gnupg")
    os.makedirs(home, mode=0o700, exist_ok=True)
    g = gpg_cmd() + ["--homedir", home, "--batch", "--no-tty"]
    r = subprocess.run(g + ["--import", p["key.asc"]], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"공개키 가져오기 실패: {r.stderr.strip()[:200]}")
    r = subprocess.run(g + ["--status-fd", "1", "--verify", p["doc.sig"], p["doc"]], capture_output=True, text=True)
    prim = None
    for ln in r.stdout.splitlines():
        if ln.startswith("[GNUPG:] VALIDSIG"):
            prim = ln.split()[-1].upper()
        if ln.startswith(("[GNUPG:] BADSIG", "[GNUPG:] ERRSIG")):
            fail(f"서명 검증 실패: {ln}")
    if prim != fingerprint.upper():
        fail(f"서명 주 키 지문이 선언값과 다릅니다(받은 {prim}, 선언 {fingerprint}) — 중단")


# ---------- 체크섬 출처 ----------
def expected_hash(name, t, version, workdir):
    """(sha256, 산출물 파일 이름) 을 돌려준다. 카탈로그에 서명이 선언돼 있으면 체크섬 문서를 먼저 서명 검증한다."""
    c = t["checksum"]
    typ = c["type"]
    fmt = {"version": version}
    if typ == "go-json":
        want_file = f"go{version}.linux-amd64.tar.gz"
        for e in json.loads(http(GO_JSON)):
            if e["version"] == f"go{version}":
                for f in e["files"]:
                    if f["filename"] == want_file and f.get("sha256"):
                        return f["sha256"], want_file
        fail(f"go.dev JSON 에 {want_file} 의 해시가 없습니다")
    doc = http(c["url"].format(**fmt))
    sg = t.get("signature") or {"type": "none"}
    if sg["type"] == "gpg-detached":
        verify_gpg(doc, http(sg["sig_url"].format(**fmt)), http(sg["key_url"]), sg["fingerprint"], workdir)
    elif sg["type"] != "none":
        fail(f"{name}: 알 수 없는 서명 방식 {sg['type']}")
    if typ == "sums-file":
        fname = c["name"].format(**fmt)
        want = next((ln.split()[0] for ln in doc.decode().splitlines() if ln.endswith(" " + fname)), None)
        if not want:
            fail(f"체크섬 문서에 {fname} 이 없습니다")
        return want, fname
    if typ == "json-manifest":
        cur = json.loads(doc)
        if cur.get("version") not in (None, version):
            fail(f"manifest 버전 불일치: {cur.get('version')} ≠ {version}")
        for k in c["path"].split("."):
            cur = (cur or {}).get(k)
        if not isinstance(cur, str):
            fail(f"manifest 에서 {c['path']} 를 찾지 못했습니다")
        return cur, None
    fail(f"알 수 없는 체크섬 방식: {typ}")


# ---------- 받기·풀기 ----------
def _make_writable_tree(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)


def _make_readonly_tree(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode & ~0o222)
    os.chmod(path, os.stat(path).st_mode & ~0o222)


def fetch(name, version):
    t = tool(name)
    if not EXACT.fullmatch(version):
        fail(f"정확한 버전이 필요합니다: {version}")
    dest = os.path.join(CACHE, name, version)
    if os.path.isdir(dest) and os.listdir(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(dest), prefix=".x-")
    try:
        want, fname = expected_hash(name, t, version, tmp)
        if not re.fullmatch(r"[a-f0-9]{64}", want):
            fail(f"체크섬 형식이 올바르지 않습니다: {want!r}")
        url = t["url"].format(version=version, file=fname or "")
        key = f"{name}/{version}/{os.path.basename(url)}"
        lock = load_lock()
        if key in lock and lock[key] != want:
            fail(f"잠금 해시와 공식 체크섬이 다릅니다({key}) — 중단")
        h = hashlib.sha256()
        art = os.path.join(tmp, "artifact")
        with urllib.request.urlopen(url, timeout=300) as r, open(art, "wb") as out:  # noqa: S310
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                h.update(b)
                out.write(b)
        if h.hexdigest() != want:
            fail(f"sha256 불일치: 받은 {h.hexdigest()} ≠ 공식 {want}")
        if key not in lock:
            lock[key] = want
            save_lock(lock)
        a = t["archive"]
        final = os.path.join(tmp, "final")
        if a["type"] == "tar":
            ex = os.path.join(tmp, "ex")
            with tarfile.open(art) as tf:
                tf.extractall(ex, filter="data")
            src = ex
            for _ in range(int(a.get("strip", 0))):
                kids = os.listdir(src)
                if len(kids) != 1:
                    fail("압축 파일의 맨 앞 폴더가 하나가 아닙니다")
                src = os.path.join(src, kids[0])
            os.replace(src, final)
        elif a["type"] == "binary":
            os.makedirs(final)
            os.replace(art, os.path.join(final, a["name"]))
            os.chmod(os.path.join(final, a["name"]), 0o755)
        else:
            fail(f"알 수 없는 압축 방식: {a['type']}")
        for rel in (t.get("links") or {}).values():
            if not os.path.lexists(os.path.join(final, rel)):
                fail(f"푼 결과에 링크 대상이 없습니다: {rel}")
        os.replace(final, dest)  # 폴더 이름 바꾸기는 쓰기 권한이 필요하므로 읽기 전용으로 만들기 전에
        _make_readonly_tree(dest)
    finally:
        if os.path.isdir(tmp):
            _make_writable_tree(tmp)
            shutil.rmtree(tmp, ignore_errors=True)
    return dest


def prune(name, keep, used):
    """CACHE/name/* 중 keep 이 아니고 used(경로 집합)에 없는 버전 폴더를 지운다."""
    base = os.path.join(CACHE, name)
    removed = []
    if not os.path.isdir(base):
        return removed
    used = {os.path.realpath(p) for p in used}
    for v in sorted(os.listdir(base)):
        d = os.path.join(base, v)
        if v.startswith(".") or v == keep or os.path.realpath(d) in used or not os.path.isdir(d):
            continue
        _make_writable_tree(d)
        shutil.rmtree(d)
        removed.append(v)
    return removed


# ---------- 프로젝트 추론·매니페스트 ----------
def infer(repo):
    out = {}
    nv = os.path.join(repo, ".nvmrc")
    if os.path.isfile(nv):
        out["node"] = {"spec": open(nv, encoding="utf-8").read().strip().lstrip("v"), "source": ".nvmrc"}
    pj = os.path.join(repo, "package.json")
    if "node" not in out and os.path.isfile(pj):
        try:
            eng = (json.load(open(pj, encoding="utf-8")).get("engines") or {}).get("node")
        except ValueError:
            eng = None
        m = re.search(r"(\d+)", eng or "")
        if m:
            out["node"] = {"spec": m.group(1), "source": f"package.json engines.node ({eng})"}
    gm = os.path.join(repo, "go.mod")
    if os.path.isfile(gm):
        txt = open(gm, encoding="utf-8").read()
        m = re.search(r"^toolchain\s+go(\d+\.\d+(?:\.\d+)?)", txt, re.M) or re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", txt, re.M)
        if m:
            out["go"] = {"spec": m.group(1), "source": "go.mod"}
    return out


def effective(path):
    with open(path, "rb") as f:
        m = tomllib.load(f)
    tools = {}
    for k, v in (m.get("inferred") or {}).items():
        tools[k] = {"spec": v, "from": "inferred"}
    for k, v in (m.get("override") or {}).items():
        tools[k] = {"spec": v, "from": "override"}
    return tools


def manifest_path(name):
    return os.path.expanduser(f"~/.config/sbox/manifests/{name}.toml")


def q(x):
    return json.dumps(str(x), ensure_ascii=False)


def write_manifest(path, project, repo, inferred, override, resolved):
    lines = ["# sbox 프로젝트 버전 매니페스트(plan dev-sandbox-pilot §29). [inferred]·[resolved] 는 sbox 가 다시 쓰고, [override] 는 사람이 씁니다.",
             "# [resolved] 는 re(실행환경) 도구만 — de(개발환경) 도구는 항상 최신이라 고정하지 않습니다.",
             "[project]", f"name = {q(project)}", f"repo = {q(repo)}", "", "[inferred]"]
    for k, v in sorted(inferred.items()):
        lines.append(f"{k} = {q(v['spec'])}  # 출처: {v['source']}".replace("\n", " "))
    lines += ["", "[override]"] + [f"{k} = {q(v)}" for k, v in sorted(override.items())]
    for k, v in sorted(resolved.items()):
        lines += ["", f"[resolved.{k}]", f"spec = {q(v['spec'])}", f"version = {q(v['version'])}"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def plan(a):
    repo = path = None
    update = False
    given = {}
    i = 0
    while i < len(a):
        if a[i] == "--repo":
            repo = os.path.abspath(a[i + 1]); i += 2
        elif a[i] == "--manifest":
            path = os.path.abspath(a[i + 1]); i += 2
        elif a[i] == "--update":
            update = True; i += 1
        elif a[i] == "--tool":
            k, _, v = a[i + 1].partition("="); given[k] = v; i += 2
        else:
            fail(f"plan: 알 수 없는 인자 {a[i]}")
    if not (repo or path):
        fail("plan: --repo 또는 --manifest 가 필요합니다")
    if not path:
        path = manifest_path(os.path.basename(repo.rstrip("/")))
    old = {}
    if os.path.isfile(path):
        with open(path, "rb") as f:
            old = tomllib.load(f)
    project = (old.get("project") or {}).get("name") or (os.path.basename(repo.rstrip("/")) if repo else os.path.basename(path)[:-5])
    repo = repo or (old.get("project") or {}).get("repo", "")
    inferred = infer(repo) if repo and os.path.isdir(repo) else {k: {"spec": v, "source": "기존 매니페스트"} for k, v in (old.get("inferred") or {}).items()}
    override = dict(old.get("override") or {})
    override.update(given)
    resolved_old = old.get("resolved") or {}
    effective_spec = {k: v["spec"] for k, v in inferred.items()}
    effective_spec.update(override)
    out, resolved = {}, {}
    for k, spec in effective_spec.items():
        t = tool(k)
        src = "override" if k in override else inferred.get(k, {}).get("source", "인자")
        if t.get("role") == "de":  # 개발환경 도구: 고정하지 않고 매번 해석(항상 최신)
            ver = resolve(k, spec)
            out[k] = {"spec": spec, "version": ver, "source": src, "how": "최신(de, 고정 안 함)", "role": "de"}
            continue
        prev = resolved_old.get(k) or {}
        if not update and prev.get("spec") == spec and prev.get("version"):
            ver, how = prev["version"], "고정값 재사용"
        else:
            ver = spec.lstrip("v") if re.fullmatch(r"v?\d+\.\d+\.\d+", spec) else resolve(k, spec)
            how = "새로 해석" + (" (--update)" if update else "")
        resolved[k] = {"spec": spec, "version": ver}
        out[k] = {"spec": spec, "version": ver, "source": src, "how": how, "role": "re"}
    write_manifest(path, project, repo, inferred, override, resolved)
    return {"manifest": path, "tools": out}


def main(a):
    if a and a[0] == "catalog":
        print(json.dumps({k: {"role": v.get("role"), "desc": v.get("desc")} for k, v in catalog().items()}, ensure_ascii=False))
    elif a and a[0] == "resolve" and len(a) in (2, 3):
        print(resolve(a[1], a[2] if len(a) == 3 else None))
    elif len(a) == 3 and a[0] == "fetch":
        print(fetch(a[1], a[2]))
    elif len(a) == 2 and a[0] == "links":
        print(json.dumps(tool(a[1]).get("links") or {}, ensure_ascii=False))
    elif a and a[0] == "prune" and len(a) >= 2:
        keep = a[3] if len(a) >= 4 and a[2] == "--keep" else None
        used = [ln.strip() for ln in sys.stdin if ln.strip()]
        print(" ".join(prune(a[1], keep, used)))
    elif len(a) == 2 and a[0] == "infer":
        print(json.dumps(infer(a[1]), ensure_ascii=False))
    elif len(a) == 2 and a[0] == "effective":
        print(json.dumps(effective(a[1]), ensure_ascii=False))
    elif a and a[0] == "plan":
        print(json.dumps(plan(a[1:]), ensure_ascii=False))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
