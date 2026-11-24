#!/usr/bin/env python3
"""프로젝트 저장소를 **읽기만 해서** 필요한 송신 프리셋·추가 도메인을 제안한다(plan dev-sandbox-pilot §29-44, S71 후속). 아무것도 허용하지 않는다 —
허용은 사람이 매니페스트 [network] 에 옮겨 적는다(허용 확대는 보안 결정이라 자동 적용하지 않음). 저장소 파일은 데이터로만 읽고 실행하지 않는다.
  scan.py REPO [--manifest M] [--json]
읽는 것: Dockerfile*·*.dockerfile·docker-compose*.yml·compose*.y?ml 의 FROM/image(레지스트리·기반 배포판)와 RUN 줄(apk·apt·pip·npm·cargo·go·curl/wget URL).
한계: 휴리스틱이다 — 변수(${REGISTRY})로 만든 주소, 스크립트 안에서 받는 주소, 빌드 인자로 바뀌는 기반 이미지는 못 본다. 「제안 없음」은 「필요 없음」이 아니다.
"""
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import egress  # noqa: E402

DOCKERFILE_GLOBS = ["Dockerfile*", "**/Dockerfile*", "*.dockerfile", "**/*.dockerfile"]
COMPOSE_GLOBS = ["docker-compose*.y*ml", "compose*.y*ml", "**/docker-compose*.y*ml", "**/compose*.y*ml"]
SKIP_DIRS = ("node_modules", ".git", "vendor", "target", ".venv", "dist", "build")
REGISTRY_PRESET = {"ghcr.io": "ghcr"}                      # 프리셋이 있는 레지스트리
DOCKER_HUB_HOSTS = {"docker.io", "registry-1.docker.io", "index.docker.io"}


def files(repo, globs):
    out = set()
    for g in globs:
        for f in glob.glob(os.path.join(repo, g), recursive=True):
            rel = os.path.relpath(f, repo)
            if os.path.isfile(f) and not any(part in SKIP_DIRS for part in rel.split(os.sep)):
                out.add(f)
    return sorted(out)


def read(f):
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            return fh.read(512 * 1024)
    except OSError:
        return ""


def image_registry(ref):
    """이미지 참조 → (레지스트리, 이름). 첫 구성요소에 `.`·`:` 가 있거나 localhost 면 레지스트리, 아니면 Docker Hub."""
    first, _, rest = ref.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        return first, rest
    return "docker.io", ref


def base_family(name):
    n = name.lower()
    if "alpine" in n:
        return "alpine"
    if n.startswith(("ubuntu", "mongo")) or "ubuntu" in n:
        return "ubuntu"
    return "debian"       # node·python·debian·그 밖의 기본 이미지는 대개 Debian 계열 — 틀릴 수 있어 이유에 「추정」을 적는다


def scan(repo):
    """→ {"presets": {이름: [이유…]}, "egress": {호스트: [이유…]}, "unknown_registries": {호스트: [이유…]}}"""
    pre, eg, unk = {}, {}, {}
    def add(d, k, why):
        d.setdefault(k, [])
        if why not in d[k]:
            d[k].append(why)
    for f in files(repo, DOCKERFILE_GLOBS):
        rel = os.path.relpath(f, repo)
        text = read(f)
        stages = set()
        for m in re.finditer(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", text, re.I | re.M):
            ref, alias = m.group(1), m.group(2)
            if alias:
                stages.add(alias.lower())
            if ref.lower() in stages or ref.lower() == "scratch" or "$" in ref:
                if "$" in ref:
                    add(unk, "(변수로 정한 기반 이미지)", f"{rel}: FROM {ref} — 값을 알 수 없음")
                continue
            reg, name = image_registry(ref)
            add(pre, "docker", f"{rel}: FROM {ref} (Docker 이미지 pull)") if reg == "docker.io" else None
            if reg in REGISTRY_PRESET:
                add(pre, REGISTRY_PRESET[reg], f"{rel}: FROM {ref}")
            elif reg not in DOCKER_HUB_HOSTS and reg != "docker.io":
                add(unk, reg, f"{rel}: FROM {ref}")
            fam = base_family(name)
            if fam == "alpine":
                add(pre, "alpine", f"{rel}: 기반 이미지 {ref} (Alpine)")
            elif fam == "ubuntu":
                add(pre, "os-ubuntu", f"{rel}: 기반 이미지 {ref} (Ubuntu 계열 추정)")
            elif re.search(r"\bapt(-get)?\s+(install|update)", text):
                add(pre, "os-debian", f"{rel}: 기반 {ref} (Debian 계열 추정) + apt 사용")
        run_text = "\n".join(re.findall(r"^\s*RUN\s+(.*(?:\\\n.*)*)", text, re.M))
        if re.search(r"\bapk\s+(add|update)", run_text):
            add(pre, "alpine", f"{rel}: RUN apk")
        if re.search(r"\bpip3?\s+install|\buv\s+(pip|sync)", run_text):
            add(pre, "python", f"{rel}: RUN pip/uv")
        if re.search(r"\b(npm|yarn|pnpm)\s+(i|install|ci|add)\b", run_text):
            add(pre, "node", f"{rel}: RUN npm/yarn/pnpm")
        if re.search(r"\bcargo\s+(build|install|fetch)", run_text):
            add(pre, "rust", f"{rel}: RUN cargo")
        if re.search(r"\bgo\s+(build|mod|get|install)\b", run_text):
            add(pre, "go", f"{rel}: RUN go")
        if re.search(r"nodesource", run_text, re.I):
            add(pre, "nodesource", f"{rel}: nodesource 저장소")
        if re.search(r"repo\.mongodb\.org|mongodb-org", run_text):
            add(pre, "mongodb-apt", f"{rel}: MongoDB apt 저장소")
        for m in re.finditer(r"https?://([A-Za-z0-9.-]+)(?::(\d+))?", run_text):
            host = m.group(1).lower()
            if "$" in host or "." not in host:
                continue
            add(eg, host + (":" + m.group(2) if m.group(2) else ""), f"{rel}: RUN 에서 URL 사용")
    for f in files(repo, COMPOSE_GLOBS):
        rel = os.path.relpath(f, repo)
        for m in re.finditer(r"^\s*image:\s*[\"']?([^\s\"'#]+)", read(f), re.M):
            ref = m.group(1)
            if "$" in ref:
                add(unk, "(변수로 정한 이미지)", f"{rel}: image: {ref}")
                continue
            reg, name = image_registry(ref)
            if reg in REGISTRY_PRESET:
                add(pre, REGISTRY_PRESET[reg], f"{rel}: image: {ref}")
            elif reg != "docker.io":
                add(unk, reg, f"{rel}: image: {ref}")
            else:
                add(pre, "docker", f"{rel}: image: {ref}")
    return {"presets": pre, "egress": eg, "unknown_registries": unk}


def filter_known(res, manifest, flavor=None):
    """이미 허용되는 것(always·자동·매니페스트)은 제안에서 뺀다. 프리셋 표에 없는 이름은 제안하지 않는다."""
    t = egress.presets_table()
    covered = set(t.get("always", []))
    md = egress.manifest_data(manifest) or {}
    covered |= set(md.get("network", {}).get("presets", []))
    for k in list((md.get("inferred") or {})) + list((md.get("override") or {})) + list((md.get("resolved") or {})):
        covered |= set(t.get("auto", {}).get("tool", {}).get(k, []))
    if flavor:
        covered |= set(t.get("auto", {}).get("flavor", {}).get(flavor, []))
    have_hosts = set()
    for name in covered:
        have_hosts |= {egress.norm(r) for r in t.get("preset", {}).get(name, {}).get("allow", [])}
    have_hosts |= set(egress.manifest_egress(manifest)) if manifest else set()
    out = {"presets": {k: v for k, v in res["presets"].items() if k in t.get("preset", {}) and k not in covered},
           "egress": {}, "unknown_registries": res["unknown_registries"]}
    all_preset_hosts = set()
    for p in t.get("preset", {}).values():
        all_preset_hosts |= {egress.norm(r) for r in p.get("allow", [])}
    for h, why in res["egress"].items():
        try:
            n = egress.norm(h)
        except SystemExit:
            continue
        if n not in have_hosts and n not in all_preset_hosts:
            out["egress"][h] = why
    return out


def render(res):
    lines = []
    if res["presets"]:
        lines.append("제안 프리셋(매니페스트 [network] presets 에 추가):")
        for k, why in sorted(res["presets"].items()):
            lines.append(f"  - {k}   ← {why[0]}" + (f" 외 {len(why) - 1}곳" if len(why) > 1 else ""))
    if res["egress"]:
        lines.append("프리셋에 없는 주소(필요하면 [network] egress 에 — 정말 필요한지 확인 후):")
        for k, why in sorted(res["egress"].items()):
            lines.append(f"  - {k}   ← {why[0]}")
    if res["unknown_registries"]:
        lines.append("프리셋이 없는 레지스트리·값을 알 수 없는 이미지(자동 판단 불가 — 사람이 확인):")
        for k, why in sorted(res["unknown_registries"].items()):
            lines.append(f"  - {k}   ← {why[0]}")
    if not lines:
        lines.append("제안 없음(이미 허용되거나 휴리스틱이 보지 못함 — 「필요 없음」이 아닐 수 있음)")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("repo"); ap.add_argument("--manifest"); ap.add_argument("--flavor"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.repo):
        raise SystemExit(f"저장소 디렉터리가 없습니다: {a.repo}")
    res = filter_known(scan(a.repo), a.manifest, a.flavor)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
