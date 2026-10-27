# llm-cli 데이터 파일

`../llm-cli.nix` 가 `builtins.readFile` 로 읽는 순수 데이터다. 모듈 로직은 `../llm-cli.nix` 에 있다.
파일 내용이 그대로 산출물이 되므로(Nix 보간 없음) 끝 개행·들여쓰기까지 의미가 있다.

| 파일 | 쓰임 |
|---|---|
| `claude-md.md` | `~/.claude/CLAUDE.md` 의 공통 본문(모든 호스트) |
| `observe.md` | 위 뒤에 붙는 「관측(observectl)」 절 — `mods.sys.services.observe` 가 켜진 호스트만 |
| `procctl.md` | 「프로세스 종료(procctl)」 절 — 같은 조건 |
| `qa-desktop.md` | 「화면 확인용 QA 데스크톱」 절 — `mods.sys.services.qa-desktop` 이 켜진 호스트만 |
| `otel-collector.yaml` | Claude Code 사용량 OTLP 로컬 수집기 설정(`${env:HOME}` 는 수집기가 푸는 값) |

절 파일(`observe.md` 등)은 첫 줄이 빈 줄이다 — 앞 절과 한 줄 띄우기 위한 것이므로 지우지 않는다.
