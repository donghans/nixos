-- claude-ctx 스키마: 여러 머신·프로젝트의 Claude Code 대화/사용량을 한곳에 모은다. 멱등(여러 번 실행해도 안전).
-- 원문의 정본은 각 머신의 트랜스크립트(jsonl)이고, 여기는 조회용 사본이다(uuid 로 중복 방지).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

SET ROLE claude_ctx;

-- 멱등 원칙: 모든 쓰기는 자연키(uuid·request_id·(host,path))로 ON CONFLICT 처리하고, 합계가 필요한 토큰·비용은 요청 단위인
-- usage_events 로만 센다(resume/fork 는 옛 메시지를 같은 uuid 로 새 트랜스크립트에 복사하므로 messages 의 usage 합산은 이중 계산이다).
-- 어느 머신·어느 프로젝트인지: host(작업한 컴퓨터), cwd(작업 디렉터리), repo_url(git remote origin), branch
CREATE TABLE IF NOT EXISTS sessions (
  session_id   text PRIMARY KEY,
  host         text NOT NULL,   -- 처음 수집한 머신
  hosts        text[] NOT NULL DEFAULT '{}',  -- 이 세션이 관측된 모든 머신(~/.claude 를 복사·동기화한 경우)
  cwd          text,
  repo_url     text,   -- 정규화된 https 형태(경로·머신이 달라도 같은 저장소로 묶는 키)
  repo_root    text,
  branch       text,
  head_sha     text,
  transcript   text,
  client_ver   text,
  first_ts     timestamptz,
  last_ts      timestamptz,
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_repo ON sessions (repo_url, last_ts DESC);
CREATE INDEX IF NOT EXISTS sessions_host ON sessions (host, last_ts DESC);

CREATE TABLE IF NOT EXISTS messages (
  uuid         text PRIMARY KEY,
  session_id   text NOT NULL,
  host         text NOT NULL,
  parent_uuid  text,
  ts           timestamptz,
  role         text,            -- user | assistant | system
  kind         text,            -- prompt | response | tool_use | tool_result | other
  is_sidechain boolean NOT NULL DEFAULT false,
  agent_id     text,            -- 서브에이전트 기록이면 그 ID
  prompt_id    text,
  cwd          text,
  branch       text,
  model        text,
  input_tokens int, output_tokens int, cache_read_tokens int, cache_create_tokens int,
  text         text,            -- 검색용 평문(도구 결과는 앞부분만)
  raw          jsonb,           -- 원본 한 줄(너무 크면 잘림 표시)
  source       text NOT NULL DEFAULT 'transcript',
  ingested_at  timestamptz NOT NULL DEFAULT now(),
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED
);
CREATE INDEX IF NOT EXISTS messages_session ON messages (session_id, ts);
CREATE INDEX IF NOT EXISTS messages_ts ON messages (ts DESC);
CREATE INDEX IF NOT EXISTS messages_kind ON messages (kind, ts DESC);
CREATE INDEX IF NOT EXISTS messages_tsv ON messages USING gin (tsv);
CREATE INDEX IF NOT EXISTS messages_trgm ON messages USING gin (text gin_trgm_ops);

-- 훅이 받은 원본 payload(이벤트 시점 기록; 발화 원문은 트랜스크립트에 반영되기 전에도 여기엔 있다)
CREATE TABLE IF NOT EXISTS hook_events (
  id         bigserial PRIMARY KEY,
  ts         timestamptz NOT NULL DEFAULT now(),
  host       text NOT NULL,
  session_id text,
  event      text NOT NULL,
  prompt_id  text,
  cwd        text,
  payload    jsonb,
  payload_md5 text NOT NULL   -- 클라이언트가 계산(재전송 중복 방지용; jsonb→text 는 immutable 이 아니라 생성 열로 못 쓴다)
);
CREATE UNIQUE INDEX IF NOT EXISTS hook_events_dedup ON hook_events (host, session_id, event, payload_md5);
CREATE INDEX IF NOT EXISTS hook_events_session ON hook_events (session_id, ts);

-- OTel api_request: 모델·토큰·비용·시간(요청 단위)
CREATE TABLE IF NOT EXISTS usage_events (
  request_id  text PRIMARY KEY,
  host        text NOT NULL,
  ts          timestamptz,
  session_id  text,
  prompt_id   text,
  model       text,
  input_tokens bigint, output_tokens bigint, cache_read_tokens bigint, cache_create_tokens bigint,
  cost_usd    double precision,
  duration_ms int,
  query_source text,
  effort      text,
  speed       text
);
CREATE INDEX IF NOT EXISTS usage_session ON usage_events (session_id, ts);
CREATE INDEX IF NOT EXISTS usage_ts ON usage_events (ts DESC);

-- 상태 표시줄이 남긴 5h/7d 한도 스냅샷
CREATE TABLE IF NOT EXISTS limit_samples (
  host text NOT NULL, ts timestamptz NOT NULL, session_id text,
  five_hour_pct real, seven_day_pct real, cost_usd double precision, model text, ctx_pct real,
  PRIMARY KEY (host, ts, session_id)
);
-- 3: 계정별 최고 사용률 집계용 — 한도 %는 계정 단위라 계정(account_id=accountUuid)과 한도 창 리셋 시각이 있어야 창별 최고값을 낼 수 있다.
--    이전 행은 NULL(계정을 알 수 없음).
ALTER TABLE limit_samples ADD COLUMN IF NOT EXISTS account_id text;
ALTER TABLE limit_samples ADD COLUMN IF NOT EXISTS account_email text;
ALTER TABLE limit_samples ADD COLUMN IF NOT EXISTS account_plan text;   -- 계정마다 플랜(한도 크기)이 달라 같은 %도 의미가 다르다
ALTER TABLE limit_samples ADD COLUMN IF NOT EXISTS five_hour_resets_at timestamptz;
ALTER TABLE limit_samples ADD COLUMN IF NOT EXISTS seven_day_resets_at timestamptz;
CREATE INDEX IF NOT EXISTS limit_samples_acct ON limit_samples (account_id, ts DESC);

-- 인수인계: 머신이 달라도 resume 할 수 있게 문서를 DB 에도 둔다(저장소는 repo_url 로 식별)
CREATE TABLE IF NOT EXISTS handoffs (
  session_id text PRIMARY KEY,
  host       text NOT NULL,
  repo_url   text,
  repo_root  text,
  head_sha   text,
  branch     text,
  note       text,
  doc_name   text,
  doc_text   text,
  details    jsonb,   -- {상대경로: 내용} 상세 문서
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS handoffs_repo ON handoffs (repo_url, created_at DESC);

-- 수집 위치(머신별 파일 오프셋)
CREATE TABLE IF NOT EXISTS ingest_state (
  host text NOT NULL, path text NOT NULL, byte_offset bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (host, path)
);

-- 비밀 등록표(설계: 평문 저장 — ctx DB 는 허용된 tailnet 기기만 접속). 출력 치환·주입 래퍼·후보 탐지에 쓴다. ctx_secrets.py 의 SCHEMA_STATEMENTS 와 같아야 한다(시험이 확인).
CREATE TABLE IF NOT EXISTS secrets (
  id         bigserial PRIMARY KEY,
  label      text NOT NULL UNIQUE,
  kind       text NOT NULL DEFAULT 'literal' CHECK (kind IN ('literal','regex')),
  value      text NOT NULL,
  enabled    boolean NOT NULL DEFAULT true,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS secret_ignores (
  fp         text PRIMARY KEY,
  pattern    text,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 스키마 버전(점진 마이그레이션용: 새 변경은 ALTER ... IF NOT EXISTS 로 추가하고 버전을 올린다)
CREATE TABLE IF NOT EXISTS schema_version (v int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_version (v) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO schema_version (v) VALUES (2) ON CONFLICT DO NOTHING;  -- 2: secrets, secret_ignores
INSERT INTO schema_version (v) VALUES (3) ON CONFLICT DO NOTHING;  -- 3: limit_samples 계정·리셋 시각

-- 프로젝트별 지침(`.claude/donghans-instructions.md`·`donghans-override.md`)의 공유 정본 — 로컬 파일은 SessionStart 훅이 만드는 캐시(ctx_instr.py).
-- rev 는 낙관적 잠금: 올릴 때 `WHERE rev = 읽은 값` 이 아니면 거부한다(다른 기기가 먼저 바꾼 것을 덮지 않는다). 본문에 비밀 값을 두지 않는다(올릴 때 등록표로 검사).
CREATE TABLE IF NOT EXISTS project_instructions (
  repo_url     text NOT NULL,
  name         text NOT NULL CHECK (name IN ('instructions', 'override')),
  body         text NOT NULL,
  rev          integer NOT NULL DEFAULT 1,
  updated_host text NOT NULL,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (repo_url, name)
);
