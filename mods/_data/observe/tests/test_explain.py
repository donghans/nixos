#!/usr/bin/env python3
"""observectl explain 시험: 전력 4지표·신뢰 제외, 시스템 활동의 출처(Netdata/observectl)·관측 공백, 프로세스(옛 표본 제외·커버리지), 포커스/스팬 자름, 기준 대비 순위, CLI."""
import contextlib, io, json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-explain-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import observe_core as core, observe_explain as ex, observe_trace as tr, observe_cli
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

T = 1_700_000_000.0
def row(t, psys, pkg=2.0, vi=5.0, q=None, ac=0, procs=None, cpu_all=3.0, ctxt=2000, intr=1500, state="low", legacy=False, status="Discharging"):
    r = {"v": 3, "t": t, "dt": 30, "state": state,
         "pw": {"psys_w": psys, "pkg_w": pkg, "batt_vi_w": vi, "q_uah": q, "v_uv": 15_000_000, "status": status, "ac": ac},
         "irq": {"cpu_all_pct": cpu_all, "ctxt_s": ctxt, "intr_s": intr},
         "dev": {"lid": "closed", "vt": "tty1", "psr": {"mode": "PSR1 enabled", "sink": "active"}}, "proc": procs if procs is not None else []}
    if legacy:
        r["legacy"] = True
    return r
def windowed(t0, n, **kw):   # 30초 간격 n개, q 는 계량 W(kw['cw'])에서 역산
    cw = kw.pop("cw", None); out = []; q = 3_000_000
    for i in range(n):
        out.append(row(t0 + i * 30, q=int(q) if cw is not None else None, **kw))
        if cw is not None:
            q -= cw / 15.0 * 1e6 * 30 / 3600
    return out

B0, B1 = T, T + 600           # 기준 10분
C0, C1 = T + 600, T + 1200    # 이 구간 10분
base_rows = windowed(B0, 20, psys=4.0, pkg=1.6, vi=5.0, cw=5.0, cpu_all=3.0, ctxt=2000, procs=[{"comm": "claude", "cpu_core_pct": 5.0, "ctxsw_vol_s": 40.0}])
cur_rows = windowed(C0, 20, psys=6.5, pkg=2.6, vi=7.0, cw=7.0, cpu_all=9.0, ctxt=9000, procs=[
    {"comm": "claude", "cpu_core_pct": 5.0, "ctxsw_vol_s": 40.0}, {"comm": "nix", "cpu_core_pct": 80.0, "ctxsw_vol_s": 10.0}, {"comm": "netdata", "cpu_core_pct": 3.0, "ctxsw_vol_s": 360.0}])
rows = base_rows + cur_rows
spans = [
    {"id": "w1", "trace": "w1", "parent": None, "comp": "windows", "name": "window:kitty", "t0": C0 - 500, "t1": C1 + 50, "ms": 1, "status": "ok", "attrs": {}, "pid": 1},
    {"id": "f1", "trace": "w1", "parent": "w1", "comp": "windows", "name": "focus:kitty", "t0": C0 - 100, "t1": C0 + 300, "ms": 1, "status": "ok", "attrs": {}, "pid": 1},
    {"id": "f2", "trace": "w2", "parent": "w2", "comp": "windows", "name": "focus:vivaldi-stable", "t0": C0 + 300, "t1": C1 + 100, "ms": 1, "status": "ok", "attrs": {}, "pid": 1},
    {"id": "n1", "trace": "n1", "parent": None, "comp": "nixup", "name": "run", "t0": C0 + 60, "t1": C0 + 240, "ms": 180000, "status": "ok", "attrs": {}, "pid": 2},
]
def nd_fake(t0, t1):
    cur = t0 >= C0
    return {"coverage": 1.0, "signals": {"psys_w": 6.7 if cur else 4.2, "pkg_w": 2.7 if cur else 1.7, "batt_vi_w": 7.2 if cur else 5.1, "cpu_all_pct": 9.5 if cur else 3.2, "ctxsw_all_s": 9100.0 if cur else 2050.0,
            "intr_all_s": 1600.0, "net_rx_kbps": 900.0 if cur else 40.0, "net_tx_kbps": 20.0, "disk_read_kibs": 0.0, "disk_write_kibs": 0.0, "nvme_temp_c": 35.0, "forks_s": 40.0 if cur else 2.0},
            "apps_cpu": [("nix-daemon", 85.0 if cur else 0.5), ("start-hyprland", 12.0)]}

res = ex.build(rows, spans, C0, C1, (B0, B1), nd_fake)
check("전력: 이 구간·기준·Netdata 값이 같이 있음(psys 6.5 / 4.0 / 6.7)", abs(res["power"]["psys_w"]["value"] - 6.5) < 1e-9 and abs(res["power"]["psys_w"]["base"] - 4.0) < 1e-9 and res["power"]["psys_w"]["netdata"] == 6.7, str(res["power"]["psys_w"]))
check("전력: 10분 구간은 순간 V×I(표본 20개)·누적 계량이 신뢰 가능", res["power"]["batt_vi_w"]["reliable"] and res["power"]["coulomb_w"]["reliable"] and abs(res["power"]["coulomb_w"]["value"] - 7.0) < 0.1, str(res["power"]))
check("상태 요약(low 100%, PSR 100%)", res["state"]["low_pct"] == 100 and res["state"]["psr_pct"] == 100)
check("시스템 활동: Netdata 가 있으면 Netdata 값을 우선(전체 CPU 9.5), observectl 값도 함께 보관(9.0)", (lambda s: s["nd"] == 9.5 and abs(s["obs"] - 9.0) < 1e-9)({x["name"]: x for x in res["system"]}["cpu_all_pct"]))
check("프로세스: 코어 기준 CPU·모든 스레드 전환(netdata 360/s)", res["procs"]["cur"]["netdata"]["ctxsw"] == 360.0 and res["procs"]["cur"]["nix"]["cpu"] == 80.0)
check("포커스: 구간 안으로 잘라 앱별 시간(kitty 300초, vivaldi 300초)", dict((a, round(s)) for a, s, _ in res["focus"]) == {"kitty": 300, "vivaldi-stable": 300}, str(res["focus"]))
check("스팬: windows 제외, nixup:run 180초와 에너지", res["spans"][0][0] == "nixup:run" and abs(res["spans"][0][1] - 180) < 1 and res["spans"][0][2] is not None, str(res["spans"]))
names = [c["name"] for c in res["changes"]]
check("달라진 것 순위에 psys·시스템 문맥 전환·nix 프로세스가 들어감", "psys(RAPL, 약 1 W 누락)" in names and "시스템 전체 문맥 전환" in names and "nix" in names, str(names))
check("순위에서 신규 프로세스(nix: 0 → 80)가 '신규'(무한 상대 변화)로 위쪽", any(c["name"] == "nix" and c["rel"] == float("inf") for c in res["changes"]))
text = "\n".join(ex.render(res, core.hms))
check("render: 섹션(전력·시스템 활동·프로세스·앱·포커스·열린 구간·달라진 것·한계)이 모두 있음", all(k in text for k in ("[전력]", "[시스템 활동]", "[프로세스·앱]", "앱 그룹 CPU", "[포커스·열린 구간]", "포커스한 앱:", "열린 구간(스팬):", "[기준 대비 달라진 것", "[한계와 주의]")), text)
check("render: '상관일 뿐 인과가 아님'과 psys 누락 한계를 명시", "상관일 뿐 인과가 아님" in text and "약 1 W" in text)
check("render: 출처 표기(Netdata 1초 / observectl 30초)", "Netdata 1초" in text and "observectl(30초 표본)" in text)

sec = ex.sections(res, core.hms)
check("sections: 제목 순서가 SECTION_TITLES 와 같고 각 섹션에 내용이 있음(powerui 박스용)", [t for t, _ in sec] == ex.SECTION_TITLES and all(lines for _, lines in sec), str([t for t, _ in sec]))
check("render 는 sections 와 같은 내용(줄 수가 섹션 합 이상)", len(ex.render(res, core.hms)) >= sum(len(l) for _, l in sec))

# Netdata 꺼짐 → 관측 공백(0 이 아님), 알림
res2 = ex.build(rows, spans, C0, C1, (B0, B1), lambda a, b: None)
t2 = "\n".join(ex.render(res2, core.hms))
check("Netdata 꺼짐: 알림 문구와 네트워크·디스크 항목이 '관측 공백'(0 으로 두지 않음)", "Netdata 가 응답하지 않음" in t2 and t2.count("관측 공백") >= 5 and "응답 없음" in t2, t2)
check("Netdata 꺼짐: observectl 값으로 시스템 활동(CPU·문맥 전환·인터럽트)은 계속 보임", "observectl 30초" in t2 and res2["apps_nd"]["cur"] is None)
res3 = ex.build(rows, spans, C0, C1, (B0, B1), lambda a, b: {**nd_fake(a, b), "coverage": 0.4})
check("Netdata 부분 공백(40%): 있는 부분의 평균이라는 알림", any("40%" in n for n in res3["notes"]), str(res3["notes"]))

# 짧은 구간 → 신뢰 낮은 지표는 순위에서 제외
short = ex.build(rows, spans, C0, C0 + 90, None, None)
check("짧은 구간(90초): 누적 계량 신뢰 낮음 표시 + 안내", short["power"]["coulomb_w"]["reliable"] is False and any("5분 이상" in n for n in short["notes"]), str(short["power"]["coulomb_w"]))
check("기준 없음(baseline=None): 변화 순위 비어 있음·안내", short["changes"] == [] and "기준 구간이 없어" in "\n".join(ex.render(short, core.hms)))

# 옛 표본: 프로세스 전환은 제외, CPU 는 유효
leg = [dict(r, legacy=True, proc=[{"comm": "claude", "cpu_core_pct": 5.0, "ctxsw_vol_leader_s": 7.0}]) for r in cur_rows[:10]]
r4 = ex.build(leg + cur_rows[10:], spans, C0, C1, None, None)
check("옛 표본 섞임: 전환은 v3 표본만으로(claude 40/s, 옛 값 7 이 섞이지 않음), CPU 는 전체 표본", r4["procs"]["cur"]["claude"]["ctxsw"] == 40.0 and r4["procs"]["ctx_samples"] == 10 and r4["procs"]["legacy_samples"] == 10, str(r4["procs"]["cur"]["claude"]))
check("옛 표본 섞임: 안내 문구", any("옛 형식 표본 10개" in n for n in r4["notes"]))
cov = ex.ctxsw_coverage(cur_rows)
check("전환 커버리지: 저장된 상위 행 합 410 / 시스템 9000 ≈ 4.6% — 낮으면 긴 꼬리 안내", abs(cov - 410 / 9000) < 1e-6 and any("긴 꼬리" in n for n in res["notes"]), str((cov, res["notes"])))

# 한글 칸 폭 정렬(문자 수가 아니라 터미널 칸 수) — 실제 터미널에서 표가 어긋났던 문제
check("칸 폭: 한글 2칸·영문 1칸, _l/_r 이 칸 수로 맞춤", ex._w("가나a") == 5 and ex._w(ex._l("가나", 7)) == 7 and ex._w(ex._r("가나", 7)) == 7 and ex._l("ab", 4) == "ab  ")
tab = ex.sections(res, core.hms)[1][1]
def prefix_at(line, n):
    """칸 폭이 정확히 n 이 되는 앞부분(한글이 걸쳐 있어 n 이 안 나오면 None)"""
    return next((line[:i] for i in range(len(line) + 1) if ex._w(line[:i]) == n), None)
ends = [prefix_at(l, 34) for l in tab[1:]]
check("전력 표: '이 구간' 열이 모든 줄에서 같은 칸(34)에 끝나고 숫자로 끝남(한글 라벨이 있어도)", all(e is not None and e.rstrip()[-1] in "0123456789-" for e in ends), str(tab))

# 충전 중: 순간 V×I·계량 없음 — Netdata 의 충전 전력과 혼동하지 않게
chg = windowed(C0, 20, psys=9.0, status="Charging", ac=1)
r5 = ex.build(chg, [], C0, C1, None, nd_fake)
t5 = "\n".join(ex.render(r5, core.hms))
check("충전 중: 방전 표본이 없으면 Netdata V×I(충전 전력)를 방전 전력과 나란히 두지 않고 뺀다", r5["power"]["batt_vi_w"]["netdata"] is None and any("전원이 섞인" in n for n in r5["notes"]) and r5["power"]["psys_w"]["netdata"] is not None, t5)
mixed = windowed(C0, 20, psys=9.0)
for i in range(0, len(mixed), 2):
    mixed[i]["pw"]["status"] = "Charging"
r6 = ex.build(mixed, [], C0, C1, None, nd_fake)
check("전원이 섞인 구간: Netdata V×I 제외 + 안내(psys·패키지는 유지), 방전 전용 구간은 그대로 병기", r6["power"]["batt_vi_w"]["netdata"] is None and r6["power"]["pkg_w"]["netdata"] is not None and res["power"]["batt_vi_w"]["netdata"] is not None, str(r6["notes"]))

# CLI 통합
now = time.time()
M = int(now // 30 * 30) - 30                               # 경계를 시계에 맞추지 않고 고정한다(실행 시각에 따라 경계 표본이 이쪽저쪽으로 흔들리지 않게)
for i in range(40):
    r = row(M - 600 + 1 + i * 30, psys=4.0 if i < 20 else 6.0, vi=5.0 if i < 20 else 7.0, q=3_000_000 - i * 1500, procs=[{"comm": "x", "cpu_core_pct": 1.0 + (i >= 20) * 20, "ctxsw_vol_s": 5.0}])
    core.append_jsonl(core.SAMPLE_DIR, "samples", r, t=r["t"])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    observe_cli.main(["explain", "--since", str(M), "--until", str(M + 600), "--baseline", f"{M - 600}..{M}", "--no-netdata"])
out = buf.getvalue()
check("observectl explain: 실제 표본으로 구간·기준 비교 출력(psys +2.00)", "== explain" in out and "+2.00" in out and "[기준 대비 달라진 것" in out, out)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    observe_cli.main(["explain", "--since", str(M), "--until", str(M + 600), "--baseline", "none", "--json", "--no-netdata"])
j = json.loads(buf.getvalue())
check("observectl explain --json: 구조화 결과", j["n"] > 0 and "power" in j and j["baseline"] is None)
try:
    observe_cli.main(["explain", "--baseline", "엉터리"])
    check("잘못된 --baseline 은 안내 후 종료", False)
except SystemExit as e:
    check("잘못된 --baseline 은 안내 후 종료", "--baseline" in str(e))
finish("explain")
