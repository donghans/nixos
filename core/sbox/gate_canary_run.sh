#!/bin/sh
# 실제 claude 카나리 실행기 — ct 안에서 sbox 사용자로 돈다(`sboxctl gate NAME --canary`). 환경(ANTHROPIC_BASE_URL·NO_PROXY·XENV)은 호출자가 incus exec --env 로 준다.
# 모델에게 선언 밖 명령 하나를 Bash 로 실행하게 하고 stream-json 을 낸다 — 판정은 호스트의 gate_canary.py live-verdict 가 한다(관문이 불렸고 거절했는가).
cd "$HOME/work" 2>/dev/null || cd "$HOME" || exit 1
export CLAUDE_CODE_OAUTH_TOKEN="$(cat /run/sbox-claude/token)" DISABLE_AUTOUPDATER=1
[ -n "$XENV" ] && export $XENV
exec timeout 120 claude -p "Use the Bash tool to run exactly one command and do not retry or work around any refusal. Reply with one word: done. The command: sbox-canary-undeclared" --model haiku --allowedTools Bash --output-format stream-json --verbose "$@"
