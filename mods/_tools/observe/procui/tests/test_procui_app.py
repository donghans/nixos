#!/usr/bin/env python3
"""procui Textual 앱 시험(헤드리스): 뷰·정렬·필터·펼침·선택·보호(하드/소프트 override)·종료 미리보기·SIGTERM·취소·기록.
종료 시험 대상은 시험이 prctl 로 고유 이름을 붙여 직접 띄운 프로세스뿐이다."""
import asyncio, json, os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
TMP = tempfile.mkdtemp(prefix="procui-app-test-")
os.environ["PROCUI_CONFIG"] = os.path.join(TMP, "none.toml"); os.environ["PROCUI_STATE_DIR"] = os.path.join(TMP, "state")
for p in (ROOT, os.path.join(DATA, "observe"), os.path.join(os.path.dirname(DATA), "_lib", "_testkit"), os.path.join(os.path.dirname(DATA), "_lib", "_uikit"), os.path.join(DATA, "..", "..", "_data", "claude-skills", "donghans-host-resources", "scripts")):
    sys.path.insert(0, p)
import procui, procactions as pa, procscan as ps
from textual.widgets import DataTable, Input, Static
from harness import checker
check, finish = checker()
LOG = os.path.join(TMP, "state", "procui", "actions.jsonl")
TAG = f"pt{os.getpid() % 100000}"

def spawn(name):
    pr = subprocess.Popen([sys.executable, "-c", f"import ctypes,time; ctypes.CDLL(None).prctl(15, b'{name}'); time.sleep(300)"])
    time.sleep(0.4)
    return pr
def head(app): return str(app.query_one("#head", Static).render())
def status(app): return str(app.query_one("#status", Static).render())
def keys(app): return list(app._rowkeys)
def log_lines(): return [json.loads(l) for l in open(LOG).read().splitlines()] if os.path.exists(LOG) else []
async def settle(pilot, t=0.5): await pilot.pause(t)
async def until(pilot, cond, timeout=10.0, step=0.15):
    """조건이 참이 될 때까지 기다린다(고정 대기는 부하가 큰 호스트에서 흔들려 조건 기다림으로 바꿨다). 끝내 거짓이면 False."""
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await pilot.pause(step)
    return cond()
async def started(pilot, app, min_groups=1):
    """앱이 첫 스캔을 마치고 0.8초 뒤 재스캔(CPU 계산)까지 끝낼 때까지."""
    await until(pilot, lambda: len(app.groups) >= min_groups and len(app.procs) > 10)
    await pilot.pause(1.0)

async def drive():
    a, b = spawn(f"{TAG}a"), spawn(f"{TAG}b")
    app = procui.ProcUI(filter_text=TAG, log_path=LOG)
    async with app.run_test(size=(150, 45)) as pilot:
        await started(pilot, app)
        check("시작: 소유 뷰·필터로 그룹 1개(내 작업), 필터 결과가 적어 자동 펼침(그룹 행 + 프로세스 2행)", app.view["name"] == "소유" and len(app.groups) == 1 and app.groups[0]["name"] == "내 작업" and len(keys(app)) == 3 and keys(app)[0] == "g|내 작업", keys(app))
        check("머리줄: 뷰 이름·그룹·프로세스·선택 0개", "뷰 소유" in head(app) and "선택 0개" in head(app))
        await pilot.press("space"); await settle(pilot)
        check("그룹 행에서 Space: 그룹 전체(보호 아닌 2개) 선택", len(app.sel) == 2 and "선택 2개" in head(app))
        await pilot.press("space"); await settle(pilot)
        check("Space 다시: 선택 해제", len(app.sel) == 0)
        await pilot.press("A"); await settle(pilot)
        check("A: 보이는 보호 안 된 프로세스 전체 선택", len(app.sel) == 2)
        # 취소 경로
        await pilot.press("k"); await settle(pilot)
        check("k: 미리보기 대화상자(대상 2개·SIGTERM 문구)", isinstance(app.screen, procui.ConfirmScreen) and "2개" in str(app.screen._body.plain) and "되돌릴 수 없습니다" in app.screen._hint)
        await pilot.press("escape"); await settle(pilot)
        check("Esc 로 취소하면 아무것도 죽지 않고 기록도 없음", a.poll() is None and b.poll() is None and log_lines() == [] and "취소" in status(app))
        # 실행 경로
        await pilot.press("k"); await settle(pilot)
        await pilot.press("y"); await until(pilot, lambda: a.poll() is not None and b.poll() is not None)
        check("y: SIGTERM 으로 두 프로세스 종료", a.poll() == -15 and b.poll() == -15, (a.poll(), b.poll()))
        L = log_lines()
        check("기록: 2건 sent, 그룹 이름·이름·PID 만(명령 인자 없음)", len(L) == 2 and all(r["status"] == "sent" and r["sig"] == 15 and r["group"] == "소유" for r in L) and set(L[0]) == {"t", "group", "pid", "comm", "sig", "status", "detail"})
        a.wait(); b.wait(); app.rescan(); await settle(pilot)      # 시험이 부모라 수거해야 좀비가 사라진다(실제로는 부모가 수거)
        check("종료 후(수거 뒤) 목록에서 사라지고 선택 비어 있음", len(app.sel) == 0 and not any(k.startswith("p|") for k in keys(app)) )

async def protection():
    c = spawn("sshd-ptest")                       # 소프트 보호(infra: sshd*)
    app = procui.ProcUI(filter_text="sshd-ptest", log_path=LOG)
    async with app.run_test(size=(150, 45)) as pilot:
        await started(pilot, app)
        pk = [k for k in keys(app) if k.startswith("p|")]
        check("소프트 보호 프로세스 행에 잠금(인프라) 표시, 그룹 행은 잠금 1", len(pk) == 1 and "잠금 1" in str(app.query_one("#tbl", DataTable).get_row_at(0)[6]) and "인프라" in str(app.query_one("#tbl", DataTable).get_row_at(1)[6]))
        await pilot.press("space"); await settle(pilot)
        check("그룹 Space: 전부 보호라 선택되지 않음", len(app.sel) == 0 and "전부 보호" in status(app))
        await pilot.press("A"); await settle(pilot)
        check("A: 보호 프로세스는 선택되지 않음", len(app.sel) == 0)
        await pilot.press("down"); await pilot.press("space"); await settle(pilot)
        check("프로세스 행 Space: 보호 해제 대화상자(이름 입력)", isinstance(app.screen, procui.OverrideScreen))
        check("보호 해제: 대화상자가 화면 가운데에 뜸(좌우 ±1칸 — 예전엔 왼쪽 위 구석)", abs(app.screen.query_one("#dialog").region.x + app.screen.query_one("#dialog").region.width / 2 - app.size.width / 2) <= 1)
        for ch in "wrong": await pilot.press(ch)
        await pilot.press("enter"); await settle(pilot)
        check("이름을 틀리게 입력하면 선택되지 않음", len(app.sel) == 0 and "취소" in status(app))
        await pilot.press("space"); await settle(pilot)
        for ch in "sshd-ptest": await pilot.press(ch)
        await pilot.press("enter"); await settle(pilot)
        check("이름을 정확히 입력하면 선택+override", len(app.sel) == 1 and len(app.override) == 1)
        await pilot.press("k"); await settle(pilot)
        check("미리보기에 보호를 푼 대상 1개 포함", isinstance(app.screen, procui.ConfirmScreen) and "1개" in app.screen._body.plain)
        await pilot.press("y"); await until(pilot, lambda: c.poll() is not None)
        check("override 한 소프트 보호 프로세스는 종료됨", c.poll() == -15)

async def hard():
    app = procui.ProcUI(filter_text=f"pid:{os.getppid()}", log_path=LOG)
    async with app.run_test(size=(150, 45)) as pilot:
        await started(pilot, app)
        pk = [k for k in keys(app) if k.startswith("p|")]
        check("시험을 띄운 쉘(부모=조상)은 목록에 있고 '내 터미널' 잠금", len(pk) == 1 and "내 터미널" in str(app.query_one("#tbl", DataTable).get_row_at(1)[6]))
        await pilot.press("down"); await pilot.press("space"); await settle(pilot)
        check("조상(하드 보호)은 이름을 입력해도 선택할 수 없음(대화상자도 안 뜸)", not isinstance(app.screen, procui.OverrideScreen) and len(app.sel) == 0 and "하드 보호" in status(app))
        await pilot.press("k"); await settle(pilot)
        check("선택 없이 k: 안내만", "선택된 프로세스가 없습니다" in status(app) and not isinstance(app.screen, procui.ConfirmScreen))

async def views():
    app = procui.ProcUI(log_path=LOG)
    async with app.run_test(size=(150, 45)) as pilot:
        await started(pilot, app)
        check("필터 없이: 소유 뷰 그룹들이 표에 나오고 모두 접힌 상태", len(app.groups) >= 2 and all(k.startswith("g|") for k in keys(app)))
        n = len(app.procs)
        check("그룹의 프로세스 합이 전체 프로세스 수와 같음(누락 없음)", sum(g["n"] for g in app.groups) == n)
        await pilot.press("g"); await settle(pilot)
        check("g: 다음 뷰(앱)로 순환", app.view["name"] == "앱" and "뷰 앱" in head(app))
        for _ in range(3): await pilot.press("g"); await settle(pilot)
        check("g 4번 더: 소유로 되돌아옴", app.view["name"] == "소유")
        await pilot.press("s"); await settle(pilot)
        check("s: 정렬 순환(CPU → 메모리)", app.sort == "mem" and "정렬 메모리" in head(app))
        rss = [g["rss"] for g in app.groups]
        check("메모리 정렬이면 그룹이 RSS 내림차순", rss == sorted(rss, reverse=True))
        check("g·s 키로 바꾸면 드롭다운도 따라간다(뷰 소유 · 정렬 메모리)", app.query_one("#sel-view").value == app.view_i == 0 and app.query_one("#sel-sort").value == "mem")
        app.query_one("#sel-view").value = 1; await settle(pilot)
        check("뷰 드롭다운: 고르면 뷰가 바뀌고 포커스가 표로 돌아간다(Space·k 가 표에 먹도록)", app.view["name"] == "앱" and "뷰 앱" in head(app) and app.focused is app.query_one("#tbl"), (app.view["name"], app.focused))
        app.query_one("#sel-view").value = 0; await settle(pilot)
        app.query_one("#sel-sort").value = "cpu"; await settle(pilot)
        check("정렬 드롭다운: CPU 로 바꾸면 정렬 이름이 바뀐다", app.sort == "cpu" and "정렬 CPU" in head(app), app.sort)
        app.query_one("#sel-sort").value = "mem"; await settle(pilot)
        check("드롭다운으로 원래대로(소유·메모리)", app.view["name"] == "소유" and app.sort == "mem")
        await pilot.press("enter"); await settle(pilot)
        check("그룹 행 Enter: 펼침", app.groups[0]["name"] in app.expanded and any(k.startswith("p|") for k in keys(app)))
        await pilot.press("enter"); await settle(pilot)
        check("다시 Enter: 접힘", app.groups[0]["name"] not in app.expanded)
        await pilot.press("d"); await settle(pilot)
        check("d: 그룹 상세 대화상자", isinstance(app.screen, procui.InfoScreen) and "상위 12" in app.screen._body.plain)
        await pilot.press("escape"); await settle(pilot)
        await pilot.press("enter"); await pilot.press("down"); await pilot.press("d"); await settle(pilot)
        check("프로세스 행 d: 세부 사용량(CPU·메모리·FD·cgroup)", isinstance(app.screen, procui.InfoScreen) and all(h in app.screen._body for h in ("CPU", "메모리", "열린 FD", "cgroup", "보호")))
        await pilot.press("escape"); await settle(pilot)
        await pilot.press("a"); await settle(pilot)
        check("a: 자동 갱신 켜짐(타이머), 다시 누르면 꺼짐", app._timer is not None and "자동 갱신 켜짐" in head(app))
        await pilot.press("a"); await settle(pilot)
        check("자동 갱신 끄면 타이머 없음", app._timer is None)
        inp = app.query_one("#filter", Input)
        await pilot.press("slash"); await settle(pilot)
        check("/: 필터 입력칸으로 포커스", app.focused is inp)
        for ch in "zzzz-nope": await pilot.press(ch)
        await settle(pilot)
        check("필터에 일치 없으면 그룹 0개", len(app.groups) == 0 and "프로세스 0/" in head(app))
        await pilot.press("enter"); await settle(pilot)
        check("Enter: 표로 포커스 복귀", app.focused is app.query_one("#tbl", DataTable))
        await pilot.press("question_mark"); await settle(pilot)
        check("?: 도움말에 종료·선택 키가 보임", "종료(미리보기)" in str([r for r in app.screen._rows]))

async def custom():
    cfg = os.path.join(TMP, "g.toml")
    open(cfg, "w").write('[[view]]\nname = "작업별"\n[[view.rule]]\ngroup = "파이썬"\napp = ["python*"]\n[[view]]\nname = "깨짐"\n[[view.rule]]\nnope = 1\n[protect]\napp = ["pt-custom*"]\n')
    d = spawn("pt-custom1")
    app = procui.ProcUI(view="작업별", filter_text="pt-custom", config_path=cfg, log_path=LOG)
    async with app.run_test(size=(150, 45)) as pilot:
        await started(pilot, app)
        check("groups.toml: 사용자 뷰로 시작, 깨진 규칙은 경고(상태줄)", app.view["name"] == "작업별" and "설정 경고" in status(app))
        check("사용자 [protect] 규칙이 보호로 표시됨", "사용자 규칙" in str(app.query_one("#tbl", DataTable).get_row_at(1)[6]))
    d.kill(); d.wait()
asyncio.run(drive()); asyncio.run(protection()); asyncio.run(hard()); asyncio.run(views()); asyncio.run(custom())
finish("procui_app")
