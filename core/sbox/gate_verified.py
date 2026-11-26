#!/usr/bin/env python3
"""sbox 검증된 claude 버전 목록(호스트 상태 파일, 표준 라이브러리만) — 관문이 설치된 ct 에서 **카나리(실제 claude)를 통과한 버전만** 세션을 시작할 수 있다(미확인 U20·U22).
관문은 Claude Code 의 호출 형식과 설정 우선순위에 의존하므로 버전이 바뀌면(기본이 최신 채널이라 사람이 모르게 바뀔 수 있다) 다시 확인해야 한다.
  check VERSION   목록에 있으면 0, 없으면 1        add VERSION   카나리 통과 뒤 기록        list   목록 출력
상태 파일: ~/.local/state/sbox/claude-verified.json (SBOX_VERIFIED_STATE 로 바꿀 수 있다 — 시험용)."""
import json, os, re, sys, time

VER_RE = re.compile(r"\d+\.\d+\.\d+")


def state_path():
    return os.environ.get("SBOX_VERIFIED_STATE") or os.path.expanduser("~/.local/state/sbox/claude-verified.json")


def load():
    try:
        d = json.load(open(state_path()))
        return d if isinstance(d, dict) and isinstance(d.get("versions"), dict) else {"versions": {}}
    except (OSError, ValueError):
        return {"versions": {}}


def is_verified(version):
    return bool(VER_RE.fullmatch(version or "")) and version in load()["versions"]


def add(version, how="live-canary"):
    if not VER_RE.fullmatch(version or ""):
        raise ValueError(f"버전 형식이 아니다: {version!r}")
    d = load()
    d["versions"][version] = {"verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "how": how}
    p = state_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def main(argv):
    if len(argv) == 2 and argv[0] == "check":
        return 0 if is_verified(argv[1]) else 1
    if len(argv) == 2 and argv[0] == "add":
        add(argv[1]); return 0
    if argv == ["list"]:
        for v, m in sorted(load()["versions"].items()):
            print(f"{v}  {m.get('verified_at', '')}  {m.get('how', '')}")
        return 0
    print(__doc__, file=sys.stderr); return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
