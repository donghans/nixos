#!/usr/bin/env python3
"""agents(에이전트별 어댑터) 시험 — DB 없이 순수 함수만. Claude Code 어댑터의 파싱·경로 규칙과, 어댑터를 더하면 경로·적재 목록·표식에 반영되는지(교체 가능성)."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "_testkit"))
from harness import checker
check, finish = checker()
import agents
from agents import claude

# ---------------------------------------------------------------- 레지스트리
check("기본 어댑터는 claude", agents.get() is claude and agents.DEFAULT == "claude")
try:
    agents.get("nope"); ok = False
except KeyError as e:
    ok = "nope" in str(e) and "claude" in str(e)
check("모르는 어댑터는 KeyError(있는 것을 안내)", ok)
check("표식: 이전 AGENT_ENV_MARKERS 와 같은 집합(CLAUDECODE·GEMINI_CLI·DONGHANS_AGENT)", set(agents.ENV_MARKERS) == {"CLAUDECODE", "GEMINI_CLI", "DONGHANS_AGENT"}, str(agents.ENV_MARKERS))
check("provider_for_path: .claude/projects 는 claude", agents.provider_for_path("/h/.claude/projects/p/s.jsonl") is claude)
check("provider_for_path: 아무도 안 맡으면 기본(claude)", agents.provider_for_path("/tmp/other.jsonl") is claude)

# ---------------------------------------------------------------- 경로 규칙
check("subagent_id: agent- 접두를 뗀다", claude.subagent_id("/h/.claude/projects/p/sid/subagents/agent-abc.jsonl") == "abc")
check("subagent_id: 접두 없는 것도", claude.subagent_id("/h/.claude/projects/p/sid/subagents/xyz.jsonl") == "xyz")
check("subagent_id: 본 기록은 None", claude.subagent_id("/h/.claude/projects/p/sid.jsonl") is None)
TMP = tempfile.mkdtemp(prefix="agents-test-")
proj = os.path.join(TMP, ".claude/projects/-tmp-proj"); os.makedirs(os.path.join(proj, "S1/subagents")); os.makedirs(os.path.join(proj, "S2"))
for f in ("S1.jsonl", "S2.jsonl", "S1/subagents/agent-a.jsonl", "S1/subagents/agent-b.jsonl"):
    open(os.path.join(proj, f), "w").write("{}\n")
open(os.path.join(proj, "S1/notes.txt"), "w").write("x")
files = claude.transcript_files(TMP)
check("transcript_files: 본 기록 2개 + 서브에이전트 2개(정렬)", [os.path.relpath(f, proj) for f in files] == ["S1.jsonl", "S2.jsonl", "S1/subagents/agent-a.jsonl", "S1/subagents/agent-b.jsonl"], str(files))
fam = claude.family(os.path.join(proj, "S1.jsonl"))
check("family: 본 기록 + 딸린 서브에이전트", [os.path.relpath(f, proj) for f in fam] == ["S1.jsonl", "S1/subagents/agent-a.jsonl", "S1/subagents/agent-b.jsonl"], str(fam))
check("family: 서브에이전트 없는 기록은 자기 자신만", claude.family(os.path.join(proj, "S2.jsonl")) == [os.path.join(proj, "S2.jsonl")])
check("session_files: 세션 ID 로 본 기록 + 서브에이전트", len(claude.session_files(TMP, "S1")) == 3 and claude.session_files(TMP, "none") == [])
check("agents.all_transcript_files == claude 목록(어댑터 하나)", agents.all_transcript_files(TMP) == files)
check("agents.session_family == claude.session_files", agents.session_family(TMP, "S1") == claude.session_files(TMP, "S1"))
check("agents.family: 경로로 어댑터를 찾아 위임", agents.family(os.path.join(proj, "S1.jsonl")) == fam)

# ---------------------------------------------------------------- 한 줄 파싱
L = lambda **d: json.dumps(d, ensure_ascii=False)
base = dict(uuid="u1", sessionId="s1", parentUuid="p0", timestamp="2026-10-27T00:00:00Z", cwd="/w", gitBranch="main", version="2.0")
r = claude.parse_line(L(type="user", message=dict(role="user", content="안녕"), **base), None)
check("user 문자열 → role user·kind prompt·평문", r and r["role"] == "user" and r["kind"] == "prompt" and r["text"] == "안녕" and r["sid"] == "s1" and r["cwd"] == "/w" and r["branch"] == "main" and r["ver"] == "2.0", str(r))
check("raw 는 dict(DB 래핑은 호출하는 쪽) — 원본 줄의 JSON", isinstance(r["raw"], dict) and r["raw"]["uuid"] == "u1")
r = claude.parse_line(L(type="user", isMeta=True, message=dict(content="m"), **base), None)
check("isMeta → kind meta", r["kind"] == "meta")
r = claude.parse_line(L(type="user", message=dict(content=[dict(type="tool_result", content=[dict(text="결과")])]), **base), None)
check("tool_result → kind tool_result·평문에 [tool_result]", r["kind"] == "tool_result" and "[tool_result] 결과" in r["text"], str(r))
r = claude.parse_line(L(type="assistant", message=dict(model="m1", content=[dict(type="text", text="답")], usage=dict(input_tokens=1, output_tokens=2, cache_read_input_tokens=3, cache_creation_input_tokens=4)), requestId="rq", **base), None)
check("assistant text → response·모델·토큰·요청 ID", r["kind"] == "response" and r["model"] == "m1" and (r["it"], r["ot"], r["cr"], r["cc"]) == (1, 2, 3, 4) and r["pid"] == "rq", str(r))
r = claude.parse_line(L(type="assistant", message=dict(content=[dict(type="tool_use", name="Bash", input=dict(command="ls"))]), **base), None)
check("assistant tool_use → kind tool_use·평문에 도구 이름", r["kind"] == "tool_use" and "[tool_use Bash]" in r["text"], str(r))
check("system → kind other", claude.parse_line(L(type="system", content="x", **base), None)["kind"] == "other")
check("깨진 JSON·uuid 없음·모르는 type 은 None", claude.parse_line("{bad", None) is None and claude.parse_line(L(type="user", sessionId="s"), None) is None and claude.parse_line(L(type="summary", uuid="u"), None) is None and claude.parse_line("[]", None) is None)
r = claude.parse_line(L(type="user", message=dict(content="a\u0000b"), **base).replace("\\u0000", "\\\\u0000"), None)
raw_line = '{"type":"user","uuid":"u9","sessionId":"s","message":{"content":"x\\u0000y"}}'
r = claude.parse_line(raw_line, None)
check("NUL(\\u0000)은 지운다(Postgres 가 못 담는다)", r and r["text"] == "xy", str(r))
r = claude.parse_line(L(type="user", message=dict(content="z" * (agents.MAX_TEXT + 500)), **base), None)
check("검색용 평문은 MAX_TEXT 로 자른다", len(r["text"]) == agents.MAX_TEXT)
big = L(type="user", message=dict(content="q" * (agents.MAX_RAW + 10)), **base)
r = claude.parse_line(big, None)
check("MAX_RAW 보다 큰 줄은 raw 에 잘림 표식(size·head)", r["raw"].get("truncated") is True and r["raw"]["size"] == len(big) and len(r["raw"]["head"]) == 2000, str(list(r["raw"])))
check("서브에이전트 id: 인자가 우선, 없으면 기록의 agentId", claude.parse_line(L(type="user", message=dict(content="s"), **base), "A1")["agent"] == "A1" and claude.parse_line(L(type="user", message=dict(content="s"), agentId="B2", **base), None)["agent"] == "B2")
check("isSidechain → side", claude.parse_line(L(type="user", isSidechain=True, message=dict(content="s"), **base), None)["side"] is True)

# ---------------------------------------------------------------- 교체 가능성: 가짜 어댑터를 더하면 전체가 따라온다
class Fake:
    NAME = "fake"; ENV_MARKERS = ("FAKE_AGENT_CLI",)
    owns = staticmethod(lambda p: "/.fake/" in p)
    transcript_files = staticmethod(lambda home: [os.path.join(home, ".fake/t1.log")])
    session_files = staticmethod(lambda home, sid: [os.path.join(home, f".fake/{sid}.log")])
    family = staticmethod(lambda p: [p])
    subagent_id = staticmethod(lambda p: None)
    parse_line = staticmethod(lambda line, a: dict(uuid=line.strip(), sid="fs", raw={}))
agents.PROVIDERS["fake"] = Fake
try:
    check("가짜 어댑터: 경로로 라우팅", agents.provider_for_path("/h/.fake/x.log") is Fake and agents.provider_for_path("/h/.claude/projects/p/s.jsonl") is claude)
    check("가짜 어댑터: 적재 대상 목록에 합쳐진다", os.path.join(TMP, ".fake/t1.log") in agents.all_transcript_files(TMP) and set(files) <= set(agents.all_transcript_files(TMP)))
    check("가짜 어댑터: 세션 기록 목록에도", os.path.join(TMP, ".fake/S9.log") in agents.session_family(TMP, "S9"))
    check("가짜 어댑터: parse_line 은 그 어댑터 것(인터페이스만 맞으면 된다)", agents.provider_for_path("/h/.fake/x.log").parse_line("id-1", None)["uuid"] == "id-1")
finally:
    del agents.PROVIDERS["fake"]
check("어댑터를 빼면 원래대로", agents.all_transcript_files(TMP) == files and agents.provider_for_path("/h/.fake/x.log") is claude)
import shutil; shutil.rmtree(TMP, ignore_errors=True)
finish("agents")
