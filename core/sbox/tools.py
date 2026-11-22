#!/usr/bin/env python3
"""sbox 도구 층(plan dev-sandbox-pilot §29, 체크리스트 S5·S34).

호스트에서 공식 배포 파일을 받아 **sha256 을 검증**하고 풀어 `~/.cache/sbox/tools/<도구>/<버전>/` 에 둔다.
컨테이너는 그 폴더를 **읽기 전용 디스크 장치**로만 `/opt/tools/<도구>/<버전>` 에 받는다(컨테이너가 직접 내려받지 않음).

서브명령(표준출력은 기계가 읽는 한 줄 또는 JSON):
  resolve TOOL SPEC            SPEC(22, 22.11, 22.11.0, lts) → 정확한 버전
  fetch TOOL VERSION           내려받기·검증·풀기 → 풀린 폴더 경로
  (지원 도구: node — 공식 tarball+SHASUMS256 / claude — 공식 네이티브 바이너리+GPG 서명 manifest)
  infer REPO                   프로젝트 파일(.nvmrc·package.json engines)에서 버전 추론 → JSON
  effective MANIFEST           매니페스트의 [override] 가 [inferred] 를 덮은 최종 도구 표 → JSON
  plan [--repo DIR] [--manifest FILE] [--update] [--tool T=SPEC ...]
                               매니페스트를 만들거나 갱신하고, **정확한 버전**을 [resolved] 에 고정해 JSON 으로 낸다
                               (이미 고정된 버전은 스펙이 그대로면 재사용 — 새 패치로 조용히 바뀌지 않음. --update 로만 다시 해석)

검증: 공식 SHASUMS256.txt(HTTPS)의 값과 받은 파일을 대조하고, 처음 본 (도구, 버전, 파일)의 해시를 잠금 파일
(`~/.config/sbox/tools.lock`)에 적는다(TOFU). 이후엔 잠금 값과 다르면 거부한다.
서명(GPG) 검증은 하지 않는다 — v1 한계, 문서 §29 에 기록.
"""
import hashlib
import shutil
import subprocess
import json
import os
import re
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

CACHE = os.path.expanduser(os.environ.get("SBOX_TOOLS_CACHE", "~/.cache/sbox/tools"))
LOCK = os.path.expanduser(os.environ.get("SBOX_TOOLS_LOCK", "~/.config/sbox/tools.lock"))
NODE_DIST = "https://nodejs.org/dist"
CLAUDE_BASE = "https://downloads.claude.ai/claude-code-releases"
CLAUDE_KEY_URL = "https://downloads.claude.ai/keys/claude-code.asc"
# 공식 문서(code.claude.com/docs/en/setup 「Verify the manifest signature」, 2026-11-22 확인)가 적은 릴리스 서명 키 지문. 코드에 고정한다.
CLAUDE_KEY_FPR = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
CLAUDE_PLATFORM = "linux-x64"
SUPPORTED = ("node", "claude")


def fail(msg):
    print(f"sbox-tools: {msg}", file=sys.stderr)
    sys.exit(1)


def http(url):
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 — https 고정 주소
        return r.read()


def node_resolve(spec):
    idx = json.loads(http(f"{NODE_DIST}/index.json"))
    spec = str(spec).lstrip("v")
    if spec == "lts":
        for e in idx:
            if e.get("lts"):
                return e["version"].lstrip("v")
        fail("LTS 를 찾지 못했습니다")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", spec):
        fail(f"지원하지 않는 버전 표기: {spec}")
    for e in idx:  # index.json 은 최신순
        v = e["version"].lstrip("v")
        if v == spec or v.startswith(spec + "."):
            return v
    fail(f"node {spec} 에 맞는 버전이 없습니다")


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


def node_fetch(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"정확한 버전이 필요합니다: {version}")
    dest = os.path.join(CACHE, "node", version)
    if os.path.isfile(os.path.join(dest, "bin", "node")):
        return dest
    fname = f"node-v{version}-linux-x64.tar.xz"
    sums = http(f"{NODE_DIST}/v{version}/SHASUMS256.txt").decode()
    want = next((ln.split()[0] for ln in sums.splitlines() if ln.endswith(" " + fname)), None)
    if not want:
        fail(f"SHASUMS256.txt 에 {fname} 이 없습니다")
    key = f"node/{version}/{fname}"
    lock = load_lock()
    if key in lock and lock[key] != want:
        fail(f"잠금 해시와 공식 SHASUMS 가 다릅니다({key}) — 중단")
    data = http(f"{NODE_DIST}/v{version}/{fname}")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        fail(f"sha256 불일치: 받은 {got} ≠ 공식 {want}")
    if key not in lock:
        lock[key] = want
        save_lock(lock)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(dest), prefix=".x-")
    with tempfile.NamedTemporaryFile(suffix=".tar.xz", dir=tmp) as t:
        t.write(data)
        t.flush()
        with tarfile.open(t.name) as tf:
            tf.extractall(tmp, filter="data")
    os.rename(os.path.join(tmp, f"node-v{version}-linux-x64"), dest)
    os.rmdir(tmp) if not os.listdir(tmp) else None
    # 읽기 전용(소유자도 쓰기 금지) — 컨테이너에 ro 로 주는 폴더가 호스트에서도 바뀌지 않게
    for root, dirs, files in os.walk(dest):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode & ~0o222)
    os.chmod(dest, os.stat(dest).st_mode & ~0o222)
    return dest


def gpg_cmd():
    """gpg 가 호스트에 없으면 일회성으로 nix shell nixpkgs#gnupg 를 쓴다(전역 지침: 임의 설치 금지)."""
    if shutil.which("gpg"):
        return ["gpg"]
    if shutil.which("nix"):
        return ["nix", "shell", "nixpkgs#gnupg", "-c", "gpg"]
    fail("gpg 도 nix 도 없습니다")


def claude_resolve(spec):
    spec = str(spec).lstrip("v")
    if spec in ("latest", "stable"):
        v = http(f"{CLAUDE_BASE}/{spec}").decode().strip()
    else:
        v = spec
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        fail(f"claude 버전 표기가 올바르지 않습니다: {spec} → {v!r}")
    maj = tuple(int(x) for x in v.split("."))
    if maj < (2, 1, 89):
        fail(f"claude {v} 는 서명된 manifest 가 없는 옛 릴리스입니다(2.1.89 부터 서명) — 거부")
    return v


def claude_verify_manifest(version, workdir):
    """manifest.json 을 내려받아 분리 서명을 gpg 로 검증하고(주 키 지문이 고정값과 같아야 함) 파싱한 dict 를 돌려준다."""
    mpath = os.path.join(workdir, "manifest.json")
    open(mpath, "wb").write(http(f"{CLAUDE_BASE}/{version}/manifest.json"))
    open(mpath + ".sig", "wb").write(http(f"{CLAUDE_BASE}/{version}/manifest.json.sig"))
    keyfile = os.path.join(workdir, "key.asc")
    open(keyfile, "wb").write(http(CLAUDE_KEY_URL))
    home = os.path.join(workdir, "gnupg")
    os.makedirs(home, mode=0o700)
    g = gpg_cmd() + ["--homedir", home, "--batch", "--no-tty"]
    r = subprocess.run(g + ["--import", keyfile], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"공개키 가져오기 실패: {r.stderr.strip()[:200]}")
    r = subprocess.run(g + ["--status-fd", "1", "--verify", mpath + ".sig", mpath], capture_output=True, text=True)
    prim = None
    for ln in r.stdout.splitlines():
        if ln.startswith("[GNUPG:] VALIDSIG"):
            prim = ln.split()[-1].upper()  # 마지막 필드가 주 키 지문
        if ln.startswith("[GNUPG:] BADSIG") or ln.startswith("[GNUPG:] ERRSIG"):
            fail(f"manifest 서명 검증 실패: {ln}")
    if prim != CLAUDE_KEY_FPR:
        fail(f"manifest 서명 주 키 지문이 고정값과 다릅니다(받은 {prim}, 고정 {CLAUDE_KEY_FPR}) — 중단")
    return json.load(open(mpath, encoding="utf-8"))


def claude_fetch(version):
    dest = os.path.join(CACHE, "claude", version)
    if os.path.isfile(os.path.join(dest, "claude")):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(dest), prefix=".x-")
    try:
        m = claude_verify_manifest(version, tmp)
        if m.get("version") != version:
            fail(f"manifest 버전 불일치: {m.get('version')} ≠ {version}")
        plat = (m.get("platforms") or {}).get(CLAUDE_PLATFORM) or {}
        want = plat.get("checksum", "")
        if not re.fullmatch(r"[a-f0-9]{64}", want):
            fail(f"manifest 에 {CLAUDE_PLATFORM} 체크섬이 없습니다")
        key = f"claude/{version}/{CLAUDE_PLATFORM}"
        lock = load_lock()
        if key in lock and lock[key] != want:
            fail(f"잠금 해시와 서명된 manifest 가 다릅니다({key}) — 중단")
        h = hashlib.sha256()
        binp = os.path.join(tmp, "claude")
        with urllib.request.urlopen(f"{CLAUDE_BASE}/{version}/{CLAUDE_PLATFORM}/claude", timeout=120) as r, open(binp, "wb") as out:  # noqa: S310
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                h.update(b)
                out.write(b)
        if h.hexdigest() != want:
            fail(f"sha256 불일치: 받은 {h.hexdigest()} ≠ 서명된 manifest {want}")
        if key not in lock:
            lock[key] = want
            save_lock(lock)
        os.chmod(binp, 0o555)
        os.makedirs(dest)
        os.replace(binp, os.path.join(dest, "claude"))
        os.chmod(dest, 0o555)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # gnupg 작업 폴더 포함
    return dest


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
    return json.dumps(str(x), ensure_ascii=False)  # TOML 기본 문자열과 호환되는 따옴표 표기


def write_manifest(path, project, repo, inferred, override, resolved):
    lines = ["# sbox 프로젝트 버전 매니페스트(plan dev-sandbox-pilot §29). [inferred]·[resolved] 는 sbox 가 다시 쓰고, [override] 는 사람이 씁니다.",
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
    override.update(given)  # 명령줄 지정은 override 로 기록된다
    resolved_old = old.get("resolved") or {}
    effective_spec = {k: v["spec"] for k, v in inferred.items()}
    effective_spec.update(override)
    out, resolved = {}, {}
    for k, spec in effective_spec.items():
        if k not in SUPPORTED:
            fail(f"지원하지 않는 도구: {k} (지원: {', '.join(SUPPORTED)})")
        prev = resolved_old.get(k) or {}
        if not update and prev.get("spec") == spec and prev.get("version"):
            ver, how = prev["version"], "고정값 재사용"
        else:
            if re.fullmatch(r"v?\d+\.\d+\.\d+", spec):
                ver = spec.lstrip("v")
            else:
                ver = node_resolve(spec) if k == "node" else claude_resolve(spec)
            how = "새로 해석" + (" (--update)" if update else "")
        resolved[k] = {"spec": spec, "version": ver}
        src = "override" if k in override else inferred.get(k, {}).get("source", "인자")
        out[k] = {"spec": spec, "version": ver, "source": src, "how": how}
    write_manifest(path, project, repo, inferred, override, resolved)
    return {"manifest": path, "tools": out}


def main(a):
    if len(a) >= 3 and a[0] == "resolve":
        if a[1] not in SUPPORTED:
            fail(f"지원하지 않는 도구: {a[1]} (지원: {', '.join(SUPPORTED)})")
        print(node_resolve(a[2]) if a[1] == "node" else claude_resolve(a[2]))
    elif len(a) == 3 and a[0] == "fetch":
        if a[1] not in SUPPORTED:
            fail(f"지원하지 않는 도구: {a[1]} (지원: {', '.join(SUPPORTED)})")
        print(node_fetch(a[2]) if a[1] == "node" else claude_fetch(a[2]))
    elif len(a) == 2 and a[0] == "infer":
        print(json.dumps(infer(a[1]), ensure_ascii=False))
    elif a and a[0] == "plan":
        print(json.dumps(plan(a[1:]), ensure_ascii=False))
    elif len(a) == 2 and a[0] == "effective":
        print(json.dumps(effective(a[1]), ensure_ascii=False))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
