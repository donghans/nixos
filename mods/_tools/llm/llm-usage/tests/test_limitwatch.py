#!/usr/bin/env python3
"""limitwatch.py(스킬 donghans-limit-watch)의 보정(calibrate)·예상(estimate)·사후 비교(review)·고정(pin) 시험.
합성 limits.jsonl 을 `--file` 로 주입하고(보정·예측 파일은 그 파일 옆에 생긴다) 실제 스크립트를 `python3 -I` 로 실행한다.
숫자는 시험이 정한 $/pt 에서 거꾸로 만든 합성값이다(이 머신 실제 기록의 값 아님). 실제 기록이 있으면 마지막에 중앙값이 대략 맞는지만 본다."""
import json, os, statistics, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "_data", "claude-skills", "donghans-limit-watch", "scripts", "limitwatch.py")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
assert os.path.exists(SCRIPT), SCRIPT

NOW = 1_795_000_000.0          # 시험용 현재 시각(2026-11-18 근처). 보정 시작일(10-28)보다 뒤
DAY = 86400
ENV0 = {"HOME": "/nonexistent", "PATH": os.environ.get("PATH", ""), "LIMITWATCH_PLAN": "max_5x"}


def run(d, *args, env=None, now=NOW):
    e = dict(ENV0, **(env or {}))
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--file", os.path.join(d, "limits.jsonl"), "--now", str(now), *args], capture_output=True, text=True, env=e, cwd=d)
    return r.returncode, r.stdout, r.stderr


def line(t, sid, f, fr, cost, s=10, sr=None, acct="a@x", plan="max_5x", model="claude-sonnet-5-5"):
    d = dict(ts=__import__("datetime").datetime.fromtimestamp(t, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000"), session_id=sid,
             five_hour=dict(used_percentage=f, resets_at=fr), seven_day=dict(used_percentage=s, resets_at=sr or int(fr + 2 * DAY)), cost_usd=cost, model=model)
    if acct: d["account_email"] = acct
    if plan: d["account_plan"] = plan
    return json.dumps(d)


def window(start, k, top=20, first=2, sid="win00000", **kw):
    """start 에 시작하는 5h 창: 첫 %=first, 최고 %=top, 세션 비용 증가 = (top)*k 달러 → 이 창의 $/pt = top 기준 k(최고 % 로 나눔)."""
    fr = int(start + 18000); usd = top * k
    pts = [(60, first, 1.0), (3600, (first + top) // 2, 1.0 + usd / 2), (7200, top, 1.0 + usd)]
    return [line(start + dt, sid + str(int(start) % 97), f, fr, c, **kw) for dt, f, c in pts]


def write(d, lines):
    with open(os.path.join(d, "limits.jsonl"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def mk(ks, base=NOW - 15 * DAY, **kw):
    out = []
    for i, k in enumerate(ks):
        out += window(base + i * 6 * 3600, k, **kw)
    return out


def jrun(d, *args, **kw):
    rc, out, err = run(d, *args, "--json", **kw)
    try:
        return rc, json.loads(out)
    except ValueError:
        return rc, {"_raw": out, "_err": err}


def calfile(d, **kw):
    ent = dict(five=dict(median=2.0, p25=1.8, p75=2.2, n=12), seven=dict(median=10.0, p25=9.5, p75=10.5, n=3), updated="2026-11-09T00:00:00+09:00", pinned={})
    ent.update(kw)
    json.dump(dict(version=1, plans={"max_5x": ent}), open(os.path.join(d, "limit-calibration.json"), "w"))


# ───── S1 calibrate
d = tempfile.mkdtemp(prefix="lw-test-")
ks = [1.5, 1.6, 1.7, 1.7, 1.8, 1.9, 1.65, 1.75, 1.7, 1.72]   # 10개 창
write(d, mk(ks))
rc, j = jrun(d, "calibrate")
five = (j.get("plans") or [{}])[0].get("five") or {}
check("calibrate: 창 10개를 모아 5h 중앙값을 낸다(= 시험이 정한 값의 중앙값)", rc == 0 and five.get("n") == 10 and abs(five["median"] - statistics.median(ks)) < 0.01, str(j))
check("calibrate: --write 없으면 파일을 만들지 않는다", not os.path.exists(os.path.join(d, "limit-calibration.json")))
rc, j = jrun(d, "calibrate", "--write")
cal = json.load(open(os.path.join(d, "limit-calibration.json"))) if os.path.exists(os.path.join(d, "limit-calibration.json")) else {}
check("calibrate --write: 창 8개 이상·폭 좁으면 파일을 쓴다", j.get("wrote") is True and abs(cal["plans"]["max_5x"]["five"]["median"] - statistics.median(ks)) < 0.01, str(j))
check("calibrate --write: 7d 창이 모자라면 7d 값은 비워 둔다(노트에 이유)", cal["plans"]["max_5x"].get("seven") is None and any("7d" in n for n in j["notes"]), str(j))

# 창 모자람: 기존 파일 불변
before = open(os.path.join(d, "limit-calibration.json")).read()
write(d, mk(ks[:5]))
rc, j = jrun(d, "calibrate", "--write")
check("calibrate --write: 창 5개(8개 미만)면 쓰지 않고 기존 파일 불변", j.get("wrote") is False and open(os.path.join(d, "limit-calibration.json")).read() == before and any("창 5개" in n for n in j["notes"]), str(j))
# 폭 초과
write(d, mk([0.5, 0.6, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]))
rc, j = jrun(d, "calibrate", "--write")
check("calibrate --write: 25/75분위 폭이 중앙값의 50 % 초과면 쓰지 않음", j.get("wrote") is False and open(os.path.join(d, "limit-calibration.json")).read() == before and any("폭" in n for n in j["notes"]), str(j))

# 필터: 계정/플랜 없음·시작일 전·첫 % 큼·최고 % 작음·파일 없음
d2 = tempfile.mkdtemp(prefix="lw-test-")
L = mk(ks)
L += window(NOW - 16 * DAY, 9.0, sid="noplan00", plan=None)                      # 플랜 없음 → 제외
L += window(NOW - 16 * DAY + 7 * 3600, 9.0, sid="noacct00", acct=None)             # 계정 없음 → 제외
L += window(NOW - 17 * DAY, 9.0, sid="midwin00", first=8)                           # 첫 % 8 > 3 → 제외
L += window(NOW - 17 * DAY + 7 * 3600, 9.0, sid="small000", top=9)                  # 최고 % 9 < 10 → 제외
L += window(NOW - 40 * DAY, 9.0, sid="old00000")                                    # 21일 밖 → 제외
write(d2, L)
rc, j = jrun(d2, "calibrate")
check("calibrate: 플랜·계정 없음, 첫 % 3 초과, 최고 % 10 미만, 최근 21일 밖 창은 제외", j["plans"][0]["five"]["n"] == 10 and len(j["plans"]) == 1, str(j))
rc, j = jrun(d2, "calibrate", "--days", "60", "--since", "2026-01-01T00:00:00+09:00")
check("calibrate: --days·--since 로 범위를 넓히면 옛 창(21일 밖)이 들어온다", j["plans"][0]["five"]["n"] == 11, str(j))
rc, j = jrun(d2, "calibrate", "--days", "60")   # 시작일 하한(기본 2026-10-28)이 항상 우선: NOW-40일은 10-ish
import datetime as _dt
since_default = _dt.datetime.fromisoformat("2026-10-28T00:00:00+09:00").timestamp()
exp = 10 + (1 if NOW - 40 * DAY - 0 >= since_default else 0)
check("calibrate: 시작일 하한이 --days 보다 우선(하한 전 창은 제외)", j["plans"][0]["five"]["n"] == exp, f"{j['plans'][0]['five']['n']} vs {exp}")

rc, j = jrun(d, "calibrate", now=NOW + 20 * DAY)
check("calibrate: 최근 21일 밖(시작일 하한은 통과)의 창은 제외", rc == 0 and j["plans"] == [], str(j))
rc, j = jrun(d, "calibrate", "--days", "60", now=NOW + 20 * DAY)
check("calibrate: --days 를 늘리면 그 창이 들어온다", j["plans"] and j["plans"][0]["five"]["n"] == 10, str(j))

# 계정 섞임: pro 계정 창은 pro 로 따로, max_5x 값은 그대로
d3 = tempfile.mkdtemp(prefix="lw-test-")
L = mk(ks) + mk([0.3] * 9, base=NOW - 14 * DAY + 3600, acct="b@y", plan="pro", sid="pro00000")
write(d3, L)
rc, j = jrun(d3, "calibrate")
byplan = {p["plan"]: p for p in j["plans"]}
check("calibrate: 플랜별로 따로 묶는다(pro 창이 max_5x 값에 섞이지 않음)", set(byplan) == {"max_5x", "pro"} and abs(byplan["max_5x"]["five"]["median"] - statistics.median(ks)) < 0.01 and byplan["pro"]["five"]["n"] == 9, str(j))

# 비용 감소 줄 건너뛰기
d4 = tempfile.mkdtemp(prefix="lw-test-")
base = NOW - 5 * DAY; fr = int(base + 18000)
lines = [line(base + 60, "dec00000", 2, fr, 10.0), line(base + 600, "dec00000", 10, fr, 15.0), line(base + 1200, "dec00000", 20, fr, 20.0),
         line(base + 1500, "dec00000", 20, fr, 3.0)]     # 끝의 감소 줄: 건너뜀(안 건너뛰면 합이 −7 이 되어 창이 사라진다)
write(d4, lines)
rc, j = jrun(d4, "calibrate", "--since", "2026-01-01T00:00:00+09:00")
check("calibrate: 세션 비용이 줄어드는 줄은 건너뛴다(증가 10 달러 ÷ 최고 20 % = 0.5)", rc == 0 and abs(j["plans"][0]["five"]["median"] - 0.5) < 0.001, str(j))

# 7d: 완주한 두 주(증가 큼)로 7d 값이 쓰인다
d5 = tempfile.mkdtemp(prefix="lw-test-")
L = mk(ks)
for w in range(2):
    ws = NOW - 14 * DAY + w * 7 * DAY; sr = int(ws + 7 * DAY)
    for i, (dt_, s, c) in enumerate([(60, 1, 0.0), (3 * DAY, 25, 100.0), (6 * DAY, 41, 160.0)]):
        L.append(line(ws + dt_, "wk%05d" % w, 5, int(ws + dt_ + 3600), c, s=s, sr=sr))
write(d5, L)
rc, j = jrun(d5, "calibrate", "--write")
cal = json.load(open(os.path.join(d5, "limit-calibration.json")))
check("calibrate: 완주한 주 2개(증가 40p·비용 160 달러)로 7d 값 4.0 을 쓴다", cal["plans"]["max_5x"]["seven"] and abs(cal["plans"]["max_5x"]["seven"]["median"] - 4.0) < 0.01 and cal["plans"]["max_5x"]["seven"]["n"] == 2, str(j))

# pin: 고정하면 자동은 suggest 에만
rc, out, _ = run(d5, "pin", "--five", "3.0")
write(d5, mk([1.0] * 10))
rc, j = jrun(d5, "calibrate", "--write")
cal = json.load(open(os.path.join(d5, "limit-calibration.json")))["plans"]["max_5x"]
check("pin: 고정값이 있으면 자동 값은 suggest 에만 쓰고 고정값은 그대로", cal["pinned"] == {"five": 3.0} and cal["suggest"]["five"]["median"] < 1.1 and cal["five"]["median"] > 1.5, str(cal))
rc, out, _ = run(d5, "pin", "--unpin")
check("pin --unpin: 고정 해제", json.load(open(os.path.join(d5, "limit-calibration.json")))["plans"]["max_5x"]["pinned"] == {})
rc, out, _ = run(d5, "pin", "--five", "-1")
check("pin: 0 이하 값은 거부", rc == 1)

# ───── S2 estimate
FR = int(NOW + 2 * 3600)          # 리셋 2시간 뒤
SID_ME, SID_OTHER = "meeeeeee-0000", "otherrrr-1111"


def est_log(extra=(), age=60, cur=50, other_gain=12.0, me_gain=8.0, first_f=40, model="claude-sonnet-5-5"):
    t0 = NOW - 3600
    return [line(t0, SID_OTHER, first_f, FR, 10.0, model=model), line(t0 + 1, SID_ME, first_f, FR, 5.0),
            line(NOW - age, SID_OTHER, cur, FR, 10.0 + other_gain, model=model), line(NOW - age + 1, SID_ME, cur, FR, 5.0 + me_gain), *extra]


d = tempfile.mkdtemp(prefix="lw-test-")
write(d, est_log())
rc, j = jrun(d, "estimate", "--usd", "42")
check("estimate: 보정 파일이 없으면 못 쟀음(종료 1, --json 은 error)", rc == 1 and "error" in j and "보정 없음" in j["error"], str(j))
calfile(d)
rc, j = jrun(d, "estimate", "--usd", "42", "--exclude-session", SID_ME)
# 구간 계정 증가 10p, 이 세션 몫 8달러÷2.0=4p, 구간 길이 (3600-60)/60=59분 → 다른 세션 6p/59분 × 60분
oth = 6 / 59 * 60
check("estimate: 작업 %p = 달러 ÷ 중앙값, 범위는 ÷p75 ~ ÷p25", rc == 0 and j["task_5h_pts"] == [21.0, round(42 / 2.2, 1), round(42 / 1.8, 1)], str(j))
check("estimate: 다른 세션 속도에서 현재 세션 몫(달러÷$/p)을 빼고 작업 시간을 곱한다", abs(j["others_5h_pts"][0] - round(oth, 1)) < 0.11, str(j["others_5h_pts"]))
check("estimate: 예상 종료 % = 현재 + 작업 + 다른 세션", abs(j["end_5h"][0] - (50 + 21 + oth)) < 0.2 and j["end_5h"][1] < j["end_5h"][0] < j["end_5h"][2], str(j["end_5h"]))
check("estimate: 7d 보정이 있으면 7d 예상도(작업 42÷10 = +4.2p)", j["end_7d"] and abs(j["end_7d"][0] - (10 + 4.2 + oth * 2.0 / 10.0)) < 0.2, str(j["end_7d"]))
rc, j0 = jrun(d, "estimate", "--usd", "42", "--exclude-session", "zzzzzzzz")
check("estimate: 현재 세션을 못 찾으면 다른 세션 속도에 섞이므로 값이 커지고 노트가 붙는다", j0["others_5h_pts"][0] > j["others_5h_pts"][0] and any("구간에 없음" in n for n in j0["notes"]), str(j0["notes"]))
# 판정 경계(확인선 5h 80, 7d 90): 중앙값/상단/현재
def verdict(usd, **kw):
    return jrun(d, "estimate", "--usd", str(usd), "--exclude-session", SID_ME, "--no-log", **kw)[1]["verdict_5h"]
check("estimate: 중앙값이 확인선 아래·상단도 아래면 진행", verdict(5) == "go")
check("estimate: 중앙값은 아래·상단이 확인선을 넘으면 알리고 진행", verdict(45) == "notify", verdict(45))
check("estimate: 중앙값이 확인선을 넘으면 묻기", verdict(100) == "ask")
write(d, est_log(cur=85))
rc, j = jrun(d, "estimate", "--usd", "1", "--exclude-session", SID_ME, "--no-log")
check("estimate: 현재 값이 이미 확인선 이상이면 묻기(ask-now) — 작은 작업이어도", j["verdict"] == "ask-now" and j["verdict_5h"] == "ask-now", str(j))
write(d, est_log())
# 입력 방식
rc, out, _ = run(d, "estimate", "--agents", "3")
check("estimate: --agents 는 단가 없으면 거부(기본 단가 없음)", rc == 1 and "단가 없음" in out, out)
rc, j = jrun(d, "estimate", "--agents", "3", "--per-agent", "14", "--exclude-session", SID_ME, "--no-log")
check("estimate: --agents N --per-agent USD = $N×단가", rc == 0 and j["usd"] == 42.0, str(j))
rc, out, _ = run(d, "estimate")
check("estimate: 크기 입력이 없으면 거부", rc == 1)
rc, out, _ = run(d, "estimate", "--usd", "5", "--minutes", "30")
check("estimate: 크기 입력이 둘이면 거부", rc == 1)
rc, j = jrun(d, "estimate", "--minutes", "30", "--exclude-session", SID_ME, "--no-log")
# 이 세션 비용 8달러/59분 → 30분이면 약 4.07 달러, 시간 30분
check("estimate: --minutes 는 현재 세션 비용 속도 × 분(= $8/59분×30)", rc == 0 and abs(j["usd"] - 8 / 59 * 30) < 0.02 and j["duration_min"] == 30, str(j))
rc, out, _ = run(d, "estimate", "--minutes", "30")
check("estimate: --minutes 는 현재 세션을 모르면 거부", rc == 1 and "못 쟀음" in out, out)
# 작은 증가: 범위로만
write(d, est_log(cur=41, me_gain=0.0))
rc, j = jrun(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log")
check("estimate: 구간 계정 증가 3p 미만이면 다른 세션은 0~상한 범위로만(중앙 0)", j["others_5h_pts"][0] == 0.0 and j["others_5h_pts"][2] > 0 and j["others_5h_pts"][1] == 0.0, str(j["others_5h_pts"]))
# 구간 기록이 짧음
write(d, [line(NOW - 120, SID_OTHER, 50, FR, 10.0), line(NOW - 60, SID_ME, 50, FR, 5.0)])
rc, j = jrun(d, "estimate", "--usd", "10", "--no-log")
check("estimate: 구간 기록이 10분 미만이면 다른 세션 합산은 하한(0)·노트", j["others_rate_known"] is False and any("10분 미만" in n for n in j["notes"]), str(j))
# 낡은 기록
write(d, est_log(age=1800))
rc, out, _ = run(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log")
check("estimate: 기록이 10분 넘게 낡으면 「약 N%」로 표시", "예상 종료 약 " in out, out)
# 창 끝남
write(d, [line(NOW - 3600, SID_ME, 50, int(NOW - 60), 5.0)])
rc, out, _ = run(d, "estimate", "--usd", "10", "--no-log")
check("estimate: 마지막 기록의 5h 창이 이미 끝났으면 못 쟀음", rc == 1 and "이미 끝" in out, out)
# opus 경고
write(d, est_log(model="claude-opus-5"))
rc, j = jrun(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log")
check("estimate: opus 비중이 크면 경고(보정은 sonnet 위주에서만 검증)", any("opus" in n for n in j["notes"]), str(j["notes"]))
write(d, est_log())
rc, j = jrun(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log")
check("estimate: sonnet 뿐이면 opus 경고 없음", not any("opus" in n for n in j["notes"]))
# 플랜 불일치(보정이 없는 플랜)
rc, j = jrun(d, "estimate", "--usd", "10", env={"LIMITWATCH_PLAN": "pro"})
check("estimate: 보정이 없는 플랜(pro·max_20x)은 못 쟀음", rc == 1 and "pro" in j["error"], str(j))
# 고정값
calfile(d, pinned={"five": 4.0})
rc, j = jrun(d, "estimate", "--usd", "40", "--exclude-session", SID_ME, "--no-log")
check("estimate: 고정값이 있으면 그 값을 쓴다(40÷4.0 = +10p)", j["task_5h_pts"][0] == 10.0 and j["calibration"]["pinned"] is True, str(j))
check("estimate: 고정값은 자동 값의 상대 폭으로 범위를 넓힌다(40÷(1.8×2)=11.1 / 40÷(2.2×2)=9.1)", j["task_5h_pts"][1:] == [9.1, 11.1], str(j["task_5h_pts"]))
calfile(d)
rc, ja = jrun(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log", "--duration", "30")
rc, jb = jrun(d, "estimate", "--usd", "10", "--exclude-session", SID_ME, "--no-log", "--duration", "60")
check("estimate: 다른 세션 합산은 작업 시간에 비례(30분은 60분의 절반)", abs(ja["others_5h_pts"][0] * 2 - jb["others_5h_pts"][0]) < 0.15 and jb["others_5h_pts"][0] > 3, f"{ja['others_5h_pts']} {jb['others_5h_pts']}")

# 예측 기록: 숫자만, 세션 ID·설명·경로 없음
logp = os.path.join(d, "limit-estimates.jsonl")
if os.path.exists(logp): os.remove(logp)
run(d, "estimate", "--usd", "20", "--exclude-session", SID_ME)
run(d, "estimate", "--usd", "20", "--exclude-session", SID_ME, "--no-log")
rows = [json.loads(l) for l in open(logp)]
raw = open(logp).read()
check("estimate: 예측을 한 줄 남긴다(--no-log 는 안 남김)", len(rows) == 1 and rows[0]["input"] == "usd" and rows[0]["usd"] == 20.0, raw)
check("estimate: 기록에는 숫자·플랜뿐 — 세션 ID·계정·경로·설명 없음", not any(x in raw for x in (SID_ME[:8], SID_OTHER[:8], "a@x", d, "/")) and set(rows[0]) == {"t", "plan", "input", "usd", "duration_min", "task5", "others5", "end5", "f", "s", "fr", "sr", "verdict", "calib_n"}, raw)

# ───── S4 review
d6 = tempfile.mkdtemp(prefix="lw-test-")
FR6 = int(NOW + 7200)
recs = [line(NOW - 100, "r0000000", 50, FR6, 1.0), line(NOW + 3000, "r0000000", 64, FR6, 20.0), line(NOW + 3400, "r0000000", 71, FR6, 22.0), line(NOW + 3800, "r0000000", 90, FR6, 30.0)]
write(d6, recs)
est = [dict(t=round(NOW - 100), plan="max_5x", input="usd", usd=30.0, duration_min=60.0, task5=[15, 14, 17], others5=[5, 3, 7], end5=[70, 67, 74], f=50, s=10, fr=FR6, sr=FR6 + DAY, verdict="go", calib_n=12),
       dict(t=round(NOW - 100), plan="max_5x", input="usd", usd=10.0, duration_min=60.0, task5=[5, 4, 6], others5=[0, 0, 2], end5=[55, 54, 58], f=50, s=10, fr=FR6, sr=FR6 + DAY, verdict="go", calib_n=12),
       dict(t=round(NOW + 100), plan="max_5x", input="usd", usd=10.0, duration_min=600.0, task5=[5, 4, 6], others5=[0, 0, 2], end5=[55, 54, 58], f=50, s=10, fr=FR6, sr=FR6 + DAY, verdict="go", calib_n=12)]
open(os.path.join(d6, "limit-estimates.jsonl"), "w").write("\n".join(json.dumps(e) for e in est) + "\n")
rc, j = jrun(d6, "review", now=NOW + 4000)
r = j["rows"]
check("review: 예측 시각+작업 시간 시점의 관측으로 실제 증가를 맞댄다(예측 +20, 실제 +21 → 오차 +5 %, 범위 안)", r[0]["status"] == "done" and r[0]["actual"] == 21 and abs(r[0]["err"] - 0.05) < 0.001 and r[0]["in_range"], str(r[0]))
check("review: 범위 밖 판정(예측 +5·실제 +21 → 범위 밖)", r[1]["status"] == "done" and r[1]["in_range"] is False and r[1]["err"] > 1, str(r[1]))
check("review: 아직 안 끝난 예측은 pending", r[2]["status"] == "pending", str(r[2]))
check("review: 20건 미만이면 판정 보류, 요약에 집계", j["summary"]["done"] == 2 and "보류" in j["summary"]["verdict"] and j["summary"]["in_range"] == 0.5, str(j["summary"]))
rc, out, _ = run(d6, "review", now=NOW + 4000)
check("review: 텍스트 출력에 요약 줄", "요약: 기록 3건 중 비교 2건" in out, out)
d7 = tempfile.mkdtemp(prefix="lw-test-"); write(d7, recs)
rc, out, _ = run(d7, "review")
check("review: 예측 기록이 없으면 안내(종료 0)", rc == 0 and "예측 기록 없음" in out, out)
# 20건 이상: 유지 기준
many = [dict(est[0], t=round(NOW - 100)) for _ in range(20)]
open(os.path.join(d6, "limit-estimates.jsonl"), "w").write("\n".join(json.dumps(e) for e in many) + "\n")
rc, j = jrun(d6, "review", now=NOW + 4000)
check("review: 20건 이상이고 오차 ±30 %·범위 안 60 % 이상이면 유지 기준 충족", j["summary"]["done"] == 20 and "충족" in j["summary"]["verdict"], str(j["summary"]))

# ───── 기존 동작 보존
d8 = tempfile.mkdtemp(prefix="lw-test-"); write(d8, est_log())
rc, out, _ = run(d8, "status")
check("status: 기존 출력(5h·7d·확인선 판정 줄) 그대로", rc == 0 and out.startswith("5h 50%") and "확인선 5h 80%·7d 90%" in out, out)
rc, j = jrun(d8, "status")
check("status --json: 기존 키 유지", rc == 0 and {"plan", "ask_five_hour", "five_hour", "recent_delta"} <= set(j), str(j))
rc, out, _ = run(tempfile.mkdtemp(prefix="lw-test-"), "status")
check("status: 기록 파일이 없으면 못 쟀음 종료 1", rc == 1 and "못 쟀음" in out, out)

# ───── 이 머신의 실제 기록(있을 때만): 중앙값이 대략 맞는지 — 값은 날마다 조금 바뀌므로 넓게(계획 S1 의 1.70±0.05 는 2026-11-09 값)
real = os.path.expanduser("~/.local/share/claude-otel/limits.jsonl")
if os.path.exists(real):
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--file", real, "calibrate", "--json"], capture_output=True, text=True, env=dict(ENV0))
    try:
        pl = {p["plan"]: p for p in json.loads(r.stdout)["plans"]}.get("max_5x")
    except Exception:
        pl = None
    if pl and pl["five"] and pl["five"]["n"] >= 8:
        check("실제 기록: max_5x 5h $/pt 중앙값이 1.3~2.2 안(2026-11-09 값 1.68~1.70)", 1.3 <= pl["five"]["median"] <= 2.2, str(pl["five"]))
finish("limitwatch")
