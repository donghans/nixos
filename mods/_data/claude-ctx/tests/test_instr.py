#!/usr/bin/env python3
"""ctx_instr 시험 — 프로젝트별 지침의 공유 정본 동기화.
1부(순수·파일): 판정표 plan · git 루트/워크트리 · .git/info/exclude 멱등 — psycopg 없이 돈다.
2부(임시 Postgres): 두 「기기」(같은 저장소 URL, 다른 체크아웃)에서 채택→갱신→앞섬→충돌→강제, 비밀 거부, 훅(SessionStart) 실행. psycopg·postgres 17 이 없으면 건너뛴다."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
check, finish = checker()
import ctx_instr as ci

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
    import claude_ctx as cc
    URL = "https://github.com/test/proj"
    class Mask:   # 등록된 비밀 값 하나를 가정한 치환기
        def text(self, s): return s.replace("hunter2", "[protected]")
    conn = cc.connect()
    m2 = mkrepo("m2")     # 같은 저장소 URL 의 다른 체크아웃(= 다른 기기)
    r1, r2 = ci.roots(m1), ci.roots(m2)
    F1 = lambda n: ci.local_path(m1, n); F2 = lambda n: ci.local_path(m2, n)
    os.makedirs(os.path.join(m1, ".claude")); open(F1("instructions"), "w").write("v1\n")

    n = ci.sync(conn, URL, r1[0], r1[1], "hostA")
    check("A: DB 가 비었고 로컬이 있으면 첫 채택(rev 1)", [k for _, k, _ in n] == ["adopted"] and ci.db_rows(conn, URL)["instructions"]["rev"] == 1, str(n))
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 로컬이 없으면 DB 본문으로 채운다", open(F2("instructions")).read() == "v1\n" and [k for _, k, _ in n] == ["updated"], str(n))
    check("B: .git/info/exclude 도 맞춘다", all(l in open(os.path.join(r2[1], "info", "exclude")).read() for l in ci.EXCLUDE))
    check("B: 두 번째 sync 는 알릴 것이 없다", ci.sync(conn, URL, r2[0], r2[1], "hostB") == [])

    open(F1("instructions"), "w").write("v2\n")
    code, msg = ci.push(conn, URL, r1[0], "instructions", "hostA", masker=Mask())
    check("A: 고쳐서 올리면 rev 2", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 2, msg)
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 손대지 않았으면 다음 세션에 rev 2 로 갱신", open(F2("instructions")).read() == "v2\n" and [k for _, k, _ in n] == ["updated"], str(n))

    open(F2("instructions"), "w").write("v3-local-B\n")
    n = ci.sync(conn, URL, r2[0], r2[1], "hostB")
    check("B: 로컬만 고치면 앞섬 — 파일도 DB 도 그대로", [k for _, k, _ in n] == ["ahead"] and open(F2("instructions")).read() == "v3-local-B\n" and ci.db_rows(conn, URL)["instructions"]["body"] == "v2\n", str(n))
    code, msg = ci.push(conn, URL, r2[0], "instructions", "hostB", masker=Mask())
    check("B: 명시적 push 로 rev 3", code == 0 and ci.db_rows(conn, URL)["instructions"]["rev"] == 3, msg)

    open(F1("instructions"), "w").write("v4-local-A\n")      # A 는 rev 2 를 본 상태에서 고친다 — B 가 rev 3 을 올린 뒤
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

    open(F1("override"), "w").write("key=hunter2\n")
    code, msg = ci.push(conn, URL, r1[0], "override", "hostA", masker=Mask())
    check("등록된 비밀이 든 본문은 올리지 않는다", code == 1 and "override" not in ci.db_rows(conn, URL), msg)

    # 낙관적 잠금: 읽은 rev 가 낡았으면 UPDATE 가 0행
    check("rev 가 어긋난 UPDATE 는 거부(None)", ci._update(conn, URL, "instructions", "zzz", "hostC", expect_rev=1) is None)

    # 훅 end-to-end: 같은 URL 의 세 번째 체크아웃, 파일 없음 → SessionStart 가 채우고 additionalContext 를 낸다
    m3 = mkrepo("m3"); conn.commit()
    p = subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-1", "cwd": m3, "hook_event_name": "SessionStart"}), env=pg.env())
    out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    check("훅: 지침 파일을 만들고 짧은 알림만 낸다(본문 주입 없음)",
          p.returncode == 0 and open(ci.local_path(m3, "instructions")).read() == "v4-local-A\n"
          and "공유 저장소" in out.get("hookSpecificOutput", {}).get("additionalContext", "") and "v4-local-A" not in p.stdout, p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-2", "cwd": m3, "hook_event_name": "SessionStart"}), env=pg.env())
    check("훅: 바뀐 것이 없으면 아무것도 출력하지 않는다", p.returncode == 0 and p.stdout.strip() == "", p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), "ctx", "hook", "SessionStart"], capture_output=True, text=True,
                       input=json.dumps({"session_id": "s-instr-3", "cwd": tempfile.gettempdir()}), env=pg.env())
    check("훅: git 저장소가 아닌 cwd 는 조용히 통과", p.returncode == 0 and p.stdout.strip() == "", p.stdout + p.stderr)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), "instr", "list"], capture_output=True, text=True, cwd=m3, env=pg.env())
    check("CLI instr list", "instructions: rev 4" in p.stdout, p.stdout + p.stderr)
finally:
    pg.stop()
    import shutil; shutil.rmtree(TMP, ignore_errors=True)
finish("instr")
