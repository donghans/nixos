# llm-sessions — ssh 와 kitty 에서 같은 claude 세션 이어 쓰기

작성 2026-10-23. 구현: `mods/_tools/llm/llm-sessions/`, 배선: `mods/devel/apps/llm-cli.nix`. 시험: `mods/_tools/llm/llm-sessions/tests/test_llm_sessions.py`.

## 사용자가 원한 것(2026-10-22~23 확인)
- kitty 의 다른 창·VT 는 그대로, **LLM 도구(claude)에만** tmux 를 붙인다. 세션은 사용자가 끝낼 때 끝낸다.
- ssh 에서 시작한 세션을 kitty 로 옮겨 이어 쓰기, 반대로 kitty 에서 시작한 세션을 ssh 에서 붙기.
- 한 세션에 여러 곳이 동시에 붙어도 된다(tmux 는 기본으로 화면을 서로 비춘다) — 그래서 「한 곳에서만 attach」·「원격 접속 중 알림」은 만들지 않았다.
- kitty 창을 닫으면 그 tmux 도 같이 끝나게 하되, 다른 곳이 붙어 있으면 유지한다(아래 「kitty 닫힘」).
- ssh 에서는 claude 세션 목록을 보여 주고 접속·새 세션 생성을 고르는 UI(`llm-sessions`). 디자인은 usageui·ctxui 와 같은 `uikit` 틀.

## 구성
| 부분 | 파일 | 역할 |
|---|---|---|
| 래퍼 | `claude-tmux` (bash) | `claude` 셸 함수가 대화형 호출일 때 부른다. 새 세션 `claude-<디렉터리>-<시각>` 을 만들고 붙는다. `--wants` 는 감쌀지 판단(종료 코드) |
| 목록 UI·CLI | `llm_sessions.py` | `llm-sessions`(Textual) · `ls` · `attach <이름\|접두\|번호>` · `new [디렉터리] [-- claude 인자]` |
| tmux 조작 | `tmuxsess.py` | 목록(붙은 곳 출처 ssh/kitty/tty)·미리보기·생성·정리·떼기 |
| 설정 | `claude-tmux.conf` | 전용 소켓 `tmux -L claude` 에서만 읽힌다 — 일반 tmux 에 영향 없음 |
| 실행기 | nix 의 `claude-run` | tmux 안에서 `--settings`(훅·모션) 주입 후 claude 실행. **sudo 인증도 여기서 받는다** |

## 결정과 근거
- **전용 소켓·전용 설정**: 사용자의 일반 tmux 와 섞이지 않고, 목록은 `claude-` 접두 세션만 보인다.
- **접두 키는 Ctrl+]**: tmux 기본 Ctrl+B 는 Claude Code 의 백그라운드 키, Ctrl+A 는 줄 처음 이동과 겹친다. 분리는 **F12** 한 번 또는 Ctrl+] d. 붙을 때 3초 안내가 뜬다.
- **상태 줄 끔**(`status off`): 시계 같은 주기 갱신이 화면 절전(PSR)을 방해할 수 있다(ctx 장부 #57 과 같은 문제). 노트북 전력 영향은 측정하지 않았다.
- **sudo 는 `claude-run` 에서**: sudo 인증 캐시는 tty 별이라 셸 함수의 `sudo -v`·60초 갱신 루프는 tmux pane 의 tty 에 효과가 없다. 그래서 tmux 경로에서는 pane 안(`claude-run`)에서 인증하고, claude 가 끝나면 갱신 루프도 끝난다. 처음 붙으면 sudo 인증 프롬프트가 pane 에 보일 수 있다.
- **감싸지 않는 호출**: `CLAUDE_TMUX=0` · 이미 tmux 안 · 터미널이 아님 · `-p/--print/--help/--version/--output-format` · 서브커맨드(한 단어: mcp, config, update …). 따라서 스크립트·`claude -p` 는 그대로다. 한 단어짜리 프롬프트(`claude hello`)는 서브커맨드로 보여 감싸지지 않는다.
- **kitty 닫힘**: 래퍼가 SIGHUP/터미널 소실을 감지하면, 그 세션에 다른 접속이 **없을 때만** 세션을 끝낸다. 다른 곳(ssh 등)이 붙어 있으면 그쪽이 이어 쓰게 두고, 이후 고아가 되면 `llm-sessions` 에서 `x` 로 정리한다. 분리(F12)는 터미널이 살아 있으므로 정리하지 않는다. kitty 가 강제 종료(SIGKILL)되면 세션이 남을 수 있다.
- **ssh 에서 만든 세션은 끊겨도 산다**: `llm-sessions` 의 `n` 은 분리된 세션을 만들고 붙는다. 분리하면 목록으로 돌아온다.
- **이미 떠 있는 Claude 세션은 tmux 안으로 옮길 수 없다** — 새로 시작하는 세션부터 적용.

## 시험(실제 tmux 3.6a · pty · Textual Pilot, 51건)
생성·목록·미리보기·정리, `--wants` 판단, 붙기·F12 분리·세션 유지, 동시 접속 2곳과 출처 조회, `d`(붙은 곳 떼기), **kitty 닫힘 시 정리 / 다른 접속이 있으면 유지**, claude 종료 시 세션 종료, UI(목록·미리보기·붙기·새 세션·정리·도움말)와 CLI. 변이 검사: 접속자 수 확인을 없애 항상 죽이게 하면 「다른 접속 있음 → 유지」 시험이 실패함을 확인했다.
실제 Claude Code 를 이 설정의 tmux 안에서 헤드리스 kitty 로 띄워 화면(신뢰 확인 대화상자)이 정상 표시되고 `llm-sessions ls` 가 세션·접속 출처를 보이는 것까지 확인했다. **키 입력(Shift+Enter 등)·알림·이미지 붙여넣기는 아직 실사용으로 확인하지 못했다** — 새 셸에서 써 보며 이상하면 `CLAUDE_TMUX=0 claude` 로 우회하고 `claude-tmux.conf` 의 `extended-keys`·`allow-passthrough` 를 조정한다.

## 아직 안 한 것
- 노트북 전력(상태 줄 끔 이후 화면 갱신) ABAB 측정.
- observectl 앱 귀속(tmux 서버의 자식이 된 claude 도 `.claude-wrapped` 로 집계되는지) 확인.
- ctxui 에 「세션」 탭으로 붙이기(독립 도구로 먼저 만들었다 — DB 없이도 서버에서 동작).
