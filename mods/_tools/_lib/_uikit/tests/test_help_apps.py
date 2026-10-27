#!/usr/bin/env python3
"""uikit 를 쓰는 모든 앱의 도움말 통합 규칙 시험: 별도 「용어」 탭 없이 ? / F1 도움말 한 화면에 키 목록 + 용어·사용법 + 공통 종료 안내가 있는지.
정적(모든 앱 클래스의 HELP_TERMS) + 동적(Pilot: usageui · procui · notif). psycopg 가 있으면 ctxui 도 본다."""
import asyncio, json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))        # mods/_tools
for p in ("_lib/_uikit", "observe", "procui", "notif", "clipboard", "display", "claude-sessions", "claude-ctx", "_lib/_testkit", "../_data/claude-skills/donghans-host-resources/scripts"):
    sys.path.insert(0, os.path.join(DATA, p))
TMP = tempfile.mkdtemp(prefix="help-apps-")
os.makedirs(os.path.join(TMP, "notif")); open(os.path.join(TMP, "notif", "t.log"), "w").write(json.dumps({"ts": "2026-10-26 09:00:00", "app": "Slack", "summary": "제목", "body": "본문", "urgency": 1}, ensure_ascii=False) + "\n")
os.environ.update(NOTIF_LOG_DIR=os.path.join(TMP, "notif"), USER="t", OBSERVE_DATA_DIR=os.path.join(TMP, "v"), OBSERVE_STATE_DIR=os.path.join(TMP, "s"), PROCUI_STATE_DIR=os.path.join(TMP, "p"))
from harness import checker
check, finish = checker()
import uikit
from textual.widgets import Static

CLASSES = []
for mod, cls in (("usageui", "UsageUI"), ("procui", "ProcUI"), ("notif_ui", "NotifUI"), ("clipui", "ClipUI"), ("displayui", "DisplayUI"), ("claude_sessions", "SessionsUI"), ("ctxui", "CtxUI")):
    try:
        m = __import__(mod)
        CLASSES.append((mod, getattr(m, cls)))
    except ImportError as e:
        print(f"  (건너뜀: {mod} — {e})")
check("앱 클래스를 7개 중 6개 이상 읽음(ctxui 는 psycopg 필요)", len(CLASSES) >= 6, [m for m, _ in CLASSES])
for mod, cls in CLASSES:
    terms = cls.HELP_TERMS
    ok = isinstance(terms, list) and len(terms) >= 2 and all(isinstance(t, tuple) and len(t) == 2 and all(isinstance(x, str) and x.strip() for x in t) for t in terms)
    check(f"{mod}: HELP_TERMS 가 (용어, 설명) 2개 이상이고 비어 있지 않음", ok)
    check(f"{mod}: 용어 이름이 중복되지 않고 설명이 한 줄 이상(8자+)", len({k for k, _ in terms}) == len(terms) and all(len(d) >= 8 for _, d in terms))
    check(f"{mod}: HELP_NOTES 에 종료·Esc 규칙이 적혀 있음", cls.HELP_NOTES and any(("종료" in n or "q" in n) for n in cls.HELP_NOTES))
    check(f"{mod}: HelpMixin 을 쓰고 ?/F1 바인딩이 있음", issubclass(cls, uikit.HelpMixin) and any("f1" in b.key for b in cls.BINDINGS))
import usageui, usagedata as ud, procui, notif_ui
check("usageui: HELP_TERMS 는 용어집(GLOSSARY) 그대로이고 용어 탭(#help)·5 키가 없음", usageui.UsageUI.HELP_TERMS is usageui.uv.GLOSSARY and not any("tab('help')" in str(b.action) for b in usageui.UsageUI.BINDINGS))

async def help_of(app, key="f1"):
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(1.2)
        has_help_pane = bool(app.query("#helptext")) or bool(app.query("TabPane#help"))
        await pilot.press(key); await pilot.pause(0.5)
        scr = app.screen
        name = type(scr).__name__
        body = " ".join(str(scr.query_one(i, Static).render()) for i in ("#help-keys", "#help-terms", "#help-common")) if name == "HelpScreen" else ""
        await pilot.press("escape"); await pilot.pause(0.3)
        return name, body, type(app.screen).__name__, has_help_pane

async def main():
    for label, factory, terms in (("usageui", lambda: usageui.UsageUI(ud.preset("1시간", time.time()), tab="dashboard"), usageui.UsageUI.HELP_TERMS),
                                  ("procui", lambda: procui.ProcUI(log_path=os.path.join(TMP, "a.jsonl")), procui.ProcUI.HELP_TERMS),
                                  ("notif", lambda: notif_ui.NotifUI(), notif_ui.NotifUI.HELP_TERMS)):
        name, body, after, pane = await help_of(factory())
        check(f"{label}: F1 → 도움말 한 화면에 키 목록·용어(첫 용어 이름 포함)·공통(Ctrl+Q·Ctrl+C) 안내, Esc 로 닫힘, 용어 탭 없음",
              name == "HelpScreen" and "키" in body and "용어 · 사용법" in body and terms[0][0] in body and "Ctrl+Q" in body and "Ctrl+C" in body and after != "HelpScreen" and not pane, (name, body[:120], after, pane))
asyncio.run(main())
finish("help_apps")
