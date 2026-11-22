#!/usr/bin/env python3
"""sbox 도구 층 릴리스 최소 연령(쿨다운) 시험(plan dev-sandbox-pilot S55). 네트워크 없음 — `tools.http` 를 가짜 응답으로 바꾸고 날짜는 모두 오늘 기준 상대값이다.
지키는 것:
 ① 움직이는 스펙(22·latest 등)은 공개된 지 N일 미만인 버전을 건너뛴다(처음 해석할 때 막 올라온 악성 릴리스를 받지 않는다)
 ② 정확한 X.Y.Z·쿨다운 0·날짜를 못 읽은 후보는 막히지 않되 날짜 불명은 알린다(안 보이는 안전이 되지 않게)
 ③ 쿨다운이 더 낮은 버전을 골라도 롤백 방지(S47)가 오작동하지 않는다 — 단 「이전에 본 버전」이 이번에 건너뛴 후보가 아닐 때의 진짜 롤백은 여전히 거부한다
실행: python3 -I core/sbox/tests/test_tools_age.py  (mods/_tools/run-tests.sh 의 sbox-tools-age)"""
import contextlib, io, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp()
os.environ["SBOX_TOOLS_LOCK"] = os.path.join(TMP, "tools.lock")
os.environ.pop("SBOX_TOOLS_MIN_AGE_DAYS", None)
os.environ.pop("SBOX_TOOLS_ALLOW_DOWNGRADE", None)
sys.path.insert(0, ROOT)
import tools  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


now = time.time()
ago = lambda d: now - d * 86400  # noqa: E731
day = lambda d: time.strftime("%Y-%m-%d", time.gmtime(ago(d)))  # noqa: E731
iso = lambda d: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ago(d)))  # noqa: E731

# ① 순수 함수
check("_epoch: 날짜·ISO·pbs 태그·HTTP 날짜를 읽고 쓰레기는 None",
      abs(tools._epoch(day(3)) - ago(3)) < 86400 and abs(tools._epoch(iso(3)) - ago(3)) < 5 and tools._epoch("20260101") is not None
      and tools._epoch("Tue, 10 Nov 2026 16:48:48 GMT") is not None and tools._epoch("garbage") is None and tools._epoch(None) is None)
check("_is_moving: latest·lts·stable·22·22.11 은 움직임, 22.11.0 은 아님", all(tools._is_moving(s) for s in ("latest", "lts", "stable", "22", "22.11")) and not tools._is_moving("22.11.0"))
v, notes, sk = tools.pick_aged([("2.0.0", ago(1)), ("1.9.0", ago(3)), ("1.8.0", ago(20))], 7, now)
check("pick_aged: 7일 미만 둘을 건너뛰고 20일 된 것을 고르며 건너뛴 목록을 준다", v == "1.8.0" and sk == ["2.0.0", "1.9.0"] and notes, (v, sk, notes))
v, notes, sk = tools.pick_aged([("2.0.0", ago(8))], 7, now)
check("pick_aged: 첫 후보가 충분히 오래되면 그대로(알림 없음)", v == "2.0.0" and notes == [] and sk == [], (v, notes, sk))
v, notes, sk = tools.pick_aged([("2.0.0", ago(1)), ("1.9.0", ago(2))], 7, now)
check("pick_aged: 전부 젊으면 None + 사유", v is None and notes, (v, notes))
v, notes, sk = tools.pick_aged([("2.0.0", None)], 7, now)
check("pick_aged: 날짜를 못 읽으면 막지 않고 「날짜 불명」을 알린다", v == "2.0.0" and any("날짜 불명" in x for x in notes), (v, notes))
v, notes, sk = tools.pick_aged([("2.0.0", ago(0.1))], 0, now)
check("pick_aged: 0 이면 쿨다운을 끈다", v == "2.0.0" and notes == [])
gen_calls = []
def lazy():
    for x in (("3.0.0", ago(30)), ("2.0.0", ago(40))):
        gen_calls.append(x[0]); yield x
tools.pick_aged(lazy(), 7, now)
check("pick_aged: 게으르게 소비(고른 뒤 더 조회하지 않음 — Go 의 HEAD 요청 수 억제)", gen_calls == ["3.0.0"], gen_calls)

# ② resolve — Node 인덱스를 가짜로
INDEX = [{"version": "v22.12.0", "date": day(1), "lts": "Jod"}, {"version": "v22.11.0", "date": day(30), "lts": "Jod"}, {"version": "v22.10.0", "date": day(60), "lts": False},
         {"version": "v27.0.0-alpha.0", "date": day(0), "lts": False}]
tools.http = lambda url: json.dumps(INDEX).encode() if url == tools.NODE_INDEX else (_ for _ in ()).throw(AssertionError("예상 밖 요청 " + url))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    r22 = tools.resolve("node", "22")
check("node 22: 1일 된 22.12.0 은 건너뛰고 22.11.0(알림이 stderr 에)", r22 == "22.11.0" and "22.12.0" in err.getvalue(), (r22, err.getvalue()))
with contextlib.redirect_stderr(io.StringIO()):
    check("정확한 22.12.0 은 쿨다운 대상 아님(사용자가 직접 고른 것)", tools.resolve("node", "22.12.0") == "22.12.0")
    os.environ["SBOX_TOOLS_MIN_AGE_DAYS"] = "0"
    check("SBOX_TOOLS_MIN_AGE_DAYS=0 이면 쿨다운을 끈다", tools.resolve("node", "22") == "22.12.0")
    os.environ["SBOX_TOOLS_MIN_AGE_DAYS"] = "90"
    try:
        tools.resolve("node", "22"); check("모든 후보가 N일 미만이면 거부", False)
    except SystemExit:
        check("모든 후보가 N일 미만이면 거부", True)
    os.environ.pop("SBOX_TOOLS_MIN_AGE_DAYS")

# ③ 롤백 방지와의 상호작용 — 잠금에 「이전에 본 최고 버전」을 직접 심는다
key = "_max/node/lts"      # 롤백 방지는 latest·lts·stable 에만 걸린다(22 같은 메이저 스펙에는 원래 없음)
lock = tools.load_lock(); lock[key] = "22.12.0"; tools.save_lock(lock)          # 쿨다운이 생기기 전에 젊은 22.12.0 을 본 적이 있는 상태
with contextlib.redirect_stderr(io.StringIO()):
    r = tools.resolve("node", "lts")
check("이전에 본 22.12.0 이 이번에 건너뛴 후보면 롤백으로 오인하지 않고 22.11.0 을 고른다(기준선은 그대로)", r == "22.11.0" and tools.load_lock()[key] == "22.12.0", (r, tools.load_lock()))
lock = tools.load_lock(); lock[key] = "22.14.0"; tools.save_lock(lock)           # 후보 목록에 없는(설명되지 않는) 더 높은 이전 버전 = 진짜 롤백 신호
try:
    with contextlib.redirect_stderr(io.StringIO()):
        tools.resolve("node", "lts")
    check("설명되지 않는 더 높은 이전 버전은 여전히 롤백으로 거부", False)
except SystemExit:
    check("설명되지 않는 더 높은 이전 버전은 여전히 롤백으로 거부", True)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print(f"sbox-tools-age {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
