# claude-ctx — Claude 공유 컨텍스트 저장소

여러 머신(데스크톱·노트북)·프로젝트에서 Claude Code 로 한 대화·사용량을 Postgres 한 곳에 모아 조회한다. handoff/resume 도 이 저장소를 따라간다.

## 구성
| 부분 | 위치 | 역할 |
|---|---|---|
| 서버 | `mods/sys/services/claude-ctx.nix` (호스트 toml 에 `claude-ctx = true`) | Postgres 17 + pgvector, DB `claude_ctx`, 역할 `claude_ctx`. localhost 와 tailnet(100.64.0.0/10) 에서만 scram 비밀번호로 접속 |
| 스키마 | `mods/_data/claude-ctx/schema.sql` | 멱등. 서비스 `claude-ctx-schema` 가 적용 |
| 클라이언트 | `mods/_data/claude-ctx/claude_ctx.py` → `donghans` 명령 (`donghans ctx …`, `donghans handoff put|get`) (`mods/devel/apps/llm-cli.nix`) | 훅 적재 · 백필 · 조회 · handoff 업/다운 |
| 훅 | 같은 파일의 `claude` 래퍼가 `--settings` 로 주입 | UserPromptSubmit/Stop/SubagentStop/SessionStart/SessionEnd/PreCompact (async) |
| 안전망 | user 타이머 `claude-ctx-ingest` (10분) | 훅이 놓친 것을 오프셋 기준으로 따라잡음 |

## 새 머신 연결
nix 만으로 끝난다 — **비밀번호도 dsn 파일도 없다.**
1. 서버 머신(beelink-ser7-co)은 unix 소켓 peer 인증이라 아무 설정이 없다.
2. 원격 머신(노트북 등): `mods/sys/services/claude-ctx.nix` 의 `allowedClients` 에 그 기기의 tailnet IP 를 넣고 서버를 `nixup`, 클라이언트 머신은 `nixup`. 클라이언트는 MagicDNS 이름 `beelink-ser7-co:5432` 로 붙고, 서버가 출발지 IP 로 허용 여부를 판단한다(trust).
3. **과거 대화를 일괄 이전하지 않는다.** 지금부터 쌓이는 대화만 올라가고(훅 + 10분 타이머, 최근 2일 활동 파일), 옛 세션은 `claude --resume` 으로 들어가 그 세션에서 handoff(→ 그 세션의 대화가 그때 적재됨)하는 방식으로 필요한 것만 끌어온다. 전체 백필이 필요하면 `donghans ctx ingest --days N` 을 명시적으로 실행.
- 신뢰 모델: tailnet 출발지 IP(WireGuard 인증) + 방화벽의 tailscale0 외 차단. 남는 위험은 허용된 기기 안의 다른 프로그램. 이를 받아들이지 않으면 pg_hba 의 `trust` 를 `scram-sha-256` 으로 바꾸고 비밀번호를 설정해야 한다(그때는 비밀 파일이 생긴다).

## 다른 서버로 이관 (클라우드·온프레미스)
`pg_dump claude_ctx` → 새 서버에 `psql` 복원 → 클라이언트의 서버 이름(`CLAUDE_CTX_SERVER`, 기본 beelink-ser7-co)만 교체. 서버 호스트의 `claude-ctx` 모드(toml)를 끄면 된다.

## 멱등성 (여러 머신이 올려도 안 깨지는 이유)
- 자연키 `ON CONFLICT DO NOTHING`: 메시지 uuid · 사용 요청 request_id · 훅 (host,session,event,payload md5).
- 파일 수집은 (host,path) 어드바이저리 락 + 오프셋 갱신을 같은 트랜잭션에서 → 훅·타이머·수동 백필이 겹쳐도 한 번만.
- 세션은 `hosts[]` 에 관측 머신을 누적, first/last 는 least/greatest. `claude --resume` 이 옛 메시지를 같은 uuid 로 복사해도 중복 행이 안 생긴다.
- **토큰·비용 합계는 `usage_events`(요청 단위)로만** 센다. `messages` 의 토큰을 합치면 resume/fork 로 복사된 만큼 이중 계산된다.
- 한계: 같은 한도 샘플(`limit_samples`)은 머신별 행이라 계정 공통 값이 머신마다 따로 쌓인다(의도). 머신 시계가 어긋나면 ts 비교가 어긋난다.

## 접속 허용 목록 · 백업 · 초안
- **허용 목록:** `claude-ctx.nix` 의 `allowedClients` (tailnet IP, trust). 새 기기는 IP 를 추가한다. headscale 이 IP 를 재할당하면 그 기기는 접속이 막힌다(fail-closed).
- **백업:** 매일 03:30 `pg_dump`(zstd) → `/var/backup/postgresql/claude_ctx.sql.zstd` (최신 1개만, 같은 디스크). Claude Code 가 오래된 로컬 트랜스크립트를 정리하면 이 DB 가 옛 대화의 유일한 사본이 된다.
- **초안:** `donghans handoff draft --session <ID> [--focus "…"] [--model haiku] [--dry-run]` — DB 의 사용자 발언·최근 응답만 작은 모델이 읽고 `.claude/handoffs/DRAFT-<ID>.md` 를 만든다(예: 사용자 발언 6개·약 3천 토큰 입력, 74초). 검증 전 자료이므로 본 세션이 사실 칸을 확인하고 보강한다.

## 머신이 바뀔 때 (SSD 교체·노트북 추가·재설치)
- 수집 위치는 `(hostname#machine-id 해시, 파일 경로)` 로 관리한다. 같은 hostname 의 다른 물리 머신이 오프셋을 공유해 데이터를 건너뛰는 것을 막기 위함. OS 재설치로 machine-id 가 바뀌면 처음부터 다시 읽지만 uuid/request_id 중복 방지로 행이 늘지 않는다.
- 세션·메시지 ID 는 전역 고유라 머신 간 충돌이 없다. `~/.claude` 를 복원·복사해도 같은 uuid 는 건너뛴다.

## 알려진 한계 / 주의
- 기록에 고객사 데이터·시크릿·개인정보가 섞인다 → tailnet 안에서만, 클라우드 이관 전에 걸러내기 단계를 추가할 것. 백업은 아직 없음(pg_dump 타이머 필요).
- 원본 한 줄이 100KB 를 넘으면 `raw` 는 잘려 저장된다(`raw->>'truncated'`); 정본은 각 머신의 트랜스크립트.
- 훅은 `claude` 셸 래퍼로 띄운 세션에만 걸린다(VSCode 확장 등은 타이머 백필만). `claude -p` 에서는 Stop 훅이 기록되지 않았다(SessionEnd 로 보충됨).

## 비밀번호 관리 (2026-10-23) — 등록표 · 출력 치환 · 주입 래퍼 · 후보 탐지 · 로컬 치환 · ctxui
**목적**: Claude 등이 ctx 를 불러갈 때 비밀번호·토큰·키가 대화에 실려 나가지 않게 하고(출력 치환), 비밀이 필요한 명령은 값을 대화에 적지 않고 실행하게 한다(주입 래퍼).
**사용자 결정**: ① 등록표는 ctx DB(Postgres)에 **평문 저장** — DB 는 허용된 tailnet 기기만 접속하는 설계이고, 분산된 비밀 키 관리의 복잡도를 늘리지 않는다. ② DB 원문(messages·hook_events)은 **바꾸지 않는다**. ③ 이미 DB 에 적재된 **로컬** 트랜스크립트 사본만 치환한다. ④ 기존 데이터 일괄 치환은 별도 명령(`scrub`).

| 부분 | 위치 | 역할 |
|---|---|---|
| 핵심 | `mods/_data/claude-ctx/ctx_secrets.py` | 등록표 DDL·치환 엔진(`Masker`)·후보 탐지(`PATTERNS`)·주입 래퍼(`run_masked`)·jsonl 치환(`scrub_bytes`/`scrub_local`). DB 없이 시험 가능한 순수 함수 중심 |
| 명령 | `claude_ctx.py` 의 `donghans secret …` | `add`(숨겨 입력, `--stdin`) · `list` · `rm/enable/disable` · `show`(TTY) · `run` · `scan` · `adopt` · `ignore` · `scrub` |
| 치환 지점 | `ctx search/recent/session/sql` · `handoff get/draft` | 출력 직전에 치환. `--raw` 는 TTY + `CLAUDECODE` 없음일 때만 |
| 조회 계층 | `ctxdata.py` | 개요 집계 · 검색 · 저장소별 발언 대조 · 세션 맥락 · 비밀·후보 관리(화면과 분리) |
| 화면 | `ctxui.py` (`ctxui` 명령, Textual) | 1 개요(저장소별 개수·용량·DB 크기) · 2 검색(키워드/정규식·저장소·기간·역할) · 3 대조(같은 문구를 저장소별로 묶어 「내가 그렇게 말했나」) · 4 비밀(추가·끄기·삭제·값 보기) · 5 후보(승인·무시) |
| 스키마 | `schema.sql` 의 `secrets` · `secret_ignores` (v2) | `ctx_secrets.SCHEMA_STATEMENTS` 와 같은 DDL(시험이 확인). 클라이언트도 쓰기 전에 `CREATE TABLE IF NOT EXISTS` 로 보장 |
| 자동화 | `claude-ctx-ingest` 서비스의 `ExecStartPost` | 10분마다 `secret scrub --apply --quiet --idle-min 180`. 등록표가 비면 아무 일도 안 한다 |
| 시험 | `claude-ctx/tests/` (`mods/_data/run-tests.sh` 에 등록) | `test_secrets`(순수) · `test_ctx_db`(임시 Postgres 통합) · `test_ctxdata` · `test_ctxui`(Pilot) |

### 치환이 걸리는 곳과 규칙
- 치환 형식은 `[protected]`. literal 은 값 그대로 **와 JSON 이스케이프 형태**(따옴표·역슬래시·`\uXXXX`)를, regex 는 패턴을 가린다. 값 4자 미만은 등록을 거부한다(일반 단어까지 지워지므로; `--force`).
- **치환한 뒤에 자른다**: 스니펫·1500자 절단·300자 셀 절단 모두 치환 후에 한다(경계에서 잘린 비밀 조각이 남지 않게).
- 검색어에 등록된 비밀이 들어 있으면 검색 자체를 거부한다(결과 유무로 존재 여부가 드러나므로).
- 등록표(`secrets`) 를 직접 SQL 로 읽는 것은 사람(TTY)만 된다.
- 표가 아직 없는 DB(마이그레이션 전)에서도 조회 명령은 치환 없이 동작한다.

### 주입 래퍼 `donghans secret run`
`donghans secret run [--env A,B] -- 명령 인자…` — 인자의 `{{secret:이름}}` 은 실행 직전에 값으로, `{{secret-file:이름}}` 은 0600 임시 파일(`$XDG_RUNTIME_DIR`, 실행 후 삭제)로 바뀐다. 환경변수는 `--env` 로 지정한 것만(최소 권한). 하위 프로세스 출력은 줄 단위 치환, 종료 코드 전달. 한계: 값이 줄바꿈을 포함하면 줄 단위 치환에 안 걸린다(여러 줄 키는 `{{secret-file:…}}` 로 쓰고 출력에 찍지 않는다).

### 후보 탐지 `donghans secret scan`
전체 메시지(`messages.text`)를 서버 측 커서로 훑어 패턴(Anthropic·OpenAI·GitHub·AWS·Slack·Google 키, JWT, 개인키 블록, URL 안 비밀번호, `password=`·`token=` 류, 한국어 「비밀번호는 …」)에 맞는 값을 모은다. 후보는 **흐린 미리보기**(`Pa…(9자)`)와 fp(값의 sha1 앞 10자)로만 보이고, 사람이 `adopt <fp> <이름>` 으로 승인하거나 `ignore <fp>` 로 숨긴다. 키워드형 패턴은 오탐 필터가 있다: 자리표시자(`changeme`·`${X}`·`<…>`), 경로·URL·코드 호출·코드 참조(`process.env.X`), snake_case 식별자, 한 종류 문자만으로 된 값 제외. 실제 데이터(약 7.7만 메시지)에서 91 → 53개로 줄었고 나머지는 사람이 판단한다(예: 데모용 공용 비밀번호는 `ignore`).

### 로컬 트랜스크립트 치환 `donghans secret scrub`
- 대상은 `~/.claude/projects/**/*.jsonl`(서브에이전트 포함). **DB 에 다 적재된 파일**만 바꾼다: 적용 전에 그 파일을 먼저 적재하고, `ingest_state` 의 오프셋이 파일 크기와 같을 때만 진행한다.
- **오프셋을 같이 갱신한다.** 치환하면 파일 길이가 달라지므로 같은 트랜잭션에서 `byte_offset` 을 새 크기로 맞춘다(안 맞추면 다음 적재가 줄 중간에서 시작해 줄을 잃는다). 수정 시각은 보존한다(`--days` 선별에 영향 없음).
- 진행 중인 세션을 건드리지 않는다: 최근 `--idle-min`(기본 60, 타이머는 180)분 안에 수정된 파일은 건너뛰고, 읽은 뒤 쓰기 전에 파일이 바뀌었으면 포기한다. 줄마다 JSON 으로 다시 읽혀야만 적용하고 아니면 그 줄은 그대로 둔다(`skipped`).
- 점검 캐시: `~/.local/state/claude-ctx/scrub-state.json` 에 (수정 시각, 크기, **등록표 해시**)를 기록해, 같은 등록표로 이미 본 안 바뀐 파일은 읽지 않는다(트랜스크립트가 1.6GB). 등록표가 바뀌면 해시가 달라져 전체를 다시 본다. `--no-cache` 로 강제 점검.
- 기본은 **dry-run**(`--apply` 로 적용). 원문은 DB(`messages.raw`·`text`)에 있다.
- 끄기: `claude-ctx-ingest` 서비스의 `ExecStartPost` 줄을 `mods/devel/apps/llm-cli.nix` 에서 지운다. `history.jsonl`·`file-history` 등 다른 `.claude` 파일은 아직 대상이 아니다.

### 한계 (정직하게)
- 치환은 **`donghans` 경로**에서만 걸린다. `psql` 등으로 DB 에 직접 붙거나 `~/.claude/projects` 의 치환 전 파일을 읽는 것은 막지 못한다. `ctx sql` 에서 `substring()` 으로 조각을 빼내는 것도 완전히 막을 수 없다(`secrets` 표 직접 조회만 막음). 설계상 ctx DB 는 허용된 tailnet 기기에 열려 있다(사용자 결정).
- 이미 대화에 입력된 값, 사용자가 프롬프트에 직접 적은 값은 그 순간 transcript 에 남는다 — 이 도구는 **앞으로의 노출과 로컬 사본**을 줄인다. 실서비스 비밀이 노출됐다면 교체가 정답이다.
- 등록표가 평문이라 `pg_dump` 에 비밀이 그대로 들어간다(이관·백업 시 주의).
- 후보 탐지는 휴리스틱이다(놓침과 오탐 모두 있다). 문장 중간의 평범한 비밀번호(`제 비번은 abc 입니다`)는 못 잡는다.

### 쓰는 법
```bash
donghans secret add NAS_PW            # 터미널에서 숨겨 입력(평문 저장, 대화에 안 남음)
donghans secret list                  # 이름·길이·fp 만(값 없음)
donghans secret scan                  # 후보(흐린 미리보기) → adopt <fp> <이름> / ignore <fp>
donghans secret run -- curl -u me:{{secret:NAS_PW}} https://nas.local   # 값은 실행 직전에만, 출력은 치환
donghans secret scrub                 # 로컬 트랜스크립트 점검(dry-run) → --apply
ctxui                                 # 개요·검색·대조·비밀·후보 화면(사람 전용)
```
