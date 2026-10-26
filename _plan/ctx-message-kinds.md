# ctx 메시지 종류 분류·표시 — XML 로 감싼 자동 메시지(스킬 호출·작업 알림 등)를 사람 발언과 구분하기 — 계획

상태: **계획(미구현, 사용자 결정 대기 — §5).** 작성 2026-10-26. 이 문서는 무맥락 검증 에이전트를 거치지 않았다. 대상: `mods/_data/claude-ctx/`(`ctxdata.py`·`ctxui.py`·`claude_ctx.py`).

## 0. 읽기 전에 (용어)
| 이름 | 뜻 |
|---|---|
| 자동 메시지 | 사람이 타자로 친 것이 아닌데 `user` 역할·`prompt` 종류로 저장된 메시지. 대개 `<태그>…</태그>` XML 모양으로 시작한다(Claude Code 가 만든다) |
| 종류(kind) | DB `messages.kind`: prompt·response·tool_use·tool_result·meta·other. **`prompt` 안에 자동 메시지가 섞여 있다**(이 문서의 문제) |
| meta | 수집기가 `isMeta` 표지가 있는 줄을 `kind='meta'` 로 따로 저장한 것(`claude_ctx.py:161`). 스킬 본문·시스템 알림 주입 등 |
| 표시 분류 | 이 계획이 새로 정할, 화면·집계용 분류(DB 열이 아니라 읽을 때 계산하는 함수 `classify`) |

## 1. 배경 — 일어난 일 (2026-10-26 실제 DB 를 건수로만 집계, 내용은 열람하지 않음. 140 세션)
- `user`·`prompt` 2,753건 중 **877건(32%)이 `<태그>` 로 시작**한다: `task-notification` 699 · `command-message` 92 · `command-name` 59 · `pasted_content` 16 · `local-command-stdout` 7 · `bash-input` 2 · `bash-stdout` 2. 이 중 17건은 태그 밖에 일반 문장이 함께 있다. 프롬프트 중간에 끼는 경우도 있다(`pasted_content` 4 · `command-name` 2 · `local-command-caveat` 2).
- `meta` 781건은 시작 문구가 `Another Claude…` 376 · `Base directory…`(스킬 본문) 148 · `<local-command…` 60 · `[Image: origin…` 58 · `<system-remind…` 46 · `[Cross-session…` 35.
- 결과로 지금 화면·집계가 어긋난다:
  1. **세션 제목**(첫 프롬프트 앞부분)이 140 세션 중 **59개(42%)** 에서 `<command-message>…` 같은 태그 조각이다(대부분 `/donghans-resume` 등 스킬로 시작한 세션).
  2. **검색 F2 「사용자 발언만」·3 대조 탭(사용자 발언 기준)** 이 `task-notification` 자동 보고를 사용자 말로 센다 — 「내가 그렇게 말했나」 교차검증이 오염된다.
  3. **통계의 「프롬프트 수」·세션당 프롬프트**가 자동 메시지만큼 부풀려진다(`ctxdata.py` 의 `kind='prompt'` 집계 다수).
  4. 대화 화면(SessionScreen)에서 태그 원문이 그대로 길게 보여 읽기 어렵다(작업 알림은 수백 자 XML).

## 2. 결정할 설계 (제안)
### 2.1 분류표 (`classify(role, kind, text)` → 분류·한 줄 요약·본문)
| 분류 | 판별 | 한 줄 요약 | 사람 발언? |
|---|---|---|---|
| 사람 | `prompt` 이고 아래에 해당 없음 | (원문) | 예 |
| 스킬/명령 호출 | `<command-message>`·`<command-name>`(+`<command-args>`) | `/이름 인자` | **예**(사용자가 직접 호출) |
| 작업 알림 | `<task-notification>` | `[작업 <status>] <summary>` (task-id·output-file 은 접힌 본문) | 아니오 |
| 로컬 명령 | `<local-command-stdout>`·`<local-command-caveat>`·`<bash-stdout>` | `[명령 출력]` + 첫 줄 | 아니오 |
| 셸 입력 | `<bash-input>` | `! <명령>` | 예 |
| 붙여넣기 | `<pasted_content>` | 태그를 벗긴 본문 + 「붙여넣음」 배지 | 예(사람이 붙임) |
| 시스템 알림 | `<system-reminder>` | `[시스템 알림]` | 아니오 |
| 주입(meta) | `kind='meta'` | 시작 문구로 세분: 스킬 본문 · 다른 세션 메시지 · 이미지 표지 · 교차 세션 | 아니오 |
| 알 수 없는 태그 | 위 목록에 없는 `<태그>` 로 시작 | 원문 + `<태그>` 배지 | **사람으로 둔다**(오탐으로 사람 말을 숨기지 않으려고) |
- 태그 밖에 일반 문장이 있으면(17건) **분할**한다: 태그 부분은 자동, 나머지는 사람 발언으로 따로 취급.
- 판별은 **엄격한 알려진 태그 집합**으로만 한다(정규식 `^\s*<(task-notification|command-name|…)[ >]`).

### 2.2 DB 는 바꾸지 않는다
- 분류는 **읽을 때 계산**(`ctxdata.classify` 순수 함수 + SQL 쪽은 같은 정의의 `AUTO_PROMPT_RE` 상수 하나). 스키마 열 추가·백필은 하지 않는다(필요해지면 그때 사용자 허가를 받고 한다).
- SQL(집계·제목·`F2` 필터)과 파이썬(`classify`)이 어긋나지 않게 **같은 상수에서 만들고 동치 시험**을 둔다.

### 2.3 표시·집계 변경점
| 곳 | 변경 |
|---|---|
| 대화 화면(SessionScreen) | 자동 메시지는 배지(색)+한 줄 요약으로 **접어서** 보인다. Enter 로 원문 펼침. 키 하나(예 `i`)로 자동 메시지 숨김/표시 토글. 스킬 호출은 `/이름 인자` 로 읽기 쉽게 |
| 세션 제목 | 「첫 **사람** 프롬프트」, 없으면 첫 스킬 호출 요약(`/donghans-resume c9bf7759`) → 59개 제목 정상화 |
| 검색 | F2 「사용자 발언만」은 사람·스킬 호출·셸 입력·붙여넣기만. 결과 행의 일치 열에 분류 배지 |
| 3 대조 | 사용자 발언 기준에서 자동 메시지 제외 |
| 대시보드 통계 | 프롬프트 수는 사람 발언만, 별도로 「자동 N」 열(또는 요약 줄). 세션 표 제목도 위 규칙 |
| `donghans ctx`(CLI) | `search --role user`·`session`·`recent`(first_prompt)·`handoff draft`(`claude_ctx.py` 의 사용자 메시지 수집)도 같은 정의를 쓴다 — LLM 이 자동 보고를 사용자 지시로 읽는 일을 막는다 |
| 제한 모드(LLM) | 요약·제목은 **치환(masker) 후** 텍스트에서 만든다(태그 안에 비밀이 있을 수 있음) |

## 3. 순서·예상 규모
1. `ctxdata.py`: `AUTO_TAGS`·`classify`·`AUTO_PROMPT_RE`·`first_human_title`. 단위 시험(알려진 7종 + meta 4종 + 분할 17건형 + 알 수 없는 태그 + 빈 문자열). 작음.
2. SQL 집계 교체(`prompt` 계수·제목·F2·대조). 중간 — `ctxdata.py` 의 해당 쿼리 약 8곳. 시험 `test_ctxdata.py` 갱신.
3. SessionScreen 접힘·배지·토글. 중간 — `test_ctxui.py` 에 합성 자동 메시지 추가. 촬영 도구(`mods/_data/_uikit/tools`)로 화면 확인(합성 DB 에 자동 메시지 케이스 추가).
4. CLI(`claude_ctx.py`) 쪽 동일 적용 + `donghans-ctx` 스킬·`_docs/content/explanation/claude-ctx.md` 갱신.
5. 실제 DB 로는 **건수·제목 개수 변화만** 검증(내용 비열람): 제목의 `<` 시작 59 → 0, 프롬프트 수 변화.

## 4. 위험·함정
- 알려진 태그 집합이 Claude Code 버전에 따라 늘어난다 → 모르는 태그는 사람으로 두고 배지만 붙이므로 안전 쪽으로 실패한다. 새 태그가 많이 보이면 집합에 추가.
- 사람이 코드나 XML 예시를 붙여 넣은 메시지가 알려진 태그로 시작하면(예: 사용자가 `<task-notification>` 문서를 붙임) 자동으로 오분류될 수 있다 — 드물고, 펼치면 원문이 보인다.
- SQL 과 파이썬 정의가 갈라지는 것이 가장 큰 위험 → 단일 상수 + 동치 시험(§2.2).
- 세션 제목 규칙이 바뀌면 `usageui`·`donghans ctx recent` 등 제목을 쓰는 곳의 표시가 달라진다(의도된 변화).

## 5. 열린 결정 (추천 답 — 모두 에이전트 제안)
1. 자동 메시지를 **숨김 vs 접힌 한 줄**로 둘지 → 추천: 접힌 한 줄이 기본, 키로 숨김.
2. 통계 프롬프트 수에서 자동 메시지 제외 → 추천: 제외하고 「자동 N」 따로 표시.
3. 분류를 읽기 시점 함수로 둘지 DB 열+백필로 할지 → 추천: 함수(먼저), 성능 문제가 보이면 열.
4. 슬래시 명령 호출을 「사람 발언」에 포함할지 → 추천: 포함(사용자가 직접 호출), 단 화면에는 `/이름` 으로.
5. 범위: ctxui 만 vs `donghans ctx` CLI·handoff draft 까지 → 추천: 같은 정의를 공유하도록 함께(LLM 오독 방지가 CLI 쪽에서 더 중요).
