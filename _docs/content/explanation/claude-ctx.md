# claude-ctx — Claude 공유 컨텍스트 저장소

여러 머신(데스크톱·노트북)·프로젝트에서 Claude Code 로 한 대화·사용량을 Postgres 한 곳에 모아 조회한다. handoff/resume 도 이 저장소를 따라간다.

## 구성
| 부분 | 위치 | 역할 |
|---|---|---|
| 서버 | `mods/sys/services/claude-ctx.nix` (호스트 toml 에 `claude-ctx = true`) | Postgres 17 + pgvector, DB `claude_ctx`, 역할 `claude_ctx`. localhost 와 tailnet(100.64.0.0/10) 에서만 scram 비밀번호로 접속 |
| 스키마 | `mods/_data/claude-ctx/schema.sql` | 멱등. 서비스 `claude-ctx-schema` 가 적용 |
| 클라이언트 | `mods/_data/claude-ctx/claude_ctx.py` → `claude-ctx` 명령 (`mods/devel/apps/llm-cli.nix`) | 훅 적재 · 백필 · 조회 · handoff 업/다운 |
| 훅 | 같은 파일의 `claude` 래퍼가 `--settings` 로 주입 | UserPromptSubmit/Stop/SubagentStop/SessionStart/SessionEnd/PreCompact (async) |
| 안전망 | user 타이머 `claude-ctx-ingest` (10분) | 훅이 놓친 것을 오프셋 기준으로 따라잡음 |

## 새 머신 연결 (수동 1회 — 비밀번호는 nix 에 두지 않는다)
1. 서버: `sudo -u postgres psql -c "ALTER ROLE claude_ctx WITH LOGIN PASSWORD '<새 비밀번호>'"` (이미 설정했다면 생략)
2. 클라이언트: `~/.config/claude-ctx/dsn` (권한 600) 에 `postgresql://claude_ctx:<비밀번호>@beelink-ser7-co:5432/claude_ctx`
3. `claude-ctx ingest --days 30` 으로 첫 적재. 머신 이름은 hostname (`CLAUDE_CTX_HOST` 로 덮어쓸 수 있음)

## 다른 서버로 이관 (클라우드·온프레미스)
`pg_dump claude_ctx` → 새 서버에 `psql` 복원 → 각 머신의 dsn 파일만 교체. 서버 호스트의 `claude-ctx` 를 끄면 된다.

## 멱등성 (여러 머신이 올려도 안 깨지는 이유)
- 자연키 `ON CONFLICT DO NOTHING`: 메시지 uuid · 사용 요청 request_id · 훅 (host,session,event,payload md5).
- 파일 수집은 (host,path) 어드바이저리 락 + 오프셋 갱신을 같은 트랜잭션에서 → 훅·타이머·수동 백필이 겹쳐도 한 번만.
- 세션은 `hosts[]` 에 관측 머신을 누적, first/last 는 least/greatest. `claude --resume` 이 옛 메시지를 같은 uuid 로 복사해도 중복 행이 안 생긴다.
- **토큰·비용 합계는 `usage_events`(요청 단위)로만** 센다. `messages` 의 토큰을 합치면 resume/fork 로 복사된 만큼 이중 계산된다.
- 한계: 같은 한도 샘플(`limit_samples`)은 머신별 행이라 계정 공통 값이 머신마다 따로 쌓인다(의도). 머신 시계가 어긋나면 ts 비교가 어긋난다.

## 알려진 한계 / 주의
- 기록에 고객사 데이터·시크릿·개인정보가 섞인다 → tailnet 안에서만, 클라우드 이관 전에 걸러내기 단계를 추가할 것. 백업은 아직 없음(pg_dump 타이머 필요).
- 원본 한 줄이 100KB 를 넘으면 `raw` 는 잘려 저장된다(`raw->>'truncated'`); 정본은 각 머신의 트랜스크립트.
- 훅은 `claude` 셸 래퍼로 띄운 세션에만 걸린다(VSCode 확장 등은 타이머 백필만). `claude -p` 에서는 Stop 훅이 기록되지 않았다(SessionEnd 로 보충됨).
