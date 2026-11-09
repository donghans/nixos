# llm-host — LLM 세션 호스트 코어 (규격 v0)

설계 근거: ctx 문서 `plan llm-trust/11-p5prime-2-session-host` (읽기: `donghans ctx doc read plan llm-trust/11-p5prime-2-session-host --project nixos`). 이 폴더는 계획서 §9 의 S1~S9 를 모두 갖췄다. **P5′-3 이 쓰려면 맨 아래 「공개 API (S9)」와 「확인 못 함·소비자 책임」부터 읽는다.** 아래 절들은 모듈별 상세다(규격 `events.py`·어댑터 `adapter.py`/`claude_adapter.py`·세션 `session.py`·가짜 백엔드 `fake_claude.py`·정책 `policy.py`·다중 세션 `host.py`·기록 `recorder.py`·실제 시험 `integration_real.py`·래퍼 `launcher.py`).
시험(모두 비용 0, 가짜 백엔드·녹화본): `tests/test_events.py`(규격)·`test_claude_adapter.py`(어댑터; 녹화본 `tests/fixtures/` 전체 재생)·`test_session.py`·`test_policy.py`·`test_host.py`·`test_recorder.py`·`test_integration_real.py`(판정 함수)·`test_launcher.py`. 각각 `cd mods/_tools/llm/llm-host && python3 -I tests/<파일>` 로 직접 실행하고, `mods/_tools/run-tests.sh` 에 `llm-host-ev`·`-claude`·`-session`·`-policy`·`-host`·`-recorder`·`-integ`·`-launcher` 8항목으로 등록돼 있다. 비용이 드는 `integration_real.py`·`launcher_real.py` 는 run-tests.sh 에 없다.

**규격은 v0 이다.** P5′-3(TUI)을 만들며 부족한 필드를 추가하고 P5′-4(두 번째 백엔드) 때 한 번 정리한다. 그때까지 `raw` 통과가 안전판이다.
nix 에는 아직 등록하지 않았다(`mods/devel/apps/llm-cli.nix` 의 `ctxSrc`·`sessionsSrc` 는 파일 이름을 하나씩 나열해 복사하므로 이 폴더는 자동 수집되지 않고, 빌드·평가에 영향이 없다 — 등록은 계획서 S8 의 별도 허락 사항).

## 형식
- JSON 줄 하나가 이벤트(호스트 → 소비자) 또는 명령(소비자 → 호스트) 하나. UTF-8, 비 ASCII 보존, 줄 안에 개행 없음.
- Python 3 표준 라이브러리만 쓴다(`dataclass`, `kw_only` 때문에 3.10+).
- `events.to_json(obj)`, `events.event_from_json(line)`, `events.command_from_json(line)`.
- **알려진 kind 에 모르는 필드**가 오면 `extra` 에 보존해 다시 직렬화에 그대로 나간다(앞으로 호환).
- **알 수 없는 kind, 깨진 필드(형이 틀림), JSON 이 아닌 줄**은 이벤트로는 `raw` 로 돌려준다(원문을 `payload` 에 보존; `vendor` 는 각각 `unknown-kind`·`malformed`). **명령**은 잘못되면 `ValueError`(조용히 통과시키지 않는다).

## 이벤트의 공통 필드
`seq`(세션 안 증가 번호) · `ts`(호스트 수신 시각, epoch 초) · `host_session`(호스트가 붙인 id) · `backend_session`(백엔드가 준 id, 없으면 null) · `run`(서브에이전트 실행 id, 주 대화는 null) · `kind`.

## 이벤트 종류
| kind | 필드 | 설명 |
|---|---|---|
| `session_ready` | `backend`·`backend_version`·`model`·`cwd`·`capabilities[]`·`tools[]`·`skills[]`·`slash[]`·`mcp[]`·`permission_mode` | 첫 `send` 뒤의 첫 init(메시지 전에는 오지 않는다 [S0 확인]) |
| `session_info` | `changed{}` | 이후 턴의 init 에서 바뀐 값만 |
| `turn_started` | `turn`·`source`(user·auto) | |
| `text_delta` | `block`·`text` | 글자 조각 |
| `thinking` | `tokens_est` | |
| `message` | `role`·`blocks[]` | 완결 메시지. 블록은 text·tool_use·tool_result·image |
| `tool_call` | `call`·`name`·`input` | 실행 전 |
| `tool_result` | `call`·`content`·`is_error` | |
| `permission_request` | `req`·`tool`·`display`·`input`·`call`·`description`·`suggestions[]` | **S1 결정**: S0 실측의 `description`·`permission_suggestions` 를 `description`·`suggestions` 로 담는다. `suggestions` 는 백엔드가 제안한 규칙·모드 변경(벤더 형식 그대로) — 소비자는 표시하고, 채택하면 `answer_permission.updated_permissions` 로 되돌려 보낸다 |
| `question_request` | `req`·`questions[]`·`call` | `questions` 원소: question·header·options[{label,description}]·multiSelect. 백엔드의 `requires_user_interaction` 은 이 kind 로 구분되므로 필드로 두지 않는다 |
| `request_resolved` | `req`·`outcome`(allow·deny·answered)·`by`(user·policy·timeout·session_end)·`message` | 감사용 |
| `subtask` | `state`(started·progress·updated·done)·`summary` | 서브에이전트 진행(`run` 으로 구분) |
| `hook` | `name`·`phase` | |
| `turn_result` | `ok`·`subtype`·`text`·`cost_total`·`cost_delta`·`permission_denials[]`·`terminal_reason`·`stop_reason`·`num_turns`·`model_usage` | **S1 결정**: S0 실측의 `terminal_reason`·`stop_reason`·`num_turns` 와 `model_usage_since_last_result`(→`model_usage`, 후보 — 비용 차이와의 일치는 어댑터 단계에서 확인)를 넣는다. `cost_delta` 는 호스트가 누적값 차이로 계산 |
| `rate_limit` | `status`·`resets_at`·`window` | |
| `notice` | `level`(info·warn·error)·`text` | 호스트 자체 경고 |
| `session_ended` | `reason`(closed·crashed·killed·eof)·`exit_code` | |
| `raw` | `vendor`·`payload` | 번역표에 없는 줄. 버리지 않고 통과 |

## 명령 (공통 필드 `cmd`)
| 명령 | 필드 | 효과 |
|---|---|---|
| `start` | `spec{cwd·model·permission_mode·policy·resume·persist(기본 true)·extra_args[]·env_extra{}·label}` | 프로세스 기동 |
| `send` | `text` 또는 `blocks[]`(정확히 하나) | 사용자 메시지 |
| `interrupt` | — | 현재 턴 중단, 세션 유지 |
| `answer_permission` | `req`·`allow`·`message`·`updated_input`·`updated_permissions` | 권한 응답. deny 의 `message` 는 모델에게 간다 |
| `answer_question` | `req`·`answers{질문: label 또는 label[]}`·`free_text` | 질문 응답 |
| `set_policy` | `policy` | 이후 요청의 정책 교체(호스트 안에서만) |
| `close` | `grace` | 정상 종료 |
| `kill` | — | 즉시 강제 종료(자기 자식만) |

첫 `send` 전에는 백엔드의 능력을 알 수 없다(init 이 첫 메시지 뒤에 온다). 능력에 의존하는 명령은 `unknown` 으로 두고 시도 후 오류를 받아들인다.

## 어댑터 (S2)
- `adapter.Adapter`: `argv(spec)`·`env(spec)`·`decode(line)->[Event]`·`encode(Command)->[줄]`·`capabilities`. 어댑터는 **세션마다 인스턴스 하나**(decode 가 상태를 가진다). `decode` 는 `seq`·`ts` 를 채우지 않는다(세션이 받는 순서로 매긴다).
- `claude_adapter.ClaudeAdapter(host_session)`: `decode`·`capabilities`(S2)와 `argv`·`env`·`encode`(S3). `encode(Send)` 가 `note_sent()` 를 불러 `turn_started.source` 가 `user` 가 된다.
- 알 수 없는 줄·모양이 틀린 줄·JSON 이 아닌 줄은 `raw`(`vendor="claude"`, 원문 `payload`)로 통과. 알려진 줄 중 소비자에게 줄 게 없는 것은 이벤트 0개이고 `adapter.ignored` 에 종류별로 센다.

### claude 번역 (녹화본 `tests/fixtures/{noinit,perm,main,sub}.jsonl` 로 시험, claude 2.1.317·haiku)
| claude 줄 | 이벤트 |
|---|---|
| 첫 `system/init` | `session_ready` (메시지 전에는 init 이 없다 — noinit 녹화본은 출력 0줄) |
| 이후 `system/init`(매 턴) | 바뀐 값만 `session_info.changed`, 바뀐 게 없으면 이벤트 없음. **실측**: 첫 턴 뒤 init 에서 `tools` 32→85·`mcp` 0→30(계정 커넥터)로 늘어 `session_info` 가 한 번 나온다 |
| `system/status requesting` | 턴의 **첫 것만** `turn_started`(API 호출마다 오므로). `source`: `note_sent()` 로 센 호스트 발 메시지가 있으면 user, 없으면 auto. `result` 가 턴 끝 |
| `stream_event` 글자 조각 | `text_delta`(`block`=content index). 뼈대(message_start/delta/stop·content_block_start/stop)·도구 입력 조각·사고 조각·서명 조각은 이벤트 없음 |
| `system/thinking_tokens` | `thinking`(`tokens_est`) |
| `assistant` | `message`(role assistant) + 안의 `tool_use` 마다 `tool_call`(실행 전) |
| `user` | `message`(role user) + 안의 `tool_result` 마다 `tool_result` |
| `result` | `turn_result`. `cost_delta` = 누적 `total_cost_usd` 의 차(첫 턴은 total, 값이 줄면 새 프로세스로 보고 total). **확인됨**: `cost_delta` 는 `model_usage_since_last_result` 의 `costUSD` 합과 일치(녹화본 12턴, 중단된 턴은 둘 다 0·`{}`) |
| `control_request/can_use_tool` | `permission_request`(`description`·`suggestions`=`permission_suggestions`), `AskUserQuestion` 은 `question_request`. `run` 은 그 도구 호출 id 를 앞서 서브에이전트 메시지에서 봤으면 그 run |
| `control_response`(claude 가 보낸 것: interrupt 수락 등) | `notice`(info; `extra.request_id`·`extra.response`). error 는 level error |
| `system/hook_started`·`hook_response` | `hook`(`name`=hook_name, `phase` started·finished; finished 의 `extra` 에 `outcome`·`exit_code`·`hook_id`·`hook_event`) |
| `system/task_started`·`task_progress`·`task_updated`·`task_notification` | `subtask` started·progress·updated·done. `run` = Agent 도구 호출 id(`tool_use_id`; `task_updated` 는 task_id 표로 이음). `done` 의 `extra.status` 에 종료 상태 |
| `rate_limit_event` | `rate_limit`(`window`=`rateLimitType`) |
| `system/api_retry` | `notice`(warn, 원문 `extra.payload`) — **형식 미녹화**, 합성 줄로만 시험(실제 줄이 오면 확인) |
| `parent_tool_use_id` 가 붙은 줄 | 그 줄의 모든 이벤트의 `run` = 그 값(서브에이전트를 띄운 Agent 도구 호출 id). 녹화본에서 서브에이전트의 글자 조각 stream_event 는 오지 않았다(완결 메시지만) |
| 그 밖 | `raw` |

### Message 블록과 중복 표시 (`shown_as`)
`--include-partial-messages` 로 이미 `text_delta` 로 전한 글은 이어서 오는 `assistant` 완결 메시지(**중단 직후의 부분 응답 포함**)에 또 들어 있다. `message.blocks` 는 완결본을 그대로 담되, **다른 이벤트로 이미 전달한 블록에 `shown_as` 를 붙인다**: `text`→`"text_delta"`, `tool_use`→`"tool_call"`, `tool_result`→`"tool_result"`. 소비자는 `shown_as` 가 있는 블록을 다시 그리지 않는다. 글자 조각 없이 온 글(부분 메시지 옵션 없음)은 `shown_as` 가 없어 Message 로 그린다. 사고 블록은 `{"type":"thinking","text":…}`(불투명 서명은 버린다).
녹화본은 경로·uuid·소켓 치환본이다(원본은 개인 경로를 담아 저장소에 두지 않는다). `sub.jsonl` 은 S2 에서 실제 claude 로 재녹화(훅 3종·서브에이전트 1개, `--include-hook-events`)했다.

## 어댑터 쓰기 쪽 (S3)
- `argv(spec)`: `[exe…] -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --include-hook-events --permission-mode <spec.permission_mode|manual> --permission-prompt-tool stdio [--model] [--resume] [--no-session-persistence(persist=false)] [extra_args…]`. 실행 파일은 `spec["exe"]`(문자열 또는 `[실행 파일, 인자…]`)로 갈아끼운다(시험: 가짜 백엔드). 없으면 `claude`. bypass 거부 같은 정책은 S4.
- `env(spec)`: 상속하지 않는다. `HOME`·`PATH`·`TERM=dumb` + `spec["env_extra"]`. 래퍼 재현(sudo·`claude-run`)은 S8.
- `encode`: 줄은 공백 없는 JSON(`ensure_ascii=False`). `send`→`{"type":"user","message":{"role":"user","content":…}}`, `interrupt`→`control_request` `{"subtype":"interrupt"}`(요청 id `host-int-N`), `answer_permission` allow→`{"behavior":"allow","updatedInput":<바꾼 input 없으면 원래 input>[,"updatedPermissions"]}`·deny→`{"behavior":"deny","message":…}`, `answer_question`→allow + `updatedInput={questions(원본), answers}`. 허용·거부·질문 답·user 줄은 S0 녹화본과 **바이트 단위로 같다**(시험). 확인 못 한 것: 다중 선택 답을 `", "` 로 잇는 형식(공식 문서 서술 기준, 실측 없음)과 `free_text` 의 자리(답 없는 첫 질문의 답으로 둠) — S7 에서 실제 claude 로 확인.

## 세션 (S3, `session.py`)
`Session(adapter, spec, host_session, keep_history=False, term_wait=5)` → `await start()` → `await send(text)`·`interrupt()`·`answer_permission(req, allow, message)`·`answer_question(req, answers)`·`command(cmd)`·`close(grace)`·`kill()`. 이벤트는 `async for ev in session.events()`(SessionEnded 까지; 소비자 하나), `next_event(timeout)`, `collect_until(pred, timeout)`.
- 자식은 `start_new_session=True` 새 프로세스 그룹, 신호는 자기 자식 그룹에만(`killpg`). 읽기·쓰기·표준오류는 각각 태스크. 쓰기는 큐로 순서를 지킨다.
- 상태: `starting → idle ⇄ busy ⇄ waiting_request → closing → closed`, 예기치 않은 종료 `crashed`. 기동 직후 idle(첫 메시지 전에는 백엔드 출력이 없다). busy 는 send 뒤 turn_result 까지(백엔드 대기열의 send 도 센다). 대기 표 `session.pending`.
- 종료 사유: 우리가 close → `closed`, kill → `killed`, 예기치 않은 종료는 코드 0 이면 `eof`, 그 밖은 `crashed`. 미해결 요청은 `request_resolved(deny, session_end)` 로 닫고 `session_ended` 가 마지막 이벤트. close 는 표준입력 닫기 → grace → SIGTERM → term_wait → SIGKILL.
- 표준오류 줄은 `notice(warn, extra.stream=stderr)`(최대 50줄). 어댑터 decode 예외·너무 긴 줄은 `notice(error)`. 실행 파일이 없으면 `notice(error)` + `session_ended(crashed)`.
- 아직 없는 것(뒤 단계): 정책을 세션에 연결해 대기 상한 시각에 자동 거부를 실제로 보내는 일(host.py·S5; S4 는 순수 함수만), 다중 세션·상한·고아 레지스트리(S5), 이벤트 로그(S6, 아래 「기록」 절에서 연결됨).

## 가짜 백엔드 (`fake_claude.py`)
`python3 fake_claude.py 시나리오.jsonl [--timeout 초]`. 시나리오 한 줄이 단계 하나: `{"emit":[줄…]}` · `{"expect":{stdin_type|line|text|control_response|control_request|request_id|stdin_eof}}` · `{"sleep":초}` · `{"stderr":"글"}` · `{"ignore_sigterm":true}` · `{"exit":코드}`. `line` 은 바이트 단위 비교, `control_response`·`control_request` 는 부분집합 비교. 기대가 어긋나면 종료 코드 3, 입력이 안 오면 4, 입력이 닫히면 5, 시나리오 오류 2. 시나리오 끝에서는 입력 EOF 까지 읽고 0 으로 끝난다. 시험은 녹화본 fixtures 를 시나리오로 바꿔 쓴다(in→expect, out→emit).

## 정책 (`policy.py`, S4) — 순수 함수
시계·세션을 모른다. 호출하는 쪽이 구독자 수·대기 시간(초)을 세어 넘긴다. `python3 policy.py --dump-messages` 가 모델이 읽는 문구 전체를 찍는다(검토용).
- **먼저 알아 둘 것**: claude 가 사용자 설정 규칙(`permissions.allow`·`ask`)과 권한 모드를 **먼저** 평가해, 규칙이 허용한 호출은 호스트에 `can_use_tool` 이 오지 않는다(S0 확인). 이 정책은 「결정이 안 난 요청」만 본다. 호스트가 허용 목록을 새로 만들지 않는다.
- `normalize_policy(dict|None) -> Policy`: `request_timeout`(초, 기본 1800)·`auto_allow`(기본 비움)·`max_auto_turns`(기본 3)·`allow_bypass`(기본 False). 잘못된 값·모르는 키는 ValueError. `auto_allow` 는 읽기 전용 집합(`Read`·`Glob`·`Grep`·`LS`) 안의 이름만 받고 나머지는 `ignored` 로 남긴다.
- `decide_request(policy, tool, subscribers=, waited=, is_question=) -> Decision(allow|wait|deny, by, message, wait_left)`: 질문은 정책이 답하지 않는다. 읽기 전용 목록에 있으면 allow(by=policy). 그 밖은 `request_timeout` 전이면 wait(구독자 유무와 무관 — 구독자가 없으면 대기 표에 둔다), 닿으면 deny(by=timeout, 모델이 읽는 문구). 구독자가 있어도 같은 상한이 적용된다(응답 없는 화면이 요청을 영원히 붙잡지 못하게).
- `check_start(spec) -> [사유]`: bypass 계열(`permission_mode` bypass*·`--dangerously-skip-permissions`·`--permission-mode bypassPermissions` 등)은 `policy.allow_bypass=True` **이고** cwd 에 `.llm-host-sandbox` 파일이 있을 때만 통과. `--settings` 파일 안의 간접 지정은 읽지 못한다.
- `next_auto_turn(policy, count) -> (허용, 새 count, 사유)`: 사람 메시지 없는 연속 자동 턴 상한.
- `deny_message(kind, user_reason=, request_timeout=, question=)`·`MESSAGES`: 거부·타임아웃·세션 종료 문구. 형식은 ① 누가·왜 ② 재시도 금지 ③ 멈추고 보고. 사용자가 쓴 이유는 그대로 전달한다. 이 문구는 모델 입력이다 — 바꾸면 tests/test_policy.py 의 속성 시험과 문구 덤프 검토 기록을 갱신한다.

## 다중 세션·수명 (S5, `host.py`)
- `SessionHost(adapter_factory, max_sessions=4, registry_dir=None, term_wait=5.0)`: 세션마다 독립 프로세스·이벤트 큐. `start_session(spec)` 은 상한을 넘으면 `HostFull`, bypass 계열 지정은 `StartRefused`, 같은 `spec["resume"]` 을 동시에 쓰면 `DuplicateResume`, 이름 중복은 `DuplicateSession`, `close_all` 뒤에는 `HostClosed`. 동시 시작도 상한을 넘지 못한다. 상한 4 는 D-9 임시값(S7 측정 뒤 조정).
- 종료: `close_session`·`close_all`(병렬) = `Session.close` 4단계(stdin 닫기→grace→SIGTERM→term_wait→SIGKILL), `kill_all` = SIGKILL. 신호는 자기 자식의 프로세스 그룹에만 간다.
- 자식 레지스트리 `<registry_dir>/children.jsonl`(기본 `$XDG_RUNTIME_DIR/llm-host/`): 추가 기록만(add·del), flock, 잘린 꼬리 줄 무시. add 에 pid·starttime·host_id·host_pid·host_starttime. 자식 환경에 `LLM_HOST_ID=<host_id>` 표지.
- 고아 탐지 `scan_orphans()`: 레지스트리에 있고 pid·starttime 이 같은 채 살아 있는데 띄운 호스트가 죽은 자식만 보고한다(표지가 읽히는데 다르면 제외, 형제 호스트의 자식은 제외). **죽이지 않는다** — `host.notices` 에 procctl plan 안내만 쌓는다(D-14: 안내만). 사람이 정리한 뒤 `forget_orphan`.
- 시험 `tests/test_host.py`(비용 0, 가짜 백엔드): 100회 시작·종료 후 자식 표지 프로세스 0개, SIGTERM·EOF 무시 가짜로 SIGKILL 경로, 호스트 흉내 프로세스 강제 종료 후 재시작·고아, 동시 세션 격리. run-tests.sh 의 `llm-host-host`.
- 호스트 사망 시 자식 거동은 유휴 상태 EOF 만 확인됨(S0). 턴 진행 중·권한 대기 중 EOF 는 미확인(S7 항목 8, 선택).

## 기록 (S6, `recorder.py`)
- **이벤트 로그** `EventLog(host_session, root, include=False)`: `<root>/<host_session>/events.jsonl`(파일 0600·폴더 0700, umask 와 무관하게 `fchmod`), 줄 하나 = `Event.to_dict()`. `text_delta` 는 기본 제외(`log_deltas=True` 로 포함). 첫 줄은 `log_open`(host_id·pid·제외 목록) — 같은 host_session 이름은 호스트가 다시 떠도 이어 쓰므로 구분용. 로그를 못 써도 세션은 죽지 않는다(`errors` 카운트). **로그에는 도구 입력·메시지 본문이 있어 비밀·고객 데이터가 섞일 수 있다** → ctx 로 올리는 코드는 없다(ctx 는 transcript 에서 따로 적재).
- **위치 관례(S6 확인)**: `$XDG_STATE_HOME`(없으면 `~/.local/state`) 아래 `llm-host/`. 이 저장소의 `displayctl`(`dispctl/config.py`)·`hypr`(hwctl)가 같은 관례를 쓰고 홈에 `observe`·`procui`·`claude-ctx` 등이 이미 있다 — 계획서의 「관례 미확인」은 확인됨.
- **보존 삭제** `purge_logs(root, days=14)`: `events.jsonl` 이 days 일보다 오래 안 바뀐 세션 폴더(파일 → 비면 폴더)만 지운다. root 바로 아래 폴더만 보고 심볼릭 링크·`events.jsonl` 없는 폴더는 건드리지 않는다. `SessionHost(log_root=…, retention_days=14)` 는 만들 때 한 번 돈다(`retention_days=None` 이면 안 지움, 결과는 `host.purged_logs`).
- **연결**: `SessionHost(log_root=None, log_deltas=False, retention_days=14, raw_dir=None)`. `log_root=None`(기본)이면 로그를 안 남긴다. `Session(sinks=[함수…])` 는 이벤트마다 함수를 부르고 예외는 삼킨다(`EventLog` 는 호출 가능).
- **비용** `CostTracker`: `turn_result.cost_delta` 의 합(`total`)·마지막 `cost_total`·턴 수. `Session.cost`, `SessionHost.cost_summary() -> {total, turns, sessions:{host_session:{total,last_cost_total,turns,priced_turns}}}`(release 한 세션 포함). `total_cost_usd` 는 클라이언트 추정치라 청구와 다를 수 있다. resume 한 세션의 합계는 이번 프로세스 증가분이다.
- **`spec["max_budget_usd"]` → `--max-budget-usd`**: 선택 안전장치, **기본값 없음**(상한 값은 추천하지 않는다 — D-8). 0 초과 유한 숫자만(아니면 `ValueError`, 자리는 잡지 않는다). claude 쪽 한도는 넘을 수 있고 resume 이전 합계는 세지 않는다 [공식].
- **원본 줄 녹화(시험용)** `RecordingAdapter(adapter, path)` / `SessionHost(raw_dir=폴더)`: 날 줄을 `{"t","dir","line"}`(in·out·out_unparsed·note)로 `<raw_dir>/<host_session>.raw.jsonl`(0600)에 쓴다 — `tests/fixtures` 와 같은 형식. 원본에는 개인 경로·세션 id 가 있으니 저장소에 두기 전 치환(S0 방식)한다. 표준오류 줄은 어댑터를 지나지 않아 녹화하지 않는다.
- 시험 `tests/test_recorder.py`(비용 0, 임시 폴더): 권한 0600/0700, 제외·포함, 왕복, 쓰기 실패 무시, 보존 삭제 경계(14일·13.9일·링크·여분 파일), 비용 합 = 마지막 누적 = 로그 합, 호스트 연결, 원본 녹화 형식, 예산 인자. run-tests.sh 의 `llm-host-recorder`.

## 실제 claude 통합 시험·카나리아 (S7, `integration_real.py`)
**비용이 든다**(haiku, 항목당 약 $0.01~0.02) — `run-tests.sh` 에 넣지 않고 사람이 부른다. 사용: `python3 -I integration_real.py --out <새 폴더> --items canary|all|1,2,…` (항목 1 hello·비용 / 2 권한 허용·거부 / 3 질문 / 4 중단 / 5 서브에이전트 / 6 동시 4세션·메모리·자식 0개 / 7 resume(persistence 켬 — 시험 cwd 세션이 ctx 에 남는다) / 8·8b 호스트 SIGKILL 뒤 자식(유휴·진행 중)). `canary` = 1·2·4, **Claude Code 를 갱신할 때마다** 한 번 돌려 줄 형식 변화를 잡는다(`raw` 가 0 이 아니거나 비용 합이 어긋나면 실패). 결과는 `<out>/results.json`·`raw/`·`logs/`.
판정 함수(`analyze_*`)는 이벤트 목록만 보는 순수 함수이고 `tests/test_integration_real.py` 가 돈 없이 시험한다(통과 사례마다 변이 사례가 실패해야 함 — `llm-host-integ`).
S7 에서 실측으로 어댑터에 반영한 것(claude 2.1.318): ① `system/background_tasks_changed` 는 알려진 줄(이벤트 없음, `ignored` 로 셈) ② `--resume` 으로 띄운 프로세스의 `total_cost_usd` 는 이전 실행분을 포함한 누적 → 재개 세션 **첫 턴 `cost_delta` 는 null**(이후는 그 값 기준). 결과 상세는 ctx 노트 `llm-trust/wf-s7-integration`.

## 래퍼·sudo (S8, `launcher.py`)
쉘 함수 `claude` 가 하는 일(훅 설정 주입·sudo 환경)을 호스트가 한 곳에서 재현한다. 쉘 함수는 부르지 않는다. 사용: `spec, plan = launcher.launch_spec(spec, sudo_ready=…)` 뒤 `Session(adapter, spec)`(`prepare`→`apply`). 시험 `tests/test_launcher.py`(비용 0, 가짜 claude-run·sudo), 실제 시험 `launcher_real.py`(비용 있음, run-tests.sh 에 넣지 않음).
- **실행 파일 = `claude-run`**. 표준입력이 파이프이면 claude-run 은 sudo 부분을 건너뛰고 `--settings <훅 설정>` 만 붙여 claude 를 부른다 — **실측 확인(S8)**: 훅 이벤트(`SessionStart:startup`·`UserPromptSubmit`·`PostToolUse:Bash`·`Stop`)가 호스트에 오고, 자식 환경에 `CLAUDE_SUDO_SOCK` 가 없다.
- **claude-run 찾기**: 인자 > PATH 의 `claude-tmux` 글에서 읽은 `CLAUDE_RUN_BIN=`(현재 프로필) > 환경변수 `CLAUDE_RUN_BIN`. **환경변수는 낡을 수 있다**(실측: 이 에이전트 세션의 환경변수는 옛 세대 claude-run 을 가리켰고 sudo 부분이 없었다) → 프로필을 먼저 본다. 독립 호스트(llmui 아님)도 nix 수정 없이 찾는다.
- **sudo 래퍼·`sudo-claude-auth` 의 store 경로**는 claude-run 글(`export PATH=<dir>:$PATH`, `<경로>/sudo-claude-auth --lease`)에서 읽는다. 글 모양에 의존한다: 못 읽으면 sudo 없는 세션 + notice.
- **sudo_ready**: 실행기가 터미널에서 `sudo-claude-auth` 로 먼저 인증하고 `sudo_ready=True` 를 넘긴다. 호스트는 비밀번호를 읽지 않는다. `prepare` 가 하는 일은 `sudo-claude-auth --lease <호스트 PID>`(표준입력 /dev/null — 티켓이 유효하면 0, 아니면 묻지 않고 1)와 쓰기 없는 `sudo true` 확인이고, 둘 다 통과해야 `CLAUDE_SUDO_SOCK`·PATH 앞붙임(래퍼 디렉터리)을 붙인다. 하나라도 실패하면 sudo 환경 없이 시작하고 `notice(warn, "sudo 중계 없음 … [사유]")`. claude-run 은 파이프 모드에서 임대를 하지 않으므로 호스트 PID 임대가 필요하다(중계는 임대 PID 가 모두 죽고 15초 뒤 끝난다).
- **claude-run 을 못 찾으면 거부**(`LauncherError`): 훅 설정에 확인 강제 규칙(`ctx doc delete`·`procctl apply` 등)이 들어 있어 없이 시작하면 안전 규칙이 빠진다. `allow_no_hooks=True` 로 명시하면 일반 claude 로 시작하고 경고 2건.
- **세션 중 만료 힌트**: `launcher.sudo_hint(ev)` — tool_result 에 `claude-sudo:` 와 안내 키(`sudo-claude-auth`·`sudo 중계가 없음`·`sudo 인증이 없거나 만료`)가 있으면 notice(warn, `extra.hint="sudo"`). Session 이 세션당 한 번 낸다. 문구 일치라 **힌트용**이다(실측: 소켓 없는 래퍼의 「중계가 없음」 문구로 1건 감지).
- `Session` 은 `spec["launch_notices"]`([(level, text)])를 시작할 때 notice 로 낸다.
- **ctx 흔적(주의)**: claude-run 이 붙이는 훅은 `--no-session-persistence` 여도 `donghans ctx hook` 으로 ctx DB 의 `hook_events`·`sessions` 에 행을 남긴다(실측: 세션 1개당 SessionStart·UserPromptSubmit·Stop·SessionEnd 등, 최소 환경 HOME·PATH·TERM 만으로도 기록됨). 시험은 cwd 로 구분한다. 지우지 않는다.

## 공개 API (S9) — P5′-3 이 규격 변경 없이 쓰는 법
모두 `llm-host/` 폴더를 `sys.path` 에 올려 `import events, host, ...` 로 쓴다(패키지 아님; nix 에는 아직 등록 안 함 — 위 안내). Python 3.10+, 표준 라이브러리만.

**1. 기동(소비자 한 곳에서 이 순서를 지킨다)**
```python
import host, claude_adapter, launcher, policy, recorder

pol_dict = {"request_timeout": 1800}
pol  = policy.normalize_policy(pol_dict)                         # 잘못된 값은 ValueError. decide_request 에 넘기는 값
spec = {"cwd": "/작업/폴더", "model": "haiku", "permission_mode": "manual",
        "persist": True, "policy": pol_dict}
bad  = policy.check_start(spec)                                  # ★ 소비자가 부른다(아래 「소비자 책임」). 비어 있지 않으면 시작하지 않는다
spec, plan = launcher.launch_spec(spec, sudo_ready=False)        # claude-run·훅 설정·(선택) sudo 환경. 못 찾으면 LauncherError
h = host.SessionHost(lambda hs: claude_adapter.ClaudeAdapter(hs), max_sessions=4,
                     log_root=recorder.default_log_root())       # log_root=None 이면 이벤트 로그 안 남김
s = await h.start_session(spec)                                  # HostFull·DuplicateResume·DuplicateSession·HostClosed·StartRefused(check_start 를 호스트가 이미 부른다)
```
- `spec` 키: `cwd`·`model`·`permission_mode`(기본 `manual`)·`resume`(백엔드 세션 id)·`persist`(기본 true)·`extra_args[]`·`env_extra{}`·`label`·`exe`(시험용 실행 파일 교체)·`max_budget_usd`(선택, 기본 없음)·`policy`. `launcher.apply` 가 `exe`·`env_extra`·`launch_notices` 를 덮어쓴다.
- 호스트 하나가 세션 여러 개를 가진다. 세션 하나만 쓸 때는 `session.Session(adapter, spec)` + `await s.start()` 로 호스트 없이도 쓸 수 있다(레지스트리·상한·로그 연결 없음).

**2. 이벤트 받기·명령 보내기 (세션 단위, 이벤트 소비자는 세션당 하나)**
```python
async for ev in s.events():          # SessionEnded 로 끝난다. 또는 await s.next_event(timeout)·s.collect_until(pred, timeout)
    if ev.kind == "permission_request":   ...  # req·tool·display·input·description·suggestions
    if ev.kind == "question_request":     ...  # req·questions
await s.send("글")                                    # 생성 중이면 백엔드가 대기열에 둔다
await s.interrupt()                                   # 세션 유지
await s.answer_permission(req, True|False, message=None, updated_input=None)
await s.answer_question(req, {"질문 문장": "고른 label"}, free_text=None)
await s.close(grace=10.0)                             # stdin 닫기 → grace → SIGTERM → SIGKILL. 미해결 요청은 deny(session_end)
await s.kill()                                        # 자기 자식 그룹만 SIGKILL
```
- `s.state`(starting·idle·busy·waiting_request·closing·closed·crashed)·`s.pending`(req → 미해결 요청)·`s.cost`·`s.pid` 는 화면 힌트다. 정합성의 근거는 이벤트다.
- 이벤트·명령은 JSON 줄로 직렬화된다(`events.to_json`·`event_from_json`·`command_from_json`) — TUI 와 웹 UI 가 같은 규격을 쓴다. 규격에 UI 의존 필드는 없다.
- 이벤트에 모르는 필드가 오면 `extra` 로 보존, 모르는 줄은 `raw`(`vendor="claude"`) 로 통과하므로 **소비자는 `raw` 를 무시하지 말고 개수를 센다**(카나리아가 `raw` 0 을 요구한다).
- `message.blocks` 중 `shown_as` 가 붙은 블록은 이미 다른 이벤트(`text_delta`·`tool_call`·`tool_result`)로 그렸으니 다시 그리지 않는다.
- `turn_result.cost_delta` 는 재개(`resume`) 세션의 첫 턴에서 `null` 이다(합산 시 None 처리 필요).
- `session_ready` 는 **첫 `send` 뒤에야** 온다. 그 전에는 `capabilities` 를 알 수 없다(`s.adapter.capabilities` 의 값은 `unknown` 가능).

**3. 정책·요청 처리(소비자가 구동한다)**
`policy.decide_request(pol, tool, subscribers=, waited=, is_question=) -> Decision(action allow|wait|deny, by, message, wait_left)`. 세션은 이 함수를 **스스로 부르지 않는다**. 소비자는 `permission_request`/`question_request` 를 받으면 대기 시간을 재서 이 함수를 부르고, `allow`·`deny` 이면 `answer_*` 로 답하며 deny 의 `message` 는 모델이 읽는 문구(`policy.deny_message`)를 그대로 쓴다. 사용자가 거부 이유를 썼으면 `deny_message(kind, user_reason=…)` 로 전달한다. 자동 턴은 `policy.next_auto_turn`.

**4. 종료·정리**: `await h.close_all()`(병렬 4단계 종료)·`h.kill_all()`. 호스트가 비정상 종료한 뒤 다시 뜨면 `h.scan_orphans()` → `host.orphan_guidance(o)` 로 procctl plan 안내를 보인다(죽이지 않는다). `h.cost_summary()`·`h.notices`·`h.purged_logs`·`recorder.read_log(path)`·`recorder.purge_logs`.

**5. 래퍼·sudo**: 실행기가 터미널에서 `sudo-claude-auth` 로 인증한 뒤 `launcher.launch_spec(spec, sudo_ready=True)`. 호스트는 비밀번호를 읽지 않는다. `launcher.sudo_hint(ev)` 는 Session 이 이미 불러 `notice(extra.hint="sudo")` 를 낸다.

## 소비자 책임 (세션·호스트가 하지 않는 것)
1. **bypass 검사**: `SessionHost.start_session` 이 시작 전에 `policy.check_start(spec)` 를 부르고, 사유가 있으면 `StartRefused`(사유 목록 `.reasons`)로 거부한다(어떤 상태도 바꾸기 전, 2026-11-09 연결). 단 `Session` 을 호스트 없이 직접 쓰는 소비자는 여전히 스스로 `check_start` 를 불러야 한다. `--settings` 파일 안의 간접 지정은 읽지 못한다.
2. **대기 상한 구동**: 위 3번처럼 `request_timeout` 에 자동 거부를 보내는 일은 세션이 안 한다(타이머는 소비자 몫).
3. **구독자 수**: 세션은 구독자를 세지 않는다. `decide_request` 의 `subscribers` 는 소비자가 센다.
4. **로그의 민감성**: 이벤트 로그에는 도구 입력·메시지 본문이 있어 비밀·고객 데이터가 섞일 수 있다(0600, 14일). ctx 로 올리지 않는다.
5. **시험 세션의 ctx 흔적**: claude-run 훅은 `--no-session-persistence` 여도 ctx DB 에 행을 남긴다(S8 실측). 시험은 cwd 를 스크래치 아래로 두고, 집계에서 빼는 자동 규칙은 없다(수동 구분).

## 확인 못 함 (S9 시점 갱신, claude 2.1.317~2.1.318)
확인된 것은 각 절 본문과 계획서 §2-2·§2-2b·§5·§7-3 에 있다. 아래는 **아직 근거가 없는 것**이다.
| 항목 | 상태 |
|---|---|
| 서브에이전트가 요청한 권한의 원본 필드 전체 | 도착과 `run`(=Agent 도구 호출 id) 매핑은 S7 에서 실제로 확인(서브의 Bash 요청, 허용 뒤 파일 생김). 원본 줄의 키 목록은 메인 요청과 대조하지 않았다 |
| `system/api_retry` 의 실제 형식 | 한 번도 녹화하지 못함. 합성 줄로만 시험(`notice` warn, 키 이름 추정) |
| 훅 종료 정보(`outcome`·`exit_code`) | 규격 필드가 아니라 `hook.extra` 에 담는다. P5′-3 에서 정식 필드로 올릴지 정한다(규격 v0 변경 후보) |
| 다중 선택 질문 답 형식(`", "` 로 이음)·`free_text` 자리 | 공식 서술 기준, 실측은 단일 선택만(S7 항목 3) |
| bypass 모드에서 `can_use_tool` 이 오는지 | 시험 안 함(계획서 §6-1-5). 그래서 기본 거부 |
| 20분 넘는 권한 대기 | 20분까지만 확인(S0 `hold.log`) |
| `--max-budget-usd` 가 실제로 세션을 끊는 동작 | 인자 전달만 시험, 실제 한도 도달은 안 봄 |
| 브로커의 「인증 만료」 문구가 세션에서 오는 경로 | 합성 문구 단위 시험만. 실물은 「중계가 없음」 경로 1건(S8) |
| 호스트 사망 시 자식 거동의 일반성 | 유휴·진행 중 턴 각 1~2회(S7). 권한 대기 중은 안 해 봄 |
| 많은 세션의 자원 | 4세션 1회, 세션당 RSS 약 245 MiB(S7). `max_sessions=4` 는 임시값(D-9) |
| MCP·계정 커넥터 | 첫 턴 뒤 `mcp` 0→30·`tools` 32→85 로 늘어남(`session_info`)만 봤다. 호출은 안 해 봄 |
| 사용자 스킬의 실제 호출 | 안 해 봄(init 에 목록만) |
| 공식 SDK 경로(D-1 비교) | S0 의 SDK 스파이크는 하지 않았다. 날 줄 프로토콜(`--permission-prompt-tool stdio`)은 비문서 값이라 버전 종속 — Claude Code 갱신 때마다 카나리아(`integration_real.py --items canary`) |
| claude-run 글 모양 의존 | `parse_claude_run` 이 못 읽으면 sudo 없는 세션으로 폴백(시험됨). nix 쪽이 바뀌면 파서 수정이 필요 |
