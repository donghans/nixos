#!/usr/bin/env python3
"""ctxui — donghans 공유 컨텍스트(ctx) 관리 TUI.

  1 개요   저장소(프로젝트)별 쌓인 세션·메시지 수와 용량, DB 크기          (Enter: 그 저장소로 검색)
  2 검색   키워드·정규식 검색, 저장소·기간·역할 필터                       (Enter: 앞뒤 대화 보기)
  3 대조   같은 문구를 저장소별로 묶어 「내가 그렇게 말했나」 교차검증      (사용자 발언 기준)
  4 비밀   등록된 비밀(출력 시 [protected] 로 치환) 관리: 추가·끄기·삭제
  5 후보   키·비밀번호처럼 보이는 문자열 자동 탐지 → 승인(등록)·무시

원문(DB)은 바꾸지 않는다. 화면의 치환(m)은 어깨너머 노출을 막는 용도이고 기본 켜짐이다. 사람이 터미널에서 직접 쓰는 도구라 TTY 가 아니면 실행하지 않는다.
등록한 비밀은 `donghans ctx …` 출력과 `donghans secret run` 출력에서 치환되고, 로컬 트랜스크립트는 `donghans secret scrub` 으로 바꾼다.
"""
from __future__ import annotations

import os
import sys

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TabbedContent, TabPane

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../_uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_uikit"))
    import uikit

import claude_ctx as cc
import ctx_secrets as cs
import ctxdata as cd

TABS = [("overview", "개요"), ("search", "검색"), ("verify", "대조"), ("secrets", "비밀"), ("cands", "후보")]


def short_repo(url: str | None) -> str:
    if not url:
        return "(저장소 없음)"
    return url.replace("https://github.com/", "gh:").replace("https://", "")


def fmt_ts(ts) -> str:
    return ts.astimezone().strftime("%m-%d %H:%M") if ts else "-"


# ---------------------------------------------------------------- 대화상자
class PromptScreen(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "취소")]

    def __init__(self, title: str, hint: str = "", password: bool = False, value: str = ""):
        super().__init__()
        self._title, self._hint, self._password, self._value = title, hint, password, value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Input(value=self._value, password=self._password, id="prompt-input")
            yield Static(self._hint + ("  ·  Enter 확인 · Esc 취소" if self._hint else "Enter 확인 · Esc 취소"), id="dialog-hint")

    def on_mount(self):
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted):
        self.dismiss(ev.value)

    def action_cancel(self):
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    BINDINGS = [Binding("y,enter", "yes", "예"), Binding("n,escape", "no", "아니오")]

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._message, id="dialog-title")
            yield Static("y / Enter 확인 · n / Esc 취소", id="dialog-hint")

    def action_yes(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


class SessionScreen(ModalScreen):
    """한 메시지 앞뒤의 대화. m 으로 치환 켬/끔."""
    BINDINGS = [Binding("escape,q", "close", "닫기"), Binding("m", "toggle_mask", "치환 켬/끔")]

    def __init__(self, app_ref, session_id: str, uuid: str | None):
        super().__init__()
        self.ctx_app, self.session_id, self.uuid = app_ref, session_id, uuid

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="stats-box"):
            yield Static("", id="session-body")

    def on_mount(self):
        self.render_body()

    def action_close(self):
        self.dismiss()

    def action_toggle_mask(self):
        self.ctx_app.action_toggle_mask()
        self.render_body()

    def render_body(self):
        with cc.connect(readonly=True) as c:
            s, msgs = cd.session_context(c, self.session_id, self.uuid, 12, masker=self.ctx_app.masker())
        t = Text()
        if not s:
            t.append("세션을 찾지 못했다")
        else:
            t.append(f"{s['session_id']}  @{s['host']}  {short_repo(s['repo'])}#{s['branch'] or '-'}\n", style="bold #33ccff")
            t.append(f"{s['cwd'] or ''}   {fmt_ts(s['first'])} ~ {fmt_ts(s['last'])}   치환 {'켜짐' if self.ctx_app.mask else '꺼짐(원문 표시 중)'}\n\n", style="#9a9a9a")
            for m in msgs:
                hit = m["uuid"] == self.uuid
                t.append(f"{'▶ ' if hit else '  '}[{fmt_ts(m['ts'])}] {m['role']}{'(sub)' if m['side'] else ''}\n", style="bold #b8a46a" if hit else "#7a7a7a")
                t.append((m["text"].strip()[:1800] or "(빈 내용)") + "\n\n", style="#ffffff" if hit else "#cfcfcf")
        self.query_one("#session-body", Static).update(t)


# ---------------------------------------------------------------- 앱
class CtxUI(uikit.HelpMixin, App):
    TITLE = "ctxui — 공유 컨텍스트 관리"
    CSS = uikit.BASE_CSS + uikit.DIALOG_CSS + """
    PromptScreen, ConfirmScreen, SessionScreen { align: center middle; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    DataTable { height: 1fr; }
    #ovhead { height: auto; padding: 0 1; }
    .filters { height: 3; }
    .filters Input { width: 1fr; }
    #days, #fdays { width: 10; }
    .state { height: 1; color: #9a9a9a; padding: 0 1; }
    #verify-tables { height: 1fr; }
    #verify-tables DataTable { width: 1fr; }
    #sdetail, #cdetail { height: auto; max-height: 4; padding: 0 1; color: #b8a46a; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('overview')", "개요"), Binding("2", "tab('search')", "검색"), Binding("3", "tab('verify')", "대조"),
        Binding("4", "tab('secrets')", "비밀"), Binding("5", "tab('cands')", "후보"),
        Binding("escape", "focus_table", "목록으로", show=False),
        Binding("m", "toggle_mask", "치환 켬/끔"), Binding("r,f5", "reload", "새로고침"),
        Binding("f2", "toggle_role", "역할(사용자만)", show=False), Binding("f3", "toggle_regex", "정규식", show=False),
        Binding("a", "secret_add", "비밀 추가", show=False), Binding("d", "secret_delete", "삭제", show=False), Binding("e", "secret_toggle", "켬/끔", show=False),
        Binding("v", "reveal", "값 보기", show=False), Binding("i", "cand_ignore", "무시", show=False),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self):
        super().__init__()
        self.mask = True
        self.only_user = False
        self.regex = False
        self.cand_rows: dict[str, dict] = {}
        self.sec_rows: dict[str, dict] = {}
        self._reveal = False

    # --- 구성
    def compose(self) -> ComposeResult:
        with TabbedContent(initial="overview", id="tabs"):
            with TabPane("1 개요", id="overview"):
                yield uikit.box(Static("", id="ovhead"), "전체 · 표별 용량")
                yield uikit.box(DataTable(id="projects", cursor_type="row", zebra_stripes=False), "저장소(프로젝트)별 — Enter: 이 저장소 검색")
            with TabPane("2 검색", id="search"):
                with Horizontal(classes="filters"):
                    yield uikit.box(Input(placeholder="검색어 (Enter)", id="q"), "검색어")
                    yield uikit.box(Input(placeholder="저장소 일부", id="repo"), "저장소")
                    yield uikit.box(Input(placeholder="일", id="days"), "기간")
                yield Static("", id="sstate", classes="state")
                yield uikit.box(DataTable(id="results", cursor_type="row"), "결과 — Enter: 앞뒤 대화")
            with TabPane("3 대조", id="verify"):
                yield uikit.box(Input(placeholder="사용자가 했던 말(문구) — Enter", id="phrase"), "문구 대조 — 사용자 발언만")
                with Horizontal(id="verify-tables"):
                    yield uikit.box(DataTable(id="vrepos", cursor_type="row"), "저장소별")
                    yield uikit.box(DataTable(id="vhits", cursor_type="row"), "발언 — Enter: 앞뒤 대화")
            with TabPane("4 비밀", id="secrets"):
                yield uikit.box(DataTable(id="secrets-table", cursor_type="row"), "등록된 비밀 — a 추가 · e 켬/끔 · d 삭제 · v 값 보기")
                yield Static("", id="sdetail")
            with TabPane("5 후보", id="cands"):
                yield uikit.box(DataTable(id="cands-table", cursor_type="row"), "자동 탐지 후보 — Enter 승인(등록) · i 무시 · v 값 보기 · r 다시 탐지")
                yield Static("", id="cdetail")
        yield Footer()

    def on_mount(self):
        self.query_one("#projects", DataTable).add_columns("저장소", "세션", "메시지", "프롬프트", "텍스트", "저장 용량", "마지막", "머신")
        self.query_one("#results", DataTable).add_columns("시각", "역할", "저장소", "세션", "내용")
        self.query_one("#vrepos", DataTable).add_columns("저장소", "건수", "세션", "최근", "대표 인용")
        self.query_one("#vhits", DataTable).add_columns("시각", "세션", "내용")
        self.query_one("#secrets-table", DataTable).add_columns("이름", "종류", "상태", "길이", "fp", "원문 포함 메시지")
        self.query_one("#cands-table", DataTable).add_columns("fp", "종류", "미리보기", "횟수", "세션", "저장소", "최근")
        self.update_state()
        self.reload_overview()

    # --- 공통
    def masker(self):
        if not self.mask:
            return cs.IDENTITY
        try:
            with cc.connect(readonly=True) as c:
                return cs.load_masker(c)
        except Exception:
            return cs.IDENTITY

    def current_tab(self) -> str:
        return self.query_one("#tabs", TabbedContent).active

    def flash(self, msg: str, severity="information"):
        self.notify(msg, severity=severity, timeout=5)

    def action_tab(self, name: str):
        self.query_one("#tabs", TabbedContent).active = name
        self.call_after_refresh(self.action_focus_table)
        self.on_tab_shown(name)

    def on_tabbed_content_tab_activated(self, ev: TabbedContent.TabActivated):
        self.on_tab_shown(ev.pane.id)

    def on_tab_shown(self, name: str):
        if name == "secrets":
            self.reload_secrets()
        elif name == "cands" and not self.cand_rows:
            self.scan_candidates()
        elif name == "overview":
            self.reload_overview()

    def action_focus_table(self):
        ids = {"overview": "#projects", "search": "#results", "verify": "#vrepos", "secrets": "#secrets-table", "cands": "#cands-table"}
        try:
            self.query_one(ids[self.current_tab()]).focus()
        except Exception:
            pass

    def action_toggle_mask(self):
        self.mask = not self.mask
        self.flash("치환 " + ("켜짐" if self.mask else "꺼짐 — 화면에 원문이 보입니다"), "information" if self.mask else "warning")
        self.update_state()
        self.action_reload()

    def action_reload(self):
        t = self.current_tab()
        {"overview": self.reload_overview, "search": self.run_search, "verify": self.run_verify, "secrets": self.reload_secrets, "cands": self.scan_candidates}[t]()

    def update_state(self):
        self.query_one("#sstate", Static).update(
            f"역할: {'사용자만' if self.only_user else '전체'} (F2)   ·   정규식: {'켜짐' if self.regex else '꺼짐'} (F3)   ·   치환: {'켜짐' if self.mask else '꺼짐'} (m)")

    def action_toggle_role(self):
        self.only_user = not self.only_user
        self.update_state()

    def action_toggle_regex(self):
        self.regex = not self.regex
        self.update_state()

    # --- 개요
    def reload_overview(self):
        try:
            with cc.connect(readonly=True) as c:
                ov = cd.overview(c)
        except Exception as e:
            self.flash(f"DB 조회 실패: {e}", "error"); return
        t = ov["totals"]
        head = Text()
        head.append(f"세션 {t['sessions']:,} · 메시지 {t['messages']:,} · 프롬프트 {t['prompts']:,} · 텍스트 {cd.human_bytes(t['text_chars'])} · DB {cd.human_bytes(t['db_bytes'])}\n", style="bold")
        head.append("표별: " + "  ".join(f"{x['name']} {cd.human_bytes(x['bytes'])}" for x in ov["tables"][:6]), style="#9a9a9a")
        self.query_one("#ovhead", Static).update(head)
        tb = self.query_one("#projects", DataTable)
        tb.clear()
        for p in ov["projects"]:
            tb.add_row(short_repo(p["repo"]), f"{p['sessions']:,}", f"{p['messages']:,}", f"{p['prompts']:,}", cd.human_bytes(p["text_chars"]),
                       cd.human_bytes(p["stored_bytes"]), fmt_ts(p["last_ts"]), ",".join(p["hosts"]), key=p["repo"])

    def on_data_table_row_selected(self, ev: DataTable.RowSelected):
        tid, key = ev.data_table.id, (ev.row_key.value if ev.row_key else None)
        if tid == "projects":
            repo = key if key and key != "(저장소 없음)" else ""
            self.query_one("#repo", Input).value = repo.replace("https://github.com/", "") if repo else ""
            self.action_tab("search")
            self.run_search()
        elif tid in ("results", "vhits"):
            sid, _, uid = (key or "").partition("|")
            if sid:
                self.push_screen(SessionScreen(self, sid, uid or None))
        elif tid == "vrepos":
            self.query_one("#vhits", DataTable).focus()
        elif tid == "cands-table":
            self.adopt_selected()

    # --- 검색
    def on_input_submitted(self, ev: Input.Submitted):
        if ev.input.id in ("q", "repo", "days"):
            self.run_search()
        elif ev.input.id == "phrase":
            self.run_verify()

    def run_search(self):
        q = self.query_one("#q", Input).value.strip()
        repo = self.query_one("#repo", Input).value.strip() or None
        dv = self.query_one("#days", Input).value.strip()
        days = int(dv) if dv.isdigit() else None
        tb = self.query_one("#results", DataTable)
        try:
            with cc.connect(readonly=True) as c:
                rows = cd.search(c, q, regex=self.regex, repo=repo, role="user" if self.only_user else None, days=days, limit=300, masker=self.masker())
        except ValueError as e:
            self.flash(str(e), "error"); return   # 잘못된 입력이면 이전 결과를 지우지 않는다
        tb.clear()
        for r in rows:
            tb.add_row(fmt_ts(r["ts"]), r["role"], short_repo(r["repo"]), r["session_id"][:8], r["snippet"][:160], key=f"{r['session_id']}|{r['uuid']}")
        self.query_one("#results").border_title = f"결과 {len(rows)}건" + (" (최대 300)" if len(rows) >= 300 else "") + " — Enter: 앞뒤 대화"
        if rows:
            tb.focus()

    # --- 대조
    def run_verify(self):
        phrase = self.query_one("#phrase", Input).value.strip()
        vr, vh = self.query_one("#vrepos", DataTable), self.query_one("#vhits", DataTable)
        if not phrase:
            vr.clear(); vh.clear(); return
        try:
            with cc.connect(readonly=True) as c:
                groups = cd.phrase_by_repo(c, phrase, regex=self.regex, role="user", masker=self.masker())
        except ValueError as e:
            self.flash(str(e), "error"); return   # 잘못된 입력이면 이전 결과를 지우지 않는다
        vr.clear(); vh.clear()
        self._verify_hits = {g["repo"]: g["hits"] for g in groups}
        for g in groups:
            vr.add_row(short_repo(g["repo"]), g["count"], g["sessions"], fmt_ts(g["last"]), g["quote"][:80], key=g["repo"])
        self.query_one("#vrepos").border_title = f"저장소별 — {sum(g['count'] for g in groups)}건 / {len(groups)}곳"
        if groups:
            vr.focus()
            self.show_verify_hits(groups[0]["repo"])

    def show_verify_hits(self, repo):
        vh = self.query_one("#vhits", DataTable)
        vh.clear()
        for r in getattr(self, "_verify_hits", {}).get(repo, [])[:300]:
            vh.add_row(fmt_ts(r["ts"]), r["session_id"][:8], r["snippet"][:140], key=f"{r['session_id']}|{r['uuid']}")

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted):
        if ev.data_table.id == "vrepos" and ev.row_key and ev.row_key.value:
            self.show_verify_hits(ev.row_key.value)
        elif ev.data_table.id in ("secrets-table", "cands-table"):
            self._reveal = False
            self.query_one("#sdetail" if ev.data_table.id == "secrets-table" else "#cdetail", Static).update("")

    # --- 비밀 등록표
    def reload_secrets(self):
        tb = self.query_one("#secrets-table", DataTable)
        tb.clear()
        try:
            with cc.connect(readonly=True) as c:
                rows = cd.secret_rows(c)
                counts = {r["label"]: cd.occurrences(c, r["value"], r["kind"]) for r in rows}
        except Exception as e:
            self.flash(f"DB 조회 실패: {e}", "error"); return
        self.sec_rows = {r["label"]: r for r in rows}
        for r in rows:
            tb.add_row(r["label"], r["kind"], "켜짐" if r["enabled"] else "꺼짐", r["length"], r["fp"], counts[r["label"]], key=r["label"])
        self.query_one("#secrets-table").border_title = f"등록된 비밀 {len(rows)}개 — a 추가 · e 켬/끔 · d 삭제 · v 값 보기"

    def selected_key(self, table_id):
        tb = self.query_one(table_id, DataTable)
        try:
            return tb.coordinate_to_cell_key(tb.cursor_coordinate).row_key.value
        except Exception:
            return None

    def action_secret_add(self):
        if self.current_tab() != "secrets":
            return

        def got_label(label):
            if not label:
                return

            def got_value(value):
                if not value:
                    return
                try:
                    with cc.connect() as c:
                        cs.add_secret(c, label.strip(), "literal", value)
                except ValueError as e:
                    self.flash(str(e), "error"); return
                self.flash(f"등록: {label} ({len(value)}자)")
                self.reload_secrets()
            self.push_screen(PromptScreen(f"{label} 의 값", "화면에 표시되지 않음", password=True), got_value)
        self.push_screen(PromptScreen("비밀 이름", "영문·숫자·_ (환경변수 이름이 됨)"), got_label)

    def action_secret_delete(self):
        key = self.selected_key("#secrets-table") if self.current_tab() == "secrets" else None
        if not key:
            return

        def done(yes):
            if yes:
                with cc.connect() as c:
                    cd.delete_secret(c, key)
                self.flash(f"삭제: {key}")
                self.reload_secrets()
        self.push_screen(ConfirmScreen(f"'{key}' 을(를) 등록표에서 삭제할까요? (DB 원문은 그대로)"), done)

    def action_secret_toggle(self):
        key = self.selected_key("#secrets-table") if self.current_tab() == "secrets" else None
        if not key:
            return
        with cc.connect() as c:
            cd.set_enabled(c, key, not self.sec_rows[key]["enabled"])
        self.reload_secrets()

    def action_reveal(self):
        tab = self.current_tab()
        if tab == "secrets":
            key = self.selected_key("#secrets-table")
            if key:
                self._reveal = not self._reveal
                self.query_one("#sdetail", Static).update(f"{key} = {self.sec_rows[key]['value']}" if self._reveal else "")
        elif tab == "cands":
            key = self.selected_key("#cands-table")
            if key and key in self.cand_rows:
                self._reveal = not self._reveal
                self.query_one("#cdetail", Static).update(f"{key} = {self.cand_rows[key]['value']}" if self._reveal else "")

    # --- 후보
    @work(thread=True, exclusive=True, group="scan")
    def scan_candidates(self):
        self.call_from_thread(self.flash, "후보를 탐지하는 중…")
        try:
            with cc.connect(readonly=True) as c:
                found = cd.scan_candidates(c)
        except Exception as e:
            self.call_from_thread(self.flash, f"탐지 실패: {e}", "error"); return
        self.call_from_thread(self.show_candidates, found)

    def show_candidates(self, found):
        tb = self.query_one("#cands-table", DataTable)
        tb.clear()
        self.cand_rows = {d["fp"]: d for d in found}
        for d in found:
            tb.add_row(d["fp"], d["pattern"], cs.preview(d["value"]), d["count"], len(d["sessions"]), ",".join(sorted(short_repo(r) for r in d["repos"]))[:50] or "-",
                       fmt_ts(d["last"]), key=d["fp"])
        self.query_one("#cands-table").border_title = f"자동 탐지 후보 {len(found)}개 — Enter 승인 · i 무시 · v 값 보기 · r 다시 탐지"
        self.flash(f"후보 {len(found)}개")

    def adopt_selected(self):
        key = self.selected_key("#cands-table")
        d = self.cand_rows.get(key or "")
        if not d:
            return

        def got(label):
            if not label:
                return
            try:
                with cc.connect() as c:
                    cd.adopt(c, d["value"], label.strip(), d["pattern"])
            except ValueError as e:
                self.flash(str(e), "error"); return
            self.flash(f"등록: {label} — 이제 출력에서 [protected] 로 바뀝니다")
            self.scan_candidates()
        self.push_screen(PromptScreen(f"이 후보({d['pattern']}, {len(d['value'])}자)의 이름", "영문·숫자·_ — 예: NAS_PW"), got)

    def action_cand_ignore(self):
        key = self.selected_key("#cands-table") if self.current_tab() == "cands" else None
        d = self.cand_rows.get(key or "")
        if not d:
            return
        with cc.connect() as c:
            cd.ignore_fp(c, d["fp"], d["pattern"])
        self.flash(f"무시: {d['fp']}")
        self.scan_candidates()


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or cc.is_agent_session():
        sys.exit("ctxui 는 사람이 터미널에서 직접 실행하는 도구입니다")
    CtxUI().run()


if __name__ == "__main__":
    main()
