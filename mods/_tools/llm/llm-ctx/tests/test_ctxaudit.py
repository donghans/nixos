#!/usr/bin/env python3
"""ctxaudit 시험 — 전제 감사관 보고의 기계 검사(위조 인용·순서·붙여넣기 블록)와 채점(오탐률·재현율·꼬리 읽기).
시험 판정(donghans-test-judgment): A 형(장기 보호) — 지키는 것: 「위조 0건」 지표와 오탐·재현율 채점이 정직하게 계산된다. 깨지면 감사관 시험 결과를 잘못 읽는다.
순수 함수 시험(DB 없음) + `--texts` 폴더로 CLI 를 실제 프로세스로 돌린다."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctxaudit as au

U1 = "11111111-aaaa-4bbb-8ccc-000000000001"
U2 = "22222222-aaaa-4bbb-8ccc-000000000002"
T1 = "이번 설계에 한해서 캐시는 쓰지 마.\n\n그리고 추천대로 진행해줘."
T2 = "앞 인사말입니다.\n<pasted_content id=\"a1\">\n보고서: 골든 스냅샷을 만들었습니다. 킬스위치도 추가했습니다.\n</pasted_content>\n\n끝에 요청: 스킬 문제점을 개선해줘."

# ---------------------------------------------------------------- 인용 일치(엄격)
check("공백 정규화 부분 문자열", au.ordered_match("캐시는   쓰지 마", T1))
check("없는 문장은 불일치", not au.ordered_match("캐시를 꼭 써", T1))
check("조각은 보고된 순서대로면 통과", au.ordered_match("이번 설계에 … 추천대로 진행해줘", T1))
check("조각 순서가 뒤집히면 불통과(quote_matches 는 통과)", not au.ordered_match("추천대로 진행해줘 … 이번 설계에", T1) and au.cx.quote_matches("추천대로 진행해줘 … 이번 설계에", T1))
check("`...` 도 생략 표시", au.ordered_match("이번 설계에...쓰지 마", T1))
check("같은 조각 두 번은 겹치지 않는 두 곳이 있어야 한다", not au.ordered_match("쓰지 마 … 쓰지 마", T1))
check("2자 미만 조각만 있으면 불통과", not au.ordered_match("가", T1) and not au.ordered_match("", T1))

# ---------------------------------------------------------------- 붙여넣기 블록
check("블록 밖 인용 → outside", au.locate("스킬 문제점을 개선해줘", T2) == "outside")
check("블록 안 인용 → inside(사용자 말로 세지 않음)", au.locate("골든 스냅샷을 만들었습니다", T2) == "inside")
check("블록 안 + 밖 조각 → mixed", au.locate("골든 스냅샷을 … 스킬 문제점을", T2) in ("mixed", "order") and au.locate("스킬 문제점을 … 골든 스냅샷", T2) != "outside")
check("원문에 없으면 none", au.locate("킬스위치를 켜라", T1) == "none")
check("조각 순서 어긋남 → order", au.locate("추천대로 진행해줘 … 이번 설계에", T1) == "order")
check("닫는 태그가 없으면 끝까지 블록", au.locate("뒤 요청", "<pasted_content>붙임 뒤 요청") == "inside")

# ---------------------------------------------------------------- 보고서 파싱
REPORT = f"""# 감사 보고
| 전제(계획서 위치) | a/b/c | 근거 | 확장·한정 상실 |
|---|---|---|---|
| [N1-01] 캐시는 쓰지 않는다 (§2) | a | {U1[:8]} 「이번 설계에 한해서 캐시는 쓰지 마」 11-06 18:36 | 한정(이번 설계) 상실 |
| [N1-02] 추천대로 → 확정 | b | {U1} “추천대로 진행해줘” | 포괄 승인 |
| [P1-01] 골든 스냅샷 요구 | c | {U2[:8]} "골든 스냅샷을 만들었습니다" | 블록 안 |
| [P1-02] 킬스위치 요구 | c | {U2[:8]} 「킬스위치를 켜라」 | 위조 |
| [H1-01] 요청은 스킬 개선 | a | {U2[:8]} 「스킬 문제점을 개선해줘」 | |
| [P1-03] 근거 불명 | 확인 불가 | 없음 | |
"""
rows = au.parse_report(REPORT)
check("머리·구분선 행은 건너뛴다", len(rows) == 6 and all(r["pid"] for r in rows), str([r["pid"] for r in rows]))
check("분류 칸 해석: a/b/c·확인 불가", [r["cls"] for r in rows] == ["a", "b", "c", "c", "a", "?"], str([r["cls"] for r in rows]))
check("uuid(8자·36자)와 세 가지 따옴표 인용 추출", rows[0]["uuids"] == [U1[:8]] and rows[1]["uuids"] == [U1] and rows[1]["quotes"] == ["추천대로 진행해줘"] and rows[2]["quotes"] == ["골든 스냅샷을 만들었습니다"], str(rows[:3]))
check("시각(11-06 18:36)은 uuid 로 오인하지 않는다", rows[0]["uuids"] == [U1[:8]])

texts = {U1[:8]: T1, U2[:8]: T2}
def fetch(u):
    for k, v in texts.items():
        if u.startswith(k):
            return ("ok", v)
    return ("none",)

res = au.check_rows(rows, fetch)
st = {x["pid"]: x["status"] for x in res}
check("일치·블록 안·미일치 구분", st["N1-01"] == "일치" and st["N1-02"] == "일치" and st["P1-01"] == "블록 안" and st["P1-02"] == "미일치" and st["H1-01"] == "일치", str(st))
sm = au.summarize_check(res)
check("위조(무효)는 미일치만 1건, 블록 안은 별도 집계", sm["forged"] == 1 and sm["블록 안"] == 1 and sm["total"] == 5, str(sm))
bad = au.check_rows(au.parse_report("| [X1-01] 가 | a | 99999999 「없는 메시지의 인용」 |\n| [X1-02] 나 | a | 「uuid 없는 인용」 |"), fetch)
check("메시지 없음·uuid 없음도 무효", [x["status"] for x in bad] == ["메시지 없음", "uuid 없음"] and au.summarize_check(bad)["forged"] == 2, str(bad))
multi = au.check_rows(au.parse_report(f"| [X1-03] 다 | a | {U2[:8]} {U1[:8]} 「캐시는 쓰지 마」 |"), fetch)
check("uuid 가 여럿이면 어느 본문에서든 일치하면 일치", multi[0]["status"] == "일치" and multi[0]["uuid"].startswith("11111111"), str(multi))

# ---------------------------------------------------------------- 채점
KEY = {"premises": {
    "N1-01": {"group": "N", "defect": False}, "N1-02": {"group": "N", "defect": False},
    "P1-01": {"group": "P", "defect": True}, "P1-02": {"group": "P", "defect": True},
    "H1-01": {"group": "H", "defect": False, "tail": "스킬 문제점을 개선해줘"}, "P1-03": {"group": "P", "defect": True},
    "P1-04": {"group": "P", "defect": True}}}
sc = au.score(KEY, rows, fetch)
check("오탐률 = N 군 중 b/c 지적 ÷ N 군(1/2)", sc["false_positive"] == ["N1-02"] and sc["fp_rate"] == 0.5, str(sc))
check("재현율 = 결함 중 b/c 지적(2/4: 확인 불가는 못 잡은 것, 보고에 없는 전제는 누락)", sc["caught"] == ["P1-01", "P1-02"] and sc["recall"] == 0.5 and sc["missing"] == ["P1-04"] and "P1-03" in sc["missed"], str(sc))
check("꼬리 읽기: H 행이 꼬리 요청을 인용했는가", sc["tail_rate"] == 1.0 and sc["tail_read"] == ["H1-01"], str(sc))
check("위조 인용 수가 채점에 들어간다", sc["check"]["forged"] == 1)
check("기준 판정: 오탐 0.5>0.1 아니오·재현율 0.5<0.8 아니오·위조 1>0 아니오·꼬리 예", sc["meets"] == {"fp_rate": False, "recall": False, "forged": False, "tail_rate": True}, str(sc["meets"]))
good = au.parse_report(f"| [N1-01] a | a | {U1[:8]} 「캐시는 쓰지 마」 |\n| [N1-02] b | a | {U1[:8]} 「추천대로 진행해줘」 |\n| [P1-01] c | b | {U2[:8]} 「스킬 문제점을 개선해줘」 |")
k2 = {"premises": {"N1-01": {"group": "N"}, "N1-02": {"group": "N"}, "P1-01": {"group": "P", "defect": True}}}
sg = au.score(k2, good, fetch)
check("깨끗한 보고는 모든 기준 충족", sg["meets"] == {"fp_rate": True, "recall": True, "forged": True} and sg["fp_rate"] == 0 and sg["recall"] == 1, str(sg))
check("정답표에 없는 행은 unlabeled 로 따로 센다", au.score(k2, good + au.parse_report("| [Z9-01] x | b | 없음 |"), fetch)["unlabeled_rows"] != [])
check("반복 간 불일치 전제", au.disagreements(sc, sg) == sorted(set(sc["flagged"]) ^ set(sg["flagged"])) and "N1-02" in au.disagreements(sc, sg))
check("같은 전제 여러 행 중 하나라도 b/c 면 지적", au.score(k2, au.parse_report("| [N1-01] 가 | a | x |\n| [N1-01] 가 | c | x |"))["flagged"] == ["N1-01"])

# ---------------------------------------------------------------- CLI(실제 프로세스, --texts)
with tempfile.TemporaryDirectory() as d:
    for k, v in texts.items():
        open(os.path.join(d, k + ".txt"), "w", encoding="utf-8").write(v)
    rp = os.path.join(d, "r.md"); open(rp, "w", encoding="utf-8").write(REPORT)
    kp = os.path.join(d, "k.json"); json.dump(KEY, open(kp, "w", encoding="utf-8"), ensure_ascii=False)
    run = lambda *a: subprocess.run([sys.executable, "-I", os.path.join(ROOT, "ctxaudit.py"), *a], capture_output=True, text=True)
    r = run("check", rp, "--texts", d)
    check("CLI check: 위조가 있으면 종료 코드 1·무효 행과 약한 검사 경고를 낸다", r.returncode == 1 and "위조(무효) 1" in r.stdout and "P1-02" in r.stdout and "증명이 아니다" in r.stdout, r.stdout + r.stderr)
    clean = os.path.join(d, "c.md"); open(clean, "w", encoding="utf-8").write(f"| [N1-01] a | a | {U1[:8]} 「캐시는 쓰지 마」 |")
    check("CLI check: 위조 없으면 종료 코드 0", run("check", clean, "--texts", d).returncode == 0)
    r = run("score", "--key", kp, rp, rp, "--texts", d)
    check("CLI score: 지표 한 줄과 기준 충족 표시", r.returncode == 0 and "오탐률 50%" in r.stdout and "재현율 50%" in r.stdout and "꼬리 읽기 100%" in r.stdout, r.stdout + r.stderr)
    j = json.loads(run("score", "--key", kp, rp, "--texts", d, "--json").stdout)
    check("CLI score --json", j["runs"][0]["fp_rate"] == 0.5 and j["disagree"] == [])

finish("ctxaudit")
