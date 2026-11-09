# llm-host — LLM 세션 호스트 코어 (규격 v0)

설계 근거: ctx 문서 `plan llm-trust/11-p5prime-2-session-host` (읽기: `donghans ctx doc read plan llm-trust/11-p5prime-2-session-host --project nixos`). 이 폴더는 단계 S3 까지 있다(규격 `events.py`, 어댑터 인터페이스 `adapter.py`, claude 어댑터 `claude_adapter.py` 의 읽기 `decode` 와 쓰기 `argv`·`env`·`encode`, 세션 `session.py`, 시험용 가짜 백엔드 `fake_claude.py`). 정책·다중 세션·기록 등은 계획서 §9 의 뒤 단계에서 추가된다.
시험: `tests/test_events.py`(규격)·`tests/test_claude_adapter.py`(어댑터 읽기; 녹화본 `tests/fixtures/` 전체 재생). 직접 실행: `cd mods/_tools/llm/llm-host && python3 -I tests/test_claude_adapter.py`. `tests/test_session.py`(세션·가짜 백엔드·어댑터 쓰기; 비용 0). `mods/_tools/run-tests.sh` 에 `llm-host-ev`·`llm-host-claude`·`llm-host-session` 으로 등록돼 있다.

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
- 아직 없는 것(뒤 단계): 정책을 세션에 연결해 대기 상한 시각에 자동 거부를 실제로 보내는 일(host.py·S5; S4 는 순수 함수만), 다중 세션·상한·고아 레지스트리(S5), 이벤트 로그(S6).

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
