"""agents — LLM 에이전트(CLI)별 어댑터. 대화 기록의 형식·위치·표식처럼 **에이전트마다 다른 것**을 한곳에 모은다.

왜(사용자 결정 2026-10-27): 이 도구(`donghans ctx`)는 지금 Claude Code 의 기록만 읽는다. 다른 에이전트(예: Gemini CLI)를 쓰게 되면
파서 한 파일만 더하면 되도록, 조회·검색·비밀 치환·주입·`ctxui` 같은 **에이전트와 무관한 부분**(llm_ctx·ctx_secrets·ctx_instr·ctx_store·ctxdata·ctxui)에서
에이전트 종속 코드를 이 패키지로 뺐다. 지금 구현은 `claude` 하나다(과설계를 피하려고 두 번째 구현은 아직 없다).

어댑터 모듈이 제공해야 하는 것(`claude.py` 가 본보기):
  NAME             에이전트 이름(문자열)
  ENV_MARKERS      이 에이전트의 셸 도구가 설정하는 환경변수 이름들 — 「LLM 세션이 실행했다」를 가르는 보조 표식(제한 모드·사람 전용 명령)
  owns(path)       이 대화 파일이 이 에이전트의 것인가
  transcript_files(home)   적재·치환 대상 대화 파일 전체(정렬된 목록)
  session_files(home, sid) 한 세션의 본 기록 + 서브에이전트 기록 파일
  family(path)     본 기록 파일 하나 → 그 기록 + 딸린 서브에이전트 기록
  subagent_id(path)        파일 경로에서 서브에이전트 id(없으면 None)
  parse_line(line, subagent_id) → dict | None
        기록 한 줄 → 메시지 행. 키: uuid sid parent ts role kind side agent pid cwd branch model ver it ot cr cc text raw
        (raw 는 JSON 으로 저장할 dict — DB 래핑은 호출하는 쪽이 한다. DB·psycopg 를 모른다: 순수 함수)
  아직 이 인터페이스 밖(Claude Code 전용으로 llm_ctx.py 에 남아 있음): 훅 입력 JSON(session_id·cwd·transcript_path),
  OTel·상태줄 한도 기록(ingest_otel·backfill_accounts). 두 번째 에이전트를 실제로 붙일 때 이 목록을 어댑터로 옮긴다.
DB 에는 아직 「어느 에이전트의 기록인가」 열이 없다(sessions·messages). 두 번째 에이전트를 적재하기 전에 `provider` 열을 더해야 한다.
"""
from . import claude

MAX_RAW = 100_000      # 원본 한 줄이 이보다 크면 잘라서 보관(정본은 대화 파일)
MAX_TEXT = 20_000      # 검색용 평문 상한

PROVIDERS = {claude.NAME: claude}
DEFAULT = claude.NAME
# 파서는 아직 없지만 셸 표식은 미리 막아 둔다(사람 전용 명령·제한 모드가 다른 에이전트의 셸에서도 안전하도록).
EXTRA_ENV_MARKERS = ("GEMINI_CLI", "DONGHANS_AGENT")
ENV_MARKERS = tuple(m for p in PROVIDERS.values() for m in p.ENV_MARKERS) + EXTRA_ENV_MARKERS


def get(name=None):
    name = name or DEFAULT
    if name not in PROVIDERS:
        raise KeyError(f"알 수 없는 에이전트: {name} (있는 것: {', '.join(PROVIDERS)})")
    return PROVIDERS[name]


def provider_for_path(path):
    """대화 파일 경로 → 어댑터. 어느 쪽도 자기 것이라 하지 않으면 기본(claude)."""
    for p in PROVIDERS.values():
        if p.owns(path):
            return p
    return PROVIDERS[DEFAULT]


def all_transcript_files(home):
    out = []
    for p in PROVIDERS.values():
        out += p.transcript_files(home)
    return out


def session_family(home, sid):
    """한 세션의 모든 기록 파일(어댑터 전부에서). 가장 최근 대화까지 적재할 때 쓴다."""
    out = []
    for p in PROVIDERS.values():
        out += p.session_files(home, sid)
    return out


def family(path):
    return provider_for_path(path).family(path)
