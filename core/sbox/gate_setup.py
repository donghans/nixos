#!/usr/bin/env python3
"""sbox 관문 설치 보조(호스트, 표준 라이브러리만) — ct 의 관리 설정(/etc/claude-code/managed-settings.json)에 `env.CLAUDE_CODE_SHELL` 을 병합·제거한다.
관리 설정은 저장소의 claude-managed-settings.json(⑱ 업데이트 제동 등)이 기본이고, 관문이 설치된 ct 는 거기에 `env.CLAUDE_CODE_SHELL` 만 더한다(다른 키·다른 env 키는 그대로).
  merge   [--shell PATH]   표준 입력의 JSON 에 env.CLAUDE_CODE_SHELL 을 더해 표준 출력으로
  unmerge                  표준 입력의 JSON 에서 env.CLAUDE_CODE_SHELL 만 지운다(env 가 비면 env 키도 지운다)"""
import json, sys

GATE_PATH = "/usr/local/bin/sbox-gate-bash"      # 이름에 bash 가 들어가야 Claude Code 가 쓴다(U6)
KEY = "CLAUDE_CODE_SHELL"


def merge(text, shell=GATE_PATH):
    j = json.loads(text) if text.strip() else {}
    env = j.get("env")
    if not isinstance(env, dict):
        env = {}
    env[KEY] = shell
    j["env"] = env
    return json.dumps(j, ensure_ascii=False, indent=2) + "\n"


def unmerge(text):
    j = json.loads(text) if text.strip() else {}
    env = j.get("env")
    if isinstance(env, dict):
        env.pop(KEY, None)
        if not env:
            j.pop("env", None)
    return json.dumps(j, ensure_ascii=False, indent=2) + "\n"


def main(argv):
    if not argv or argv[0] not in ("merge", "unmerge"):
        print("usage: gate_setup.py merge [--shell PATH] | unmerge   (stdin → stdout)", file=sys.stderr); return 2
    data = sys.stdin.read()
    if argv[0] == "merge":
        shell = argv[argv.index("--shell") + 1] if "--shell" in argv else GATE_PATH
        sys.stdout.write(merge(data, shell))
    else:
        sys.stdout.write(unmerge(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
