#!/usr/bin/env python3
"""protocolcheck(규약 검사기)·protocolhook(UserPromptSubmit·Stop 훅) 시험.
시험 판정(donghans-test-judgment): A 형(장기 보호) — 지키는 것: ① 검사기가 S1 동결 명세대로 판정한다(정상 샘플 FAIL·WARN 0, 틀린 샘플마다 의도한 ID) ② 게이트(LLM_PROTOCOL_PILOT=1)가 없으면 훅이 아무것도 하지 않는다
③ G 는 기록만·F 는 프롬프트당 1회·세션당 3회까지만 되돌린다·stop_hook_active 면 통과. 깨지면 파일럿 세션이 조용히 잘못 검사되거나 모든 세션의 응답이 막힌다.
DB 없음(C6 은 fetch 를 주입하고, DB 접속 실패는 가짜 donghans 실행 파일로 만든다). 훅은 실제 프로세스로 돌린다."""
import json, os, shutil, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker, script
check, finish = checker()

TMP = tempfile.mkdtemp()
HOME = os.path.join(TMP, "proto-home")
os.environ["LLM_PROTOCOL_HOME"] = HOME
import protocolcheck as pc
import protocolhook as ph
import protocol_text as T

CLI = os.path.join(ROOT, "protocolcheck.py")


def head(mod, kind="해석", who="LLM"):
    return f"---\n종류: {kind}\n모듈: {mod}\n작성: {who}\n근거: 없음\n---\n"


COVER = """## 결정할 것
- D1. 캐시 사용 여부
  - 선택지: (가) 쓴다 (나) 안 쓴다
  - 추천: (나). 이유: 단순하다
  - 되돌리기: 쉬움
## 한 줄 그림
캐시가 없어 느리다 → 캐시를 넣을지 정한다.
## 최종사용자 영향
사용자는 응답 속도 차이를 느낀다.
"""
UNKNOWN = "## 못 쟀음·미확인\n- 실제 부하는 못 쟀음. 요청 1 은 여기에 답했다.\n## 빠진 것\n빠진 것 없음. 요청 2번 항목은 cover 에 답했다.\n"
GLOSS = "| 용어 | 뜻 |\n|---|---|\n| 캐시 | 자주 쓰는 값을 저장해 두는 곳 |\n"
OPTS = "- (가) 쓴다\n  - 전: 캐시 없음\n  - 후: 캐시 있음\n  - 엮이는 곳: 설정 파일\n- (나) 안 쓴다\n  - 전: 캐시 없음\n  - 후: 그대로\n  - 엮이는 곳: 없음\n"
EVID = '- [msg:aaaa1111] "캐시는 쓰지 마" (2026-11-01·한정: 이번 설계)\n'
REMAIN = "## 열린 결정\n- D1. 순서 — 추천: 작은 것부터. 되돌리기: 쉬움\n## 재방문 조건\n세 번째 모듈을 옮길 때 다시 본다.\n"
BEFORE = "## 바뀐 파일\n- `mods/a/x.py` 와 `docs/`\n## 전후\n전에는 느렸고 후에는 빠르다.\n## 사용 가능 수준\n지금 써도 된다.\n"
MODS = {"결정": [("10-glossary.md", "glossary", GLOSS), ("11-options.md", "options", OPTS), ("12-evidence.md", "evidence", EVID)],
        "계획": [("20-remaining.md", "remaining", REMAIN)], "구현 결과": [("50-before-after.md", "beforeafter", BEFORE)]}
SECRET = "sk-ant-" + "a1B2c3D4e5" * 3


def index_text(klass, files, state="완료", cols=6):
    hdr = ["파일", "한 줄 요약", "언제 읽나", "근거 대화 범위", "종류", "검사"][:cols]
    rows = "".join("| " + " | ".join([f, "요약", "지금", "aaaa1111~bbbb2222", "해석", "(도구가 기록)"][:cols]) + " |\n" for f in files)
    return (head("index") + f"# INDEX — 시험\n- 분류: {klass}\n- 켜진 모듈: {', '.join(m[0] for m in MODS.get(klass, [])) or '없음'}\n- 세션: ab12cd34 · 2026-11-10T10:00+09:00 · HEAD 없음\n- 상태: {state}\n"
            "## 지금 결정할 것\n1. D1 캐시 — 추천: 안 쓴다. 되돌리기: 쉬움\n## 파일\n| " + " | ".join(hdr) + " |\n|" + "---|" * cols + "\n" + rows)


_n = [0]


def build(klass="결정", over=None, state="완료", diff_files=("mods/a/x.py", "docs/readme.md"), skip_index_row=None):
    """정상 샘플 폴더를 만든다(훅이 만드는 facts 포함). over: {파일: 텍스트|None(삭제)}."""
    over = over or {}
    _n[0] += 1
    sid = f"{_n[0]:08x}-0000-4000-8000-000000000000"
    cwd = os.path.join(TMP, f"cwd{_n[0]}"); os.makedirs(cwd, exist_ok=True)
    d = ph.make_folder(sid, cwd, "1. 첫째 요청\n2) 둘째 요청\n그냥 글")
    files = {"00-cover.md": ("cover", COVER), "01-unknown.md": ("unknown", UNKNOWN)}
    for n, m, t in MODS.get(klass, []):
        files[n] = (m, t)
    for n, (m, t) in files.items():
        files[n] = head(m) + t
    if klass == "구현 결과":
        pc.write_tool_file(os.path.join(d, "facts", "diff-stat.txt"), pc.head_text() + f"시작 HEAD: 없음\n작업 폴더: {cwd}\n--- 변경·미추적 파일 ---\n" + "".join(f"파일: {f}\n" for f in diff_files))
        pc.register_sha(d, ["facts/diff-stat.txt"])
    listed = [f for f in files if f != skip_index_row]
    if klass == "구현 결과":
        listed.append("facts/diff-stat.txt")
    files["INDEX.md"] = index_text(klass, listed, state)
    for n, t in over.items():
        if t is None:
            files.pop(n, None)
        else:
            files[n] = t
    for n, t in files.items():
        open(os.path.join(d, n), "w", encoding="utf-8").write(t)
    return d, sid, cwd


def ids(res, level=None):
    return sorted({i["id"] for i in res["items"] if level is None or i["level"] == level})


def run(d, mode="attempt", **kw):
    return pc.run_checks(d, mode, **kw)


def fetch_ok(u):
    return ("ok", "앞말 캐시는 쓰지 마 뒷말", "s1")


def repo_ok(s):
    return "https://github.com/donghans/nixos"


def final(d, fetch=fetch_ok, repo=repo_ok):
    qi, qr = pc.collect_quotes(pc.Folder(d), fetch, repo)
    return run(d, "final", quote_items=qi), qr


# ================================================================ 정상 샘플
for klass in ("결정", "계획", "구현 결과"):
    d, *_ = build(klass)
    r = run(d)
    check(f"정상 샘플({klass}): FAIL·WARN 0", r["counts"]["FAIL"] == 0 and r["counts"]["WARN"] == 0, str(r["items"]))
d, *_ = build("결정")
rf, qr = final(d)
check("정상 샘플(결정) --final: FAIL·WARN 0, 인용 일치 기록", rf["counts"]["FAIL"] == 0 and rf["counts"]["WARN"] == 0 and [x["status"] for x in qr] == ["일치"], str(rf["items"]))
d, *_ = build("모름")
check("분류 모름: 모듈 없이 FAIL 0", run(d)["counts"]["FAIL"] == 0, str(run(d)["items"]))

# ================================================================ 변이 점검(틀린 샘플마다 의도한 ID)
d, *_ = build("결정", {"INDEX.md": None}); r = run(d)
check("변이 INDEX 없음 → C1 FAIL 하나뿐", ids(r, "FAIL") == ["C1"] and len(r["items"]) == 1 and r["items"][0]["reason"] == "INDEX.md 없음", str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + "\n"}); r = run(d)
check("변이 빈 파일 → C3", "C3" in ids(r, "FAIL"), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": head("cover") + COVER.replace("## 최종사용자 영향\n사용자는 응답 속도 차이를 느낀다.\n", "")}); r = run(d)
check("변이 필수 절 누락 → C4", any(i["id"] == "C4" and "최종사용자 영향" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": head("cover") + COVER.replace("  - 추천: (나). 이유: 단순하다\n", "")}); r = run(d)
check("변이 결정에 추천 없음 → C4(결정 D1)", any(i["id"] == "C4" and "D1" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": head("cover") + COVER.replace("  - 되돌리기: 쉬움\n", "")}); r = run(d)
check("변이 결정에 되돌리기 없음 → C4", any(i["id"] == "C4" and "D1" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정"); rf, qr = final(d, lambda u: ("ok", "전혀 다른 본문입니다", "s1"))
check("변이 가짜 인용 → C6 FAIL(인용 불일치)", any(i["id"] == "C6" and i["level"] == "FAIL" and "불일치" in i["reason"] for i in rf["items"]) and qr[0]["status"] == "미일치", str(rf["items"]))
d, *_ = build("결정", {"12-evidence.md": head("evidence") + '- [msg:aaaa1111] "캐시는 쓰지 마" (2026-11-01)\n'}); rf, _q = final(d)
check("변이 한정 없음 → C6 FAIL(날짜·한정 표기 없음)", any(i["id"] == "C6" and i["level"] == "FAIL" and "한정" in i["reason"] for i in rf["items"]), str(rf["items"]))
d, *_ = build("결정"); rf, _q = final(d, repo=lambda s: "https://github.com/donghans/genple")
check("변이 다른 저장소 대화 인용 → C6 FAIL(nixos 아님)", any(i["id"] == "C6" and "nixos" in i["reason"] for i in rf["items"]), str(rf["items"]))
d, *_ = build("구현 결과", {"50-before-after.md": head("beforeafter") + BEFORE.replace("`mods/a/x.py`", "`mods/zzz/ghost.py`")}); r = run(d)
check("변이 허위 파일 주장 → C8 FAIL(+실제 변경이 문서에 없으면 WARN)", any(i["id"] == "C8" and i["level"] == "FAIL" and "ghost.py" in i["reason"] for i in r["items"]) and any(i["id"] == "C8" and i["level"] == "WARN" for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + f"키: {SECRET}\n"}); r = run(d)
check("변이 비밀 패턴 → C9 FAIL", "C9" in ids(r, "FAIL"), str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + "긴 줄 " * 800}); r = run(d)
check("변이 상한 초과 → C7 WARN 만(FAIL 없음)", "C7" in ids(r, "WARN") and r["counts"]["FAIL"] == 0, str(r["items"]))
d, *_ = build("결정"); os.chmod(os.path.join(d, "facts"), 0o700); fp = os.path.join(d, "facts", "request-items.txt")
os.chmod(fp, 0o600); open(fp, "a").write("3. 몰래 추가\n"); r = run(d)
check("변이 사실분 변조 → C5 FAIL(facts 파일이 바뀜)", any(i["id"] == "C5" and "바뀜" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + "TODO: 나중에\n"}); r = run(d)
check("변이 플레이스홀더 TODO → C4b", any(i["id"] == "C4b" and "TODO" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + "자리표시자 <여기에 쓸 내용> 입니다\n"}); r = run(d)
check("변이 미치환 <…> → C4b", "C4b" in ids(r, "FAIL"), str(r["items"]))
d, *_ = build("결정", skip_index_row="11-options.md"); r = run(d)
check("변이 표↔파일 불일치(표에 없는 파일) → C2", any(i["id"] == "C2" and "11-options.md" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"INDEX.md": index_text("결정", ["00-cover.md", "01-unknown.md", "10-glossary.md", "11-options.md", "12-evidence.md", "99-ghost.md"])}); r = run(d)
check("변이 표↔파일 불일치(파일 없는 행) → C2", any(i["id"] == "C2" and "99-ghost.md" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"INDEX.md": index_text("결정", ["00-cover.md"], cols=5)}); r = run(d)
check("변이 표 5열 → C1", any(i["id"] == "C1" and "열" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"12-evidence.md": None}); r = run(d)
check("변이 필수 모듈 파일 없음 → C4", any(i["id"] == "C4" and "12-evidence.md" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"20-remaining.md": head("remaining") + REMAIN}); r = run(d)
check("분류에 속하지 않는 모듈 파일 → C4 WARN", any(i["id"] == "C4" and i["level"] == "WARN" for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + "## 못 쟀음·미확인\n없음 하지만 길이는 채운다 채운다\n## 빠진 것\n빠진 것 없음\n"}); r = run(d)
check("요청 번호 언급 없음 → C10 WARN 둘", [i["reason"] for i in r["items"] if i["id"] == "C10"] == ["요청 1 언급 없음", "요청 2 언급 없음"] and "C10" in ids(r, "WARN"), str(r["items"]))
d, *_ = build("결정", {"10-glossary.md": head("glossary") + "표가 아닌 글만 있다 표가 아닌 글만 있다\n"}); r = run(d)
check("용어 사전에 표 데이터 없음 → C4", any(i["id"] == "C4" and "10-glossary" in i["file"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": "표지 없는 본문 표지 없는 본문 표지 없는 본문\n"}); r = run(d)
check("머리 없는 파일 → C5", any(i["id"] == "C5" and i["file"] == "00-cover.md" for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": head("cover", who="tool:x") + COVER}); r = run(d)
check("해석분이 tool 작성 표지 → C5", any(i["id"] == "C5" and i["file"] == "00-cover.md" for i in r["items"]), str(r["items"]))
d, *_ = build("결정", {"00-cover.md": head("cover") + COVER.replace("## 결정할 것\n- D1. 캐시 사용 여부\n  - 선택지: (가) 쓴다 (나) 안 쓴다\n  - 추천: (나). 이유: 단순하다\n  - 되돌리기: 쉬움\n", "## 결정할 것\n결정할 것 없음\n")}); r = run(d)
check("「결정할 것 없음」 한 줄은 허용", r["counts"]["FAIL"] == 0, str(r["items"]))

# 모드별: 작업중(C1·C3·C9 만), final 의 작업중은 C1 FAIL
d, *_ = build("결정", {"01-unknown.md": None, "12-evidence.md": None}, state="작업중"); r = run(d, "working")
check("작업중 Stop: 없는 고정 틀·모듈은 FAIL 아님", r["counts"]["FAIL"] == 0, str(r["items"]))
d, *_ = build("결정", {"01-unknown.md": head("unknown") + "\n", "00-cover.md": head("cover") + f"{SECRET}\n" * 2}, state="작업중"); r = run(d, "working")
check("작업중 Stop: 존재하는 빈 파일은 C3, 비밀은 C9", ids(r, "FAIL") == ["C3", "C9"], str(r["items"]))
d, *_ = build("결정", state="작업중"); r = run(d, "final", quote_items=[])
check("--final 에서 상태 작업중은 C1 FAIL(미완료)", any(i["id"] == "C1" and "미완료" in i["reason"] for i in r["items"]), str(r["items"]))
d, *_ = build("결정", state="작업중"); r = run(d, "working")
check("작업중 INDEX 는 작업중 모드에서 C1 통과", "C1" not in ids(r, "FAIL"), str(r["items"]))

# C6: DB 접속 실패 → INFO 미실시(FAIL 도 통과도 아님), 실제 실행 파일 경로로도
d, *_ = build("결정")
def boom(u):
    return ("error", "접속 실패")
rf, qr = final(d, boom)
check("C6 fetch 오류 → INFO 미실시, FAIL 아님", any(i["id"] == "C6" and i["level"] == "INFO" and "미실시" in i["reason"] for i in rf["items"]) and rf["counts"]["FAIL"] == 0 and qr[0]["status"] == "미실시", str(rf["items"]))
fake = script(TMP, "donghans", "import sys\nsys.stderr.write('psycopg.OperationalError: connection refused\\n')\nsys.exit(1)\n")
os.environ["LLM_PROTOCOL_DONGHANS"] = fake
qi, qr = pc.collect_quotes(pc.Folder(d))
check("가짜 donghans(접속 실패, 종료 코드 1) → C6 미실시", qr[0]["status"] == "미실시" and qi[0]["level"] == "INFO", str(qi))
fake2 = script(TMP, "donghans2", "import sys\nprint('일치하는 메시지 없음')\nsys.exit(1)\n")
os.environ["LLM_PROTOCOL_DONGHANS"] = fake2
qi, qr = pc.collect_quotes(pc.Folder(d))
check("가짜 donghans(메시지 없음) → C6 FAIL", qi[0]["level"] == "FAIL" and qr[0]["status"] == "메시지 없음", str(qi))
fake3 = script(TMP, "donghans3", "import sys\nif sys.argv[2:3]==['msg']:\n    print('# aaaa1111-0000  세션 abcdef12-0000-4000-8000-000000000000  2026-11-01 10:00:00  user/prompt  전체 10자(치환 뒤)')\n    print('앞 캐시는 쓰지 마 뒤')\nelse:\n    print('repo_url'); print('https://github.com/donghans/nixos')\n")
os.environ["LLM_PROTOCOL_DONGHANS"] = fake3
qi, qr = pc.collect_quotes(pc.Folder(d))
check("가짜 donghans(정상) → C6 통과 경로(ctx msg·ctx sql 호출 형식)", qi == [] and qr[0]["status"] == "일치", str((qi, qr)))
del os.environ["LLM_PROTOCOL_DONGHANS"]
check("포인터 줄은 인용 검사 대상 아님(INFO 개수만)", [i["level"] for i in pc.collect_quotes(pc.Folder(build("결정", {"12-evidence.md": head("evidence") + "- [msg:aaaa1111] (포인터 — 읽을 때 채움)\n"})[0]), boom)[0]] == ["INFO"])

d, *_ = build("결정", {"12-evidence.md": head("evidence") + '- [msg:aaaa1111-0000-4000-8000-000000000001] "캐시는 쓰지 마" (2026-11-01 10:59 KST · 한정: 이번 설계)\n'}); rf, qr = final(d)
check("전체 uuid·날짜에 시각이 붙은 인용 줄도 통과(과거 카드 그림자 적용에서 나온 보정)", rf["counts"]["FAIL"] == 0 and qr[0]["status"] == "일치", str(rf["items"]))

d, *_ = build("결정", {"INDEX.md": index_text("결정", ["INDEX.md", "00-cover.md", "01-unknown.md", "10-glossary.md", "11-options.md", "12-evidence.md"])}); r = run(d)
check("표에 INDEX.md 자신을 올려도 C2 FAIL 아님(실제 스모크 지적)", "C2" not in ids(r, "FAIL"), str(r["items"]))

# 검사기 내부 오류 → INFO C0, 던지지 않음
orig = pc.check_c4
pc.check_c4 = lambda fo: 1 / 0
d, *_ = build("결정"); r = run(d)
pc.check_c4 = orig
check("검사 함수 예외 → INFO C0(던지지 않음)", any(i["id"] == "C0" and i["level"] == "INFO" for i in r["items"]) and r["counts"]["FAIL"] == 0, str(r["items"]))

# (c) 되돌림 사유 문구 모양
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + "TODO\n", "00-cover.md": head("cover") + f"{SECRET}\n" + COVER}); r = run(d)
reason = pc.block_reason(r)
check("(c) 사유: 동결 머리·꼬리 + 항목 줄(44자 이내)", reason.startswith(T.C_HEAD) and reason.endswith(T.C_TAIL) and all(len(l) <= 44 for l in reason.split("\n") if l.startswith("- C")), reason)
many = {"items": [{"id": "C4", "level": "FAIL", "file": f"f{i}.md", "reason": "x"} for i in range(8)]}
check("(c) 사유: 5개 넘으면 외 N건 줄", "(외 3건은 .check/CHECK.md 에 있다)" in pc.block_reason(many) and pc.block_reason(many).count("\n- C4") == 5)

# run CLI + 파일 출력
d, *_ = build("결정", {"01-unknown.md": head("unknown") + UNKNOWN + "TODO\n"})
p = subprocess.run([sys.executable, "-I", CLI, "run", d], capture_output=True, text=True)
rj = json.load(open(os.path.join(d, ".check", "result.json")))
check("CLI run: FAIL 이면 종료 코드 1, result.json·CHECK.md 생성, 0400", p.returncode == 1 and rj["counts"]["FAIL"] >= 1 and os.path.exists(os.path.join(d, ".check", "CHECK.md"))
      and stat.S_IMODE(os.stat(os.path.join(d, ".check", "result.json")).st_mode) == 0o400, p.stdout + p.stderr)
d, *_ = build("결정")
p = subprocess.run([sys.executable, "-I", CLI, "run", d], capture_output=True, text=True)
check("CLI run: 정상이면 종료 코드 0", p.returncode == 0, p.stdout + p.stderr)
d, *_ = build("결정", state="작업중")
p = subprocess.run([sys.executable, "-I", CLI, "run", d, "--final", "--json"], capture_output=True, text=True, env=dict(os.environ, LLM_PROTOCOL_DONGHANS=fake))
check("CLI run --final: 작업중 INDEX 는 종료 코드 1(미완료)", p.returncode == 1 and "미완료" in p.stdout, p.stdout + p.stderr)

# facts: diff-stat(실제 git 저장소)·quotes
repo = os.path.join(TMP, "repo"); os.makedirs(repo)
def g(*a): return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *a], capture_output=True, text=True).stdout
g("init", "-q"); open(os.path.join(repo, "dirty.txt"), "w").write("v1\n"); open(os.path.join(repo, "a.txt"), "w").write("a\n"); g("add", "."); g("commit", "-qm", "init")
open(os.path.join(repo, "dirty.txt"), "w").write("v2\n")   # 시작 때 이미 변경
d = ph.make_folder("feedface-0000-4000-8000-000000000000", repo, "작업")
base = pc.parse_base(pc.Folder(d))
check("base.txt: HEAD·작업 폴더·시작 상태·해시", len(base["head"] or "") == 40 and base["cwd"] == repo and any("dirty.txt" in s for s in base["status"]) and "dirty.txt" in base["hashes"], str(base))
open(os.path.join(repo, "a.txt"), "w").write("a2\n"); open(os.path.join(repo, "new.txt"), "w").write("n\n")
pc.refresh_diff_stat(d)
ds = open(os.path.join(d, "facts", "diff-stat.txt")).read()
check("diff-stat: 변경·미추적 포함, 시작 때 변경된 채 그대로인 파일은 제외", "파일: a.txt" in ds and "파일: new.txt" in ds and "파일: dirty.txt" not in ds, ds)
open(os.path.join(repo, "dirty.txt"), "w").write("v3\n"); pc.refresh_diff_stat(d)
check("diff-stat: 시작 때 변경됐던 파일도 내용이 더 바뀌면 포함", "파일: dirty.txt" in open(os.path.join(d, "facts", "diff-stat.txt")).read())
check("diff-stat 은 등록 해시와 일치(C5 통과)", "C5" not in ids(run(d, "attempt"), "FAIL") or all("diff-stat" not in i["file"] for i in run(d, "attempt")["items"] if i["id"] == "C5"))
p = subprocess.run([sys.executable, "-I", CLI, "facts", d, "--no-quotes"], capture_output=True, text=True)
check("CLI facts --no-quotes", p.returncode == 0 and "diff-stat" in p.stdout, p.stdout + p.stderr)

# ================================================================ 훅(실제 프로세스)
def hook(which, payload, gate="1", home=HOME, stdin_raw=None):
    env = {"PATH": os.environ["PATH"], "HOME": TMP, "LLM_PROTOCOL_HOME": home}
    if gate is not None:
        env["LLM_PROTOCOL_PILOT"] = gate
    p = subprocess.run([sys.executable, "-I", CLI, "hook", which], input=stdin_raw if stdin_raw is not None else json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)
    return p


# 게이트 꺼짐 — 무동작
gate_home = os.path.join(TMP, "gate-home")
for gv in (None, "0", ""):
    for which in ("prompt", "stop"):
        p = hook(which, {"session_id": "abcdef12-0000-4000-8000-000000000000", "prompt": "1. x", "cwd": TMP}, gate=gv, home=gate_home)
        check(f"게이트 꺼짐({gv!r}) {which}: 출력 없음·종료 코드 0·아무것도 안 만듦", p.returncode == 0 and p.stdout == "" and p.stderr == "" and not os.path.exists(gate_home), repr((p.stdout, p.stderr, p.returncode)))
p = hook("stop", {}, gate=None, home=gate_home, stdin_raw="깨진 입력")
check("게이트 꺼짐: 깨진 입력도 무동작·종료 코드 0", p.returncode == 0 and p.stdout == "" and not os.path.exists(gate_home))
p = hook("prompt", {}, stdin_raw="깨진 입력")
check("게이트 켜짐: 깨진 입력도 종료 코드 0·출력 없음(실패 시 통과)", p.returncode == 0 and p.stdout == "")
p = hook("stop", {"session_id": "없는세션"})
check("게이트 켜짐: 모르는 세션의 Stop 은 무동작", p.returncode == 0 and p.stdout == "")

# 슬롯 동결(종류마다 [첫 작업 팔, 둘째 작업 팔])
os.makedirs(HOME, exist_ok=True)
json.dump({"결정": ["G", "F"], "계획": ["F", "G"], "검증·QA": ["G", "F"], "구현 결과": ["F", "G"]}, open(os.path.join(HOME, "pilot-slots.json"), "w"), ensure_ascii=False)
reg = ph.Registry(HOME)
S1 = "11111111-aaaa-4bbb-8ccc-000000000001"
p = hook("prompt", {"session_id": S1, "prompt": "1. 첫째 요청\n2) 둘째\n설명", "cwd": repo, "hook_event_name": "UserPromptSubmit"})
d1 = ph.session_dir(S1)
check("첫 프롬프트: 폴더 0700·FORMAT.md 0400·facts 0400·registry 행", stat.S_IMODE(os.stat(d1).st_mode) == 0o700 and stat.S_IMODE(os.stat(os.path.join(d1, "FORMAT.md")).st_mode) == 0o400
      and stat.S_IMODE(os.stat(os.path.join(d1, "facts", "base.txt")).st_mode) == 0o400 and reg.get(S1) is not None and reg.get(S1)["팔"] == "", p.stderr)
check("첫 프롬프트: (a) 전문 주입, 경로가 박힘", p.returncode == 0 and p.stdout.startswith("[규약 파일럿] 이 작업은") and d1 in p.stdout and "{DIR}" not in p.stdout and p.stdout.strip() == T.A_TEMPLATE.replace("{DIR}", d1).strip())
check("FORMAT.md 는 동결 문구 그대로", open(os.path.join(d1, "FORMAT.md")).read() == T.FORMAT_MD)
ri = open(os.path.join(d1, "facts", "request-items.txt")).read()
check("request-items: 번호 항목 줄만", "1. 첫째 요청" in ri and "2) 둘째" in ri and "설명" not in ri, ri)
p = hook("prompt", {"session_id": S1, "prompt": "이어서 해줘", "cwd": repo})
check("이후 프롬프트: (b) 한 줄만", p.stdout.strip() == T.B_TEMPLATE.replace("{DIR}", d1) and "[규약 파일럿]" not in p.stdout, p.stdout)
check("분류 전에는 팔 없음", reg.get(S1)["팔"] == "" and reg.get(S1)["종류"] == "")
p = hook("prompt", {"session_id": S1, "prompt": "분류: 계획", "cwd": repo})
r1 = reg.get(S1)
check("분류: 계획 → registry 에 계획 슬롯 0 의 팔(F)·종류 기록", r1["종류"] == "계획" and r1["팔"] == "F" and r1["슬롯종류"] == "계획", str(r1))
p = hook("prompt", {"session_id": S1, "prompt": "분류: 결정", "cwd": repo})
r1 = reg.get(S1)
check("재분류: 종류만 갱신, 팔 유지, 정정분류 기록", r1["종류"] == "결정" and r1["팔"] == "F" and r1["정정분류"] == "계획→결정", str(r1))
S2 = "22222222-aaaa-4bbb-8ccc-000000000002"
hook("prompt", {"session_id": S2, "prompt": "분류: 계획", "cwd": repo})
check("같은 종류 둘째 작업은 슬롯 1 의 팔(G) — 재분류가 슬롯을 소모하지 않음을 계획 슬롯 2번째로 확인", reg.get(S2)["팔"] == "G", str(reg.get(S2)))
S3 = "33333333-aaaa-4bbb-8ccc-000000000003"
hook("prompt", {"session_id": S3, "prompt": "분류: 결정", "cwd": repo})
check("결정 슬롯 0 은 S1 의 재분류로 소모되지 않았다(S3 이 G)", reg.get(S3)["팔"] == "G", str(reg.get(S3)))
S4 = "44444444-aaaa-4bbb-8ccc-000000000004"
hook("prompt", {"session_id": S4, "prompt": "분류: 모름", "cwd": repo})
check("분류: 모름 → 팔·슬롯 없음", reg.get(S4)["종류"] == "모름" and reg.get(S4)["팔"] == "" and reg.get(S4)["슬롯종류"] == "")
hook("prompt", {"session_id": S4, "prompt": "분류: 구현 결과", "cwd": repo})
check("모름 뒤 확정 분류는 그때 슬롯을 받는다", reg.get(S4)["팔"] == "F", str(reg.get(S4)))
S5 = "55555555-aaaa-4bbb-8ccc-000000000005"
hook("prompt", {"session_id": S5, "prompt": "설명 분류: 계획 이라는 말", "cwd": repo})
check("`분류:` 줄이 아닌 글 속 문구는 분류로 안 본다", reg.get(S5)["종류"] == "")

# Stop 훅
def mk_session(sid, kind, index=None, files=None):
    hook("prompt", {"session_id": sid, "prompt": f"1. 일\n분류: {kind}", "cwd": repo})
    d = ph.session_dir(sid)
    for n, t in (files or {}).items():
        open(os.path.join(d, n), "w", encoding="utf-8").write(t)
    return d

def stop(sid, pid="p1", active=False, tp=None):
    pl = {"session_id": sid, "prompt_id": pid, "stop_hook_active": active, "cwd": repo, "hook_event_name": "Stop"}
    if tp:
        pl["transcript_path"] = tp
    return hook("stop", pl)

def slog(d):
    return [json.loads(l) for l in open(os.path.join(d, ".check", "stop-log.jsonl")) if l.strip()]

def broken_index(klass="결정", state="완료"):
    return {"INDEX.md": index_text(klass, ["00-cover.md"], state)}   # 표에 없는 파일·없는 고정 틀 → FAIL 다수는 아니고 C2/C3

# G 팔: 기록만
GS = "6a6a6a6a-0000-4000-8000-0000000000aa"
json.dump({"결정": ["G", "F"], "계획": ["F", "G"], "검증·QA": ["G", "F"], "구현 결과": ["F", "G"]}, open(os.path.join(HOME, "pilot-slots.json"), "w"), ensure_ascii=False)
rows_before = len(reg.rows())
# 슬롯 소모 순서를 맞추기 위해 종류별로 새 세션을 만든다: 검증·QA 슬롯 0 = G, 1 = F
dG = mk_session(GS, "검증·QA", files=broken_index("검증·QA"))
check("시험 준비: GS 는 G 팔", reg.get(GS)["팔"] == "G", str(reg.get(GS)))
p = stop(GS)
L = slog(dG)
check("G 팔 Stop: 되돌리지 않음(출력 없음), stop-log 에 마감 시도·첫 시도·FAIL 기록, 팔 G", p.returncode == 0 and p.stdout == "" and L[-1]["attempt"] and L[-1]["first_attempt"] and L[-1]["arm"] == "G"
      and L[-1]["action"] == "log" and L[-1]["counts"]["FAIL"] >= 1 and os.path.exists(os.path.join(dG, ".check", "result.json")), str((p.stdout, L)))
p = stop(GS, pid="p2")
check("G 팔: 두 번째 마감 시도는 first_attempt 가 아님·여전히 되돌림 없음", p.stdout == "" and slog(dG)[-1]["first_attempt"] is False)
check("G 팔은 rewind.json 을 만들지 않는다", not os.path.exists(os.path.join(dG, ".check", "rewind.json")))

# F 팔: 1회 되돌림
FS = "7b7b7b7b-0000-4000-8000-0000000000bb"
dF = mk_session(FS, "검증·QA", files=broken_index("검증·QA"))
check("시험 준비: FS 는 F 팔", reg.get(FS)["팔"] == "F", str(reg.get(FS)))
p = stop(FS, "q1")
out = json.loads(p.stdout) if p.stdout.strip() else {}
check("F 팔 Stop: FAIL 이면 block JSON(decision·reason=(c) 문구)", out.get("decision") == "block" and out["reason"].startswith(T.C_HEAD) and "C" in out["reason"] and out["reason"].endswith(T.C_TAIL), p.stdout + p.stderr)
check("block 기록: action=block, 세션 카운터 1", slog(dF)[-1]["action"] == "block" and slog(dF)[-1]["rewinds_session"] == 1)
p = stop(FS, "q1", active=True)
L = slog(dF)
check("stop_hook_active=True 면 막지 않고 통과, 결과는 stop-log 에 기록", p.stdout == "" and L[-1]["action"] == "pass-active" and L[-1]["counts"]["FAIL"] >= 1 and L[-1]["stop_hook_active"] is True, str(L[-1]))
p = stop(FS, "q1")
check("같은 프롬프트에서는 두 번 되돌리지 않는다", p.stdout == "" and slog(dF)[-1]["action"] == "pass-prompt-once")
p = stop(FS, "q2"); b2 = p.stdout.strip() != ""
p = stop(FS, "q3"); b3 = p.stdout.strip() != ""
p = stop(FS, "q4")
check("세션당 3회까지만 되돌림(4번째 프롬프트는 통과 모드)", b2 and b3 and p.stdout == "" and slog(dF)[-1]["action"] == "pass-cap" and json.load(open(os.path.join(dF, ".check", "rewind.json")))["session"] == 3, str(slog(dF)[-1]))
check("카운터 파일은 0400", stat.S_IMODE(os.stat(os.path.join(dF, ".check", "rewind.json")).st_mode) == 0o400)

# F 팔: 작업중·정상·변경 없음은 되돌리지 않음
json.dump({k: ["F"] * 30 for k in ("결정", "계획", "검증·QA", "구현 결과")}, open(os.path.join(HOME, "pilot-slots.json"), "w"), ensure_ascii=False)
FS2 = "8d8d8d8d-0000-4000-8000-0000000000cd"
dW = mk_session(FS2, "계획", files=broken_index("계획", "작업중"))
check("시험 준비: FS2 는 F 팔", reg.get(FS2)["팔"] == "F", str(reg.get(FS2)))
p = stop(FS2, "w1")
L = slog(dW)
check("F 팔도 작업중 Stop 은 되돌리지 않음(기록만, 마감 시도 아님)", p.stdout == "" and L[-1]["event"] == "작업중 Stop" and L[-1]["attempt"] is False and L[-1]["action"] == "log", str(L[-1]))

FS3 = "9e9e9e9e-0000-4000-8000-0000000000dd"
d3 = mk_session(FS3, "결정")
for n, t in {"INDEX.md": None}.items():
    pass
good, _s, _c = build("결정", state="완료")
for n in os.listdir(good):
    if n.endswith(".md") and n != "FORMAT.md":
        shutil.copy(os.path.join(good, n), os.path.join(d3, n))
# 정상 샘플의 INDEX 는 facts 표를 안 쓰므로 통과해야 한다(요청 번호는 해당 샘플의 request-items 가 다르므로 WARN 만 날 수 있음)
p = stop(FS3, "g1")
check("F 팔: 정상 산출물은 되돌리지 않는다", p.stdout == "" and slog(d3)[-1]["attempt"] and slog(d3)[-1]["action"] == "log" and slog(d3)[-1]["counts"]["FAIL"] == 0, str(slog(d3)[-1]) + p.stderr)

FS4 = "afafafaf-0000-4000-8000-0000000000ee"
d4 = mk_session(FS4, "결정")
p = stop(FS4, "n1")
check("INDEX 없음+변경 없음(질문 턴): 검사 없이 기록만", p.stdout == "" and slog(d4)[-1]["event"] == "변경 없음", str(slog(d4)[-1]))
tp = os.path.join(TMP, "tr.jsonl")
open(tp, "w").write("\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"type": "user", "message": {"role": "user", "content": "이전 프롬프트"}},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/old.py"}}]}},
    {"type": "user", "message": {"role": "user", "content": "이번 프롬프트"}},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/a.py"}}]}}]) + "\n")
p = stop(FS4, "n2", tp=tp)
check("INDEX 없음: 이번 프롬프트에 변경 도구 호출이 없으면(이전 프롬프트의 것은 무관) 검사 없음", p.stdout == "" and slog(d4)[-1]["event"] == "변경 없음", str(slog(d4)[-1]))
open(tp, "a").write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/x/new.py"}}]}}) + "\n")
p = stop(FS4, "n3", tp=tp)
out = json.loads(p.stdout) if p.stdout.strip() else {}
check("INDEX 없음+변경 도구 호출 → 「INDEX.md 없음」 C1 FAIL 로 F 팔이 되돌림", out.get("decision") == "block" and "INDEX.md 없음" in out["reason"] and slog(d4)[-1]["event"] == "마감 시도", p.stdout + p.stderr)
# Bash 로 바꾼 변경은 git 상태 변화로 잡는다
FS5 = "b0b0b0b0-0000-4000-8000-0000000000ff"
d5 = mk_session(FS5, "결정")
stop(FS5, "m0")   # git 서명 기준 기록
open(os.path.join(repo, "bashed.txt"), "w").write("x\n")
p = stop(FS5, "m1")
check("Bash 로 바꾼 파일(git 상태 변화)도 변경으로 본다", slog(d5)[-1]["event"] == "마감 시도", str(slog(d5)[-1]))

# 팔 없는 Stop
NS = "c1c1c1c1-0000-4000-8000-000000000011"
hook("prompt", {"session_id": NS, "prompt": "작업", "cwd": repo})
p = stop(NS)
check("팔 없는 Stop: 검사하지 않고 INFO 기록", p.stdout == "" and slog(ph.session_dir(NS))[-1]["event"] == "팔 없는 Stop" and not os.path.exists(os.path.join(ph.session_dir(NS), ".check", "result.json")))

# 훅 입력의 session_id 가 폴더 이름 앞 8자로 대응
check("폴더 이름은 session_id 앞 8자", os.path.basename(ph.session_dir(S1)) == S1[:8] and os.path.isdir(os.path.join(HOME, "nixos", S1[:8])))

shutil.rmtree(TMP, ignore_errors=True)
finish("protocolcheck")
