# llm-sessions — ssh 와 kitty 에서 같은 claude 세션 이어 쓰기

작성 2026-10-23. 구현: `mods/_tools/llm/llm-sessions/`, 배선: `mods/devel/apps/llm-cli.nix`. 시험: `mods/_tools/llm/llm-sessions/tests/test_llm_sessions.py`.

## 사용자가 원한 것(2026-10-22~23 확인)
- kitty 의 다른 창·VT 는 그대로, **LLM 도구(claude)에만** tmux 를 붙인다. 세션은 사용자가 끝낼 때 끝낸다.
- ssh 에서 시작한 세션을 kitty 로 옮겨 이어 쓰기, 반대로 kitty 에서 시작한 세션을 ssh 에서 붙기.
- 한 세션에 여러 곳이 동시에 붙어도 된다(tmux 는 기본으로 화면을 서로 비춘다) — 그래서 「한 곳에서만 attach」·「원격 접속 중 알림」은 만들지 않았다.
- kitty 창을 닫으면 그 tmux 도 같이 끝나게 하되, 다른 곳이 붙어 있으면 유지한다(아래 「kitty 닫힘」).
- ssh 에서는 claude 세션 목록을 보여 주고 접속·새 세션 생성을 고르는 UI(`llm-sessions` — 2026-11-05 부터 `llmui --sessions`). 디자인은 usageui·llmui 와 같은 `uikit` 틀.

## 구성
| 부분 | 파일 | 역할 |
|---|---|---|
| 래퍼 | `claude-tmux` (bash) | `claude` 셸 함수가 대화형 호출일 때 부른다. 새 세션 `claude-<디렉터리>-<시각>` 을 만들고 붙는다. `--wants` 는 감쌀지 판단(종료 코드) |
| 목록 UI·CLI | `llm_sessions.py` | `llm-sessions`(Textual) · `ls` · `attach <이름\|접두\|번호>` · `new [디렉터리] [-- claude 인자]` |
| tmux 조작 | `tmuxsess.py` | 목록(붙은 곳 출처 ssh/kitty/tty)·미리보기·생성·정리·떼기 |
| 설정 | `claude-tmux.conf` | 전용 소켓 `tmux -L claude` 에서만 읽힌다 — 일반 tmux 에 영향 없음 |
| 실행기 | nix 의 `claude-run` | tmux 안에서 `--settings`(훅·모션) 주입 후 claude 실행. **sudo 인증도 여기서 받는다** |

## 새 세션 기본값(2026-10-30 추가)
- **권한 확인 건너뛰기가 기본**: `llm-sessions` 로 만드는 새 세션(UI `F2`·CLI `new`)에는 `--dangerously-skip-permissions` 가 붙는다. 이유: 세션 간 통신(SendMessage)과 root 작업(sudo)마다 승인을 물으면 흐름이 끊긴다는 사용자 경험. 끄기: UI 의 「claude 인자」 칸 비우기 · `llm-sessions new --safe` · `CLAUDE_SESSIONS_DEFAULT_ARGS=`(빈 값). `--permission-mode` 등을 직접 주면 기본값은 붙지 않는다. 셸의 `claude` 함수·`claude-tmux` 직접 호출은 바뀌지 않았다(llm-sessions 만 해당).
- **디렉터리 고르기**: UI `F2` 대화상자 맨 위가 현재 위치(ctx 에 없는 곳이면 「새 위치」), 아래는 ctx DB(llmui 에 보이는 저장소)의 이 호스트 작업 저장소 루트(최근 사용 순, 실제로 있는 디렉터리만, /tmp 아래·git worktree 사본 제외). 직접 입력도 가능(Tab). DB 에 못 붙으면 현재 위치만 보인다. 조회는 `donghans ctx sql`(nix 가 `CLAUDE_CTX_BIN` 으로 알려 줌).

## llmui 와 합침(2026-11-05, 사용자 결정)
- **형태**: `llm-sessions` 를 인자 없이 치면 `llmui --sessions`(세션 탭만 있는 단독 앱, **DB 에 연결하지 않음**)가 뜬다. 인자가 있으면(`ls`·`attach`·`new`·`-h`) 예전처럼 `llm_sessions.py` 글자 CLI 로 간다. 같은 세션 코드(`llm_sessions.py` 의 `SessionsMixin`)를 `llmui` 의 **7 세션 탭**이 그대로 쓴다.
- **이름**: 런처 항목 「Claude Sessions」→「LLM Sessions」, 「LLM Context Manager」(`ctxui`)→「LLM Manager」(`llmui`). **옛 별칭(`ctxui`·`claude-sessions`)은 만들지도 남기지도 않는다**(사용자 지시 — `claude-sessions` 는 2026-10-27 개명 때 내가 호환용으로 덧붙인 것이지 요청이 아니었다).
- **제한 모드**(LLM 세션이 실행한 경우, 사용자 확정: 이 경우가 정상이며 LLM 이 직접 쓰는 경우는 없다): 목록만 보인다. 다른 세션의 화면이 노출되지 않도록 미리보기도 끈다. 붙기·새 세션·떼기·정리는 키 바인딩·Enter 행 선택·코드 직접 호출 모두에서 막는다(`sess_deny`). 단독 앱(`--sessions`)도 같은 규칙.
- **키(llmui 탭 7)**: Enter 붙기 · F2 새 세션 · F3 붙은 곳 떼기 · Delete 정리 · F5 새로고침. 다른 탭의 F2·F3·Delete 와는 `check_action`(TAB_ACTIONS)으로 탭별 분리.
- **sudo 인증**: `llm-sessions` 래퍼 경로에서만 UI 앞에 `sudo-claude-auth` 를 받는다. 런처의 `llmui` 로 들어가 탭 7 에서 새 세션을 만들면 인증 없이 시작되어 pane 에서 물어본다(기존 「인증 없이 시작함」 경로와 같다).
- 검증: 무맥락 검증 1회(높음 2·중 4 지적 반영 — psycopg import 자체는 허용하고 DB 연결만 하지 않기, `llm-sessions ls|attach|new` CLI 유지, Enter 행 선택 경로 차단, 탭별 키 분리). 시험은 `llm-ctx/tests/test_llmui.py`(세션 탭·제한 모드·`--sessions`)와 이 폴더의 `test_llm_sessions.py`.

## 결정과 근거
- **전용 소켓·전용 설정**: 사용자의 일반 tmux 와 섞이지 않고, 목록은 `claude-` 접두 세션만 보인다.
- **접두 키는 Ctrl+]**: tmux 기본 Ctrl+B 는 Claude Code 의 백그라운드 키, Ctrl+A 는 줄 처음 이동과 겹친다. 분리는 **F12** 한 번 또는 Ctrl+] d. 붙을 때 3초 안내가 뜬다.
- **Ctrl+Z 차단**(2026-11-03): 실수로 누르면 claude 와 `claude-run`(비대화형 스크립트라 `fg` 가 없음)이 통째로 멈춰 되돌릴 방법이 없다. 그래서 tmux 가 Ctrl+Z 를 가로채 안내만 띄우고, 접두 키 뒤 Ctrl+Z(기본값 `suspend-client`)도 풀었다. 일부러 보내야 하면 **Ctrl+] z**. 이미 떠 있는 서버에는 `tmux -L claude source-file <새 claude-tmux.conf>` 로 적용(새 서버는 자동). 이미 멈춘 pane 은 멈춘 claude 프로세스에 `SIGCONT`(`kill -CONT`)를 보내면 이어진다.
- **상태 줄 끔**(`status off`): 시계 같은 주기 갱신이 화면 절전(PSR)을 방해할 수 있다(ctx 장부 #57 과 같은 문제). 노트북 전력 영향은 측정하지 않았다.
- **sudo 는 claude 쪽으로만 열린다**(2026-11-03): 이전에는 `timestamp_type=global`(72eaeb9)로 한 번 인증하면 모든 터미널에서 sudo 가 열렸다. 원인은 claude 의 Bash 도구가 명령마다 tty 없는 새 세션·새 셸이라 sudo 의 캐시 키(tty, tty 가 없으면 부모 PID, 거기에 세션)가 매번 달라서다(tmux 로 옮겨도 마찬가지 — 실측: `tty` 가 `not a tty`, 명령마다 SID 가 새로 생김).
  - **안 된 방법**: `systemd-run --user` 로 sudo 를 띄워 부모 PID 를 `systemd --user` 로 고정 — 인증 직후에도 다음 유닛에서 `a password is required`(유닛마다 새 세션이라 캐시가 공유되지 않음, 같은 날 실측).
  - **지금 방식**: 중계 프로세스(`sudo_broker.py`)가 모든 sudo 를 자기 자식으로 실행해 키를 고정한다. claude 쪽 PATH 의 `sudo` 래퍼가 0600 유닉스 소켓(`$XDG_RUNTIME_DIR/claude-sudo.sock`)으로 stdin/stdout/stderr(SCM_RIGHTS)·cwd·환경을 넘기고 종료 코드를 그대로 받는다. 일반 터미널의 sudo 는 tty 별 캐시 그대로다.
  - **중계는 머신에 하나**, `setsid` 로 터미널과 무관하게 산다. `llm-sessions` UI 와 모든 tmux claude 세션이 같이 쓴다(세션끼리는 sudo 캐시를 공유; 처음에는 세션별 중계였으나 UI 에서 만든 새 세션이 붙기 전까지 pane 에서 비밀번호를 기다리는 문제가 있어 바꿈).
  - **수명은 임대**: UI(`llm-sessions`)와 `claude-run` 이 시작할 때 자기 PID 를 등록하고, 등록된 PID 가 하나라도 살아 있는 동안 산다. UI 를 닫아도 claude 가 남아 있으면 유지되고 마지막이 끝나면 15초 뒤 정리된다(여러 UI 중 하나를 닫아도 영향 없음). 60초마다 `sudo -n -v` 로 티켓을 연장한다.
  - **인증은 앞에서 한 번**: `llm-sessions` 는 UI 를 띄우기 전에, `claude-run` 은 claude 를 띄우기 전에 `sudo-claude-auth` 로 티켓이 없을 때만 비밀번호를 묻는다(nixup 의 `sudo -v` 와 같은 구조). 비밀번호는 읽어서 파이프로만 넘기고 어디에도 저장하지 않는다. UI 에서 인증하면 이후 `n` 으로 만드는 세션은 묻지 않고, 붙기 전에도 바로 시작된다.
  - **인증이 없으면** 래퍼가 항상 `sudo -n` 으로 즉시 실패하고 안내를 출력한다(프롬프트 대기 → 우회 방지). 재인증은 아무 터미널에서 `sudo-claude-auth`.
- **감싸지 않는 호출**: `CLAUDE_TMUX=0` · 이미 tmux 안 · 터미널이 아님 · `-p/--print/--help/--version/--output-format` · 서브커맨드(한 단어: mcp, config, update …). 따라서 스크립트·`claude -p` 는 그대로다. 한 단어짜리 프롬프트(`claude hello`)는 서브커맨드로 보여 감싸지지 않는다.
- **kitty 닫힘**: 래퍼가 SIGHUP/터미널 소실을 감지하면, 그 세션에 다른 접속이 **없을 때만** 세션을 끝낸다. 다른 곳(ssh 등)이 붙어 있으면 그쪽이 이어 쓰게 두고, 이후 고아가 되면 `llm-sessions` 에서 `Delete` 로 정리한다. 분리(F12)는 터미널이 살아 있으므로 정리하지 않는다. kitty 가 강제 종료(SIGKILL)되면 세션이 남을 수 있다.
- **ssh 에서 만든 세션은 끊겨도 산다**: `llm-sessions` 의 `F2` 는 분리된 세션을 만들고 붙는다. 분리하면 목록으로 돌아온다.
- **이미 떠 있는 Claude 세션은 tmux 안으로 옮길 수 없다** — 새로 시작하는 세션부터 적용.

## 시험(실제 tmux 3.6a · pty · Textual Pilot, 51건)
생성·목록·미리보기·정리, `--wants` 판단, 붙기·F12 분리·세션 유지, 동시 접속 2곳과 출처 조회, `F3`(붙은 곳 떼기), **kitty 닫힘 시 정리 / 다른 접속이 있으면 유지**, claude 종료 시 세션 종료, UI(목록·미리보기·붙기·새 세션·정리·도움말)와 CLI. 변이 검사: 접속자 수 확인을 없애 항상 죽이게 하면 「다른 접속 있음 → 유지」 시험이 실패함을 확인했다.
실제 Claude Code 를 이 설정의 tmux 안에서 헤드리스 kitty 로 띄워 화면(신뢰 확인 대화상자)이 정상 표시되고 `llm-sessions ls` 가 세션·접속 출처를 보이는 것까지 확인했다. **키 입력(Shift+Enter 등)·알림·이미지 붙여넣기는 아직 실사용으로 확인하지 못했다** — 새 셸에서 써 보며 이상하면 `CLAUDE_TMUX=0 claude` 로 우회하고 `claude-tmux.conf` 의 `extended-keys`·`allow-passthrough` 를 조정한다.

## 아직 안 한 것
- 노트북 전력(상태 줄 끔 이후 화면 갱신) ABAB 측정.
- observectl 앱 귀속(tmux 서버의 자식이 된 claude 도 `.claude-wrapped` 로 집계되는지) 확인.
