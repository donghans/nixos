"""llmcards — llmui 「8 카드」 탭: 결정 카드 목록·체크·논의 세션 시작·상세(근거 대조)·근거 팝업·이력·승격.
설계·결정: `donghans ctx doc read --project nixos plan llm-trust/02-card-skill-ui` (S4).

순수 함수(`launch_prompt`·`promote_body`)는 시험하기 쉽게 분리했고, 화면 쪽(`CardsMixin`·`CardScreen`·`HistoryScreen`·`EvidenceScreen`)은 llmui.LlmUI 가 섞어 쓴다.
승격(draft→reviewed→adopted)은 **사람(TTY)만** 한다: 쓰기 가드는 `ctx doc propose` CLI 쪽에 있어서, 여기서는 가드(`ctxcards.guard_proposal(human=True)`)를
프로세스 안에서 직접 부른 뒤 `ctx_store.propose` 로 제안한다(subprocess 로 CLI 를 부르면 TTY 가 아니라 에이전트 경로로 판정돼 거부된다). 제한 모드(LLM 세션이 실행)는 막는다."""
from __future__ import annotations

import datetime
import os
import re
import sys

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static

import ctxcards as cx
import ctx_store as st
import llm_ctx as cc

try:
    import tmuxsess as tm                          # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../llm-sessions
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm-sessions"))
    import tmuxsess as tm

STATES = [None, "draft", "reviewed", "adopted"]
NEXT_STATE = {"draft": "reviewed", "reviewed": "adopted"}
STATE_LABEL = {"draft": "초안(에이전트 제안)", "reviewed": "사용자 확인", "adopted": "반영됨", "unknown": "미정"}
STATE_STYLE = {"draft": "#b8a46a", "reviewed": "#33ccff", "adopted": "#5fd75f", "unknown": "#9a9a9a"}
CARD_DIR_ENV = "LLMUI_CARD_DIR"                    # 카드 논의 세션을 시작할 디렉터리(기본 ~/nixos — 카드 스킬이 있는 저장소)


def card_dir() -> str:
    return os.path.expanduser(os.environ.get(CARD_DIR_ENV) or "~/nixos")


def launch_prompt(refs: list[str], issue: str = "") -> str:
    """새 세션의 초기 프롬프트: `/donghans-card 프로젝트:uuid8 […] 쟁점…`(슬래시로 시작해야 스킬로 실행된다 — S0 실험). 쟁점의 줄바꿈은 공백으로."""
    one = re.sub(r"\s+", " ", issue or "").strip()
    return "/donghans-card " + " ".join(refs) + (" " + one if one else "")


def promote_body(row: dict, target: str, today: str, who: str) -> tuple[str, dict]:
    """승격 제안 본문 = (머리말 state 를 target 으로 + 본문 `last_confirmed` 채움 + `## 이력` 한 줄). 반환: (본문 전체, 새 머리말)."""
    hdr = dict(row["meta"])
    prev = hdr.get("state", "unknown")
    hdr["state"] = target
    text = row["body"]
    if re.search(r"(?m)^last_confirmed:", text):
        text = re.sub(r"(?m)^(last_confirmed:)[^\n]*$", lambda m: f"{m.group(1)} {today}", text, count=1)
    else:                                          # 자체 머리말 끝(`---`) 바로 앞에 넣는다. 머리말이 없으면 건드리지 않는다
        m = cx._FM.match(text)
        if m:
            text = text[:m.end(1)] + f"\nlast_confirmed: {today}" + text[m.end(1):]
    text = cx.append_history(text, f"- {today} · 사용자 확인({who}): {prev} → {target}")
    return st.render_header(hdr) + text, hdr


def fmt_day(iso: str) -> str:
    return (iso or "")[:10]


# ---------------------------------------------------------------- 화면
class EvidenceScreen(ModalScreen):
    """근거 한 건의 메시지 전체 본문(팝업). 제한 모드·치환 켬이면 비밀은 [protected]."""
    BINDINGS = [Binding("escape", "close", "닫기"), Binding("enter", "close", "닫기", show=False)]

    def __init__(self, app_ref, ev: dict):
        super().__init__()
        self.ctx_app, self.ev = app_ref, ev

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Static("", id="ev-head")
            with VerticalScroll(id="ev-scroll"):
                yield Static("", id="ev-text")

    def on_mount(self):
        mk, e = self.ctx_app.masker(), self.ev
        m = e["meta"] if isinstance(e.get("meta"), dict) else {}
        where = f" · 세션 {m['session'][:8]} · {m['ts'].astimezone():%Y-%m-%d %H:%M}" if m else ""
        self.query_one("#ev-head", Static).update(Text(f"[msg:{e['uuid'][:8]}] {e['status']}{where}  ·  Esc 닫기", style="bold #33ccff"))
        body = e.get("text")
        self.query_one("#ev-text", Static).update(Text(mk.text(body) if body is not None else f"(본문 없음 — {e['status']})"))

    def action_close(self):
        self.dismiss()


class HistoryScreen(ModalScreen):
    """카드 이력(git log 처럼): 왼쪽 판 목록, 오른쪽 선택한 판의 diff. 읽기 전용."""
    BINDINGS = [Binding("escape", "close", "닫기")]

    def __init__(self, app_ref, row: dict):
        super().__init__()
        self.ctx_app, self.row, self.revs = app_ref, row, []

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Static("", id="hist-head")
            with Horizontal(id="hist-body"):
                yield DataTable(id="hist-table", cursor_type="row")
                with VerticalScroll(id="hist-diff-box"):
                    yield Static("", id="hist-diff")

    def on_mount(self):
        r = self.row
        self.revs = cx.history(self.ctx_app.store(), r["project"], r["name"])
        self.query_one("#hist-head", Static).update(Text(f"{cx.ref_of(r)} 이력 {len(self.revs)}판 · 위가 최신 · 강등은 ▼ 표시 · Esc 닫기", style="bold #33ccff"))
        tb = self.query_one("#hist-table", DataTable)
        tb.add_columns("판", "날짜", "상태", "내용")
        for i, v in enumerate(self.revs):
            tb.add_row(v["short"], fmt_day(v["date"]), Text(("▼ " if v["demoted"] else "") + v["state"], style=STATE_STYLE.get(v["state"], "")), v["subject"][:12], key=str(i))
        if self.revs:
            tb.focus()
            self.show(0)
        else:
            self.query_one("#hist-diff", Static).update("(이력 없음 — 아직 커밋되지 않았거나 저장소가 이 머신에 없다)")

    def show(self, i: int):
        v = self.revs[i]
        prev = self.revs[i + 1] if i + 1 < len(self.revs) else None
        out = Text()
        for line in cx.revision_diff(self.ctx_app.store(), self.row["project"], v, prev).split("\n"):
            style = "#5fd75f" if line.startswith("+") and not line.startswith("+++") else "#ff6e6e" if line.startswith("-") and not line.startswith("---") else "#33ccff" if line.startswith("@@") else "#cfcfcf"
            out.append(self.ctx_app.masker().text(line) + "\n", style=style)
        self.query_one("#hist-diff", Static).update(out)

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted):
        if ev.data_table.id == "hist-table" and ev.row_key and ev.row_key.value is not None:
            self.show(int(ev.row_key.value))

    def action_close(self):
        self.dismiss()


class CardScreen(ModalScreen):
    """카드 상세: 머리말·본문, 근거별 원문 대조(일치/미일치/…), 근거에서 Enter → 원문 팝업, h 이력, F2 승격(사람만)."""
    BINDINGS = [Binding("escape", "close", "닫기"), Binding("h", "history", "이력"), Binding("f2", "promote", "승격(사람만)"), Binding("f6", "copy", "복사")]

    def __init__(self, app_ref, row: dict):
        super().__init__()
        self.ctx_app, self.row, self.res = app_ref, row, []

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Static("", id="card-head")
            with VerticalScroll(id="card-body-box"):
                yield Static("", id="card-body")
            yield DataTable(id="ev-table", cursor_type="row")
            yield Static("Enter: 근거 원문 팝업 · h 이력 · F2 승격 · F6 복사 · Esc 닫기", id="card-keys", classes="state")

    def on_mount(self):
        self.query_one("#ev-table", DataTable).add_columns("메시지", "대조", "인용/설명")
        self.fill()

    def fill(self):
        r = self.row
        cm, hm = r["card"]["meta"], r["meta"]
        state = hm.get("state", "unknown")
        mk = self.ctx_app.masker()
        head = Text()
        head.append(f"{cx.ref_of(r)}  ", style="bold #33ccff")
        head.append(f"{STATE_LABEL.get(state, state)}", style=STATE_STYLE.get(state, ""))
        head.append(f" · {cm.get('kind', '?')} · {hm.get('scope', 'unknown')} · 제안자 {cm.get('proposer', '?')} — {mk.text(str(cm.get('title', '(제목 없음)')))}\n")
        if r["problems"]:
            head.append("⚠ 형식 문제: " + " / ".join(r["problems"]) + "\n", style="#ff6e6e")
        self.query_one("#card-head", Static).update(head)
        self.query_one("#card-body", Static).update(Text(mk.text(r["body"])))
        try:
            with cc.connect(readonly=True) as c:
                self.res = cx.check_evidence(r["card"], cc._card_fetch(c))
        except Exception as e:
            self.res = []
            self.ctx_app.flash(f"근거 대조 실패(DB): {e}", "error")
        tb = self.query_one("#ev-table", DataTable)
        tb.clear()
        for i, x in enumerate(self.res):
            e = r["card"]["evidence"][i]
            bad = x["status"] in ("미일치", "메시지 없음", "모호")
            tb.add_row(x["uuid"][:8], Text(x["status"], style="#ff6e6e" if bad else "#5fd75f" if x["status"] == "일치" else "#b8a46a"), mk.text((e["quote"] or e["note"] or "")[:80]), key=str(i))
        tb.focus()

    def on_data_table_row_selected(self, ev: DataTable.RowSelected):
        if ev.data_table.id == "ev-table" and ev.row_key and ev.row_key.value is not None:
            self.ctx_app.push_screen(EvidenceScreen(self.ctx_app, self.res[int(ev.row_key.value)]))

    def action_close(self):
        self.dismiss()

    def action_history(self):
        self.ctx_app.push_screen(HistoryScreen(self.ctx_app, self.row))

    def action_copy(self):
        self.ctx_app.copy_to_clipboard(self.ctx_app.masker().text(self.row["body"]))
        self.ctx_app.flash("카드 본문을 복사했습니다" + ("" if self.ctx_app.mask else " (원문)"))

    def action_promote(self):
        self.ctx_app.promote_card(self.row, done=self.after_promote)

    def after_promote(self):
        got = cx.find_cards(self.ctx_app.store(), cx.ref_of(self.row))[0]
        if got:
            self.row = got[0]
            self.fill()


# ---------------------------------------------------------------- 탭
class CardsMixin:
    """LlmUI 에 섞는다: 「8 카드」 탭. 상태 `card_checked`(체크한 카드 ref), 필터 `card_state`·`card_scope`."""

    CARD_ACTIONS = {"card_toggle": {"cards"}, "card_state_cycle": {"cards"}, "card_scope_cycle": {"cards"}}

    def cards_setup(self):
        self.card_rows: dict[str, dict] = {}
        self.card_checked: list[str] = []
        self.card_state, self.card_scope = None, None
        self.card_skipped: list[str] = []

    def cards_widgets(self):
        yield Static("", id="card-state", classes="state")
        yield DataTable(id="cards-table", cursor_type="row")
        with Vertical(id="card-bottom"):
            yield Input(placeholder="논의할 쟁점(선택) — 비워도 된다", id="card-issue")
            with Horizontal(id="card-buttons"):
                yield Button("확인(논의 세션 시작)", id="card-go", variant="primary")
                yield Button("전체 해제", id="card-clear")
            yield Static("", id="card-warn", classes="state")

    def cards_mount(self):
        self.query_one("#cards-table", DataTable).add_columns("✓", "카드", "종류", "범위", "상태", "제목")
        self.query_one("#card-bottom").display = False

    def store(self) -> str:
        return st.store_dir()

    # --- 목록
    def reload_cards(self):
        try:
            rows, skipped = cx.find_cards(self.store())
        except Exception as e:
            self.flash(f"카드를 읽지 못했다: {e}", "error"); return
        self.card_rows = {cx.ref_of(r): r for r in rows}
        self.card_skipped = skipped
        self.card_checked = [k for k in self.card_checked if k in self.card_rows]
        self.render_cards()

    def card_visible(self):
        out = []
        for ref, r in sorted(self.card_rows.items()):
            if self.card_state and r["meta"].get("state", "unknown") != self.card_state:
                continue
            if self.card_scope and r["meta"].get("scope", "unknown") != self.card_scope:
                continue
            out.append((ref, r))
        return out

    def render_cards(self):
        tb, mk = self.query_one("#cards-table", DataTable), self.masker()
        keep = self.selected_key("#cards-table")
        tb.clear()
        vis = self.card_visible()
        for ref, r in vis:
            state = r["meta"].get("state", "unknown")
            tb.add_row("✓" if ref in self.card_checked else " ", ref, r["card"]["meta"].get("kind", "?"), r["meta"].get("scope", "unknown"),
                       Text(state, style=STATE_STYLE.get(state, "")), mk.text(str(r["card"]["meta"].get("title", "(제목 없음)")))[:80], key=ref)
        keys = [ref for ref, _ in vis]
        if keep in keys:
            tb.move_cursor(row=keys.index(keep))
        skip = f" · 이 머신에 저장소가 없어 건너뜀: {', '.join(self.card_skipped)}" if self.card_skipped else ""
        self.query_one("#card-state", Static).update(
            f"카드 {len(vis)}/{len(self.card_rows)}장 · 상태: {self.card_state or '전체'} (F2) · 범위: {self.card_scope or '전체'} (F3) · 체크 {len(self.card_checked)}장{skip}")
        self.query_one("#cards-table").border_title = "결정 카드 — Space: 체크 · Enter: 상세(근거 대조·이력·승격)"
        self.update_card_bottom()

    def update_card_bottom(self):
        """체크가 1장 이상일 때만 하단(쟁점 입력·확인·전체 해제)을 보인다(사용자 결정 D-11)."""
        n = len(self.card_checked)
        self.query_one("#card-bottom").display = n > 0
        self.query_one("#card-go", Button).disabled = n == 0 or self.restricted
        self.query_one("#card-warn", Static).update(
            f"{n}장 선택 — 확인하면 {card_dir()} 에서 새 claude 세션이 권한 확인 없이(--dangerously-skip-permissions) 시작됩니다" if not self.restricted
            else "제한 모드(LLM 세션): 논의 세션 시작은 사람이 터미널에서 직접 실행할 때만 쓸 수 있습니다")

    # --- 동작
    def action_card_toggle(self):
        if self.current_tab() != "cards" or len(self.screen_stack) != 1 or not isinstance(self.focused, DataTable) or self.focused.id != "cards-table":
            return
        ref = self.selected_key("#cards-table")
        if not ref:
            return
        if ref in self.card_checked:
            self.card_checked.remove(ref)
        else:
            self.card_checked.append(ref)
        self.render_cards()

    def action_card_state_cycle(self):
        self.card_state = STATES[(STATES.index(self.card_state) + 1) % len(STATES)]
        self.render_cards()

    def action_card_scope_cycle(self):
        scopes = [None, *sorted({r["meta"].get("scope", "unknown") for r in self.card_rows.values()})]
        self.card_scope = scopes[(scopes.index(self.card_scope) + 1) % len(scopes)] if self.card_scope in scopes else None
        self.render_cards()

    def clear_card_checks(self):
        self.card_checked = []
        self.render_cards()

    def open_card(self, ref: str):
        r = self.card_rows.get(ref)
        if r:
            self.push_screen(CardScreen(self, r))

    def launch_card_session(self):
        """체크한 카드로 논의 세션을 시작한다. 성공하면 True. 제한 모드·디렉터리 없음·tmux 실패는 알리고 False."""
        if self.deny("카드 논의 세션 시작"):
            return False
        if not self.card_checked:
            return False
        issue = self.query_one("#card-issue", Input).value
        d = card_dir()
        try:
            name = tm.create(d, tm.with_defaults([]) + [launch_prompt(list(self.card_checked), issue)])
        except RuntimeError as e:
            self.flash(f"세션을 시작하지 못했습니다: {e}", "error"); return False
        self.flash(f"논의 세션을 시작했습니다: {name} — 7 세션 탭에서 붙으세요")
        self.query_one("#card-issue", Input).value = ""
        self.clear_card_checks()
        self.action_tab("sessions")
        return True

    def promote_card(self, row: dict, done=None):
        """draft→reviewed→adopted. 사람만(제한 모드 차단). 확인창 → 가드(human=True) → propose. 동기화 담당이 없는 호스트(노트북)는 DB 대기열로 보낸다(ctx_docqueue.submit)."""
        if self.deny("카드 승격(사용자 확인)"):
            return
        state = row["meta"].get("state", "unknown")
        target = NEXT_STATE.get(state)
        if not target:
            self.flash(f"{STATE_LABEL.get(state, state)} 카드는 더 올릴 단계가 없습니다" if state == "adopted" else f"상태가 {state} 라 승격할 수 없습니다 — 먼저 draft 로 만드세요", "warning"); return
        if row["problems"]:
            self.flash("형식 문제가 있는 카드는 승격할 수 없습니다: " + row["problems"][0], "error"); return

        def go(yes):
            if yes:
                self.do_promote(row, target)
                if done:
                    done()
        import uikit
        self.push_screen(uikit.ConfirmScreen(f"{cx.ref_of(row)} 를 {state} → {target} 로 올릴까요? (내가 읽고 확인했다는 뜻)"), go)

    def do_promote(self, row: dict, target: str) -> tuple[bool, str]:
        import ctx_doccli as dc
        store, today = self.store(), datetime.date.today().isoformat()
        cur = st.read_doc(store, row["project"], "note", row["name"])
        if not cur or cur["hash"] != row["hash"]:
            msg = "카드가 그사이 바뀌었습니다 — 새로고침(F5) 후 다시 확인하세요"
            self.flash(msg, "error"); return False, msg
        body, _hdr = promote_body(row, target, today, "llmui")
        man = st.load_manifest(store)
        conn = {}

        def evidence_project(u8):
            if "c" not in conn:
                conn["c"] = cc.connect(readonly=True)
            r = conn["c"].execute("SELECT s.repo_url FROM messages m JOIN sessions s USING (session_id) WHERE m.uuid LIKE %s LIMIT 1", (u8 + "%",)).fetchone()
            if not r:
                return None, False
            url = cc.norm_repo(r[0]) if r[0] else None
            return next(((p, True) for p, m in man.items() if url and m.get("repo_url") and cc.norm_repo(m["repo_url"]) == url), (None, True))
        try:
            new_body, errors, _warns = cx.guard_proposal(body, cur, human=True, project=row["project"], name=row["name"], manifest=man, evidence_project=evidence_project,
                                                         session="llmui", host=cc.HOST, today=today)
        finally:
            if "c" in conn:
                conn["c"].close()
        if errors:
            msg = "가드가 거부했습니다: " + " / ".join(errors)
            self.flash(msg, "error"); return False, msg
        import ctx_docqueue as dq
        import ctx_secrets as cs
        code, msg, pid = dq.submit(store, f"llmui-{cc.HOST}", cc.HOST, row["project"], "note", row["name"], new_body, row["hash"], "write", cc.connect, cs.load_masker)
        if code:
            self.flash(msg, "error"); return False, msg
        if pid and pid.startswith("outbox:"):
            self.flash(msg, "warning"); return True, msg
        if dq.use_queue():                                           # 읽기 뷰 호스트: DB 대기열 — 정본 호스트의 동기화 담당이 반영한다
            r = dq.wait_row(cc.connect, pid, float(os.environ.get("CTX_PROPOSE_WAIT", dq.WAIT_DEFAULT)))
            if not r or r["status"] in dq.OPEN_STATUSES:
                msg = "제안을 대기열에 넣었지만 아직 반영되지 않았습니다(서버의 동기화 담당이 처리하면 반영됩니다)"
                self.flash(msg, "warning"); return True, msg
            self.flash(r["msg"], "information" if r["status"] in dq.OK_STATUSES else "error")
            self.reload_cards()
            return r["status"] in dq.OK_STATUSES, r["msg"]
        if os.environ.get("CTX_SYNC_INLINE"):                      # 시험·동기화 담당 없는 호스트(`ctx doc propose` 와 같은 규칙)
            try:                                                   # ctx_doccli._inline_sync 는 llm_ctx 가 넘겨 준 도우미(H)가 필요해 여기서는 직접 한다
                import ctx_secrets as cs
                with cc.connect(readonly=True) as c:
                    st.process_inbox(store, cs.load_masker(c))
            except Exception as e:
                self.flash(f"비밀 검사기를 못 써서 처리하지 않고 대기시킵니다({type(e).__name__})", "warning")
            worker = True
        else:
            worker = dc._wake_worker()
        r = st.wait_result(store, pid, 10.0 if worker else 0.2)
        if not r:
            msg = "제안을 남겼지만 이 호스트에는 동기화 담당이 없어 아직 반영되지 않았습니다" if not worker else "제안을 남겼습니다(대기 중)"
            self.flash(msg, "warning"); return True, msg
        self.flash(r["msg"], "information" if r["status"] in ("applied", "same") else "error")
        self.reload_cards()
        return r["status"] in ("applied", "same"), r["msg"]
