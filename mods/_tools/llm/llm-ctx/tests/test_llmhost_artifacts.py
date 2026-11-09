#!/usr/bin/env python3
"""llmhost_artifacts 시험(비용 0, 표준 라이브러리만): 색인 파싱, 경로 밖 열기 거부, 검사 상태(검사기 결과 우선), 접기·펴기 그리기, 잘림.
화면(llmui 9 탭의 F8)은 test_llmui.py 가 본다. 표본 산출물은 이 파일이 임시 폴더에 만든다(색인+파일+.check)."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import llmhost_artifacts as ha

INDEX = """# INDEX — 표본 작업
- 분류: 결정(승인 전)
- 상태: 완료
- 세션: abcd1234

## 지금 결정할 것
1. A 안으로 갈까요 — 추천 A, 되돌릴 수 있음
2. 두 번째 결정

## 파일
| 파일 | 한 줄 요약 | 언제 읽나 | 근거 대화 범위 | 종류 | 검사 |
|---|---|---|---|---|---|
| `00-cover.md` | 표지 | 지금 | aaaa1111~bbbb2222 | 해석 | 통과 |
| [01-unknown.md](01-unknown.md) | 못 쟀음 | 지금 | - | 해석 | 미충족(절 없음) |
| facts/diff-stat.txt | 변경 목록 | 필요할 때 | - | 사실 | 통과 |
| ../outside.txt | 밖 | - | - | 해석 | 통과 |
| /etc/passwd | 절대 | - | - | 해석 | 통과 |
| linkout.md | 심볼릭 링크 | - | - | 해석 | 통과 |
| missing.md | 없는 파일 | - | - | 해석 | |
| big.md | 큰 파일 | - | - | 해석 | 통과 |
"""
tmp = tempfile.mkdtemp(prefix="art-test-")
root = os.path.join(tmp, "work", "art")
os.makedirs(os.path.join(root, "facts")); os.makedirs(os.path.join(root, ".check"))
W = lambda rel, txt: open(os.path.join(root, rel), "w", encoding="utf-8").write(txt)
W("INDEX.md", INDEX); W("00-cover.md", "# 표지\n결정할 것 본문\n"); W("01-unknown.md", "# 못 쟀음\n내용 둘째\n"); W("facts/diff-stat.txt", " a.py | 2 +-\n")
W("big.md", "가" * 20000)
open(os.path.join(tmp, "work", "outside.txt"), "w").write("밖의 비밀")
os.symlink("/etc/passwd", os.path.join(root, "linkout.md"))
json.dump({"mode": "final", "ts": "2026-11-09T00:00:00", "counts": {"FAIL": 1, "WARN": 1, "INFO": 0},
           "items": [{"id": "C3", "level": "FAIL", "file": "01-unknown.md", "reason": "x"}, {"id": "C5", "level": "WARN", "file": "facts/diff-stat.txt", "reason": "y"}]},
          open(os.path.join(root, ".check", "result.json"), "w"))

# ---- 1. 파싱
d = ha.load(root)
check("load: 색인 있는 폴더는 ok", d["ok"] and d["err"] is None, str(d["err"]))
ix = d["index"]
check("파싱: 제목·머리(분류·상태·세션)", ix["title"] == "INDEX — 표본 작업" and ix["meta"].get("분류") == "결정(승인 전)" and ix["meta"].get("상태") == "완료" and ix["meta"].get("세션") == "abcd1234", str(ix["meta"]))
check("파싱: 「지금 결정할 것」 줄", len(ix["decide"]) == 2 and "A 안" in ix["decide"][0], str(ix["decide"]))
check("파싱: 파일 표 8행, 백틱·링크 표기를 걷어낸다", [r["file"] for r in ix["rows"]][:3] == ["00-cover.md", "01-unknown.md", "facts/diff-stat.txt"] and len(ix["rows"]) == 8, str([r["file"] for r in ix["rows"]]))
check("파싱: 종류·검사 칸", ix["rows"][2]["kind"] == "사실" and ix["rows"][1]["check"] == "미충족(절 없음)")
rev = ha.parse_index("| 종류 | 파일 |\n|---|---|\n| 사실 | x.md |\n")
check("파싱: 열 순서는 머리글 이름으로 찾는다", rev["rows"] and rev["rows"][0]["file"] == "x.md" and rev["rows"][0]["kind"] == "사실", str(rev["rows"]))
check("파싱: 머리글에 「파일」 이 없는 표는 파일 표가 아니다", ha.parse_index("| a | b |\n|---|---|\n| 1 | 2 |\n")["rows"] == [])
check("파싱: 코드 블록 안의 표는 무시", ha.parse_index("```\n| 파일 | 요약 |\n|---|---|\n| z.md | q |\n```\n")["rows"] == [])
check("load: 색인이 없으면 오류 문구", not ha.load(tmp)["ok"] and "INDEX.md" in ha.load(tmp)["err"])
check("load: 폴더가 없으면 오류", not ha.load(os.path.join(tmp, "nope"))["ok"])

# ---- 2. 폴더 밖 거부
base = os.path.join(tmp, "work")
check("load(base): 세션 작업 폴더 밖의 산출물 폴더는 거부", not ha.load(root, os.path.join(tmp, "other"))["ok"] and ha.load(root, base)["ok"])
for rel, why in (("../outside.txt", ".."), ("/etc/passwd", "절대"), ("linkout.md", "심볼릭"), ("~/x", "절대"), ("a/../../outside.txt", ".."), ("", "비어")):
    t, n, e = ha.read_file(root, rel)
    check(f"경로: {rel!r} 는 열지 않는다", t is None and e is not None and why in e, str(e))
t, n, e = ha.read_file(root, "missing.md")
check("경로: 없는 파일은 오류(예외 없음)", t is None and "없다" in e)
t, n, e = ha.read_file(root, "facts")
check("경로: 폴더는 일반 파일이 아니라 거부", t is None and "일반 파일" in e)
t, n, e = ha.read_file(root, "facts/diff-stat.txt")
check("경로: 정상 파일은 읽힌다", e is None and "a.py" in t)
os.symlink(os.path.join(root, "00-cover.md"), os.path.join(root, "alias.md"))
check("경로: 폴더 안을 가리키는 심볼릭 링크는 허용", ha.read_file(root, "alias.md")[2] is None)
open(os.path.join(root, "bin.dat"), "wb").write(b"\x00\x01\x02abc")
check("경로: 바이너리는 거부", "바이너리" in (ha.read_file(root, "bin.dat")[2] or ""))
open(os.path.join(root, "latin.md"), "wb").write(b"abc\xff\xfedef")
t, n, e = ha.read_file(root, "latin.md")
check("읽기: UTF-8 이 아니면 대체하고 안내", e is None and "abc" in t and n and "UTF-8" in n)
fifo = os.path.join(root, "pipe.md"); os.mkfifo(fifo)
check("경로: FIFO 는 막히지 않고 거부", "일반 파일" in (ha.read_file(root, "pipe.md")[2] or ""))

# ---- 3. 검사 상태
ck = d["check"]
rows = {r["file"]: r for r in ix["rows"]}
check("상태: 검사기 FAIL 은 색인의 「통과」 보다 우선(미충족 C3)", ha.row_status(rows["01-unknown.md"], ck)[:2] == ("미충족 C3", "fail"))
check("상태: 검사기 WARN 은 경고", ha.row_status(rows["facts/diff-stat.txt"], ck)[:2] == ("경고 C5", "warn"))
check("상태: 검사기 결과에 항목이 없으면 통과(출처 검사기)", ha.row_status(rows["00-cover.md"], ck) == ("통과", "ok", "검사기"))
check("상태: 검사기 결과가 없으면 색인 칸(출처 색인) — 통과·미충족·빈 칸", ha.row_status(rows["00-cover.md"], None) == ("통과", "ok", "색인") and ha.row_status(rows["01-unknown.md"], None)[1] == "fail" and ha.row_status(rows["missing.md"], None)[:2] == ("검사 안 됨", "dim"))
bad = os.path.join(tmp, "badchk"); os.makedirs(os.path.join(bad, ".check")); open(os.path.join(bad, ".check", "result.json"), "w").write("{깨짐")
check("검사 결과 파일이 깨졌으면 None(예외 없음)", ha.load_check(bad) is None)
check("요약 문구", "FAIL 1" in ha.check_summary(ck) and "없음" in ha.check_summary(None))

# ---- 4. 그리기: 접기·펴기
L, starts = ha.render(d, set(), 0, {})
T = ha.to_text(L)
check("그리기(접힘): 항목마다 3줄(제목·종류·검사), 내용은 없다", len(starts) == 8 and "표지\n" not in T.replace("— 표지", "") and "결정할 것 본문" not in T and "▶ 00-cover.md" in T, T[:300])
check("그리기: 머리·분류·검사기 요약·「읽힘 보장 아님」·결정할 것", all(w in T for w in ("산출물 — INDEX — 표본 작업", "분류: 결정(승인 전)", "검사기 결과: FAIL 1", ha.NOTE_NOT_READ, "A 안으로 갈까요")), T[:500])
check("그리기: 종류 라벨(사실분/LLM 의 해석)", "도구가 모은 사실분" in T and "LLM 의 해석" in T)
check("그리기: 검사 상태 줄(출처 포함)", "검사: 미충족 C3  [검사기]" in T and "검사: 통과  [검사기]" in T)
check("그리기: 선택 표시는 커서 행만", [s for s, t in L if s == "row_sel"] and sum(1 for s, t in L if s == "row_sel") == 1 and any(s == "row_sel" and "00-cover.md" in t for s, t in L))
cache = {}
L2, _ = ha.render(d, {1}, 1, cache)
T2 = ha.to_text(L2)
check("그리기(펼침): 그 항목만 ▼ 와 내용", "▼ 01-unknown.md" in T2 and "내용 둘째" in T2 and "▶ 00-cover.md" in T2 and "결정할 것 본문" not in T2, T2[:600])
check("그리기: 읽은 내용을 캐시에 넣는다", 1 in cache and cache[1][0].startswith("# 못 쟀음"))
L3, _ = ha.render(d, set(range(8)), 0, {})
T3 = ha.to_text(L3)
check("그리기(모두 펼침): 밖·절대·심볼릭·없는 파일은 오류 줄(내용 없음), 밖의 내용은 새지 않는다", T3.count("✗") == 4 and "밖의 비밀" not in T3 and "root:" not in T3, T3[-600:])
check("그리기: 큰 파일은 화면 상한에서 자르고 남은 양을 적는다", "화면에는 앞 12,000자만" in T3 and "8,000자 더" in T3)
check("그리기: 열지 못한 폴더는 오류 한 줄", ha.render(ha.load(os.path.join(tmp, "nope")), set())[0][0][0] == "err")
ea = ha.parse_index("# t\n")
check("그리기: 파일 표가 없으면 경고", "파일 표가 없다" in ha.to_text(ha.render({"ok": True, "index": ea, "check": None, "root": root}, set())[0]))

# ---- 5. 후보 탐색
os.makedirs(os.path.join(base, "sub")); open(os.path.join(base, "sub", "INDEX.md"), "w").write("# s\n")
os.symlink(tmp, os.path.join(base, "escape"))
c = ha.find_candidates(base)
check("후보: 작업 폴더 한 단계 아래의 INDEX.md 폴더만, 밖을 가리키는 링크는 제외", sorted(os.path.basename(x) for x in c) == ["sub"] or sorted(os.path.basename(x) for x in c) == ["art", "sub"], str(c))
finish("llmhost_artifacts")
