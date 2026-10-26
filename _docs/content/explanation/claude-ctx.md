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
- **계정별 한도(2026-10-23~)**: 한도 %는 계정 단위인데 상태줄 입력에 계정이 없어, 상태줄 스크립트(`claude-usage-statusline`)가 `~/.claude.json`(`CLAUDE_CONFIG_DIR` 우선)의 `oauthAccount` 에서 `accountUuid`·이메일·플랜(`userRateLimitTier`, 없으면 `seatTier`)을 읽어 `limit_samples`(`account_id`·`account_email`·`account_plan`)에 같이 남긴다. 5h·7d 창의 리셋 시각(`*_resets_at`)도 저장해 창마다 최고 %를 낸다(`donghans ctx limits`, ctxui 대시보드 상단 그래프 — 색 = 계정). **그 이전 행은 계정·리셋 시각이 NULL** 이라 집계에서 빠진다(계정을 사후에 알 수 없음). 계정 전환 직후 상태줄이 갱신되기 전 샘플은 이전 계정으로 찍힐 수 있다.

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

## 프로젝트별 지침 공유 (2026-10-23) — `donghans instr`

**동기**: 프로젝트별 지침(`.claude/donghans-instructions.md`·`donghans-override.md`, `.git/info/exclude` 로 추적 제외)이 그 컴퓨터 디스크에만 있어 다른 기기·재설치 후에는 사라졌다.

**구조**: 정본 = DB 표 `project_instructions(repo_url, name, body, rev, updated_host, updated_at)`(PK `repo_url+name`, `repo_url` 은 `norm_repo` 정규화 — 워크트리·다른 기기가 같은 키). 로컬 파일은 **캐시**다. `claude` 래퍼가 `--settings` 로 주입하는 훅 중 `SessionStart` 가 `donghans ctx hook SessionStart` → `ctx_instr.sync` 를 돌려 파일을 맞춘다 — 그래서 읽는 쪽(`donghans-resume`·`donghans-qa`)은 같은 경로의 파일을 읽는 그대로이고, 훅이 못 돈 세션(래퍼 없이 시작)을 위해 두 스크립트도 시작 때 `donghans instr sync --quiet` 를 한 번 부른다(접속 실패는 조용히 로컬 파일 사용).

**동기화 규칙**(`ctx_instr.plan` 판정표 · 마지막 동기화 상태 rev·sha 는 `.claude/.donghans-instr-state.json`):

| 로컬 | DB | 결과 |
|---|---|---|
| 없음 | 있음 | DB 본문으로 파일 생성 + `.git/info/exclude` 보정 |
| 있음 | 없음 | **첫 채택** — DB 에 올림(rev 1). 덮을 것이 없다 |
| 손대지 않음(상태 sha 일치) | 더 새로움 | DB 로 갱신 |
| 고침 | 그대로(rev 일치) | **앞섬** — 알림만. 훅은 절대 올리지 않는다(`donghans instr push` 로 명시) |
| 고침 | 바뀜 · 또는 상태 기록 없는 기존 파일이 DB 와 다름 | **충돌** — 어느 쪽도 안 덮는다. `diff` 후 `push --force`/`pull --force` |

**안전장치**: 올릴 때 본문에 등록된 비밀 값이 있으면 거부(`secrets` 등록표) · 올리기는 `WHERE rev = 읽은 값` 낙관적 잠금(다른 기기가 먼저 바꿨으면 거부) · 실행 파일(`qa-extra`·`resume-extra`)은 동기화하지 않는다(DB 에서 받은 코드를 실행하게 되므로) · 훅은 프롬프트에 **본문을 주입하지 않고**, 파일이 바뀌었거나 앞섬·충돌일 때만 한 줄 알림을 `additionalContext` 로 낸다 · 훅 실패는 입력을 막지 않는다(기존 규칙).

**시험**: `claude-ctx/tests/test_instr.py` — 판정표 9행 · 워크트리 루트 · exclude 멱등 · 두 기기 시나리오(채택→갱신→앞섬→충돌→강제) · 비밀 거부 · 낙관적 잠금 · 훅 end-to-end. 변이(앞섬을 덮어쓰기로 / 비밀 검사 제거)로 시험이 실제로 실패함을 확인했다. **한계**: 실제 `beelink-ser7-co` DB 에서의 실행은 스키마 적용(`nixup`) 뒤 한 번 확인해야 한다.

### 명령 경유 — 읽을 때 최신화, 쓸 때 DB 먼저 (2026-10-23, 사용자 결정)

**동기**: 위 동기화는 세션 시작 때 한 번이라, 오래 열린 세션이나 훅이 안 도는 세션은 낡은 파일을 읽었다. 또 로컬 파일을 사람·에이전트가 직접 고칠 수 있어 정본이 잠깐 둘이 되고(앞섬·충돌), 그 판정표가 복잡함의 원인이었다. 그래서 **파일을 읽고 쓰는 길을 명령 하나로 모은다**.

| 하는 일 | 명령 | 동작 |
|---|---|---|
| 읽기 | `donghans instr show [이름] [--section 절]` | **먼저 sync(최신화)** 한 뒤 출력. DB 접속 실패면 캐시를 「⚠ 낡았을 수 있음」 표시와 함께 출력(읽히긴 한다). `instructions` 는 머리말 + 제목에 `--section` 말이 든 절만, 나머지는 「생략된 절」로 안내; `override` 는 늘 전체 |
| 쓰기(사람) | `donghans instr edit <이름>` | 최신본을 `$VISUAL`·`$EDITOR`·vi 로 열고, 바뀌었으면 **읽은 rev 기준**으로 DB 에 먼저 올리고 캐시를 맞춘다(TTY 가 아니면 거부) |
| 읽기·쓰기(cwd 무관) | `donghans instr show\|set\|edit … --repo <URL>` | 로컬 캐시 없이 **공유 정본(DB)만** 대상 — git 저장소 밖에서도, 다른 저장소의 지침도 다룬다(`ci.set_body(main=None)`: 캐시·상태를 건드리지 않고 낙관적 잠금·비밀·빈 본문 거부는 그대로; 캐시는 다음 `instr show`·세션 시작 동기화가 맞춘다). `push`/`pull`/`sync`/`diff` 는 로컬 파일이 필요해 `--repo` 가 없다 |
| 쓰기(사람, 화면) | `ctxui` 6 지침 탭 | 모든 저장소의 지침 목록(저장소·이름·rev·수정 머신·길이) → Enter 본문(`## ` 절 목록, 비밀 치환 `m`) → `e` 로 편집기(`$VISUAL`·`$EDITOR`·vi, 임시 파일 0600)를 열고 바뀌었으면 **연 시점의 rev 기준**으로 DB 에 저장. 낡은 rev·비밀·빈 본문은 사유를 알리고 저장하지 않는다. 지침 행 삭제·새 저장소 만들기·캐시와의 diff 는 없다 |
| 쓰기(에이전트) | `donghans instr get <이름>` → 고침 → `donghans instr set <이름> --file F [--expect-rev N]` | DB 에 낙관적 잠금으로 먼저 쓰고 캐시·상태를 맞춘다. `--expect-rev` 가 낡았으면 거부(최신본에서 다시 고친다). 비밀 값·빈 본문은 거부 |

**캐시 잠금**: 동기화·`set`·`push` 로 DB 와 같아진 파일은 `chmod 0444`(읽기 전용). **강제가 아니라 보조 장치**다 — 사용자가 `chmod u+w` 하거나 `sed -i`(임시 파일 교체) 같은 우회로 고치면 막지 못하고, 그때는 기존 판정표가 `ahead`/`conflict` 로 잡아 덮지 않는다(그래서 `plan`·`push`·`pull` 은 안전망으로 남긴다). 읽기 쪽도 파일을 직접 `cat` 하면 최신화되지 않는다 — 스킬과 스크립트가 `instr show` 를 부르도록 해 두었다.

**읽는 쪽 변경**: `context.py`(QA)는 「QA 할 때」, `resume.py` 는 「resume 할 때」, handoff 스킬은 「handoff 할 때」 절만 `show` 로 읽는다. 이전에는 파일 전체를 출력했다(ToT 지침은 약 13KB, 변경 이력 절 포함 — 세션 시작마다 불필요한 토큰). **생략된 절의 제목은 항상 보이므로** 수정 세션용 절처럼 필요한 것은 `instr show` 로 전체를 보면 된다. `donghans` 명령을 못 쓰면(옛 버전·PATH 없음) 파일을 직접 읽고 「낡았을 수 있음」을 표시한다.

**왜 handoff 에 따로 sync 를 넣지 않았나**: handoff 는 세션을 닫는 시점의 작업이라 지침이 중간에 바뀌면 오히려 혼란스럽다. 대신 읽기를 `show` 로 통일해 읽는 순간에 최신이 되게 했다.

**시험**: `test_instr.py` 55건 — 절 나누기·고르기(순수), 캐시 잠금, `set` 의 낙관적 잠금·거부 3종(낡은 rev·비밀·빈 본문), 다른 기기가 올린 최신본이 잠긴 캐시에도 반영, 우회 편집이 앞섬으로 잡힘, CLI `set`/`show`/접속 실패 `show`/비대화 `edit` 거부. 잠금 코드를 끄면 3건이 실패함을 확인했다(변이 검사). **ctxui 지침 탭·`--repo`**: `test_instr` 72건(`main=None` 4종 거부·캐시 불변, CLI `--repo` 를 git 밖에서), `test_ctxdata` 질의 함수, `test_ctxui` 화면 시나리오(가짜 편집기 실행 파일로 저장·무변경·낡은 rev·비밀·빈 본문·임시 파일 0600). 변이 검사로 낙관적 잠금 제거(여러 시험 실패)·ctxui 가 `expect_rev` 를 안 넘김(화면 시험 실패)·치환기 무시(시험 2곳 실패)를 확인했다. **미검증**: 실제 에디터(vi 등)를 `App.suspend()` 로 띄우는 실사용(시험은 `suspend` 를 빈 컨텍스트로 대체). **미검증(이전)**: 실제 에디터를 띄우는 `edit` 의 대화형 경로(시험은 비대화 거부만), Claude Code 의 Edit 도구가 0444 파일에 쓰려 할 때의 실제 오류 문구.
**주의(운영)**: 작업 트리를 여러 세션이 공유하면 한 세션의 `nixup` 이 다른 세션의 미커밋 변경까지 배포한다(이 변경도 개발 중에 다른 세션의 `nixup` 으로 먼저 배포됐다). 이 저장소의 CLAUDE.md 「배포 방식」은 이를 전제하지 않는다.

## 비밀번호 관리 (2026-10-23) — 등록표 · 출력 치환 · 주입 래퍼 · 후보 탐지 · 로컬 치환 · ctxui
**목적**: Claude 등이 ctx 를 불러갈 때 비밀번호·토큰·키가 대화에 실려 나가지 않게 하고(출력 치환), 비밀이 필요한 명령은 값을 대화에 적지 않고 실행하게 한다(주입 래퍼).
**사용자 결정**: ① 등록표는 ctx DB(Postgres)에 **평문 저장** — DB 는 허용된 tailnet 기기만 접속하는 설계이고, 분산된 비밀 키 관리의 복잡도를 늘리지 않는다. ② DB 원문(messages·hook_events)은 **바꾸지 않는다**. ③ 이미 DB 에 적재된 **로컬** 트랜스크립트 사본만 치환한다. ④ 기존 데이터 일괄 치환은 별도 명령(`scrub`).

| 부분 | 위치 | 역할 |
|---|---|---|
| 핵심 | `mods/_data/claude-ctx/ctx_secrets.py` | 등록표 DDL·치환 엔진(`Masker`)·후보 탐지(`PATTERNS`)·주입 래퍼(`run_masked`)·jsonl 치환(`scrub_bytes`/`scrub_local`). DB 없이 시험 가능한 순수 함수 중심 |
| 명령 | `claude_ctx.py` 의 `donghans secret …` | `add`(숨겨 입력, `--stdin`) · `list` · `rm/enable/disable` · `show`(TTY) · `run` · `scan` · `adopt` · `ignore` · `scrub` |
| 치환 지점 | `ctx search/recent/session/sql` · `handoff get/draft` | 출력 직전에 치환. `--raw` 는 TTY + `CLAUDECODE` 없음일 때만 |
| 조회 계층 | `ctxdata.py` | 개요 집계 · 검색 · 저장소별 발언 대조 · 세션 맥락 · 비밀·후보 관리(화면과 분리) |
| 화면 | `ctxui.py` (`ctxui` 명령, Textual) | 1 대시보드(저장소별 개수·용량·DB 크기 + 한도·통계, 아래 「ctxui 통계·대화 보기」) · 2 검색(세션 기준 목록 — 전체 대화에서 찾아 세션으로 묶음, Space 로 일치 메시지 펼침·F6 제목만, 키워드/정규식·저장소·기간·역할) · 3 대조(같은 문구를 저장소별로 묶어 「내가 그렇게 말했나」) · 4 비밀(추가·끄기·삭제·값 보기) · 5 후보(승인·무시) · 6 지침(아래 「명령 경유」) |
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

### ctxui 통계·대화 보기 (2026-10-23)
- **1 대시보드의 통계 칸**(개요 위에서 아래로: 합계·표별 용량 → 저장소별 표 + 한도 그래프 → 추이 + 분류별 → 세션 통계 + 세션 표): 추이·분류별은 기간별 토큰·비용 추이(단위 시간/일/주/월)와 분류별 합계(모델·저장소·머신·출처·effort), 아래 두 칸은 세션 통계(세션·프롬프트·도구 수, 세션당 평균·**중앙값**, 시간대·요일 분포)와 세션 표. 저장소·머신·모델은 부분 일치 입력, 기간은 `p`(전체/1/7/30일), 단위 `b`, 분류 `g`, 세션 정렬 `o`, 필터 지움 `c`. 필터는 네 칸에 함께 걸린다.
- **비용은 `usage_events` 로만 센다**(messages 의 usage 는 resume/fork 로 이중 계산 — schema.sql 주석). `usage_events` 는 OTel 수집을 켠 시점(2026-10-22)부터만 있어서 그 이전 세션은 비용이 `-` 이다. 상태줄에 「비용은 MM-DD 이후만 수집됨」을 표시한다. 일·시간 경계는 DB 쪽에서 로컬 시간대(`/etc/localtime`)로 자른다.
- **세션 길이는 평균과 중앙값이 크게 다르다**(실측: 중앙값 약 5분, 평균 약 10시간 — resume 으로 이어진 세션이 평균을 끌어올림). 화면에 둘 다 보인다. 세션 78개 중 39개는 프롬프트가 1개뿐이다.
- **대화 보기(SessionScreen)를 다시 만든 이유**(실측): 이전엔 한 메시지를 1800자에서 잘라 프롬프트 16%(264/1630)·응답 약 7%를 끝까지 읽을 수 없었고, 검색어 강조·세션 제목·이어진 세션 이동이 없었다. 지금은 메시지 단위 이동(↑↓)·펼침(Enter, `f` 전체)·검색어 강조와 `n/N` 이동(접힌 뒷부분에 있으면 자동 펼침)·`y` 복사·`t` 도구 호출/결과·`s` 서브에이전트(기본 숨김, 찾은 대상이 서브에이전트면 자동 표시)·`[`/`]` resume 으로 이어진 앞/뒤 세션. 한 번에 그리는 메시지는 600개까지(`a` 로 전부).
- **추가 메타데이터는 스키마를 바꾸지 않고 질의로 만든다**: 세션 제목 = 첫 사용자 프롬프트(`slug` 는 6개 세션에만 있고 무작위 이름이라 제목으로 부적합), 세션 연결 = 메시지 `parent_uuid` 가 다른 세션의 메시지를 가리키는지(실측 9개 세션이 연결됨), 턴 소요 시간 = `raw->>'durationMs'`(`turn_duration`), compact 횟수 = `compact_boundary`, 도구 사용 = tool_use 텍스트 앞머리 `[tool_use 이름]`. 공유 DB 의 ALTER 는 하지 않았다 — 느려지면(현재 전체 집계 0.3초) `sessions` 에 title·parent 열을 두는 것을 검토.
- **제한 모드(2026-10-26)**: `ctxui` 는 TTY 가 없으면 실행하지 않고, **LLM 세션이 실행하면(환경 표식) 제한 모드**로 뜬다 — 모든 탭을 볼 수 있되 비밀 값은 추출·조회할 수 없다. 화면의 모든 텍스트(검색 결과·대화 화면·대조·통계·지침)는 등록한 비밀 + **비밀처럼 보이는 문자열**(키 형식·`password=`·한글 「비밀번호는 …」, `StrictMasker`)을 `[protected]` 로 치환하고(끌 수 없음), 후보 표의 미리보기도 `[protected] (N자)` 이며, 값 보기(v)·비밀 추가·삭제·끄기·후보 무시(보호를 약하게 하거나 값을 드러내는 동작)·지침 편집은 막는다. 후보 승인(Enter)은 값을 보여 주지 않고 등록만 하므로 허용한다. 막힌 동작은 푸터·도움말에서도 숨긴다. 이전에는 LLM 세션이 실행하면 앱 전체를 거부했다(화면을 검증할 수 없었음).
- **화면 점검에서 고친 것(2026-10-26)**: ①DataTable 문자열 셀의 `[protected]`·`[대괄호]` 가 Rich 마크업으로 해석돼 화면에서 사라지던 것 → 사용자 텍스트는 `Text` 로(시험 `risky_cells`) ②탭 이동 때 `action_tab` 과 `TabActivated` 가 둘 다 로드해 후보 탐지·통계가 두 번 돌고 알림이 겹치던 것 ③통계·지침 탭에서 표에 포커스가 없어 Enter·↑↓ 가 동작하지 않던 것 ④대화 화면이 열릴 때 세션 **전체**를 치환하던 것 → 보일 창만 치환(`session_rows`; 검색 결과는 메시지 하나하나지만 Enter 는 그 세션을 열고 화면에는 최대 `MSG_MAX`=600개만 그린다. 텍스트 자체는 세션 전체를 읽어 오므로 수만 메시지 세션의 DB 전송은 남아 있다).
- **시험은 합성 데이터로만**: 예전에는 에이전트 세션·비-TTY 에서 실행을 거부했다(원문 대화가 화면에 나오므로) — 지금은 위 제한 모드다. 화면 시험(`test_ctxui` Pilot)은 임시 Postgres 에 합성 대화를 넣어 클래스를 직접 띄운다. 실제 DB 로는 `donghans ctx sql` 집계(원문 제외)만 확인했다.

### 쓰는 법
```bash
donghans secret add NAS_PW            # 터미널에서 숨겨 입력(평문 저장, 대화에 안 남음)
donghans secret list                  # 이름·길이·fp 만(값 없음)
donghans secret scan                  # 후보(흐린 미리보기) → adopt <fp> <이름> / ignore <fp>
donghans secret run -- curl -u me:{{secret:NAS_PW}} https://nas.local   # 값은 실행 직전에만, 출력은 치환
donghans secret scrub                 # 로컬 트랜스크립트 점검(dry-run) → --apply
ctxui                                 # 대시보드·검색·대조·비밀·후보·지침 화면
```
