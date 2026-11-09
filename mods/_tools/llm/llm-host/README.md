# llm-host — LLM 세션 호스트 코어 (규격 v0)

설계 근거: ctx 문서 `plan llm-trust/11-p5prime-2-session-host` (읽기: `donghans ctx doc read plan llm-trust/11-p5prime-2-session-host --project nixos`). 이 폴더는 단계 S1 까지만 있다(규격 `events.py`). 어댑터·세션·정책 등은 계획서 §9 의 뒤 단계에서 추가된다.
시험: `mods/_tools/llm/llm-host/tests/test_events.py` (직접 실행: `cd mods/_tools/llm/llm-host && python3 -I tests/test_events.py`; `mods/_tools/run-tests.sh` 에는 아직 등록하지 않았다 — 기존 파일 수정이라 별도 단계).

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
