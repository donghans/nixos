#!/usr/bin/env python3
"""notif 시험: 기록 파서(JSON·이전 형식), 필터/묶음/통계, 장애 감시(새 실패만 알림), waybar JSON, Notify 변환, (textual 이 있으면) 화면."""
import datetime, gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import notif
from harness import checker, tmpdir
check, finish = checker()
copied = []
notif.copy_text = lambda t: copied.append(t) or True

LEG = "[2026-10-19 15:09:39] [kitty] [Claude Code] Claude is waiting for your input"
JS = json.dumps({"ts": "2026-10-19 16:00:00", "app": "system-health", "summary": "서비스 실패: x", "body": "줄1\n줄2", "urgency": 2}, ensure_ascii=False)
e1, e2 = notif.parse_line(LEG), notif.parse_line(JS)
check("이전 형식 한 줄 파싱(긴급도 알 수 없음)", e1 and e1["app"] == "kitty" and e1["summary"] == "Claude Code" and e1["urgency"] is None, str(e1))
check("JSON 줄 파싱(줄바꿈 본문·긴급도 유지)", e2 and e2["body"] == "줄1\n줄2" and e2["urgency"] == 2, str(e2))
check("깨진 줄/빈 줄은 무시", notif.parse_line("garbage") is None and notif.parse_line("") is None and notif.parse_line("{bad") is None)

d = tmpdir()
rows = [LEG, JS, "[2026-10-18 09:00:00] [Slack] [메시지] 안녕", json.dumps({"ts": "2026-10-19 17:00:00", "app": "Slack", "summary": "또", "body": "", "urgency": 1})]
open(f"{d}/u.log", "w").write("\n".join(rows[:2]) + "\n")
with gzip.open(f"{d}/u.log.3.gz", "wt") as f: f.write(rows[2] + "\n")
open(f"{d}/u.log.1", "w").write(rows[3] + "\nbroken line\n")
open(f"{d}/other.log", "w").write(LEG + "\n")
ents = notif.read_entries(d, "u")
check("회전된 파일(.3.gz, .1, 현재)까지 오래된 순으로 읽고, 다른 사용자 파일은 제외", [e["app"] for e in ents] == ["Slack", "Slack", "kitty", "system-health"], str([e["app"] for e in ents]))
# 부팅 직후 시각이 앞선 항목이 있어도 기록된 순서가 "최신" 기준이다(시각 정렬 안 함)
d2 = tmpdir(); open(f"{d2}/u.log", "w").write("[2026-10-19 19:33:07] [a] [부팅직후 앞선 시각] x\n[2026-10-19 15:09:39] [b] [나중에 기록] y\n")
check("기록 순서 유지: 시각이 더 큰 항목이 앞에 기록돼도 나중에 기록된 것이 1번", notif.select(notif.read_entries(d2, "u"))[0]["summary"] == "나중에 기록")
open(f"{d2}/u.log.10", "w").write("[2026-09-01 00:00:00] [old] [열번째] z\n"); open(f"{d2}/u.log.2", "w").write("[2026-10-01 00:00:00] [mid] [두번째] z\n")
check("회전 번호는 숫자로 비교(.10 이 .2 보다 오래됨)", [e["app"] for e in notif.read_entries(d2, "u")] == ["old", "mid", "a", "b"], str([e["app"] for e in notif.read_entries(d2, "u")]))

now = datetime.datetime(2026, 10, 19, 18, 0, 0)
check("select: 가장 나중에 기록된 것이 1번", notif.select(ents)[0]["summary"] == "서비스 실패: x")
check("select: 앱 필터", [e["summary"] for e in notif.select(ents, app="Slack")] == ["또", "메시지"])
check("select: 기간 필터(3시간)", len(notif.select(ents, since=notif.parse_since("3h", now))) == 3)
check("select: 글자 검색은 대소문자 무시, 본문도 검색", len(notif.select(ents, grep="CLAUDE")) == 1 and len(notif.select(ents, grep="줄2")) == 1)
check("문제 알림 = system-health 또는 긴급도 2", [e["app"] for e in notif.select(ents, problems=True)] == ["system-health"])
check("긴급만", len(notif.select(ents, urgent=True)) == 1)
try: notif.parse_since("abc", now); bad = False
except ValueError: bad = True
check("잘못된 기간은 오류", bad)

g = notif.group_by_app(ents)
check("앱별 묶음: 건수 많은 순, 긴급 건수/마지막 시각", g[0][:3] == ("Slack", 2, 0) and g[0][3] == datetime.datetime(2026, 10, 19, 17, 0) and [r[0] for r in g] == ["Slack", "kitty", "system-health"], str(g))
st = notif.stats(ents)
check("통계: 전체/시간대/긴급도 분포", st["total"] == 4 and st["by_hour"][15] == 1 and st["urgency"][2] == 1 and st["urgency"][None] == 2, str(st["urgency"]))
check("통계 표시에 앱과 막대가 나옴", "Slack" in notif.render_stats(st) and "█" in notif.render_stats(st))
check("기록 없을 때 통계 문구", "없습니다" in notif.render_stats(notif.stats([])))

# Notify 호출 → 기록 한 줄
line = notif.entry_from_notify(["app", 0, "", "제목", "본문", [], {"urgency": {"type": "y", "data": 2}}, -1])
j = json.loads(line)
check("Notify 변환: 앱/제목/본문/긴급도", j["app"] == "app" and j["summary"] == "제목" and j["urgency"] == 2, line)
check("Notify 변환: 긴급도 힌트가 없으면 None", json.loads(notif.entry_from_notify(["a", 0, "", "t", "b", [], {}, -1]))["urgency"] is None)
check("Notify 변환: 제목이 비면 기록 안 함", notif.entry_from_notify(["a", 0, "", "", "b", [], {}, -1]) is None)
check("Notify 변환 결과를 다시 읽을 수 있음", notif.parse_line(line)["summary"] == "제목")

# 검색창 문법(clipui 와 같은 방식)과 select 확장
q = notif.parse_query("app:sl is:problem since:3h 안녕 since:x", now)
check("parse_query: app:/is:/since: 와 나머지 글자, 잘못된 기간은 글자로", q["app_like"] == "sl" and q["problems"] and not q["urgent"] and q["since"] == now - datetime.timedelta(hours=3) and q["words"] == ["안녕", "since:x"], str(q))
check("select app_like: 앱 이름에 글자 포함(대소문자 무시)", [e["app"] for e in notif.select(ents, app_like="SLA")] == ["Slack", "Slack"])
check("select words: 모두 포함해야 함", len(notif.select(ents, words=["claude", "waiting"])) == 1 and len(notif.select(ents, words=["claude", "없는글자"])) == 0)

# 장애 감시: 새 실패만 알린다
sf = f"{d}/health.json"; alerts = []; refreshed = []
cur = [[("system", "a.service")]]
def units(): return cur[0]
def run_h(): return notif.health(sf, alert=lambda s, u: alerts.append((s, u)), refresh=lambda: refreshed.append(1), units=units)
r = run_h()
check("첫 실행: 실패한 a 를 알림", alerts == [("system", "a.service")] and r["new"] == [("system", "a.service")] and len(refreshed) == 1)
run_h()
check("같은 상태에서 다시 실행하면 알림도 waybar 갱신도 없음", len(alerts) == 1 and len(refreshed) == 1)
cur[0] = [("system", "a.service"), ("user", "b.service")]; run_h()
check("새로 실패한 b 만 알림", alerts[-1] == ("user", "b.service") and len(alerts) == 2 and len(refreshed) == 2)
cur[0] = [("user", "b.service")]; run_h()
check("a 가 복구되면 알림 없이 목록에서 빠지고 waybar 갱신", len(alerts) == 2 and len(refreshed) == 3 and notif.load_state(sf)["failed"] == [["user", "b.service"]])
check("waybar JSON: 개수와 목록", json.loads(notif.waybar_json(sf))["text"].endswith("1") and "b.service" in json.loads(notif.waybar_json(sf))["tooltip"])
cur[0] = []; run_h()
check("실패가 없으면 waybar 출력이 비어 모듈이 사라짐", notif.waybar_json(sf) == "")
check("상태 파일이 깨져 있어도 빈 상태로 시작", notif.load_state(f"{d}/nonexistent.json") == {"failed": []})

# systemctl 출력 파싱(가짜 실행)
real_run = notif.run
class R:  # noqa
    def __init__(self, out): self.stdout = out
notif.run = lambda *c, **k: R("● x.service loaded failed failed X\ny.timer loaded failed failed Y\n" if "--user" not in c else "u.service loaded failed failed U\n")
fu = notif.failed_units()
notif.run = real_run
check("failed_units: 시스템/사용자 구분, 앞의 점 제거", fu == [("system", "x.service"), ("system", "y.timer"), ("user", "u.service")], str(fu))

# 복사 번호는 같은 조건의 list 번호와 같다
notif.LOG_DIR = d; notif.USER = "u"
import io, contextlib
orig = notif.read_entries
notif.read_entries = lambda: orig(d, "u")
with contextlib.redirect_stdout(io.StringIO()):
    rc = notif.main(["copy", "2", "--app", "Slack"])
check("copy: 앱 필터를 건 list 의 2번(메시지)을 복사", rc == 0 and copied == ["메시지\n안녕"], str(copied))
with contextlib.redirect_stdout(io.StringIO()):
    rc2 = notif.main(["copy", "1", "--body", "--problems"])
check("copy --body: 본문만", rc2 == 0 and copied[-1] == "줄1\n줄2")
with contextlib.redirect_stderr(io.StringIO()):
    rc3 = notif.main(["copy", "9"])
check("범위를 벗어난 번호는 실패", rc3 == 1)

# 화면(textual 이 있을 때만) — clipui 와 같은 조작: 검색창 필터, F키, Enter 복사 후 종료, Esc 단계적 해제
try:
    import textual, asyncio, notif_ui
except ImportError:
    print("  (textual 없음: 화면 시험은 건너뜀 — PYTHON=<textual 이 있는 python> 으로 실행)")
else:
    from textual.widgets import Input
    fresh = [dict(e, ts=datetime.datetime.now() - datetime.timedelta(minutes=10 * (len(ents) - i))) for i, e in enumerate(ents)]
    notif.read_entries = lambda: fresh
    notif.failed_units = lambda: []
    notif.health = lambda: {"failed": [("user", "x.service")], "new": []}

    async def ui():
        app = notif_ui.NotifUI()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            check("화면: 전체 보기에 알림이 나오고 가장 나중에 기록된 것이 맨 위", len(app.shown) == 4 and app.shown[0]["summary"] == "서비스 실패: x")
            check("화면: 검색창에 포커스(바로 입력 가능)", app.focused is app.query_one("#search", Input))
            await pilot.press(*"app:slack"); await pilot.pause()
            check("화면: app: 필터", len(app.shown) == 2 and all(e["app"] == "Slack" for e in app.shown))
            await pilot.press("escape"); await pilot.pause()
            check("화면: Esc 는 먼저 검색어만 지움(종료 안 함)", app.query_one("#search", Input).value == "" and len(app.shown) == 4 and app.is_running)
            await pilot.press(*"is:problem"); await pilot.pause()
            check("화면: is:problem 필터", [e["app"] for e in app.shown] == ["system-health"])
            await pilot.press("escape"); await pilot.pause()
            await pilot.press("down", "down"); await pilot.pause()
            check("화면: 검색창에 있어도 ↓ 로 목록 이동", app.query_one(notif_ui.NotifList).highlighted == 2)
            await pilot.press("f6"); await pilot.pause()
            check("화면: F6 앱별 보기는 앱 묶음 3개(건수 많은 Slack 이 맨 위)", app.view == "앱별" and len(app.shown) == 3 and app.shown[0][0] == "Slack", str(app.shown))
            await pilot.press("enter"); await pilot.pause()
            check("화면: 앱별에서 Enter 하면 그 앱 안으로(종료하지 않음)", app.app_filter == "Slack" and app.view == "전체" and len(app.shown) == 2 and app.is_running)
            await pilot.press("escape"); await pilot.pause()
            check("화면: Esc 로 앱 필터 해제", app.app_filter is None and len(app.shown) == 4)
            await pilot.press("f8"); await pilot.pause()
            check("화면: F8 같은 앱만(맨 위 항목의 앱)", app.app_filter == "system-health" and len(app.shown) == 1)
            await pilot.press("f8"); await pilot.pause()
            await pilot.press("f6", "f6"); await pilot.pause()
            check("화면: F6 두 번이면 문제 보기", app.view == "문제" and [e["app"] for e in app.shown] == ["system-health"])
            await pilot.press("f10"); await pilot.pause()
            from textual.screen import ModalScreen
            check("화면: F10 서비스 점검은 대화상자로 목록을 보여줌", isinstance(app.screen, ModalScreen) and app.failed == [("user", "x.service")])
            await pilot.press("escape"); await pilot.pause()
            check("화면: Esc 로 대화상자 닫기", not isinstance(app.screen, ModalScreen))
            await pilot.press("f9"); await pilot.pause()
            check("화면: F9 통계 대화상자", isinstance(app.screen, notif_ui.StatsScreen))
            await pilot.press("escape"); await pilot.pause()
            await pilot.press("f7"); await pilot.pause()
            check("화면: F7 미리보기 숨김", app.query_one("#main").has_class("hide-preview"))
            await pilot.press("f7"); await pilot.pause()

        # 체크 후 Enter: 체크한 것을 모두 복사하고 종료
        app = notif_ui.NotifUI()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("f6", "f6", "f6"); await pilot.pause()      # 전체로 한 바퀴
            await pilot.press("f2", "f2"); await pilot.pause()
            check("화면: F2 로 체크(표시와 상태줄)", len(app.marked) == 2 and "체크 2개" in str(app.query_one("#status").render()))
            await pilot.press("enter"); await pilot.pause()
        check("화면: Enter 는 체크한 알림을 모두 복사하고 종료", not app.is_running and copied[-1].count("\n\n") == 1 and "서비스 실패: x" in copied[-1], copied[-1])
        app = notif_ui.NotifUI()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("enter"); await pilot.pause()
        check("화면: 체크가 없으면 Enter 는 현재 항목(제목+본문)을 복사하고 종료", not app.is_running and copied[-1] == "서비스 실패: x\n줄1\n줄2", copied[-1])
        for size, cls in (((80, 30), "narrow"), ((120, 10), "short")):
            app = notif_ui.NotifUI()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                check(f"화면: 크기 {size} 에서 {cls} 배치", app.query_one("#main").has_class(cls))
    asyncio.run(ui())
finish("notif")
