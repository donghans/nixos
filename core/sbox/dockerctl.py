#!/usr/bin/env python3
"""sbox 컨테이너 안 Docker(rootless) 설치의 **호스트 쪽 계획 도구**(plan dev-sandbox-pilot §29-15, 체크리스트 S53·S55).
`sboxctl docker NAME` 이 부른다. 호스트는 Docker 저장소에서 온 어떤 것도 **실행하지 않는다** — 키(데이터)를 보관·검증하고, 설치할 버전을 고르고,
컨테이너에 쓸 설정 내용을 만들 뿐이다. 설치(apt)는 컨테이너 안 root 가 하고 서명은 apt 가 고정 키로 검증한다.

서브명령(표준출력은 JSON 또는 한 줄):
  wanted [--repo DIR] [--manifest F]   이 프로젝트가 Docker 를 쓰나(우선순위: 매니페스트 [override] docker = "yes"|"no" > [resolved.docker] 기록 > 저장소의 compose·Dockerfile) → 「yes <근거>」 / 「no」(종료코드 0/1)
  plan --distro debian|ubuntu --codename C --arch amd64 [--manifest F] [--update]
                                       키 고정(필요 시 독립 출처 교차 확인) + 쿨다운을 적용한 설치 버전 선택 → JSON(key_file·sources·versions·notes)
                                       --manifest 가 있고 [resolved.docker] 가 있으면 그 버전을 재사용(--update 로만 다시 고름), 새로 고르면 매니페스트에 기록
  key                                  고정 키를 보장하고 그 경로를 출력(이미 있으면 재검증만)

키 규칙: 키 파일은 「`pub` 레코드가 정확히 하나이고 그 지문이 공식 값」이어야 한다(공격자가 자기 키를 하나 더 붙인 파일을 거른다). 처음 고정할 때
`tools.py pincheck apt-key:docker`(독립 출처 N곳)를 통과해야 한다. 고정한 파일이 바뀌었거나 검증에 실패하면 거부 — 다시 고정하려면 그 파일을 사람이 지운다.
쿨다운: docker-ce·containerd.io 각각 apt 저장소 안 **.deb 파일의 Last-Modified** 가 N일(기본 7, SBOX_TOOLS_MIN_AGE_DAYS) 미만인 버전은 건너뛴다
(GitHub 릴리스 날짜가 아니라 apt 에 실제로 올라온 날짜라 「apt 에 있나」도 같이 확인된다). 한계: 이미지(docker pull)·Docker 의 정상 서명 악성 버전이 N일 넘게 들키지 않는 경우는 못 막는다."""
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools  # noqa: E402

KEY_FPR = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
KEY_URL = "https://download.docker.com/linux/debian/gpg"
BASE = "https://download.docker.com/linux"
PKGS = ("docker-ce", "docker-ce-cli", "docker-ce-rootless-extras")   # 같은 버전 문자열로 맞춘다
CONTAINERD = "containerd.io"
KEYDIR = os.path.expanduser(os.environ.get("SBOX_DOCKER_KEYDIR", "~/.config/sbox/docker"))
COMPOSE_NAMES = re.compile(r"^(docker-)?compose([.-][\w.-]+)?\.ya?ml$|^Dockerfile(\.[\w.-]+)?$")
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "target", "dist", "build", ".venv", "venv"}


def fail(msg):
    print(f"sbox-docker: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------- 키 ----------
def key_check(data, workdir):
    """(통과 여부, 사유). `pub` 레코드가 정확히 하나이고 그 주 키 지문이 공식 값, 비밀 키(sec) 없음."""
    p = os.path.join(workdir, "k.asc")
    with open(p, "wb") as f:
        f.write(data)
    r = subprocess.run(tools.gpg_cmd() + ["--show-keys", "--with-colons", p], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "gpg 가 키 파일을 읽지 못했습니다"
    pubs, cur = [], None
    for ln in r.stdout.splitlines():
        f = ln.split(":")
        if f[0] in ("pub", "sec"):
            if f[0] == "sec":
                return False, "비밀 키 레코드(sec)가 들어 있습니다"
            cur = len(pubs); pubs.append(None)
        elif f[0] == "fpr" and cur is not None and pubs[cur] is None:
            pubs[cur] = f[9].upper()   # pub 바로 뒤 첫 fpr = 주 키(하위 키 fpr 은 sub 뒤라 여기서 안 잡힘)
    if len(pubs) != 1:
        return False, f"주 키(pub)가 {len(pubs)}개입니다(정확히 1개여야 함)"
    if pubs[0] != KEY_FPR:
        return False, f"주 키 지문 {pubs[0]} 가 공식 값이 아닙니다"
    return True, "ok"


def pinned_key_path():
    return os.path.join(KEYDIR, "docker.asc")


def ensure_key(log=print):
    """고정 키 파일 경로. 없으면 받아서 검사 + 독립 출처 교차 확인 후 고정, 있으면 재검증만."""
    path = pinned_key_path()
    work = tempfile.mkdtemp(prefix="dockerkey-")
    try:
        if os.path.isfile(path):
            ok, why = key_check(open(path, "rb").read(), work)
            if not ok:
                fail(f"고정해 둔 키({path})가 규칙에 맞지 않습니다: {why} — 조사 후 사람이 파일을 지워 다시 고정하세요")
            return path
        log("Docker 서명 키를 처음 고정합니다 — 독립 출처로 교차 확인합니다(pincheck apt-key:docker)")
        data = tools.http(KEY_URL)
        ok, why = key_check(data, work)
        if not ok:
            fail(f"받은 키가 규칙에 맞지 않습니다: {why}")
        res, allok = tools.pincheck("apt-key:docker")
        if not allok:
            row = res.get("apt-key:docker", {})
            fail("키 지문이 독립 출처에서 충분히 확인되지 않아 고정하지 않습니다: "
                 + ", ".join(f"{r['source']}={'일치' if r['matched'] else (r['note'] or '불일치')}" for r in row.get("sources", [])))
        os.makedirs(KEYDIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o444)
        os.replace(tmp, path)
        log(f"키를 고정했습니다: {path}")
        return path
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- 버전 선택 ----------
def parse_packages(text):
    """Packages 본문 → [{Package, Version, Filename}]"""
    out = []
    for block in text.split("\n\n"):
        d = {}
        for ln in block.splitlines():
            if ":" in ln and not ln.startswith(" "):
                k, _, v = ln.partition(":")
                d[k] = v.strip()
        if d.get("Package") and d.get("Version") and d.get("Filename"):
            out.append(d)
    return out


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def candidates(entries, pkg, base):
    """pkg 의 후보를 새것부터 (apt 버전 문자열, 파일 공개 에포크) 로 — 날짜는 .deb 의 Last-Modified(게으르게 조회)."""
    rows = sorted((e for e in entries if e["Package"] == pkg and re.search(r"~(debian|ubuntu)\.", e["Version"])), key=lambda e: _vkey(e["Version"]), reverse=True)
    for e in rows:
        yield e["Version"], tools._head_date(f"{base}/{e['Filename']}")


def choose(entries, base, now=None):
    """쿨다운을 적용해 (docker-ce 계열 버전, containerd 버전, 알림들) 을 고른다. docker-ce 와 같은 문자열이 cli·rootless-extras 에도 있어야 한다."""
    days = tools._min_age_days()
    notes = []
    have = {p: {e["Version"] for e in entries if e["Package"] == p} for p in PKGS + (CONTAINERD,)}
    both = lambda: ((v, ts) for v, ts in candidates(entries, "docker-ce", base) if all(v in have[p] for p in PKGS))  # noqa: E731
    dv, n, _ = tools.pick_aged(both(), days, now)
    notes += n
    cv, n, _ = tools.pick_aged(candidates(entries, CONTAINERD, base), days, now)
    notes += n
    if not dv:
        fail("설치할 docker-ce 버전을 고르지 못했습니다: " + "; ".join(notes))
    if not cv:
        fail("설치할 containerd.io 버전을 고르지 못했습니다: " + "; ".join(notes))
    return dv, cv, notes


# ---------- 매니페스트([resolved.docker]) ----------
def read_resolved(path):
    if not (path and os.path.isfile(path)):
        return {}
    with open(path, "rb") as f:
        return (tomllib.load(f).get("resolved") or {}).get("docker") or {}


def write_resolved(path, dv, cv):
    """매니페스트의 [resolved.docker] 구역만 바꾼다(다른 내용은 건드리지 않음 — 사람이 쓴 [override]·tier·주석 보존)."""
    txt = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    txt = re.sub(r"\n?\[resolved\.docker\]\n(?:(?!\[)[^\n]*\n?)*", "\n", txt).rstrip("\n") + "\n"
    q = tools.q
    txt += f"\n[resolved.docker]\nspec = {q('engine')}\nversion = {q(dv)}\ncontainerd = {q(cv)}\n"
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, path)


def sources_text(distro, codename, arch):
    return (f"Types: deb\nURIs: {BASE}/{distro}\nSuites: {codename}\nComponents: stable\nArchitectures: {arch}\n"
            "Signed-By: /etc/apt/keyrings/docker.asc\n")


def plan(distro, codename, arch, manifest=None, update=False):
    if distro not in ("debian", "ubuntu"):
        fail(f"지원하지 않는 배포판: {distro} (debian·ubuntu)")
    if arch != "amd64":
        fail(f"지원하지 않는 아키텍처: {arch} (amd64 만 시험했습니다)")
    if not re.fullmatch(r"[a-z]+", codename):
        fail(f"이상한 코드네임: {codename!r}")
    key = ensure_key(lambda m: print(m, file=sys.stderr))
    base = f"{BASE}/{distro}"
    entries = parse_packages(gzip.decompress(tools.http(f"{base}/dists/{codename}/stable/binary-{arch}/Packages.gz")).decode("utf-8", "replace"))
    prev = read_resolved(manifest)
    notes = []
    if prev.get("version") and prev.get("containerd") and not update:
        dv, cv = prev["version"], prev["containerd"]
        have = {(e["Package"], e["Version"]) for e in entries}
        if not all((p, dv) in have for p in PKGS) or (CONTAINERD, cv) not in have:
            fail(f"매니페스트에 고정된 버전({dv}, containerd {cv})이 이 저장소({distro} {codename})에 없습니다 — 다른 배포판이거나 내려졌습니다. --update 로 다시 고르세요")
        notes.append("매니페스트에 고정된 버전을 재사용합니다(--update 로만 다시 고름)")
    else:
        dv, cv, notes = choose(entries, base)
        if manifest:
            write_resolved(manifest, dv, cv)
    return {"key_file": key, "sources": sources_text(distro, codename, arch),
            "versions": {p: dv for p in PKGS} | {CONTAINERD: cv}, "notes": notes, "manifest": manifest}


# ---------- 필요 여부 ----------
def detect_repo(repo):
    """저장소 루트와 아래 두 단계까지에서 compose·Dockerfile 을 찾는다(vendor·의존성 폴더 제외). 첫 근거 경로를 돌려준다."""
    root = os.path.abspath(repo)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if dirpath[len(root):].count(os.sep) >= 2:
            dirs[:] = []
        for f in sorted(files):
            if COMPOSE_NAMES.match(f):
                return os.path.relpath(os.path.join(dirpath, f), root)
    return None


def read_override(path):
    """사람이 매니페스트 [override] 에 적은 docker = "yes"|"no" (없으면 None)."""
    if not (path and os.path.isfile(path)):
        return None
    with open(path, "rb") as f:
        v = (tomllib.load(f).get("override") or {}).get("docker")
    if v is None:
        return None
    if str(v).lower() not in ("yes", "no"):
        fail(f"매니페스트 [override] docker 는 \"yes\" 또는 \"no\" 여야 합니다(받은 값: {v!r})")
    return str(v).lower()


def wanted(repo=None, manifest=None):
    """우선순위: 매니페스트 [override] docker(사람이 정함) > [resolved.docker](이미 설치한 기록) > 저장소 감지. 명령 인자(--docker·--no-docker)는 sboxctl 이 이보다 먼저 적용한다."""
    ov = read_override(manifest)
    if ov == "no":
        return None
    if ov == "yes":
        return "yes 매니페스트 [override] docker = \"yes\""
    if manifest and read_resolved(manifest).get("version"):
        return "yes 매니페스트에 [resolved.docker] 가 있음"
    if repo and os.path.isdir(repo):
        hit = detect_repo(repo)
        if hit:
            return f"yes 저장소에 {hit}"
    return None


def main(a):
    def opt(n):
        return a[a.index(n) + 1] if n in a else None
    if a and a[0] == "wanted":
        w = wanted(opt("--repo"), opt("--manifest"))
        print(w or "no")
        sys.exit(0 if w else 1)
    elif a and a[0] == "plan":
        import json
        print(json.dumps(plan(opt("--distro"), opt("--codename"), opt("--arch"), opt("--manifest"), "--update" in a), ensure_ascii=False))
    elif a and a[0] == "key":
        print(ensure_key(lambda m: print(m, file=sys.stderr)))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
