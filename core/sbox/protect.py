#!/usr/bin/env python3
"""R7(가) 보호 경로 — plan sbox-project-policy R7·§3 ⑧, pilot §29-94. 표준 라이브러리만(호스트의 tasks.py 와 ct 의 taskd.py 가 같이 쓴다).
작업 사본의 「제어 파일」(CLAUDE.md·.claude·package.json·락 파일·Dockerfile·compose·.githooks·.github …)을 taskd 의 시스템 유닛에서 읽기 전용 바인드 마운트로 고정한다.
패턴: `X/**` = 폴더 X 통째 / 슬래시 없는 이름(`Dockerfile*`)은 작업 사본 어디서든(.git·node_modules 안은 제외) / 슬래시 있는 것은 작업 사본 루트 기준 글롭.
심볼릭 링크가 걸리면 거부한다(링크 대상이 바뀌면 보호가 무의미해지므로). 공백·따옴표·% 가 든 경로도 유닛 파일에 안전하게 못 쓰므로 거부한다."""
import fnmatch, glob, json, os, sys

DEFAULT_PROTECT = [
    "CLAUDE.md", ".claude/**", ".mcp.json", "package.json",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "go.sum", "uv.lock", "poetry.lock",
    "pubspec.yaml", "pubspec.lock", "Podfile", "Podfile.lock",        # Flutter(사용자 결정 2026-11-26 ⑩ — 이력 측정에서 pororing 계열이 보호 밖이었음)
    "Dockerfile*", "docker-compose*.yml", ".githooks/**", ".github/**",
]
PRUNE = (".git", "node_modules")
BAD_CHARS = set(" \t\n\"'\\%$;")


def _check(rel, full):
    if os.path.islink(full):
        raise ValueError(f"보호 대상 {rel} 이(가) 심볼릭 링크입니다 — 링크 대상이 바뀌면 보호가 무의미합니다. 실제 파일로 바꾸거나 [protect] remove 로 뺀 뒤 사람이 판단하세요")
    if any(c in BAD_CHARS for c in rel):
        raise ValueError(f"보호 대상 경로 {rel!r} 에 공백·따옴표·% 등이 있어 유닛 파일에 안전하게 쓸 수 없습니다")


def expand(root, patterns):
    """root(작업 사본) 안에서 패턴에 맞고 **지금 존재하는** 경로의 정렬된 상대 경로 목록. 위반이면 ValueError."""
    found = set()
    for pat in patterns:
        if os.path.isabs(pat) or ".." in pat.split("/"):
            raise ValueError(f"패턴 {pat!r} 는 작업 사본 안의 상대 경로여야 합니다")
        if pat.endswith("/**"):
            rel = pat[:-3]
            if rel and os.path.lexists(os.path.join(root, rel)):
                found.add(rel)
        elif "/" in pat:
            for m in glob.glob(os.path.join(root, pat)):
                found.add(os.path.relpath(m, root))
        else:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [x for x in dirnames if x not in PRUNE]
                hit = [x for x in dirnames + filenames if fnmatch.fnmatchcase(x, pat)]
                for x in hit:
                    found.add(os.path.relpath(os.path.join(dirpath, x), root))
                dirnames[:] = [x for x in dirnames if x not in hit]      # 맞은 폴더 안은 더 안 들어간다(폴더째 보호)
    out = sorted(found)
    for rel in out:
        _check(rel, os.path.join(root, rel))
    # 이미 보호된 폴더 안의 항목은 중복이다(상위 폴더가 ro 이면 하위도 ro)
    return [r for r in out if not any(r.startswith(o + "/") for o in out if o != r)]


def mounted_ro(mountinfo_text, path):
    """/proc/self/mountinfo 텍스트에서 path 가 **읽기 전용 마운트 지점**인지(path 가 보호 폴더 안쪽이면 그 폴더의 마운트도 인정)."""
    best = None
    for line in mountinfo_text.splitlines():
        f = line.split()
        if len(f) < 6:
            continue
        mp = f[4].replace("\\040", " ")
        if path == mp or path.startswith(mp.rstrip("/") + "/"):
            if best is None or len(mp) >= len(best[0]):
                best = (mp, "ro" in f[5].split(","))
    return bool(best and best[1] and best[0] != "/")


SCRIPT_EXT = (".sh", ".bash", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".bat", ".cmd")


def dirinfo(root, rels, cap=20000):
    """보호 경로 중 폴더의 안쪽 요약 {상대경로: {files, scripts, top}} — 승인 화면이 「.claude/ 130개」처럼 접어 보이는 데 쓴다. 심볼릭 링크는 따라가지 않고, cap 개를 넘으면 센 만큼만(truncated)."""
    out = {}
    for rel in rels:
        base = os.path.join(root, rel)
        if not os.path.isdir(base) or os.path.islink(base):
            continue
        n = scripts = 0
        top = {}
        truncated = False
        for dp, dn, fn in os.walk(base, followlinks=False):
            for f in fn:
                n += 1
                scripts += f.endswith(SCRIPT_EXT)
                sub = os.path.relpath(dp, base).split(os.sep)[0]
                key = f if sub == "." else sub
                top[key] = top.get(key, 0) + 1
                if n >= cap:
                    truncated = True
                    break
            if truncated:
                break
        out[rel] = {"files": n, "scripts": scripts, "top": dict(sorted(top.items(), key=lambda kv: -kv[1])[:6]), "truncated": truncated}
    return out


def main(argv):
    if len(argv) >= 3 and argv[0] == "dirinfo":
        try:
            print(json.dumps(dirinfo(argv[1], json.loads(argv[2])), ensure_ascii=False))
        except ValueError as e:
            print(str(e), file=sys.stderr); return 2
        return 0
    if len(argv) >= 3 and argv[0] == "expand":
        try:
            print(json.dumps(expand(argv[1], json.loads(argv[2]))))
        except ValueError as e:
            print(str(e), file=sys.stderr); return 2
        return 0
    print("usage: protect.py expand ROOT '[patterns json]' | dirinfo ROOT '[relative paths json]'", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
