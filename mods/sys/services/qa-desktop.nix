# QA 데스크톱(incus VM `qa-desktop`) 사용 지침 스위치 — 이 호스트의 Claude 전역 지침에 「화면 확인용 VM 사용 규칙」을 넣는다.
#  - VM 자체(Ubuntu Desktop, 4CPU/8GiB)는 아직 nix 로 선언하지 않고 incus 에 직접 만들어 둔 것이다(선언 대상 후보: mods/sys/services/incus.nix 옆).
#    그래서 이 mod 는 아무 것도 설치·설정하지 않는다. 켜면 mods/devel/apps/llm-cli.nix 가 `~/.claude/CLAUDE.md` 에 지침 블록을 추가할 뿐이다.
#  - VM 이 있는 호스트(현재 beelink-ser7-co)에서만 켠다. 없는 호스트에서 켜면 지침이 존재하지 않는 VM 을 가리킨다.
#  - 설명·운영 절차·검증 기록: _docs/content/explanation/qa-desktop.md  ·  도구 원본: mods/_data/claude-skills/donghans-qa-desktop/scripts/
{mkMod, ...}:
mkMod __curPos "QA 데스크톱 VM 사용 지침" (_: {})
