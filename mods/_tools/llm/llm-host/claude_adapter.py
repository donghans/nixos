"""claude 스트리밍 모드(`-p --input-format stream-json --output-format stream-json`) 어댑터. 설계: plan llm-trust/11 §4-2.
S2(읽기: decode)와 S3(쓰기: argv·env·encode).

근거 녹화본: tests/fixtures/{noinit,perm,main,sub}.jsonl (S0 시험, claude 2.1.317; 경로·uuid 치환본). 번역 규칙 요약은 README 의 「claude 번역」.
decode 정책(계획서가 S2 에 맡긴 결정):
1. init: 첫 init → SessionReady, 이후 매 턴 init → 바뀐 값만 SessionInfo(바뀐 게 없으면 이벤트 없음).
2. 턴 시작: 한 턴 안에서 `system/status requesting` 은 API 호출마다 오므로 **턴의 첫 것만** TurnStarted. source 는 `note_sent()` 로
   센 호스트 발 메시지가 있으면 user, 없으면 auto. `result` 가 오면 턴이 끝난 것으로 본다.
3. 비용: `total_cost_usd` 는 프로세스 안 누적. cost_delta = 직전 누적과의 차(첫 턴은 0 부터; 값이 줄었으면 새 프로세스로 보고 total 자체). 중단된 턴은 차이 0.
4. message 중복: `--include-partial-messages` 로 이미 text_delta 로 보낸 글은 이어서 오는 assistant 완결 메시지(중단 직후의 부분 응답 포함)에 또 들어 있다.
   Message 의 블록은 완결본을 그대로 담되 **다른 이벤트로 이미 전달한 블록에 `shown_as` 를 붙인다**(text_delta · tool_call · tool_result).
   소비자는 `shown_as` 가 있는 블록을 다시 그리지 않는다. 델타 없이 온 글(부분 메시지 옵션 없음·서브에이전트)은 `shown_as` 가 없어 Message 로 그린다.
5. run: parent_tool_use_id(서브에이전트를 띄운 Agent 도구 호출 id)를 그대로 run 으로 쓴다. task_* 는 task_id→tool_use_id 표로, 권한 요청은 도구 호출 id→run 표로 잇는다.
6. 아는 줄이지만 소비자에게 줄 게 없는 것(글자 조각 외 stream_event 뼈대 등)은 [] — 세어 두었다가 `ignored` 로 시험이 본다. 모르는 줄은 Raw.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional, Union

import events as E
from adapter import Adapter, UNKNOWN

_INIT_FIELDS = (  # SessionReady/SessionInfo 필드 ← init 키
    ("model", "model"), ("cwd", "cwd"), ("permission_mode", "permissionMode"), ("backend_version", "claude_code_version"),
    ("capabilities", "capabilities"), ("tools", "tools"), ("skills", "skills"), ("slash", "slash_commands"), ("mcp", "mcp_servers"),
)
# 소비자에게 줄 게 없는 stream_event 안쪽 종류
_STREAM_SKELETON = {"message_start", "message_delta", "message_stop", "content_block_start", "content_block_stop"}
# 글자 조각이 아닌 delta(도구 입력 조각·사고 조각·서명). 사고는 system/thinking_tokens 로, 도구 입력은 완결 tool_use 로 전달된다.
_DELTA_SKIPPED = {"input_json_delta", "thinking_delta", "signature_delta"}


def _dump(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def _num(x: Any) -> Optional[float]:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


class ClaudeAdapter(Adapter):
    name = "claude"

    def __init__(self, host_session: str = ""):
        self.host_session = host_session
        self.backend_session: Optional[str] = None
        self.ignored: dict = {}          # 아는 줄이지만 이벤트를 만들지 않은 것의 종류별 개수(시험·진단용)
        self._init: Optional[dict] = None   # 마지막 init 에서 뽑은 {필드: 값}
        self._caps: list = []
        self._seen_init = False
        self._cost_total = 0.0
        self._resume_pending = False     # --resume 으로 띄운 프로세스의 첫 result 를 기다리는 중(S7: 그 total 은 이전 실행분까지 포함한 누적)
        self._turn = 0
        self._in_turn = False
        self._sent_pending = 0
        self._streamed: dict = {}        # api_message_id → {블록 index: 글자 조각을 이은 글}
        self._task_run: dict = {}        # task_id → run
        self._call_run: dict = {}        # 도구 호출 id → run(서브에이전트 안의 호출)
        self._req_input: dict = {}       # 미해결 요청 id → 원래 input(허용 응답의 updatedInput 기본값)
        self._int_seq = 0

    # ------------------------------------------------------------ 쓰기 쪽 (S3)
    def argv(self, spec: dict) -> list:
        """기동 명령행. 실행 파일은 spec["exe"](문자열 또는 [실행 파일, 인자…]) 로 갈아끼운다(시험: 가짜 백엔드). 없으면 ["claude"].
        옵션은 S0 에서 시험한 조합이다. permission_mode 가 없으면 manual(사용자 설정이 먼저 평가되므로 init 에는 default 로 보일 수 있다 — S0)."""
        exe = spec.get("exe") or ["claude"]
        a = [exe] if isinstance(exe, str) else list(exe)
        a += ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
              "--include-partial-messages", "--include-hook-events",
              "--permission-mode", spec.get("permission_mode") or "manual", "--permission-prompt-tool", "stdio"]
        if spec.get("model"):
            a += ["--model", spec["model"]]
        if spec.get("resume"):
            a += ["--resume", spec["resume"]]
            self._resume_pending = True
        if spec.get("persist", True) is False:
            a.append("--no-session-persistence")
        if spec.get("max_budget_usd") is not None:       # 선택 안전장치(기본 없음). 한도를 넘을 수 있고 resume 의 이전 합계는 세지 않는다 [공식]
            b = spec["max_budget_usd"]
            if isinstance(b, bool) or not isinstance(b, (int, float)) or not b > 0 or b != b or b == float("inf"):
                raise ValueError(f"max_budget_usd 는 0 보다 큰 유한한 숫자: {b!r}")
            a += ["--max-budget-usd", f"{b:g}"]
        a += [str(x) for x in (spec.get("extra_args") or [])]
        return a

    def env(self, spec: dict) -> dict:
        """자식 환경(상속하지 않는다): HOME·PATH·TERM=dumb 만 현재 환경에서 가져오고 spec["env_extra"] 를 덮어쓴다. 래퍼 재현(sudo 등)은 S8 launcher."""
        e = {"TERM": "dumb"}
        for k in ("HOME", "PATH"):
            if k in os.environ:
                e[k] = os.environ[k]
        e.update({str(k): str(v) for k, v in (spec.get("env_extra") or {}).items()})
        return e

    def encode(self, command) -> list:
        """소비자 명령 → 백엔드 입력 줄들. 호스트 안에서만 쓰는 명령(start·set_policy·close·kill)은 []. 줄은 공백 없는 JSON(ensure_ascii=False)."""
        if isinstance(command, E.Send):
            if (command.text is None) == (command.blocks is None):
                raise ValueError("send 는 text 또는 blocks 중 정확히 하나")
            self.note_sent()
            content = command.text if command.text is not None else command.blocks
            return [_dump({"type": "user", "message": {"role": "user", "content": content}})]
        if isinstance(command, E.Interrupt):
            self._int_seq += 1
            return [_dump({"type": "control_request", "request_id": f"host-int-{self._int_seq}", "request": {"subtype": "interrupt"}})]
        if isinstance(command, E.AnswerPermission):
            orig = self._req_input.pop(command.req, None)
            if command.allow:
                r: dict = {"behavior": "allow", "updatedInput": command.updated_input if command.updated_input is not None else orig}
                if command.updated_permissions:
                    r["updatedPermissions"] = command.updated_permissions
            else:
                r = {"behavior": "deny", "message": command.message or "denied"}
            return [self._respond(command.req, r)]
        if isinstance(command, E.AnswerQuestion):
            orig = self._req_input.pop(command.req, None)
            inp = dict(orig) if isinstance(orig, dict) else {}
            answers = {q: (", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v) for q, v in command.answers.items()}
            if command.free_text is not None:   # 자유 입력은 아직 답이 없는 첫 질문의 답으로 둔다(공식 형식은 질문→글; 자유 입력 칸의 실측은 없음)
                qs = inp.get("questions") or []
                first = next((q.get("question") for q in qs if isinstance(q, dict) and q.get("question") not in answers), None)
                if first is not None:
                    answers[first] = command.free_text
            inp["answers"] = answers
            return [self._respond(command.req, {"behavior": "allow", "updatedInput": inp})]
        if isinstance(command, (E.Start, E.SetPolicy, E.Close, E.Kill)):
            return []
        raise ValueError(f"알 수 없는 명령: {type(command).__name__}")

    @staticmethod
    def _respond(req: str, response: dict) -> str:
        return _dump({"type": "control_response", "response": {"subtype": "success", "request_id": req, "response": response}})

    def note_sent(self) -> None:
        """호스트가 사용자 메시지를 보냈음을 알린다(encode(Send)가 부른다). 다음 턴 시작의 source 를 user 로 만든다."""
        self._sent_pending += 1

    # ------------------------------------------------------------ 능력
    @property
    def capabilities(self) -> dict:
        interrupt: Any = UNKNOWN
        if self._seen_init:
            interrupt = any(str(c).startswith("interrupt_") for c in self._caps)
        return {
            "permission_delegation": True, "question_tool": True, "interrupt": interrupt, "partial_text": True,
            "queue_while_busy": True, "subagent_events": True, "hooks": True, "skills": True, "slash": True,
            "cost_report": True, "resume": UNKNOWN, "persistence_control": True, "bypass_mode": UNKNOWN,
        }

    # ------------------------------------------------------------ decode
    def decode(self, line: Union[str, bytes, dict]) -> list:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        if isinstance(line, str):
            if not line.strip():
                return []
            try:
                obj = json.loads(line)
            except ValueError:
                return [self._raw(line)]
        else:
            obj = line
        if not isinstance(obj, dict):
            return [self._raw(obj)]
        sid = obj.get("session_id")
        if isinstance(sid, str):
            self.backend_session = sid
        try:
            out = self._dispatch(obj)
        except (KeyError, TypeError, AttributeError, ValueError):   # 모양이 예상과 다르면 버리지 않고 raw
            out = None
        if out is None:
            return [self._raw(obj)]
        return out

    def _ev(self, cls, run: Optional[str] = None, **kw):
        return cls(host_session=self.host_session, backend_session=self.backend_session, run=run, **kw)

    def _raw(self, payload, run: Optional[str] = None) -> E.Raw:
        if isinstance(payload, dict) and isinstance(payload.get("parent_tool_use_id"), str):
            run = payload["parent_tool_use_id"]
        return self._ev(E.Raw, run=run, vendor="claude", payload=payload)

    def _skip(self, key: str) -> list:
        self.ignored[key] = self.ignored.get(key, 0) + 1
        return []

    def _dispatch(self, o: dict) -> Optional[list]:
        t = o.get("type")
        run = o.get("parent_tool_use_id") if isinstance(o.get("parent_tool_use_id"), str) else None
        if t == "system":
            return self._system(o, run)
        if t == "stream_event":
            return self._stream(o, run)
        if t == "assistant":
            return self._assistant(o, run)
        if t == "user":
            return self._user(o, run)
        if t == "result":
            return self._result(o)
        if t == "control_request":
            return self._control_request(o)
        if t == "control_response":
            return self._control_response(o)
        if t == "rate_limit_event":
            info = o["rate_limit_info"]
            return [self._ev(E.RateLimit, status=info.get("status"), resets_at=_num(info.get("resetsAt")), window=info.get("rateLimitType"))]
        return None

    # ---- system
    def _system(self, o: dict, run) -> Optional[list]:
        st = o.get("subtype")
        if st == "init":
            return self._on_init(o)
        if st == "status":
            if o.get("status") != "requesting":
                return None
            if self._in_turn:
                return self._skip("status:requesting(턴 안 반복)")
            self._in_turn = True
            self._turn += 1
            src = "user" if self._sent_pending > 0 else "auto"
            self._sent_pending = max(0, self._sent_pending - 1)
            return [self._ev(E.TurnStarted, turn=self._turn, source=src)]
        if st == "thinking_tokens":
            return [self._ev(E.Thinking, run=run, tokens_est=None if _num(o.get("estimated_tokens")) is None else int(o["estimated_tokens"]))]
        if st in ("hook_started", "hook_response"):
            name = o.get("hook_name") or o.get("hook_event")
            if not isinstance(name, str):
                return None
            ex = {k: o[k] for k in ("hook_id", "hook_event") if k in o}
            if st == "hook_response":
                ex.update({k: o[k] for k in ("outcome", "exit_code") if k in o})
            return [self._ev(E.Hook, run=run, name=name, phase="started" if st == "hook_started" else "finished", extra=ex)]
        if st in ("task_started", "task_progress", "task_updated", "task_notification"):
            return self._task(o, st)
        if st == "background_tasks_changed":   # S7 실측(2.1.318): 백그라운드 작업 목록 스냅샷. task_* 가 같은 내용을 이미 주므로 이벤트 없음
            return self._skip("system:background_tasks_changed")
        if st == "api_retry":   # 형식 미녹화(계획서 표의 notice 대응) — 알려진 키만 느슨하게 요약하고 원문은 extra 에 둔다
            bits = [f"{k}={o[k]}" for k in ("attempt", "max_retries", "retry_delay_ms", "error_status", "error") if k in o]
            return [self._ev(E.Notice, level="warn", text="API 재시도 " + " ".join(bits), extra={"payload": o})]
        return None

    def _on_init(self, o: dict) -> list:
        cur = {f: o[k] for f, k in _INIT_FIELDS if k in o}
        if isinstance(o.get("session_id"), str):
            cur["backend_session"] = o["session_id"]
        self._caps = list(o.get("capabilities") or [])
        if not self._seen_init:
            self._seen_init = True
            self._init = cur
            kw = {f: cur[f] for f, _ in _INIT_FIELDS if f in cur}
            return [self._ev(E.SessionReady, backend="claude", **kw)]
        changed = {k: v for k, v in cur.items() if (self._init or {}).get(k) != v}
        self._init = {**(self._init or {}), **cur}
        if not changed:
            return self._skip("init(바뀐 값 없음)")
        return [self._ev(E.SessionInfo, changed=changed)]

    def _task(self, o: dict, st: str) -> list:
        tid = o.get("task_id")
        if st == "task_started":
            run = o.get("tool_use_id") or tid
            if isinstance(tid, str):
                self._task_run[tid] = run
            return [self._ev(E.Subtask, run=run, state="started", summary=o.get("description"))]
        run = o.get("tool_use_id") or self._task_run.get(tid) or tid
        if st == "task_progress":
            return [self._ev(E.Subtask, run=run, state="progress", summary=o.get("description"))]
        if st == "task_updated":
            patch = o.get("patch") if isinstance(o.get("patch"), dict) else {}
            summ = patch.get("status") if isinstance(patch.get("status"), str) else json.dumps(patch, ensure_ascii=False)
            return [self._ev(E.Subtask, run=run, state="updated", summary=summ, extra={"patch": patch})]
        status = o.get("status")
        return [self._ev(E.Subtask, run=run, state="done", summary=o.get("summary"), extra={"status": status} if status else {})]

    # ---- stream_event
    def _stream(self, o: dict, run) -> Optional[list]:
        ev = o["event"]
        et = ev["type"]
        if et == "content_block_delta":
            d = ev["delta"]
            dt = d["type"]
            if dt == "text_delta":
                idx = ev.get("index", 0)
                mid = o.get("api_message_id") or ""
                per = self._streamed.setdefault(mid, {})
                per[idx] = per.get(idx, "") + d["text"]
                return [self._ev(E.TextDelta, run=run, block=idx, text=d["text"])]
            if dt in _DELTA_SKIPPED:
                return self._skip("stream:" + dt)
            return None
        if et in _STREAM_SKELETON:
            if et == "message_stop":
                self._streamed.pop(o.get("api_message_id") or "", None)
            return self._skip("stream:" + et)
        return None

    # ---- 완결 메시지
    def _blocks(self, content, msg_id: str, run, role: str):
        """(Message 블록들, 도구 호출 이벤트들, 도구 결과 이벤트들)."""
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        streamed = list((self._streamed.get(msg_id) or {}).values()) if role == "assistant" else []
        blocks, calls, results = [], [], []
        for b in content:
            bt = b.get("type")
            if bt == "text":
                nb = {"type": "text", "text": b.get("text", "")}
                if nb["text"] and nb["text"] in streamed:
                    streamed.remove(nb["text"])
                    nb["shown_as"] = "text_delta"
                blocks.append(nb)
            elif bt == "thinking":
                blocks.append({"type": "thinking", "text": b.get("thinking", "")})   # signature 는 불투명해서 버린다
            elif bt == "tool_use":
                cid = b["id"]
                if run:
                    self._call_run[cid] = run
                blocks.append({"type": "tool_use", "id": cid, "name": b.get("name"), "input": b.get("input"), "shown_as": "tool_call"})
                calls.append(self._ev(E.ToolCall, run=run, call=cid, name=b.get("name") or "", input=b.get("input")))
            elif bt == "tool_result":
                cid = b["tool_use_id"]
                blocks.append({"type": "tool_result", "tool_use_id": cid, "content": b.get("content"),
                               "is_error": bool(b.get("is_error", False)), "shown_as": "tool_result"})
                results.append(self._ev(E.ToolResult, run=run, call=cid, content=b.get("content"), is_error=bool(b.get("is_error", False))))
            else:
                blocks.append(dict(b))
        return blocks, calls, results

    def _assistant(self, o: dict, run) -> list:
        m = o["message"]
        blocks, calls, _ = self._blocks(m["content"], m.get("id") or "", run, "assistant")
        return [self._ev(E.Message, run=run, role="assistant", blocks=blocks)] + calls

    def _user(self, o: dict, run) -> list:
        m = o["message"]
        blocks, _, results = self._blocks(m["content"], "", run, "user")
        return [self._ev(E.Message, run=run, role="user", blocks=blocks)] + results

    # ---- result
    def _result(self, o: dict) -> list:
        total = _num(o.get("total_cost_usd"))
        delta = None
        if total is not None:
            if self._resume_pending:     # S7 실측(2.1.318): 재개한 프로세스의 total_cost_usd 는 이전 실행분을 포함한 누적 → 첫 턴 delta 는 알 수 없다(null), 이후는 이 값 기준
                delta = None
                self._resume_pending = False
            else:
                delta = total - self._cost_total if total >= self._cost_total else total
            self._cost_total = total
        self._in_turn = False
        self._streamed.clear()
        text = o.get("result") if isinstance(o.get("result"), str) else None
        mu = o.get("model_usage_since_last_result")
        return [self._ev(E.TurnResult, ok=o.get("subtype") == "success" and not o.get("is_error", False), subtype=o.get("subtype"),
                         text=text, cost_total=total, cost_delta=delta,
                         permission_denials=list(o.get("permission_denials") or []),
                         terminal_reason=o.get("terminal_reason"), stop_reason=o.get("stop_reason"),
                         num_turns=o.get("num_turns") if isinstance(o.get("num_turns"), int) else None,
                         model_usage=mu if isinstance(mu, dict) else None)]

    # ---- control
    def _control_request(self, o: dict) -> Optional[list]:
        r = o["request"]
        if r.get("subtype") != "can_use_tool":
            return None
        rid, tool, inp, cid = o["request_id"], r["tool_name"], r.get("input"), r.get("tool_use_id")
        run = self._call_run.get(cid)
        self._req_input[rid] = inp
        qs = inp.get("questions") if isinstance(inp, dict) else None
        if tool == "AskUserQuestion" and isinstance(qs, list):
            return [self._ev(E.QuestionRequest, run=run, req=rid, questions=qs, call=cid)]
        return [self._ev(E.PermissionRequest, run=run, req=rid, tool=tool, display=r.get("display_name"), input=inp, call=cid,
                         description=r.get("description"), suggestions=list(r.get("permission_suggestions") or []))]

    def _control_response(self, o: dict) -> Optional[list]:
        r = o["response"]
        rid, sub = r["request_id"], r.get("subtype")
        if sub == "success":
            return [self._ev(E.Notice, level="info", text=f"백엔드가 요청 {rid} 를 처리함", extra={"request_id": rid, "response": r.get("response")})]
        if sub == "error":
            return [self._ev(E.Notice, level="error", text=f"백엔드가 요청 {rid} 를 거부함: {r.get('error')}", extra={"request_id": rid})]
        return None
