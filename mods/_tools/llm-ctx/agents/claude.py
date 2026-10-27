"""Claude Code 어댑터 — 대화 기록 `~/.claude/projects/<프로젝트>/<세션>.jsonl`(+ `<세션>/subagents/*.jsonl`)의 형식과 위치.
순수 함수만 둔다(DB 를 모른다). 인터페이스는 `agents/__init__.py` 머리말."""
import glob
import json
import os
import re

NAME = "claude"
ENV_MARKERS = ("CLAUDECODE",)   # Claude Code 의 셸 도구가 설정한다

_SUB = re.compile(r"/subagents/(?:agent-)?([^/]+)\.jsonl$")


def owns(path):
    return "/.claude/projects/" in path


def transcript_files(home):
    return (sorted(glob.glob(os.path.join(home, ".claude/projects/*/*.jsonl")))
            + sorted(glob.glob(os.path.join(home, ".claude/projects/*/*/subagents/*.jsonl"))))


def family(path):
    """본 기록 + 서브에이전트 기록."""
    base = path[:-6] if path.endswith(".jsonl") else path
    return [path] + sorted(glob.glob(base + "/subagents/*.jsonl"))


def session_files(home, sid):
    out = []
    for f in glob.glob(os.path.join(home, f".claude/projects/*/{sid}.jsonl")):
        out += family(f)
    return out


def subagent_id(path):
    m = _SUB.search(path)
    return m.group(1) if m else None


def blocks_text(content):
    """메시지 content → (kind 후보, 평문)."""
    if isinstance(content, str):
        return "text", content
    parts, kinds = [], set()
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            kinds.add("text"); parts.append(b.get("text", ""))
        elif t == "tool_use":
            kinds.add("tool_use"); parts.append(f"[tool_use {b.get('name')}] " + json.dumps(b.get("input"), ensure_ascii=False)[:1500])
        elif t == "tool_result":
            kinds.add("tool_result")
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            parts.append("[tool_result] " + str(c or "")[:4000])
    k = "text" if "text" in kinds else ("tool_use" if "tool_use" in kinds else ("tool_result" if "tool_result" in kinds else "other"))
    return k, "\n".join(p for p in parts if p)


def parse_line(line, agent_id):
    from . import MAX_RAW, MAX_TEXT      # 순환 import 를 피하려고 호출 때 읽는다
    line = line.replace("\\u0000", "")  # Postgres jsonb/text 는 NUL 을 못 담는다
    try:
        d = json.loads(line)
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("uuid") or d.get("type") not in ("user", "assistant", "system"):
        return None
    msg = d.get("message") or {}
    role = d["type"]
    k, text = blocks_text(msg.get("content")) if msg else ("other", d.get("content") if isinstance(d.get("content"), str) else "")
    if role == "user":
        kind = "meta" if d.get("isMeta") else ("tool_result" if k == "tool_result" else "prompt")
    elif role == "assistant":
        kind = "response" if k == "text" else ("tool_use" if k == "tool_use" else "other")
    else:
        kind = "other"
    u = msg.get("usage") or {}
    raw = line if len(line) <= MAX_RAW else None
    return dict(uuid=d["uuid"], sid=d.get("sessionId"), parent=d.get("parentUuid"), ts=d.get("timestamp"), role=role, kind=kind,
                side=bool(d.get("isSidechain")), agent=agent_id or d.get("agentId"), pid=d.get("promptId") or d.get("requestId"),
                cwd=d.get("cwd"), branch=d.get("gitBranch"), model=msg.get("model"), ver=d.get("version"),
                it=u.get("input_tokens"), ot=u.get("output_tokens"), cr=u.get("cache_read_input_tokens"), cc=u.get("cache_creation_input_tokens"),
                text=(text or "")[:MAX_TEXT].replace("\x00", ""),
                raw=json.loads(raw) if raw else {"truncated": True, "size": len(line), "head": line[:2000]})
