#!/usr/bin/env python3
"""ctxui — donghans 공유 컨텍스트(ctx) 관리 TUI.

  1 대시보드  합계·표별 용량·저장소별 표(Enter: 그 저장소로 검색) + 한도 그래프·토큰/비용 추이·분류별·세션 통계·세션 표(Enter: 그 세션 대화). 저장소·머신·모델·기간 필터는 통계 칸에 적용
  2 검색   세션 기준 목록(제목·일치 건수·대표 일치) — Enter: 대화 열기, Space: 그 세션의 일치 메시지 펼침, x: 모두 펼침, F6: 제목만. 키워드·정규식, 저장소·기간·역할 필터
  3 대조   같은 문구를 저장소별로 묶어 「내가 그렇게 말했나」 교차검증      (사용자 발언 기준)
  4 비밀   등록된 비밀(출력 시 [protected] 로 치환) 관리: 추가·끄기·삭제
  5 후보   키·비밀번호처럼 보이는 문자열 자동 탐지 → 승인(등록)·무시
  6 지침   프로젝트별 지침(공유 정본 project_instructions)을 모든 저장소에 대해 보고 고친다 — 로컬 캐시 없이 DB 만 대상   (Enter: 본문 · e: 편집기)

원문(DB)은 바꾸지 않는다. 화면의 치환(m)은 어깨너머 노출을 막는 용도이고 기본 켜짐이다. TTY 가 없으면 실행하지 않는다.
**제한 모드**: LLM 세션이 실행한 경우(환경 표식 — llm_ctx.AGENT_ENV_MARKERS) 모든 탭을 볼 수 있되 비밀 값은 추출·조회할 수 없다 — 모든 텍스트에서 등록한 비밀과 비밀처럼 보이는 문자열(후보 패턴)을 [protected] 로 치환하고(끌 수 없음), 후보 표의 미리보기도 [protected](길이)로 보이며, 값 보기(v)·비밀 추가·삭제·끄기·후보 무시·지침 편집은 막힌다. 후보 승인(Enter)은 값을 보여 주지 않고 등록만 하므로 허용.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Select, Static, TabbedContent, TabPane

try:
    import uikit                                   # 배포: 같은 디렉터리에 복사됨
except ImportError:                                # 소스 트리: ../uikit
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib", "uikit"))
    import uikit

import llm_ctx as cc
import ctx_secrets as cs
import ctxchart as cch
import ctxdata as cd

TABS = [("dashboard", "대시보드"), ("search", "검색"), ("verify", "대조"), ("secrets", "비밀"), ("cands", "후보"), ("instr", "지침")]


def short_repo(url: str | None) -> str:
    if not url:
        return "(저장소 없음)"
    return url.replace("https://github.com/", "gh:").replace("https://", "")


def fmt_ts(ts) -> str:
    return ts.astimezone().strftime("%m-%d %H:%M") if ts else "-"


def fmt_num(n) -> str:
    """토큰 수 등 큰 수를 K/M/B 로 줄여 쓴다."""
    n = float(n or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def fmt_dur(sec) -> str:
    sec = float(sec or 0)
    if sec < 90:
        return f"{sec:.0f}초"
    if sec < 5400:
        return f"{sec / 60:.0f}분"
    if sec < 86400 * 2:
        return f"{sec / 3600:.1f}시간"
    return f"{sec / 86400:.1f}일"


def bar(v, vmax, width=20) -> str:
    """가로 막대(1/8 칸 단위). vmax 가 0 이면 빈 문자열."""
    if not vmax or v <= 0:
        return ""
    eighths = max(1, round(width * 8 * v / vmax))
    return "█" * (eighths // 8) + (" ▏▎▍▌▋▊▉"[eighths % 8] if eighths % 8 else "")


ACCT_COLORS = ["#33ccff", "#ffb347", "#b4e04e", "#ff6f91", "#c792ea", "#ffd166"]   # 계정마다 고정 색(계정 ID 순)


def summary_text(summ, width=46) -> Text:
    """세션 통계 칸 글. 가장 긴 줄이 1열 전환 기준(칸 폭 ≈ 화면의 1/3)보다 짧게 짧은 줄로 나누고, 그래프·막대는 width 에 맞춘다."""
    t = Text()
    n = max(summ["sessions"], 1)
    t.append(f"세션 {summ['sessions']:,}개 · 비용 ${summ['cost']:,.2f}\n", style="bold")
    t.append(f"프롬프트 {int(summ['prompts']):,} · 도구 호출 {int(summ['tools']):,}\n", style="bold")
    t.append(f"자동 메시지 {summ['autos']:,}건은 프롬프트에서 제외\n", style="#7a7a7a")
    if summ["unknown_tags"]:
        t.append(f"알 수 없는 태그 {summ['unknown_tags']:,}건(AUTO_TAGS 점검)\n", style="#7a7a7a")
    t.append(f"세션당  프롬프트 {summ['prompts'] / n:.1f} (중앙값 {summ['median_prompts']:.0f}) · ${summ['cost'] / n:.2f}\n", style="#cfcfcf")
    t.append(f"세션 길이  중앙값 {fmt_dur(summ['median_duration_s'])} · 평균 {fmt_dur(summ['avg_duration_s'])}\n", style="#cfcfcf")
    t.append("(resume 이어진 세션이 평균을 올림)\n\n", style="#7a7a7a")
    t.append("시간대별 프롬프트(15분 단위, 0~24시)\n", style="#9a9a9a")
    t.append_text(cch.slot_chart(summ["by_slot"], width, 4, "#33ccff"))
    top = sorted(range(24), key=lambda h: -summ["by_hour"][h])[:3]
    t.append("\n많은 시간: " + " ".join(f"{h}시({summ['by_hour'][h]})" for h in top if summ["by_hour"][h]) + "\n\n", style="#cfcfcf")
    t.append("요일별 프롬프트\n", style="#9a9a9a")
    wmax = max(summ["by_weekday"])
    bw = max(10, min(80, width - 9))
    for i, v in enumerate(summ["by_weekday"]):
        t.append(f"{WEEKDAYS[i]} {v:>5,} ", style="#cfcfcf")
        t.append(cch.fit_bar(v, wmax, bw) + "\n", style="#33ccff")
    t.rstrip()
    return t


LIMIT_H = 6                                            # 5h·7d 겹침 그래프 높이(줄)


def limits_text(win, width=60) -> Text:
    """계정별 한도 사용률 — 한 계정 = 한 색(밝은 짝 = 7d 선). 계정마다 그래프 하나에 5h(면적, 창 안에서 0 에서 올라가다 리셋에서 떨어지는 톱니)와 7d(윗면 선)를 같은 시간 축(7일)으로 겹친다.
    실제 샘플(5h 5분·7d 1시간 단위)로 그린다. width = 칸 폭."""
    t = Text()
    ids = sorted({a["account"] for k in win.values() for a in k})
    if not ids:
        t.append("한도 샘플 없음 — 계정·리셋 시각 수집은 상태줄 갱신 이후부터", style="#7a7a7a")
        return t
    color = {i: ACCT_COLORS[n % len(ACCT_COLORS)] for n, i in enumerate(ids)}
    for n, i in enumerate(ids):
        row = {k: next((a for a in win[k] if a["account"] == i), None) for k in win}
        ref = row["5h"] or row["7d"]
        if n:
            t.append("\n")
        c5, c7 = color[i], cch.tint(color[i])
        t.append("● ", style=c5); t.append(ref["label"], style=f"bold {c5}")
        t.append(f"  {ref['plan'] or '플랜 불명'}\n", style="#9a9a9a")
        for k, col in (("5h", c5), ("7d", c7)):
            a = row[k]
            if a and a["windows"]:
                vals = [v for _, v in a["windows"]]
                t.append(f"{k} ", style=f"bold {col}"); t.append(f"지금 {vals[-1]:.0f}% 최고 {max(vals):.0f}% ({len(vals)}창)   " if k == "5h" else f"지금 {vals[-1]:.0f}% 최고 {max(vals):.0f}%", style="#cfcfcf")
        t.append("\n")
        ch = cch.limit_chart_both(row["5h"]["series"] if row["5h"] else [], row["7d"]["series"] if row["7d"] else [], width, LIMIT_H, c5, line_style=c7)
        if ch is not None:
            t.append_text(ch)
            t.append("\n")
    t.rstrip()
    return t


STAT_PERIODS = [(None, "전체"), (1, "1일"), (7, "7일"), (30, "30일")]
STAT_ORDERS = [("cost", "비용"), ("last", "최근"), ("prompts", "프롬프트"), ("tools", "도구"), ("duration", "기간")]
WEEKDAYS = "월화수목금토일"


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


MSG_PREVIEW = 700      # 접힌 메시지에 보이는 글자 수(Enter 로 펼치면 전체)
SEARCH_MSG_MAX = 2000     # 검색이 읽어 오는 일치 메시지 수 상한(세션으로 묶기 전)
SEARCH_SESSION_MAX = 200   # 목록에 보이는 세션 수 상한
MSG_MAX = 600          # 한 번에 그리는 메시지 수 상한(도구 호출까지 켜면 수천 개라 느려진다 — a 로 전부 불러옴)
ROLE_LABEL = {"user": "나", "assistant": "Claude", "system": "시스템"}


class MsgView(Static):
    """대화 한 메시지. 선택되면 왼쪽 테두리가 하늘색이 된다."""


class SessionScreen(ModalScreen):
    """한 세션의 대화. ↑↓ 로 메시지 이동 · Enter 펼침 · f 전체 펼침 · t 도구 · s 서브에이전트 · n/N 검색어 이동 · y 복사 · [ ] 이어진 세션 · m 치환 켬/끔."""
    BINDINGS = [
        Binding("escape,q", "close", "닫기"),
        Binding("up,k", "move(-1)", "이전 메시지", show=False), Binding("down,j", "move(1)", "다음 메시지", show=False),
        Binding("pageup", "move(-8)", "8개 앞", show=False), Binding("pagedown", "move(8)", "8개 뒤", show=False),
        Binding("home", "jump(0)", "처음", show=False), Binding("end", "jump(-1)", "끝", show=False),
        Binding("enter,space", "toggle_one", "펼침/접음"), Binding("f", "toggle_all", "전체 펼침/접음"),
        Binding("t", "toggle_tools", "도구 호출·결과 보기"), Binding("s", "toggle_side", "서브에이전트 보기"),
        Binding("n", "hit(1)", "다음 검색어"), Binding("N", "hit(-1)", "이전 검색어", show=False),
        Binding("y", "copy", "복사"), Binding("m", "toggle_mask", "치환 켬/끔"),
        Binding("left_square_bracket", "link('parents')", "앞 세션", show=False), Binding("right_square_bracket", "link('children')", "뒤 세션", show=False),
        Binding("a", "load_all", "전부 불러오기", show=False),
        Binding("i", "toggle_auto", "자동 메시지 숨김/표시"),
    ]

    def __init__(self, app_ref, session_id: str, uuid: str | None, needle: str = "", regex: bool = False):
        super().__init__()
        self.ctx_app, self.session_id, self.uuid = app_ref, session_id, uuid
        self.needle, self.regex = needle, regex
        self.tools = self.side = False
        self.hide_auto = False                 # 자동 메시지(작업 알림·명령 출력 등) 숨김
        self.limit = MSG_MAX
        self.expanded: set[str] = set()
        self.all_open = False
        self.msgs: list[dict] = []
        self.sel = 0
        self.info: dict = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="stats-box"):
            yield Static("", id="sess-head")
            yield VerticalScroll(id="msgs")
            yield Static("", id="sess-state", classes="state")
            yield Static("↑↓ 이동 · Enter 펼침 · f 전체 펼침 · n/N 검색어 · y 복사 · t 도구 · s 서브에이전트 · i 자동 메시지 · [ ] 이어진 세션 · m 치환 · Esc 닫기", id="sess-keys", classes="state")

    def on_mount(self):
        self.load(focus_uuid=self.uuid)

    # --- 불러오기
    def hit_re(self):
        if not self.needle:
            return None
        import re
        try:
            return re.compile(self.needle if self.regex else re.escape(self.needle), re.I)
        except re.error:
            return None

    def load(self, focus_uuid=None):
        kinds = ("prompt", "response") + (("tool_use", "tool_result") if self.tools else ())
        with cc.connect(readonly=True) as c:
            masker = self.ctx_app.masker()
            s, msgs = cd.session_rows(c, self.session_id, kinds)             # 원문 — 치환은 화면에 그릴 창(rebuild)만 한다
            stats = cd.session_stats(c, session_id=self.session_id, masker=masker, limit=1)
            self.info = dict(s=s, stats=stats[0] if stats else None, tools=cd.session_tools(c, self.session_id), links=cd.session_links(c, self.session_id, masker))
        if focus_uuid and any(m["uuid"] == focus_uuid and m["side"] for m in msgs):
            self.side = True                      # 서브에이전트 쪽 메시지가 찾은 대상이면 자동으로 보여 준다
        self.all_msgs = msgs
        self.row_masker = masker
        self.rebuild(focus_uuid)

    def visible(self):
        return [m for m in self.all_msgs if (self.side or not m["side"]) and not (self.hide_auto and cd.is_auto(m["role"], m["kind"], m["text"]))]

    def rebuild(self, focus_uuid=None):
        vis = self.visible()
        idx = next((i for i, m in enumerate(vis) if m["uuid"] == focus_uuid), None)
        self.hidden_before = 0
        self.hidden_after = 0
        if len(vis) > self.limit:
            center = idx if idx is not None else len(vis) - 1
            lo = min(max(center - self.limit // 2, 0), len(vis) - self.limit)
            self.hidden_before, self.hidden_after = lo, len(vis) - lo - self.limit
            vis = vis[lo: lo + self.limit]
            idx = None if idx is None else idx - lo
        vis = [dict(m, text=self.row_masker.text(m["text"])) for m in vis]     # 보일 창만 치환(세션 전체가 아니라)
        self.msgs = vis
        if focus_uuid and idx is not None:
            self.expanded.add(focus_uuid)
        self.sel = idx if idx is not None else 0
        box = self.query_one("#msgs", VerticalScroll)
        box.remove_children()
        self.views = [MsgView(self.render_msg(m), classes="msg") for m in vis]
        if self.views:
            box.mount(*self.views)
        self.render_head()
        self.select(self.sel, scroll=True)

    # --- 그리기
    def render_msg(self, m) -> Text:
        t = Text()
        tag = {"tool_use": " · 도구 호출", "tool_result": " · 도구 결과"}.get(m["kind"], "")
        cat, summ = cd.classify(m["role"], m["kind"], m["text"])
        auto = cd.is_auto(m["role"], m["kind"], m["text"])
        t.append(f"[{fmt_ts(m['ts'])}] {ROLE_LABEL.get(m['role'], m['role'])}{tag}{' (서브에이전트)' if m['side'] else ''}",
                 style="bold #b8a46a" if m["role"] == "user" and m["kind"] == "prompt" and not auto else "#7a7a7a")
        if cd.CAT_LABEL.get(cat):
            t.append(f" [{cd.CAT_LABEL[cat]}]", style="#7a7a7a" if auto else "bold #33ccff")      # 자동은 흐린 배지, 사람이 한 것(스킬 호출·셸·붙여넣기)은 강조
        t.append("\n")
        body = (m["text"] or "").strip() or "(빈 내용)"
        open_ = self.all_open or m["uuid"] in self.expanded
        if summ and not open_:                 # 자동·명령 메시지는 한 줄 요약으로 접는다(Enter: 원문)
            body = summ + (f"   (+{len(body):,}자 원문 — Enter: 펼치기)" if len(body) > len(summ) + 20 else "")
            t.append(body, style="#7a7a7a" if auto else "#ffffff")
            rx = self.hit_re()
            if rx:
                t.highlight_regex(rx, style="bold #000000 on #b8a46a")
            return t
        limit = MSG_PREVIEW if m["kind"] in ("prompt", "response") else 300
        if not open_ and len(body) > limit:
            body = body[:limit].rstrip() + f"\n… (+{len(body) - limit:,}자 더 — Enter: 펼치기)"
        style = "#ffffff" if m["kind"] == "prompt" else ("#7a7a7a" if m["kind"] in ("tool_use", "tool_result") else "#cfcfcf")
        t.append(body, style=style)
        rx = self.hit_re()
        if rx:
            t.highlight_regex(rx, style="bold #000000 on #b8a46a")
        return t

    def render_head(self):
        s, st, links = self.info["s"], self.info["stats"], self.info["links"]
        t = Text()
        if not s:
            t.append("세션을 찾지 못했다")
            self.query_one("#sess-head", Static).update(t)
            return
        t.append(((st or {}).get("title") or "(제목 없음)")[:110] + "\n", style="bold #33ccff")
        t.append(f"{s['session_id']}  @{s['host']}  {short_repo(s['repo'])}#{s['branch'] or '-'}  {s['cwd'] or ''}\n", style="#9a9a9a")
        if st:
            t.append(f"{fmt_ts(st['first'])} ~ {fmt_ts(st['last'])} ({fmt_dur(st['duration_s'])})  프롬프트 {st['prompts']} · 응답 {st['responses']} · 도구 {st['tools']} · 서브에이전트 메시지 {st['subagent_msgs']}"
                     f" · 턴시간 {fmt_dur(st['turn_ms'] / 1000)}" + (f" · compact {st['compacts']}회" if st["compacts"] else "") + "\n", style="#9a9a9a")
            models = ", ".join(m.replace("claude-", "") for m in st["models"]) or "-"
            t.append(f"비용 {'$%.2f' % st['cost'] if st['cost'] is not None else '-'} · 요청 {st['requests']:,} · 모델 {models}", style="#9a9a9a")
            if self.info["tools"]:
                t.append("  ·  도구: " + ", ".join(f"{n} {c}" for n, c in self.info["tools"]), style="#9a9a9a")
            t.append("\n")
        for key, mark, label in (("parents", "[", "이전 세션"), ("children", "]", "다음 세션")):
            ls = links[key]
            if ls:
                x = ls[-1] if key == "parents" else ls[0]
                t.append(f"{mark} {label}: {x['session_id'][:8]} ({fmt_ts(x['first'])}) {x['title'][:60]}" + (f" 외 {len(ls) - 1}개" if len(ls) > 1 else "") + "\n", style="#b8a46a")
        self.query_one("#sess-head", Static).update(t)
        self.update_state()

    def update_state(self):
        n = len(self.msgs)
        bits = [f"메시지 {self.sel + 1 if n else 0}/{n}" + (f" (앞 {self.hidden_before} · 뒤 {self.hidden_after} 생략 — a: 전부)" if self.hidden_before or self.hidden_after else ""),
                "도구 " + ("보임" if self.tools else "숨김") + " (t)", "서브에이전트 " + ("보임" if self.side else "숨김") + " (s)",
                "자동 메시지 " + ("숨김" if self.hide_auto else "보임") + " (i)",
                "치환 " + ("켜짐" if self.ctx_app.mask else "꺼짐 — 원문 표시 중") + " (m)"]
        if self.needle:
            bits.append(f"검색어 '{self.needle}' (n/N 이동)")
        self.query_one("#sess-state", Static).update("   ·   ".join(bits))

    # --- 동작
    def select(self, i, scroll=True):
        if not self.views:
            return
        if self.sel < len(self.views):
            self.views[self.sel].remove_class("msg-sel")
        self.sel = max(0, min(i, len(self.views) - 1))
        v = self.views[self.sel]
        v.add_class("msg-sel")
        if scroll:
            self.call_after_refresh(lambda: v.scroll_visible(animate=False, top=False))
        self.update_state()

    def refresh_msg(self, i):
        self.views[i].update(self.render_msg(self.msgs[i]))

    def action_close(self):
        self.dismiss()

    def action_move(self, d: int):
        self.select(self.sel + d)

    def action_jump(self, i: int):
        self.select(i if i >= 0 else len(self.views) - 1)

    def action_toggle_one(self):
        if not self.msgs:
            return
        u = self.msgs[self.sel]["uuid"]
        self.expanded.symmetric_difference_update({u})
        self.refresh_msg(self.sel)

    def action_toggle_all(self):
        self.all_open = not self.all_open
        for i in range(len(self.msgs)):
            self.refresh_msg(i)
        self.ctx_app.flash("모든 메시지 " + ("펼침" if self.all_open else "접음"))

    def keep_focus(self):
        return self.msgs[self.sel]["uuid"] if self.msgs else None

    def action_toggle_tools(self):
        self.tools = not self.tools
        self.load(focus_uuid=self.keep_focus())

    def action_toggle_auto(self):
        self.hide_auto = not self.hide_auto
        self.rebuild(self.keep_focus())

    def action_toggle_side(self):
        self.side = not self.side
        self.rebuild(self.keep_focus())

    def action_load_all(self):
        self.limit = 10 ** 9
        self.rebuild(self.keep_focus())
        self.ctx_app.flash("전부 불러왔습니다")

    def action_hit(self, d: int):
        rx = self.hit_re()
        if not rx or not self.msgs:
            return
        idx = [i for i, m in enumerate(self.msgs) if rx.search(m["text"] or "")]
        if not idx:
            self.ctx_app.flash("이 화면에 검색어가 있는 메시지가 없습니다", "warning"); return
        after = [i for i in idx if (i > self.sel if d > 0 else i < self.sel)]
        target = (after[0] if d > 0 else after[-1]) if after else (idx[0] if d > 0 else idx[-1])
        m = self.msgs[target]
        limit = MSG_PREVIEW if m["kind"] in ("prompt", "response") else 300
        if rx.search(m["text"] or "").start() > limit and m["uuid"] not in self.expanded:
            self.expanded.add(m["uuid"])             # 검색어가 접힌 부분에 있으면 펼쳐서 보여 준다
            self.refresh_msg(target)
        self.select(target)

    def action_copy(self):
        if self.msgs:
            text = self.msgs[self.sel]["text"] or ""
            self.ctx_app.copy_to_clipboard(text)
            self.ctx_app.flash(f"복사했습니다 ({len(text):,}자" + ("" if self.ctx_app.mask else ", 원문") + ")")

    def action_toggle_mask(self):
        self.ctx_app.action_toggle_mask()
        self.load(focus_uuid=self.keep_focus())

    def action_link(self, key: str):
        ls = self.info["links"][key]
        if not ls:
            self.ctx_app.flash("이어진 세션이 없습니다", "warning"); return
        self.session_id = (ls[-1] if key == "parents" else ls[0])["session_id"]
        self.expanded.clear()
        self.limit = MSG_MAX
        self.load()


class InstrScreen(ModalScreen):
    """지침 한 건의 본문(공유 정본 그대로 — 로컬 캐시 아님). `## ` 절 목록을 위에, 본문을 아래에 보인다. e 편집 · m 치환 켬/끔."""
    BINDINGS = [Binding("escape,q", "close", "닫기"), Binding("e", "edit", "편집기로 고치기"), Binding("m", "toggle_mask", "치환 켬/끔")]

    def __init__(self, app_ref, repo: str, name: str):
        super().__init__()
        self.ctx_app, self.repo, self.iname = app_ref, repo, name

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="stats-box"):
            yield Static("", id="instr-body")

    def on_mount(self):
        self.render_body()

    def action_close(self):
        self.dismiss()

    def action_toggle_mask(self):
        self.ctx_app.action_toggle_mask()
        self.render_body()

    def action_edit(self):
        if self.ctx_app.edit_instr(self.repo, self.iname):
            self.render_body()

    def render_body(self):
        with cc.connect(readonly=True) as c:
            got = cd.instr_body(c, self.repo, self.iname, self.ctx_app.masker())
            meta = next((r for r in cd.instr_rows(c) if r["repo"] == self.repo and r["name"] == self.iname), None)
        t = Text()
        if not got or not meta:
            t.append("지침을 찾지 못했다(다른 기기가 지웠을 수 있다)")
        else:
            rev, body = got
            t.append(f"{short_repo(self.repo)}  ·  {self.iname}  ·  rev {rev}\n", style="bold #33ccff")
            t.append(f"{meta['host']} 가 {fmt_ts(meta['at'])} 에 마지막으로 고침  ·  {meta['length']:,}자  ·  치환 {'켜짐' if self.ctx_app.mask else '꺼짐(원문 표시 중)'}  ·  e: 편집기로 고치기\n", style="#9a9a9a")
            secs = cd.instr_sections(body)
            t.append(f"절 {len(secs)}개: " + (" · ".join(secs) if secs else "(없음)") + "\n\n", style="#b8a46a")
            for line in body.splitlines():
                t.append(line + "\n", style="bold #33ccff" if line.startswith("## ") else "#cfcfcf")
        self.query_one("#instr-body", Static).update(t)


# ---------------------------------------------------------------- 앱
class CtxUI(uikit.HelpMixin, App):
    TITLE = "ctxui — 공유 컨텍스트 관리"
    HELP_TERMS = [   # ? 도움말의 「용어·사용법」 — 별도 용어 탭 대신(uikit 공통 규칙)
        ('탭', '1 대시보드(저장소별 용량·한도·토큰/비용 추이·세션 통계) · 2 검색(세션 기준) · 3 대조(같은 문구를 저장소별로 묶어 교차검증) · 4 비밀(등록한 비밀 관리) · 5 후보(키처럼 보이는 문자열 탐지→승인·무시) · 6 지침(프로젝트별 공유 지침)'),
        ('치환(m)', '등록한 비밀을 [protected] 로 바꿔 보여 준다 — 기본 켜짐, 어깨너머 노출 방지용이며 원문(DB)은 바뀌지 않는다'),
        ('제한 모드', 'LLM 세션이 실행하면: 모든 탭을 볼 수 있지만 화면의 모든 텍스트에서 등록한 비밀과 비밀처럼 보이는 문자열(키 형식·password=·한글 비밀번호)이 [protected] 로 치환되고(끌 수 없음), 후보 미리보기도 [protected](N자)로 가려지며, 값 보기(v)·비밀 추가·삭제·끄기·후보 무시·지침 편집은 막힌다. 후보 승인(Enter)은 값을 보여 주지 않고 등록만 하므로 허용된다'),
        ('비용', 'Claude Code(OpenTelemetry)가 요청마다 보고한 cost_usd 의 합이다. 구독에서 실제 청구액과 같은지는 확인하지 못했다(청구액이라고 단정하지 말 것). 계정별은 요청마다 찍힌 계정(OTel user.email) 기준이고, 수집 전이거나 원본이 없는 기록은 「(계정 불명)」으로 따로 보인다. 한도 그래프는 계정 단위라 저장소·모델 필터가 걸리지 않는다'),
        ('필터 키', '검색 탭: F2 사용자 발언만 · F3 정규식 · F4 도구 메시지 포함 · F6 제목만 · Space 세션 펼침 · x 모두 펼침. 대시보드: p 기간 · b 단위 · g 분류 · o 정렬 · c 필터 지움'),
        ('자동 메시지', 'Claude Code 가 사람 대신 남기는 메시지(작업 알림·명령 출력·시스템 알림 등, `<태그>` 로 시작)는 흐린 배지+한 줄 요약으로 접혀 보이고 통계 프롬프트 수·사용자 발언 검색·대조에서 빠진다. 스킬 호출(/이름)·셸 입력·붙여넣기는 사람이 한 것이라 포함. 대화 화면 i: 자동 메시지 숨김/표시'),
        ('세션 기준 검색', '검색은 늘 전체 대화를 대상으로 하되 결과를 세션 단위로 묶어 보여 준다(제목·일치 건수·가장 최근 일치). Enter 는 그 세션 대화를 열고, Space 로 펼치면 일치한 메시지들이 아래에 나온다. F6 제목만은 세션 제목(첫 프롬프트)에 일치한 세션만 남긴다'),
    ]
    HELP_NOTES = [
        '종료는 q. Esc 는 목록으로 포커스를 돌린다',
    ]
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
    #dash-scroll { height: 1fr; }
    #dash-scroll.narrow .dash-row { layout: vertical; height: auto; }
    #dash-scroll.narrow .dash-row > * { width: 100%; height: 14; }
    .dash-row { height: 14; }
    #stat-trend-chart, #stat-limits-box { width: 3fr; }
    #stat-break, #stat-summary-box { width: 2fr; }
    #stat-trend, #projects, #stat-sessions { width: 1fr; }
    #stats-box { layout: vertical; padding: 0 1; }
    #sess-head { height: auto; max-height: 9; padding: 0 1; }
    #msgs { height: 1fr; }
    .msg { height: auto; padding: 0 1; margin-bottom: 1; border-left: tall #3a3a3a; }
    .msg-sel { border-left: tall #33ccff; background: #101010; }
    #sess-state, #sess-keys { height: auto; }
    #stat-limits-box { height: 1fr; }
    #stat-limits { padding: 0 1; }
    #stat-summary { padding: 0 1; }
    #ovhead { height: auto; }
    """
    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("1", "tab('dashboard')", "대시보드"), Binding("2", "tab('search')", "검색"), Binding("3", "tab('verify')", "대조"),
        Binding("4", "tab('secrets')", "비밀"), Binding("5", "tab('cands')", "후보"), Binding("6", "tab('instr')", "지침"),
        Binding("p", "stat_period", "기간", show=False), Binding("b", "stat_bucket", "단위", show=False), Binding("g", "stat_by", "분류", show=False),
        Binding("o", "stat_order", "정렬", show=False), Binding("c", "stat_clear", "필터 지움", show=False),
        Binding("escape", "focus_table", "목록으로", show=False),
        Binding("m", "toggle_mask", "치환 켬/끔"), Binding("r,f5", "reload", "새로고침"),
        Binding("f2", "toggle_role", "역할(사용자만)", show=False), Binding("f3", "toggle_regex", "정규식", show=False), Binding("f4", "toggle_tools", "도구 메시지 포함", show=False),
        Binding("f6", "toggle_title_only", "제목만", show=False), Binding("space", "toggle_expand", "세션 펼침", show=False), Binding("x", "expand_all", "모두 펼침", show=False),
        Binding("a", "secret_add", "비밀 추가", show=False), Binding("d", "secret_delete", "삭제", show=False), Binding("e", "secret_toggle", "켬/끔", show=False),
        Binding("v", "reveal", "값 보기", show=False), Binding("i", "cand_ignore", "무시", show=False),
        *uikit.HelpMixin.HELP_BINDINGS,
    ]

    def __init__(self, restricted=False):
        """restricted=True 는 LLM 세션이 실행한 경우: **모든 탭을 볼 수 있되** 비밀 값은 추출·조회할 수 없다 — 화면의 모든 텍스트는 등록한 비밀 + 비밀처럼 보이는 문자열(후보 패턴)을
        [protected] 로 치환하고(끌 수 없음), 값 보기(v)·비밀 추가·삭제·끄기·후보 무시·지침 편집은 막는다. 후보 승인(Enter)은 값을 보여 주지 않고 등록만 하므로 허용한다."""
        super().__init__()
        self.restricted = restricted
        self.mask = True
        self.only_user = False
        self.regex = False
        self.with_tools = False
        self.title_only = False
        self._wrap_pending, self._wrap_at = False, 0
        self.expand_all_sess = False
        self.expanded_sess: set[str] = set()
        self.groups: list[dict] = []
        self.search_query, self.search_total = "", 0
        self.cand_rows: dict[str, dict] = {}
        self.sec_rows: dict[str, dict] = {}
        self._reveal = False
        self.stat_period, self.stat_bucket, self.stat_by, self.stat_order = 3, "day", "model", "cost"   # 기본: 30일 · 일 단위 · 모델별 · 비용순
        self._stat_loaded = False

    # --- 구성
    def compose(self) -> ComposeResult:
        with TabbedContent(initial="dashboard", id="tabs"):
            with TabPane("1 대시보드", id="dashboard"):
                with Horizontal(classes="filters"):
                    yield uikit.box(Input(placeholder="저장소 일부", id="f-repo"), "저장소(통계)")
                    yield uikit.box(Input(placeholder="머신 일부", id="f-host"), "머신(통계)")
                    yield uikit.box(Input(placeholder="모델 일부 (예: sonnet)", id="f-model"), "모델(통계)")
                with Horizontal(classes="selects"):      # p/b/g/o 키와 같은 상태를 고르는 드롭다운(키로 바꾸면 여기도 따라 바뀐다)
                    yield uikit.select_box([(l, i) for i, (_, l) in enumerate(STAT_PERIODS)], self.stat_period, "sel-period", "기간 (p)")
                    yield uikit.select_box([(l, k) for k, l in cd.BUCKETS.items()], self.stat_bucket, "sel-bucket", "단위 (b)")
                    yield uikit.select_box([(l, k) for k, l in cd.BREAKDOWNS.items()], self.stat_by, "sel-by", "분류 (g)")
                    yield uikit.select_box([(l, k) for k, l in STAT_ORDERS], self.stat_order, "sel-order", "세션 정렬 (o)")
                yield Static("", id="stat-state", classes="state")
                with VerticalScroll(id="dash-scroll"):
                    yield uikit.box(Static("", id="ovhead"), "전체 · 표별 용량")
                    with Horizontal(id="dr1", classes="dash-row"):      # 얼마나 썼나: 비용 그래프 | 분류별
                        yield uikit.box(Static("", id="stat-trend-chart"), "비용 추이")
                        yield uikit.box(DataTable(id="stat-break", cursor_type="row"), "분류별")
                    with Horizontal(id="dr2", classes="dash-row"):
                        yield uikit.box(DataTable(id="stat-trend", cursor_type="row"), "토큰·비용 추이")
                    with Horizontal(id="dr3", classes="dash-row"):      # 한도 그래프 | 세션 통계(+시간대 그래프)
                        yield uikit.box(VerticalScroll(Static("", id="stat-limits"), id="stat-limits-box"), "계정별 한도 사용률 — 5h(면적)·7d(밝은 선) 실제 샘플 (색 = 계정)")
                        yield uikit.box(VerticalScroll(Static("", id="stat-summary"), id="stat-summary-box"), "세션 통계")
                    with Horizontal(id="dr4", classes="dash-row"):
                        yield uikit.box(DataTable(id="projects", cursor_type="row", zebra_stripes=False), "저장소(프로젝트)별 — Enter: 이 저장소 검색")
                    with Horizontal(id="dr5", classes="dash-row"):
                        yield uikit.box(DataTable(id="stat-sessions", cursor_type="row"), "세션 — Enter: 대화 보기")
            with TabPane("2 검색", id="search"):
                with Horizontal(classes="filters"):
                    yield uikit.box(Input(placeholder="검색어 (Enter)", id="q"), "검색어")
                    yield uikit.box(Input(placeholder="저장소 일부", id="repo"), "저장소")
                    yield uikit.box(Input(placeholder="일", id="days"), "기간")
                yield Static("", id="sstate", classes="state")
                yield uikit.box(DataTable(id="results", cursor_type="row"), "결과(세션별) — Enter: 대화 · Space: 일치 펼침 · x: 모두 · F6: 제목만")
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
            with TabPane("6 지침", id="instr"):
                yield uikit.box(DataTable(id="instr-table", cursor_type="row"), "프로젝트 지침(공유 정본) — Enter: 본문 · e: 편집기로 고치기")
        yield Footer()

    def on_mount(self):
        self.query_one("#projects", DataTable).add_columns("저장소", "세션", "메시지", "프롬프트", "텍스트", "저장 용량", "마지막", "머신")
        self.query_one("#results", DataTable).add_columns("시각", "일치", "저장소", "세션", "제목", "내용")
        self.query_one("#vrepos", DataTable).add_columns("저장소", "건수", "세션", "최근", "대표 인용")
        self.query_one("#vhits", DataTable).add_columns("시각", "세션", "내용")
        self.query_one("#secrets-table", DataTable).add_columns("이름", "종류", "상태", "길이", "fp", "원문 포함 메시지")
        self.query_one("#cands-table", DataTable).add_columns("fp", "종류", "미리보기", "횟수", "세션", "저장소", "최근")
        self.query_one("#stat-trend", DataTable).add_columns("구간", "요청", "비용", "", "입력", "출력", "캐시읽기")
        self.query_one("#stat-break", DataTable).add_columns("분류", "요청", "비용", "비중", "출력")
        self.query_one("#stat-sessions", DataTable).add_columns("최근", "머신", "저장소", "프롬프트", "도구", "턴시간", "비용", "모델", "첫 프롬프트")
        self.query_one("#instr-table", DataTable).add_columns("저장소", "이름", "rev", "수정 머신", "수정 시각", "길이")
        self.update_state()
        self.reload_overview()

    DASH_NARROW_COLS = 110      # 이보다 좁으면 대시보드의 2열 배치를 1열로(좁은 터미널에서 표가 잘리지 않게)
    WRAP_RETRY_COLS = 12        # 줄바꿈 때문에 1열이 된 뒤, 이만큼 넓어지면 2열을 다시 시도
    DASH_TEXTS = ("#stat-limits", "#stat-summary")      # 2열/1열에 따라 폭이 달라지는 글 칸(표는 줄바꿈 대신 잘리므로, 전체 폭인 #ovhead 는 열 배치와 무관하므로 제외)

    def _wrapping(self):
        """대시보드의 글 칸 중 가장 긴 논리 줄이 칸 폭보다 길어 줄바꿈될 것들 [(id, 칸 폭, 필요 폭)]."""
        from rich.cells import cell_len
        out = []
        for sel in self.DASH_TEXTS:
            try:
                w = self.query_one(sel, Static)
            except Exception:
                continue
            c = getattr(w, "content", None) or getattr(w, "renderable", None)
            txt = c.plain if hasattr(c, "plain") else str(c or "")
            need, avail = max((cell_len(l) for l in txt.split("\n")), default=0), w.content_size.width
            if avail and need > avail:
                out.append((sel, avail, need))
        return out

    def _fit_dash(self):
        try:
            box = self.query_one("#dash-scroll")
        except Exception:
            return
        w = self.size.width
        narrow = w < self.DASH_NARROW_COLS
        if not narrow and box.has_class("narrow"):
            narrow = w < self._wrap_at + self.WRAP_RETRY_COLS      # 줄바꿈으로 좁혔던 폭보다 충분히 넓어지기 전엔 1열 유지
        box.set_class(narrow, "narrow")

    def _check_wrap(self):
        """2열인데 글이 줄바꿈되면(예: 1280px 폭) 1열로 바꾼다. 레이아웃이 자리 잡기 전의 순간 값에 속지 않게 한 번 더 확인한 뒤에만."""
        try:
            box = self.query_one("#dash-scroll")
        except Exception:
            return
        if self.current_tab() != "dashboard" or box.has_class("narrow") or not self._wrapping():
            self._wrap_pending = False
            return
        if self._wrap_pending:
            self._wrap_pending = False
            self._wrap_at = self.size.width
            box.add_class("narrow")
            self.call_after_refresh(self._paint_dash)
        else:
            self._wrap_pending = True
            self.set_timer(0.35, self._check_wrap)

    def on_resize(self, event):
        self._fit_dash()
        self.call_after_refresh(self._paint_dash)
        self.call_after_refresh(self._check_wrap)

    # --- 공통
    def masker(self):
        if not self.mask:
            return cs.IDENTITY
        try:
            with cc.connect(readonly=True) as c:
                base = cs.load_masker(c)
        except Exception:
            base = cs.Masker() if self.restricted else cs.IDENTITY
        # 제한 모드는 DB 를 못 읽어도 후보 패턴 치환은 유지한다(치환기를 빈 값으로 폴백하지 않음)
        return cs.StrictMasker(base.secrets) if self.restricted else base

    def current_tab(self) -> str:
        return self.query_one("#tabs", TabbedContent).active

    def flash(self, msg: str, severity="information"):
        self.notify(msg, severity=severity, timeout=5)

    def check_action(self, action, parameters):
        """제한 모드에서는 막힌 동작(치환 끄기·값 보기·비밀 추가/삭제/끄기·후보 무시)을 푸터·도움말에서 숨긴다(눌러도 deny 가 막는다)."""
        if self.restricted and action in ("toggle_mask", "secret_add", "secret_delete", "secret_toggle", "reveal", "cand_ignore"):
            return False
        return True

    def deny(self, what="이 동작") -> bool:
        """제한 모드면 안내하고 True(호출한 동작은 중단해야 한다)."""
        if self.restricted:
            self.flash(f"제한 모드(LLM 세션): {what} 은(는) 사람이 터미널에서 직접 실행할 때만 쓸 수 있습니다", "warning")
        return self.restricted

    def action_tab(self, name: str):
        tabs = self.query_one("#tabs", TabbedContent)
        if tabs.active == name:
            self.on_tab_shown(name)              # 이미 그 탭이면 TabActivated 가 오지 않으므로 직접 갱신
        else:
            tabs.active = name                   # 바뀌면 TabActivated → on_tab_shown (예전엔 여기서 한 번 더 불러 후보 탐지·통계가 두 번 돌고 알림이 겹쳤다)
        self.call_after_refresh(self.action_focus_table)

    def on_tabbed_content_tab_activated(self, ev: TabbedContent.TabActivated):
        self.on_tab_shown(ev.pane.id)

    def on_tab_shown(self, name: str):
        if name == "secrets":
            self.reload_secrets()
        elif name == "cands" and not self.cand_rows:
            self.scan_candidates()
        elif name == "dashboard":
            self.reload_overview()
            if not self._stat_loaded:
                self.reload_stats()
        elif name == "instr":
            self.reload_instr()

    def action_focus_table(self):
        ids = {"dashboard": "#projects", "search": "#results", "verify": "#vrepos", "secrets": "#secrets-table", "cands": "#cands-table",
               "instr": "#instr-table"}      # 표가 있는 탭은 모두 표에 포커스 — 없으면 탭 키 뒤 Enter·↑↓ 가 아무 일도 안 했다
        try:
            self.query_one(ids[self.current_tab()]).focus()
        except Exception:
            pass

    def action_toggle_mask(self):
        if self.deny("치환 끄기(원문 보기)"):
            return
        self.mask = not self.mask
        self.flash("치환 " + ("켜짐" if self.mask else "꺼짐 — 화면에 원문이 보입니다"), "information" if self.mask else "warning")
        self.update_state()
        self.action_reload()

    def action_reload(self):
        t = self.current_tab()
        {"dashboard": self.reload_dashboard, "search": self.run_search, "verify": self.run_verify, "secrets": self.reload_secrets, "cands": self.scan_candidates, "instr": self.reload_instr}[t]()

    def update_state(self):
        self.query_one("#sstate", Static).update(
            f"역할: {'사용자만' if self.only_user else '전체'} (F2)   ·   정규식: {'켜짐' if self.regex else '꺼짐'} (F3)   ·   도구 메시지: {'포함' if self.with_tools else '제외'} (F4)   ·   제목만: {'켜짐' if self.title_only else '꺼짐'} (F6)   ·   치환: {'켜짐' if self.mask else '꺼짐'} (m)" + ("   ·   제한 모드(LLM): 치환 고정·값 조회/수정 불가" if self.restricted else ""))

    def action_toggle_role(self):
        self.only_user = not self.only_user
        self.update_state()

    def action_toggle_regex(self):
        self.regex = not self.regex
        self.update_state()

    def action_toggle_tools(self):
        self.with_tools = not self.with_tools
        self.update_state()

    # --- 대시보드(개요 + 통계)
    def reload_dashboard(self):
        self.reload_overview()
        self.reload_stats()

    def reload_overview(self):
        try:
            with cc.connect(readonly=True) as c:
                ov = cd.overview(c)
        except Exception as e:
            self.flash(f"DB 조회 실패: {e}", "error"); return
        t = ov["totals"]
        head = Text()
        head.append(f"세션 {t['sessions']:,} · 메시지 {t['messages']:,} · 프롬프트 {t['prompts']:,}(자동 {t['auto_prompts']:,} 제외) · 텍스트 {cd.human_bytes(t['text_chars'])} · DB {cd.human_bytes(t['db_bytes'])}\n", style="bold")
        head.append("표별: " + "  ".join(f"{x['name']} {cd.human_bytes(x['bytes'])}" for x in ov["tables"][:6]), style="#9a9a9a")
        self.query_one("#ovhead", Static).update(head)
        tb = self.query_one("#projects", DataTable)
        tb.clear()
        for p in ov["projects"]:
            tb.add_row(short_repo(p["repo"]), f"{p['sessions']:,}", f"{p['messages']:,}", f"{p['prompts']:,}", cd.human_bytes(p["text_chars"]),
                       cd.human_bytes(p["stored_bytes"]), fmt_ts(p["last_ts"]), ",".join(p["hosts"]), key=p["repo"])
        self._fit_heights()

    def on_data_table_row_selected(self, ev: DataTable.RowSelected):
        tid, key = ev.data_table.id, (ev.row_key.value if ev.row_key else None)
        if tid == "projects":
            repo = key if key and key != "(저장소 없음)" else ""
            self.query_one("#repo", Input).value = repo.replace("https://github.com/", "") if repo else ""
            self.action_tab("search")
            self.run_search()
        elif tid in ("results", "vhits"):
            sid, _, uid = (key or "").partition("|")
            if sid and not uid and tid == "results":          # 세션 행 → 그 세션의 가장 최근 일치 메시지에 맞춰 연다
                g = next((g for g in self.groups if g["session_id"] == sid), None)
                uid = g["hits"][0]["uuid"] if g else ""
            if sid:
                q = self.query_one("#q" if tid == "results" else "#phrase", Input).value.strip()
                self.push_screen(SessionScreen(self, sid, uid or None, q, self.regex))
        elif tid == "vrepos":
            self.query_one("#vhits", DataTable).focus()
        elif tid == "cands-table":
            self.adopt_selected()
        elif tid == "instr-table" and key:
            repo, _, name = key.rpartition("|")
            self.push_screen(InstrScreen(self, repo, name))
        elif tid == "stat-sessions" and key:
            self.push_screen(SessionScreen(self, key, None))

    # --- 검색
    def on_input_submitted(self, ev: Input.Submitted):
        if ev.input.id in ("q", "repo", "days"):
            self.run_search()
        elif ev.input.id == "phrase":
            self.run_verify()
        elif ev.input.id in ("f-repo", "f-host", "f-model"):
            self.reload_stats()
            self.query_one("#stat-trend").focus()

    def highlight(self, text: str, query: str) -> Text:
        """표 칸 안에서 검색어(정규식이면 그 패턴)를 강조한다. 잘못된 정규식은 강조 없이 그대로."""
        t = Text(text)
        if query:
            import re
            try:
                t.highlight_regex(re.compile(query if self.regex else re.escape(query), re.I), style="bold #000000 on #b8a46a")
            except re.error:
                pass
        return t

    def run_search(self):
        q = self.query_one("#q", Input).value.strip()
        repo = self.query_one("#repo", Input).value.strip() or None
        dv = self.query_one("#days", Input).value.strip()
        days = int(dv) if dv.isdigit() else None
        try:
            with cc.connect(readonly=True) as c:
                rows = cd.search(c, q, regex=self.regex, repo=repo, role="user" if self.only_user else None, days=days, limit=SEARCH_MSG_MAX, masker=self.masker(),
                                 kinds=("prompt", "response", "tool_use", "tool_result") if self.with_tools else ("prompt", "response"))
        except ValueError as e:
            self.flash(str(e), "error"); return   # 잘못된 입력이면 이전 결과를 지우지 않는다
        self.search_query = q
        self.search_total = len(rows)
        self.groups = cd.group_sessions(rows, q if self.title_only else None, self.regex)[:SEARCH_SESSION_MAX]
        self.expanded_sess = set()
        self.render_results()
        if self.groups:
            self.query_one("#results", DataTable).focus()

    def render_results(self, keep=None):
        """세션 행(일치 건수·대표 일치) + 펼친 세션의 일치 메시지 행. 행 키: 세션 행은 세션 ID, 메시지 행은 `세션ID|uuid`."""
        q, tb = self.search_query, self.query_one("#results", DataTable)
        keys = []
        tb.clear()
        for g in self.groups:
            h0, opened = g["hits"][0], g["session_id"] in self.expanded_sess or self.expand_all_sess
            mark = "▾" if opened else "▸"
            tb.add_row(fmt_ts(g["last"]), f"{mark} {g['count']}건", short_repo(g["repo"]), g["session_id"][:8], Text((g["title"] or "")[:24]), self.highlight(h0["snippet"][:160], q), key=g["session_id"])
            keys.append(g["session_id"])
            if opened:
                for h in g["hits"]:
                    k = f"{g['session_id']}|{h['uuid']}"
                    tb.add_row(Text(fmt_ts(h["ts"]), style="grey62"), Text("  └ " + (h["role"] if h["kind"] in ("prompt", "response") else h["kind"]) + (f" [{cd.CAT_LABEL[h['cat']]}]" if cd.CAT_LABEL.get(h.get("cat")) else ""), style="grey62"), "", "", "", self.highlight(h["snippet"][:160], q), key=k)
                    keys.append(k)
        if keep in keys:
            tb.move_cursor(row=keys.index(keep))
        n = sum(g["count"] for g in self.groups)
        self.query_one("#results").border_title = (f"세션 {len(self.groups)}개 · 일치 {n}건" + (" (최대)" if self.search_total >= SEARCH_MSG_MAX or len(self.groups) >= SEARCH_SESSION_MAX else "")
                                                   + (" · 제목만" if self.title_only else "") + " — Enter: 대화 · Space: 펼침 · x: 모두 · F6: 제목만")

    def current_session_key(self):
        key = self.selected_key("#results")
        return key.partition("|")[0] if key else None

    def action_toggle_expand(self):
        if self.current_tab() != "search" or len(self.screen_stack) != 1 or not isinstance(self.focused, DataTable) or self.focused.id != "results":
            return
        sid = self.current_session_key()
        if not sid:
            return
        self.expanded_sess.symmetric_difference_update({sid})
        self.render_results(keep=sid)           # 접을 때 커서가 그 세션 행에 남는다

    def action_expand_all(self):
        if self.current_tab() != "search" or len(self.screen_stack) != 1 or isinstance(self.focused, Input):
            return
        self.expand_all_sess = not self.expand_all_sess
        self.expanded_sess = set()
        self.render_results(keep=self.current_session_key())
        self.flash("모든 세션 " + ("펼침" if self.expand_all_sess else "접음"))

    def action_toggle_title_only(self):
        self.title_only = not self.title_only
        self.update_state()
        self.run_search()

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
            vr.add_row(short_repo(g["repo"]), g["count"], g["sessions"], fmt_ts(g["last"]), Text(g["quote"][:80]), key=g["repo"])
        self.query_one("#vrepos").border_title = f"저장소별 — {sum(g['count'] for g in groups)}건 / {len(groups)}곳"
        if groups:
            vr.focus()
            self.show_verify_hits(groups[0]["repo"])

    def show_verify_hits(self, repo):
        vh = self.query_one("#vhits", DataTable)
        vh.clear()
        for r in getattr(self, "_verify_hits", {}).get(repo, [])[:300]:
            vh.add_row(fmt_ts(r["ts"]), r["session_id"][:8], Text(r["snippet"][:140]), key=f"{r['session_id']}|{r['uuid']}")

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted):
        if ev.data_table.id == "vrepos" and ev.row_key and ev.row_key.value:
            self.show_verify_hits(ev.row_key.value)
        elif ev.data_table.id in ("secrets-table", "cands-table"):
            self._reveal = False
            self.query_one("#sdetail" if ev.data_table.id == "secrets-table" else "#cdetail", Static).update("")

    # --- 통계
    def stat_filters(self) -> dict:
        q = lambda i: self.query_one(i, Input).value.strip() or None
        return dict(days=STAT_PERIODS[self.stat_period][0], repo=q("#f-repo"), host=q("#f-host"), model=q("#f-model"))

    def update_stat_state(self, cov=None):
        f = self.stat_filters()
        txt = (f"기간: {STAT_PERIODS[self.stat_period][1]} (p)   ·   단위: {cd.BUCKETS[self.stat_bucket]} (b)   ·   분류: {cd.BREAKDOWNS[self.stat_by]} (g)   ·   "
               f"세션 정렬: {dict(STAT_ORDERS)[self.stat_order]} (o)   ·   필터 지움 (c)")
        if cov and cov.get("usage_first"):
            txt += f"   ·   비용은 {cov['usage_first'].astimezone():%m-%d} 이후만 수집됨"
        self.query_one("#stat-state", Static).update(txt)
        return f

    @work(thread=True, exclusive=True, group="stats")
    def reload_stats(self):
        f = self.stat_filters()
        try:
            with cc.connect(readonly=True) as c:
                cov = cd.coverage(c)
                trend = cd.usage_trend(c, bucket=self.stat_bucket, **f)
                span_days = (trend[-1]["bucket"] - trend[0]["bucket"]).days + 1 if trend else 0
                fine_b = "hour" if span_days <= 14 else "day"                     # 비용 그래프는 선택한 단위와 무관하게 시간당(2주 넘으면 일당)으로 곱게 잰다
                fine = trend if fine_b == self.stat_bucket else cd.usage_trend(c, bucket=fine_b, **f)
                brk, tot = cd.usage_breakdown(c, self.stat_by, **f)
                summ = cd.session_summary(c, **f)
                sess = cd.session_stats(c, order=self.stat_order, limit=300, masker=self.masker(), **f)
                lim = cd.limit_windows(c, days=f.get("days"), host=f.get("host"))
        except Exception as e:
            self.call_from_thread(self.flash, f"통계 조회 실패: {e}", "error"); return
        self.call_from_thread(self.show_stats, cov, trend, brk, tot, summ, sess, lim, (fine_b, fine))

    def show_stats(self, cov, trend, brk, tot, summ, sess, lim, fine=("day", [])):
        self._stat_loaded = True
        self._st = dict(lim=lim, trend=trend, tot=tot, summ=summ, fine=fine)
        self.update_stat_state(cov)
        self.query_one("#stat-trend").border_title = f"토큰·비용 추이 — {cd.BUCKETS[self.stat_bucket]} 단위 · 합계 ${tot['cost']:,.2f} · 요청 {tot['requests']:,} · 출력 {fmt_num(tot['output'])}"
        tb = self.query_one("#stat-break", DataTable)
        tb.clear()
        for r in brk:
            share = r["cost"] / tot["cost"] if tot["cost"] else 0
            tb.add_row(short_repo(r["key"]) if self.stat_by == "repo" else r["key"], f"{r['requests']:,}", f"${r['cost']:,.2f}", f"{share:6.1%}", fmt_num(r["output"]))
        unk = next((r for r in brk if r["key"] == "(계정 불명)"), None) if self.stat_by == "account" else None
        self.query_one("#stat-break").border_title = (f"{cd.BREAKDOWNS[self.stat_by]}별 — {len(brk)}개 (g: 분류 바꾸기)"
                                                      + (f" · 계정 불명 {unk['cost'] / tot['cost']:.0%}" if unk and tot["cost"] else ""))
        ts = self.query_one("#stat-sessions", DataTable)
        ts.clear()
        for r in sess:
            models = ",".join(sorted({m.split("-")[1] if m.startswith("claude-") and "-" in m[7:] else m for m in r["models"]}))   # claude-sonnet-5-5 → sonnet
            ts.add_row(fmt_ts(r["last"]), r["host"], short_repo(r["repo"]), r["prompts"], r["tools"], fmt_dur(r["turn_ms"] / 1000),
                       f"${r['cost']:,.2f}" if r["cost"] is not None else "-", models[:20], Text((r["title"] or "")[:60]), key=r["session_id"])
        self.query_one("#stat-sessions").border_title = f"세션 {len(sess)}개{' (최대 300)' if len(sess) >= 300 else ''} — {dict(STAT_ORDERS)[self.stat_order]}순 (o) · Enter: 대화 보기"
        self._paint_dash()
        self.call_after_refresh(self._paint_dash)      # 칸 폭이 확정된 뒤 한 번 더(처음 열 때 폭을 아직 모를 수 있다)
        self.call_after_refresh(self._check_wrap)

    def _fmt_bucket(self, b):
        return {"hour": b.strftime("%m-%d %H시"), "day": f"{b:%m-%d} ({WEEKDAYS[b.weekday()]})", "week": b.strftime("%m-%d 주"), "month": b.strftime("%Y-%m")}[self.stat_bucket]

    def _paint_dash(self):
        """칸 폭에 따라 달라지는 것(한도·시간대 그래프, 비용 막대, 요일 막대)을 지금 폭으로 다시 그리고 박스 높이를 내용에 맞춘다."""
        st = getattr(self, "_st", None)
        if not st:
            return
        lim_w = self.query_one("#stat-limits-box").size.width - 6 or 60      # 테두리 2 + 글 여백 2 + 세로 스크롤바 2(내용이 길어 생겨도 줄바꿈되지 않게 늘 비워 둔다)
        lt = limits_text(st["lim"], max(30, lim_w))
        self.query_one("#stat-limits", Static).update(lt)
        sm_w = self.query_one("#stat-summary-box").size.width - 6 or 46
        sm = summary_text(st["summ"], max(30, sm_w))
        self.query_one("#stat-summary", Static).update(sm)
        self._need = {"stat-limits-box": lt.plain.count("\n") + 1, "stat-summary-box": sm.plain.count("\n") + 1}
        self._paint_trend(st["trend"])
        self._paint_cost_chart(st["fine"], st["tot"])
        self._fit_heights()

    def _paint_trend(self, trend):
        """추이 표: 비용 막대 칸을 표 폭에서 다른 칸이 쓰고 남는 만큼으로 정한다(박스가 넓어지면 막대도 길어진다)."""
        from rich.cells import cell_len
        tt = self.query_one("#stat-trend", DataTable)
        rows = [(self._fmt_bucket(r["bucket"]), f"{r['requests']:,}", f"${r['cost']:,.2f}", r["cost"], fmt_num(r["input"] + r["cache_create"]), fmt_num(r["output"]), fmt_num(r["cache_read"])) for r in reversed(trend)]    # 최근이 위
        heads = ("구간", "요청", "비용", "", "입력", "출력", "캐시읽기")
        others = sum(max(cell_len(heads[i]), max((cell_len(r[j]) for r in rows), default=0)) + 2 for i, j in ((0, 0), (1, 1), (2, 2), (4, 4), (5, 5), (6, 6)))
        bw = max(6, min(200, tt.size.width - others - 2 - 2 - 2)) if tt.size.width else 18      # 테두리·막대 칸 여백·세로 스크롤바
        cmax = max((r["cost"] for r in trend), default=0)
        cur = tt.cursor_row
        tt.clear()
        for r in rows:
            tt.add_row(r[0], r[1], r[2], Text(cch.fit_bar(r[3], cmax, bw), style="#33ccff"), r[4], r[5], r[6])
        if rows:
            tt.move_cursor(row=min(cur, len(rows) - 1), animate=False)
        self._need["stat-trend"] = len(rows) + 3

    def cost_h(self):
        """비용 그래프 높이(줄): 터미널이 높을수록 크게(6~12). 박스 = 그래프 + 시간축 1줄 + 테두리 2줄."""
        return max(6, min(12, self.size.height // 8))

    def _paint_cost_chart(self, fine, tot):
        """시간당(2주 넘으면 일당) 비용 면적 그래프. 선택한 단위(일·주…)는 아래 추이 표가 따르고, 그래프는 늘 곱게 잰다. 폭은 박스 폭에 맞춘다(usageui 의 전력 그래프처럼 위쪽에 크게)."""
        unit, rows = fine
        box = self.query_one("#stat-trend-chart", Static)
        box.border_title = f"비용 — {'시간당' if unit == 'hour' else '일당'} $"
        if not rows:
            box.update(Text(" 비용 기록 없음 — 이 기간·필터에 사용량이 없습니다", style="grey50")); box.border_subtitle = ""
            return
        step = 3600 if unit == "hour" else 86400
        pts = [(r["bucket"].timestamp(), r["cost"]) for r in rows]       # 버킷은 지역 시간의 naive 시각 — timestamp() 가 같은 지역 시간으로 읽는다
        t0, t1 = pts[0][0], pts[-1][0] + step
        w = self.query_one("#stat-trend-chart").size.width - 4 or 60
        t, top = cch.rate_chart(pts, t0, t1, step, max(30, w), self.cost_h(), "#33ccff", lambda v: f"${v:,.0f}" if v >= 10 else f"${v:.2f}")
        box.update(t)
        peak = max(rows, key=lambda r: r["cost"])
        box.border_subtitle = f"합계 ${tot['cost']:,.2f} · 최대 ${peak['cost']:,.2f} ({peak['bucket']:%m-%d %H시})" if unit == "hour" else f"합계 ${tot['cost']:,.2f} · 최대 ${peak['cost']:,.2f} ({peak['bucket']:%m-%d})"

    DASH_ROWS = {"dr1": ("stat-trend-chart", "stat-break"), "dr2": ("stat-trend",), "dr3": ("stat-limits-box", "stat-summary-box"), "dr4": ("projects",), "dr5": ("stat-sessions",)}
    DASH_NO_STRETCH = ("stat-break",)      # 같은 줄의 옆 박스(그래프)가 높아도 늘이지 않고 내용 높이로 위에 붙인다(빈 칸 대신 빈 공간)
    DASH_CAP = 26          # 박스 하나의 최대 높이(줄) — 표가 이보다 길면 안에서 스크롤

    def _fit_heights(self):
        """박스 높이를 내용(표 행 수·글 줄 수)에 맞춘다. 2열이면 한 줄(row)의 높이를 두 박스 중 큰 쪽에, 1열이면 박스마다 따로."""
        try:
            narrow = self.query_one("#dash-scroll").has_class("narrow")
            need = dict(getattr(self, "_need", {}))
            for tid in ("projects", "stat-break", "stat-sessions"):
                need[tid] = self.query_one("#" + tid, DataTable).row_count + 3
            need["stat-trend-chart"] = self.cost_h() + 3                    # 그래프 + 시간축 1줄 + 테두리
            need["stat-sessions"] = max(need["stat-sessions"], 12)       # 세션 표는 길어서 스크롤 — 최소한 열 줄은 보이게
            cap = {"projects": 12, "stat-trend": 14}
            h = {k: max(6, min(cap.get(k, self.DASH_CAP), v + (2 if k.endswith("-box") else 0))) for k, v in need.items()}
            for row, kids in self.DASH_ROWS.items():
                r = self.query_one("#" + row)
                if narrow:
                    r.styles.height = None
                    for k in kids:
                        self.query_one("#" + k).styles.height = h.get(k, 8)
                else:
                    for k in kids:
                        self.query_one("#" + k).styles.height = h.get(k, 8) if k in self.DASH_NO_STRETCH else None
                    r.styles.height = max(h.get(k, 8) for k in kids)
        except Exception:
            pass

    def _stat_changed(self):
        self._sync_selects()
        self.update_stat_state()
        self.reload_stats()

    def _sync_selects(self):
        """키(p·b·g·o)로 바꾼 상태를 드롭다운 값에 맞춘다(같은 값이면 건드리지 않아 Changed 가 되돌아오지 않는다)."""
        for sid, v in (("sel-period", self.stat_period), ("sel-bucket", self.stat_bucket), ("sel-by", self.stat_by), ("sel-order", self.stat_order)):
            try:
                uikit.sync_select(self.query_one("#" + sid, Select), v)
            except Exception:
                pass

    def on_select_changed(self, ev: Select.Changed):
        """드롭다운으로 기간·단위·분류·정렬을 고른다. 현재 상태와 같으면(키로 바꾼 값이 되돌아온 경우) 무시."""
        attr = {"sel-period": "stat_period", "sel-bucket": "stat_bucket", "sel-by": "stat_by", "sel-order": "stat_order"}.get(ev.select.id or "")
        if not attr or ev.value is Select.BLANK or getattr(self, attr) == ev.value:
            return
        setattr(self, attr, ev.value)
        self.update_stat_state()
        self.reload_stats()
        self.set_focus(None)

    def action_stat_period(self):
        if self.current_tab() == "dashboard" and len(self.screen_stack) == 1:
            self.stat_period = (self.stat_period + 1) % len(STAT_PERIODS)
            self._stat_changed()

    def action_stat_bucket(self):
        if self.current_tab() == "dashboard" and len(self.screen_stack) == 1:
            keys = list(cd.BUCKETS)
            self.stat_bucket = keys[(keys.index(self.stat_bucket) + 1) % len(keys)]
            self._stat_changed()

    def action_stat_by(self):
        if self.current_tab() == "dashboard" and len(self.screen_stack) == 1:
            keys = list(cd.BREAKDOWNS)
            self.stat_by = keys[(keys.index(self.stat_by) + 1) % len(keys)]
            self._stat_changed()

    def action_stat_order(self):
        if self.current_tab() == "dashboard" and len(self.screen_stack) == 1:
            keys = [k for k, _ in STAT_ORDERS]
            self.stat_order = keys[(keys.index(self.stat_order) + 1) % len(keys)]
            self._stat_changed()

    def action_stat_clear(self):
        if self.current_tab() == "dashboard" and len(self.screen_stack) == 1:
            for i in ("#f-repo", "#f-host", "#f-model"):
                self.query_one(i, Input).value = ""
            self.reload_stats()

    # --- 지침(프로젝트별 공유 정본) — 사람 전용 편집 경로. 로컬 캐시 파일은 건드리지 않는다(다음 `instr show`·세션 시작 동기화가 맞춘다)
    def reload_instr(self):
        try:
            with cc.connect(readonly=True) as c:
                rows = cd.instr_rows(c)
        except Exception as e:
            self.flash(f"DB 조회 실패: {e}", "error"); return
        tb = self.query_one("#instr-table", DataTable)
        keep = self.selected_key("#instr-table")
        tb.clear()
        for r in rows:
            tb.add_row(short_repo(r["repo"]), r["name"], r["rev"], r["host"], fmt_ts(r["at"]), f"{r['length']:,}", key=f"{r['repo']}|{r['name']}")
        keys = [f"{r['repo']}|{r['name']}" for r in rows]
        if keep in keys:
            tb.move_cursor(row=keys.index(keep))
        self.query_one("#instr-table").border_title = f"프로젝트 지침 {len(rows)}건(공유 정본) — Enter: 본문 · e: 편집기로 고치기"

    def edit_instr(self, repo: str, name: str) -> bool:
        if self.deny("지침 고치기(`donghans instr set` 을 쓰세요)"):
            return False
        """편집기($VISUAL·$EDITOR·vi)로 원문을 열고, 바뀌었으면 연 시점의 rev 를 기대값으로 DB 에 올린다. 거부(낡은 rev·비밀·빈 본문)는 사유를 알리고 저장하지 않는다. 저장되면 True."""
        with cc.connect(readonly=True) as c:
            got = cd.instr_raw(c, repo, name)
        if not got:
            self.flash("지침을 찾지 못했다(다른 기기가 지웠을 수 있다)", "error"); self.reload_instr(); return False
        rev, base = got
        fd, tmp = tempfile.mkstemp(prefix="instr-", suffix=".md", dir=os.environ.get("XDG_RUNTIME_DIR") or None)   # 0600
        try:
            with os.fdopen(fd, "w") as f:
                f.write(base)
            editor = (os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi").split()
            with self.suspend():
                subprocess.run([*editor, tmp])
            new = open(tmp, errors="ignore").read()
        finally:
            os.unlink(tmp)
        if new == base:
            self.flash("변경 없음"); return False
        with cc.connect() as c:
            code, msg = cd.instr_save(c, repo, name, new, cc.HOST, rev, masker=cs.load_masker(c))
        self.flash(msg, "information" if code == 0 else "error")
        if code == 0:
            self.reload_instr()
        return code == 0

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
        if self.deny("비밀 값 조회·추가·삭제·끄기, 후보 무시"):
            return
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
        if self.deny("비밀 값 조회·추가·삭제·끄기, 후보 무시"):
            return
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
        if self.deny("비밀 값 조회·추가·삭제·끄기, 후보 무시"):
            return
        if self.current_tab() == "instr" and len(self.screen_stack) == 1:
            key = self.selected_key("#instr-table")
            if key:
                repo, _, name = key.rpartition("|")
                self.edit_instr(repo, name)
            return
        key = self.selected_key("#secrets-table") if self.current_tab() == "secrets" else None
        if not key:
            return
        with cc.connect() as c:
            cd.set_enabled(c, key, not self.sec_rows[key]["enabled"])
        self.reload_secrets()

    def action_reveal(self):
        if self.deny("비밀 값 조회·추가·삭제·끄기, 후보 무시"):
            return
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
            tb.add_row(d["fp"], d["pattern"], Text(f"{cs.MASK} ({len(d['value'])}자)" if self.restricted else cs.preview(d["value"])), d["count"], len(d["sessions"]), ",".join(sorted(short_repo(r) for r in d["repos"]))[:50] or "-",
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
        if self.deny("비밀 값 조회·추가·삭제·끄기, 후보 무시"):
            return
        key = self.selected_key("#cands-table") if self.current_tab() == "cands" else None
        d = self.cand_rows.get(key or "")
        if not d:
            return
        with cc.connect() as c:
            cd.ignore_fp(c, d["fp"], d["pattern"])
        self.flash(f"무시: {d['fp']}")
        self.scan_candidates()


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("ctxui 는 화면(TTY)이 있는 터미널에서만 실행합니다")
    # LLM 세션이 실행하면(환경 표식) 제한 모드: 열람 제한 정보(비밀·후보)는 읽지도 보이지도 않고 치환을 끌 수 없다. 대시보드·검색·대조·지침 보기는 `donghans ctx` CLI 와 같은 범위라 허용
    CtxUI(restricted=cc.is_agent_session()).run()


if __name__ == "__main__":
    main()
