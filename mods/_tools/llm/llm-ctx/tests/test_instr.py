#!/usr/bin/env python3
"""ctx_instr 시험 — 프로젝트별 지침의 공유 정본 동기화.
1부(순수·파일): 판정표 plan · git 루트/워크트리 · .git/info/exclude 멱등 — psycopg 없이 돈다.
2부(임시 Postgres): 두 「기기」(같은 저장소 URL, 다른 체크아웃)에서 채택→갱신→앞섬→충돌→강제, 비밀 거부, 훅(SessionStart) 실행. psycopg·postgres 17 이 없으면 건너뛴다."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctx_instr as ci


def edit(path, text):
    """캐시는 읽기 전용이라 시험이 「사람이 우회해서 직접 고친」 상황을 만들 때 쓴다(chmod u+w 후 쓰기)."""
    if os.path.exists(path):
        os.chmod(path, 0o644)
    open(path, "w").write(text)

# ---------------------------------------------------------------- 1부: 판정표
S = ci.sha
db = lambda rev, body: {"rev": rev, "body": body}
cases = [
    ("DB 없음·로컬 없음", (None, None, None), "noop"),
    ("DB 없음·로컬 있음 → 첫 채택", ("a", None, None), "adopt"),
    ("DB 있음·로컬 없음 → 받아 씀", (None, None, db(1, "a")), "write"),
    ("같다·상태 없음 → 상태만 기록", ("a", None, db(1, "a")), "record"),
    ("같다·상태 일치 → 변화 없음", ("a", {"rev": 1, "sha": S("a")}, db(1, "a")), "noop"),
    ("로컬 손대지 않음·DB 갱신 → 덮어씀", ("a", {"rev": 1, "sha": S("a")}, db(2, "b")), "write"),
    ("로컬만 고침·DB 그대로 → 앞섬(훅은 안 올린다)", ("b", {"rev": 1, "sha": S("a")}, db(1, "a")), "ahead"),
    ("둘 다 바뀜 → 충돌(어느 쪽도 안 덮는다)", ("c", {"rev": 1, "sha": S("a")}, db(2, "b")), "conflict"),
    ("상태 기록 없는 기존 파일이 DB 와 다름 → 충돌", ("x", None, db(3, "y")), "conflict"),
]
for name, args, want in cases:
    check(f"plan: {name}", ci.plan(*args) == want, f"{ci.plan(*args)} != {want}")

# ---------------------------------------------------------------- 절 고르기(순수)
DOC = "# 제목\n머리말\n\n## QA 할 때 (원칙)\nqa 본문\n### 하위\n하위 본문\n\n## resume 할 때\nre 본문\n\n## 수정 세션\nfix 본문\n"
pre, secs = ci.split_sections(DOC)
check("절 나누기: 머리말 + 3개(### 은 절이 아니다)", pre == "# 제목\n머리말\n\n" and len(secs) == 3 and "하위 본문" in secs[0], str(secs))
sel, om = ci.select_sections(DOC, ["QA 할 때"])
check("절 고르기: 제목에 말이 든 절만 + 머리말, 나머지는 생략 목록", "qa 본문" in sel and "하위 본문" in sel and "머리말" in sel and "re 본문" not in sel and om == ["resume 할 때", "수정 세션"], f"{sel!r} {om}")
sel, om = ci.select_sections(DOC, [])
check("절 고르기: 조건이 없으면 전체", sel == DOC and om == [])
sel, om = ci.select_sections(DOC, ["resume 할 때", "수정 세션"])
check("절 고르기: 여러 개", "re 본문" in sel and "fix 본문" in sel and "qa 본문" not in sel and om == ["QA 할 때 (원칙)"])
sel, om = ci.select_sections(DOC, ["없는 절"])
check("절 고르기: 일치가 없어도 머리말은 남고 전부 생략으로 알린다", sel == "# 제목\n머리말\n\n" and len(om) == 3)

# ---------------------------------------------------------------- git 픽스처
TMP = tempfile.mkdtemp(prefix="instr-test-")
def sh(*a, cwd=None):
    r = subprocess.run(a, capture_output=True, text=True, cwd=cwd); return r.stdout.strip()
def mkrepo(name, url="git@github.com:test/proj.git"):
    d = os.path.join(TMP, name); os.makedirs(d)
    sh("git", "init", "-q", "-b", "main", cwd=d); sh("git", "remote", "add", "origin", url, cwd=d)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=d)
    return d
m1 = mkrepo("m1")
wt = os.path.join(TMP, "m1-wt"); sh("git", "worktree", "add", "-q", wt, "-b", "side", cwd=m1)
r = ci.roots(wt)
check("워크트리에서도 루트는 메인 체크아웃", r and os.path.realpath(r[0]) == os.path.realpath(m1), str(r))
check("git 저장소가 아니면 None", ci.roots(tempfile.gettempdir() + "/nonexistent-xyz") is None)
common = r[1]
check("exclude 첫 추가는 True", ci.ensure_excluded(common) is True)
check("exclude 두 번째는 변화 없음(멱등)", ci.ensure_excluded(common) is False)
ex = open(os.path.join(common, "info", "exclude")).read().splitlines()
check("exclude 에 지침 두 파일과 상태 파일", all(l in ex for l in ci.EXCLUDE), str(ex))

# ---------------------------------------------------------------- 2부: DB
try:
    import psycopg  # noqa: F401
    import pgscratch
    pg = pgscratch.start()
except ImportError:
    pg = None
if not pg:
    print("psycopg/postgres 가 없어 2부(DB)를 건너뜀"); finish("instr(순수)")
try:
    os.environ.update(pg.env())
    import llm_ctx as cc
    URL = "https://github.com/test/proj"
    class Mask:   # 등록된 비밀 값 하나를 가정한 치환기
        def text(self, s): return s.replace("hunter2", "[protected]")
    conn = cc.connect()
    m2 = mkrepo("m2")     # 같은 저장소 URL 의 다른 체크아웃(= 다른 기기)
    r1, r2 = ci.roots(m1), ci.roots(m2)
    F1 = lambda n: ci.local_path(m1, n); F2 = lambda n: ci.local_path(m2, n)
    os.makedirs(os.path.join(m1, ".claude")); edit(F1("instructions"), "v1\n")

    n = ci.sync(conn, URL, r1[0], r1[1], "hostA")
    check("A: DB 가 비었고 로컬이 있으면 첫 채택(rev 1)", [k for _, k, _ in n] == ["adopted"] and ci.db_rows(conn, URL)["instructions"]["rev"] == 1, str(n))
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 로컬이 없으면 DB 본문으로 채운다", open(F2("instructions")).read() == "v1\n" and [k for _, k, _ in n] == ["updated"], str(n))
    check("B: .git/info/exclude 도 맞춘다", all(l in open(os.path.join(r2[1], "info", "exclude")).read() for l in ci.EXCLUDE))
    check("B: 두 번째 sync 는 알릴 것이 없다", ci.sync(conn, URL, r2[0], r2[1], "hostB") == [])

    edit(F1("instructions"), "v2\n")
    code, msg = ci.push(conn, URL, r1[0], "instructions", "hostA", masker=Mask())
    check("A: 고쳐서 올리면 rev 2", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 2, msg)
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 손대지 않았으면 다음 세션에 rev 2 로 갱신", open(F2("instructions")).read() == "v2\n" and [k for _, k, _ in n] == ["updated"], str(n))

    edit(F2("instructions"), "v3-local-B\n")
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 로컬만 고치면 앞섬 — 파일도 DB 도 그대로", [k for _, k, _ in n] == ["ahead"] and open(F2("instructions")).read() == "v3-local-B\n" and ci.db_rows(conn, URL)["instructions"]["body"] == "v2\n", str(n))
    code, msg = ci.push(conn, URL, r2[0], "instructions", "hostB", masker=Mask())
    check("B: 명시적 push 로 rev 3", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 3, msg)

    edit(F1("instructions"), "v4-local-A\n")      # A 는 rev 2 를 본 상태에서 고친다 — B 가 rev 3 을 올린 뒤
    n = ci.sync(conn, URL, r1[0], r1[1], "hostA")
    check("A: 양쪽이 바뀌면 충돌 — 어느 쪽도 안 덮는다", [k for _, k, _ in n] == ["conflict"] and open(F1("instructions")).read() == "v4-local-A\n" and ci.db_rows(conn, URL)["instructions"]["body"] == "v3-local-B\n", str(n))
    code, msg = ci.push(conn, URL, r1[0], "instructions", "hostA", masker=Mask())
    check("A: 충돌 상태의 push 는 --force 없이는 거부", code == 1 and ci.db_rows(conn, URL)["instructions"]["rev"] == 3, msg)
    code, msg = ci.pull(conn, URL, r1[0], "instructions")
    check("A: 충돌 상태의 pull 은 --force 없이는 거부(로컬 편집 보호)", code == 1 and open(F1("instructions")).read() == "v4-local-A\n", msg)
    d = ci.diff_text(conn, URL, r1[0], "instructions")
    check("diff 가 양쪽 차이를 보인다", "v3-local-B" in d and "v4-local-A" in d, d)
    code, msg = ci.push(conn, URL, r1[0], "instructions", "hostA", force=True, masker=Mask())
    check("A: --force 로 올리면 rev 4", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 4, msg)
    code, msg = ci.pull(conn, URL, r2[0], "instructions", force=True)
    check("B: pull --force 는 DB 본문으로 덮는다", code == 0 and open(F2("instructions")).read() == "v4-local-A\n", msg)

    edit(F1("override"), "key=hunter2\n")
    code, msg = ci.push(conn, URL, r1[0], "override", "hostA", masker=Mask())
    check("등록된 비밀이 든 본문은 올리지 않는다", code == 1 and "override" not in ci.db_rows(conn, URL), msg)

    # 낙관적 잠금: 읽은 rev 가 낡았으면 UPDATE 가 0행
    check("rev 가 어긋난 UPDATE 는 거부(None)", ci._update(conn, URL, "instructions", "zzz", "hostC", expect_rev=1) is None)

    # 훅 end-to-end: 같은 URL 의 세 번째 체크아웃, 파일 없음 → SessionStart 가 채우고 additionalContext 를 낸다
    m3 = mkrepo("m3"); conn.commit()
    p = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-1", "cwd": m3, "hook_event_name": "SessionStart"}), env=pg.env())
    out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    check("훅: 지침 파일을 만들고 짧은 알림만 낸다(본문 주입 없음)",
          p.returncode == 0 and open(ci.local_path(m3, "instructions")).read() == "v4-local-A\n"
          and "공유 저장소" in out.get("hookSpecificOutput", {}).get("additionalContext", "") and "v4-local-A" not in p.stdout, p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-2", "cwd": m3, "hook_event_name": "SessionStart"}), env=pg.env())
    check("훅: 바뀐 것이 없으면 아무것도 출력하지 않는다", p.returncode == 0 and p.stdout.strip() == "", p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-3", "cwd": tempfile.gettempdir()}), env=pg.env())
    check("훅: git 저장소가 아닌 cwd 는 조용히 통과", p.returncode == 0 and p.stdout.strip() == "", p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "instr", "list"], capture_output=True, text=True, cwd=m3, env=pg.env())
    check("CLI instr list", "instructions: rev 4" in p.stdout, p.stdout + p.stderr)

    # ------------------------------------------------ 명령 경유(읽기 최신화 · 쓰기 DB 먼저 · 캐시 읽기 전용)
    writable = lambda path: bool(os.stat(path).st_mode & 0o222)
    check("동기화로 받아 쓴 캐시는 읽기 전용", not writable(F2("instructions")) and not writable(ci.local_path(m3, "instructions")))
    check("첫 채택·push 뒤의 캐시도 읽기 전용", not writable(F1("instructions")))
    code, msg = ci.set_body(conn, URL, r1[0], "instructions", "v5-set\n", "hostA", masker=Mask(), expect_rev=4)
    st = ci.load_state(r1[0])["instructions"]
    check("set: 기대 rev 가 맞으면 DB 먼저 rev 5, 캐시·상태도 맞고 읽기 전용",
          code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 5 and open(F1("instructions")).read() == "v5-set\n" and st["rev"] == 5 and not writable(F1("instructions")), msg)
    code, msg = ci.set_body(conn, URL, r2[0], "instructions", "v5-stale\n", "hostB", masker=Mask(), expect_rev=4)
    check("set: 읽은 뒤 바뀌었으면(낡은 rev) 거부하고 DB·캐시를 건드리지 않는다",
          code == 1 and ci.db_rows(conn, URL)["instructions"]["body"] == "v5-set\n" and open(F2("instructions")).read() == "v4-local-A\n", msg)
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("읽기 전 동기화: 다른 기기가 올린 최신본이 (잠긴 캐시에도) 반영된다", open(F2("instructions")).read() == "v5-set\n" and [k for _, k, _ in n] == ["updated"] and not writable(F2("instructions")), str(n))
    code, msg = ci.set_body(conn, URL, r1[0], "instructions", "key=hunter2\n", "hostA", masker=Mask())
    check("set: 등록된 비밀이 든 본문은 거부", code == 1 and ci.db_rows(conn, URL)["instructions"]["body"] == "v5-set\n", msg)
    code, msg = ci.set_body(conn, URL, r1[0], "instructions", "  \n", "hostA", masker=Mask())
    check("set: 빈 본문은 거부", code == 1, msg)
    code, msg = ci.set_body(conn, URL, r1[0], "instructions", "v5-set\n", "hostA", masker=Mask())
    check("set: 같은 내용이면 rev 를 올리지 않는다", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 5, msg)
    code, msg = ci.set_body(conn, URL, r1[0], "override", "ov-new\n", "hostA", masker=Mask())
    check("set: 아직 없는 이름은 rev 1 로 만든다", code == 0 and ci.db_rows(conn, URL)["override"]["rev"] == 1 and open(F1("override")).read() == "ov-new\n", msg)
    edit(F2("instructions"), "v6-direct\n")
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("캐시를 직접 고쳐 우회해도 앞섬으로 잡힌다(DB 는 그대로)", [k for nm, k, _ in n if nm == "instructions"] == ["ahead"] and ci.db_rows(conn, URL)["instructions"]["rev"] == 5, str(n))
    code, msg = ci.push(conn, URL, r2[0], "instructions", "hostB", masker=Mask())
    check("우회한 편집도 push 로 정리되면 다시 잠긴다", code == 0 and not writable(F2("instructions")), msg)

    conn.commit()   # 아래 CLI 는 별도 프로세스(다른 연결) — 이 연결의 열린 트랜잭션이 행 잠금을 쥐고 있으면 기다리다 멈춘다
    # CLI: set → show(절 고르기·생략 안내) → show(접속 실패) → edit(비대화 거부)
    CLI = lambda *args, **kw: subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "instr", *args], capture_output=True, text=True, cwd=m3, env=kw.pop("env", pg.env()), **kw)
    DOC2 = "# 프로젝트 지침 제목\n\n## QA 할 때\nqa-안내\n\n## resume 할 때\nresume-안내\n"
    p = CLI("set", "instructions", "--stdin", input=DOC2)
    check("CLI set --stdin", p.returncode == 0 and "rev 7" in p.stdout, p.stdout + p.stderr)
    p = CLI("show", "--section", "QA 할 때")
    check("CLI show: 고른 절 + 머리말, 생략한 절을 알린다", p.returncode == 0 and "qa-안내" in p.stdout and "프로젝트 지침 제목" in p.stdout and "resume-안내" not in p.stdout
          and "생략된 절 1개: resume 할 때" in p.stdout and "· 최신)" in p.stdout, p.stdout + p.stderr)
    p = CLI("show", "override")
    check("CLI show override: 절 고르기 없이 전체", p.returncode == 0 and "ov-new" in p.stdout and "생략" not in p.stdout, p.stdout + p.stderr)
    bad = dict(pg.env()); bad["CLAUDE_CTX_DSN"] = "postgresql://nobody@127.0.0.1:1/none"
    p = CLI("show", "--section", "resume 할 때", env=bad)
    check("CLI show: 접속 실패면 캐시를 「낡았을 수 있음」으로 보인다(그래도 읽힌다)", p.returncode == 0 and "resume-안내" in p.stdout and "접속 실패" in p.stdout and "낡았을 수 있음" in p.stdout, p.stdout + p.stderr)
    p = CLI("edit", "instructions", stdin=subprocess.DEVNULL)
    check("CLI edit: 대화형이 아니면 거부(에이전트는 set 을 쓴다)", p.returncode != 0 and "대화형" in (p.stdout + p.stderr), p.stdout + p.stderr)

    # ------------------------------------------------ --repo / main=None: 로컬 캐시 없이 DB 만(ctxui 「지침」 탭·cwd 와 무관한 편집 경로)
    conn.commit()
    cur = ci.db_rows(conn, URL)["instructions"]
    cache_before = (open(F1("instructions")).read(), json.dumps(ci.load_state(r1[0]), sort_keys=True))
    code, msg = ci.set_body(conn, URL, None, "instructions", "v-db-only\n", "hostZ", masker=Mask(), expect_rev=cur["rev"])
    check("set_body(main=None): DB 에만 쓴다(rev +1·수정 머신 기록)", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == cur["rev"] + 1 and ci.db_rows(conn, URL)["instructions"]["body"] == "v-db-only\n", msg)
    check("set_body(main=None): 로컬 캐시 파일·상태는 그대로", (open(F1("instructions")).read(), json.dumps(ci.load_state(r1[0]), sort_keys=True)) == cache_before)
    rev_now = ci.db_rows(conn, URL)["instructions"]["rev"]
    code, msg = ci.set_body(conn, URL, None, "instructions", "stale\n", "hostZ", masker=Mask(), expect_rev=rev_now - 1)
    check("set_body(main=None): 낡은 rev 는 거부(낙관적 잠금 유지)", code == 1 and ci.db_rows(conn, URL)["instructions"]["body"] == "v-db-only\n", msg)
    code, msg = ci.set_body(conn, URL, None, "instructions", "key=hunter2\n", "hostZ", masker=Mask(), expect_rev=rev_now)
    check("set_body(main=None): 비밀 든 본문은 거부", code == 1 and ci.db_rows(conn, URL)["instructions"]["body"] == "v-db-only\n", msg)
    code, msg = ci.set_body(conn, URL, None, "instructions", " \n", "hostZ", masker=Mask(), expect_rev=rev_now)
    check("set_body(main=None): 빈 본문은 거부", code == 1, msg)
    code, msg = ci.set_body(conn, URL + "-other", None, "override", "새 저장소 지침\n", "hostZ", masker=Mask())
    check("set_body(main=None): 아직 없는 저장소·이름은 rev 1 로 만든다(캐시 없음)", code == 0 and ci.db_rows(conn, URL + "-other")["override"]["rev"] == 1, msg)
    rd = ci.render(None, "instructions", [], "공유 저장소(DB)", db={"rev": 9, "body": "# 제목\n\n## QA\nqa\n\n## 다른\nx\n"})
    check("render(main=None): DB 본문과 rev 를 보인다", "rev 9" in rd and "공유 저장소(DB)" in rd and "## QA" in rd, rd)
    rd = ci.render(None, "instructions", ["QA"], "s", db={"rev": 9, "body": "# 제목\n\n## QA\nqa\n\n## 다른\nx\n"})
    check("render(main=None): 절 고르기와 생략 안내", "qa" in rd and "## 다른" not in rd and "생략된 절 1개: 다른" in rd, rd)
    check("render(main=None): 본문이 없으면 None", ci.render(None, "override", [], "s", db=None) is None)
    conn.commit()

    NOGIT = tempfile.mkdtemp(prefix="nogit-", dir=TMP)    # git 저장소가 아닌 cwd
    CLI2 = lambda *args, **kw: subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "instr", *args], capture_output=True, text=True, cwd=NOGIT, env=kw.pop("env", pg.env()), **kw)
    p = CLI2("show", "--repo", URL, "instructions")
    check("CLI show --repo: git 밖에서도 DB 본문을 보인다(저장소·rev·DB 표시)", p.returncode == 0 and "v-db-only" in p.stdout and f"rev {rev_now}" in p.stdout and "공유 저장소(DB)" in p.stdout, p.stdout + p.stderr)
    p = CLI2("show", "--repo", URL + "-none")
    check("CLI show --repo: 지침이 없는 저장소는 안내만(오류 아님)", p.returncode == 0 and "지침 없음" in p.stderr, p.stdout + p.stderr)
    p = CLI2("set", "override", "--repo", URL, "--stdin", input="repo-set override\n")
    conn.commit()
    ov = ci.db_rows(conn, URL)["override"]
    check("CLI set --repo: DB 에 새 본문이 들어가고 rev 가 오른다(git 밖에서)", p.returncode == 0 and "올렸다" in p.stdout and ov["body"] == "repo-set override\n" and ov["rev"] == 2, p.stdout + p.stderr + str(ov))
    check("CLI set --repo: 로컬 캐시는 건드리지 않는다", (open(F1("instructions")).read(), json.dumps(ci.load_state(r1[0]), sort_keys=True)) == cache_before)
    p = CLI2("set", "instructions", "--repo", URL, "--stdin", "--expect-rev", "1", input="낡은 rev 로 쓰기\n")
    check("CLI set --repo --expect-rev: 낡은 rev 는 거부(종료 코드 1)", p.returncode == 1 and "바뀌었다" in p.stdout, p.stdout + p.stderr)
    p = CLI2("set", "instructions", "--stdin", input="repo 없이\n")
    check("CLI set(--repo 없이 git 밖): 실패하고 --repo 를 안내한다", p.returncode != 0 and "--repo" in (p.stdout + p.stderr), p.stdout + p.stderr)
    p = CLI2("edit", "instructions", "--repo", URL, stdin=subprocess.DEVNULL)
    check("CLI edit --repo: 대화형이 아니면 거부", p.returncode != 0 and "대화형" in (p.stdout + p.stderr), p.stdout + p.stderr)
    p = CLI2("show", "instructions")
    check("CLI show(--repo 없이 git 밖): 에러가 --repo 로 DB 만 볼 수 있다고 안내", p.returncode != 0 and "--repo" in (p.stdout + p.stderr), p.stdout + p.stderr)
finally:
    pg.stop()
    import shutil; shutil.rmtree(TMP, ignore_errors=True)
finish("instr")
