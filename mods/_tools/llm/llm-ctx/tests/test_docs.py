#!/usr/bin/env python3
"""ctx_docs 시험 — 저장소에 올리지 않는 프로젝트 문서(계획·QA·메모)의 공유 정본.
1부(순수·파일): 이름 검사·경로→이름·텍스트 읽기(이진·큰·빈 파일 건너뜀) — psycopg 없이 돈다.
2부(임시 Postgres): 만들기·수정·같음·낙관적 잠금·비밀 거부·상태·검색·import 멱등·CLI. psycopg·postgres 17 이 없으면 건너뛴다."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctx_docs as cd

TMP = tempfile.mkdtemp(prefix="docs-test-")

# ---------------------------------------------------------------- 1부: 순수
check("이름: 정상(슬래시 허용)", cd.valid_name("repo-restructure/README") is None)
for bad in ("", "  ", "/abs", "a/../b", "..", "x" * 301):
    check(f"이름 거부: {bad[:12]!r}", cd.valid_name(bad) is not None)
check("경로→이름: .md 만 뗀다", cd.name_from_path("/r/_plan/a/b.md", "/r/_plan") == "a/b")
check("경로→이름: 다른 확장자는 둔다", cd.name_from_path("/r/x/data.tsv", "/r/x") == "data.tsv")
check("경로→이름: 접두", cd.name_from_path("/r/x/a.md", "/r/x", "pfx/") == "pfx/a")
open(f"{TMP}/ok.md", "w").write("본문 한글\n")
open(f"{TMP}/empty.md", "w").close()
open(f"{TMP}/bin.png", "wb").write(b"\x89PNG\x00\x01")
open(f"{TMP}/latin.txt", "wb").write(b"\xff\xfe\xfa")
open(f"{TMP}/big.md", "w").write("x" * 50)
check("읽기: 텍스트", cd.read_text(f"{TMP}/ok.md") == ("본문 한글\n", None))
check("읽기: 빈 파일은 건너뜀", cd.read_text(f"{TMP}/empty.md")[0] is None and "빈" in cd.read_text(f"{TMP}/empty.md")[1])
check("읽기: NUL 이 있으면 이진", "이진" in (cd.read_text(f"{TMP}/bin.png")[1] or ""))
check("읽기: UTF-8 이 아니면 건너뜀", cd.read_text(f"{TMP}/latin.txt")[0] is None)
check("읽기: 한도 초과는 건너뜀", cd.read_text(f"{TMP}/big.md", max_bytes=10)[0] is None)
check("읽기: 없는 파일은 건너뜀", cd.read_text(f"{TMP}/nope")[0] is None)

# ---------------------------------------------------------------- 2부: DB
try:
    import psycopg  # noqa: F401
    import pgscratch
    pg = pgscratch.start()
except ImportError:
    pg = None
if not pg:
    print("psycopg/postgres 가 없어 2부(DB)를 건너뜀"); finish("docs(순수)")
try:
    os.environ.update(pg.env())
    import llm_ctx as cc
    URL = "https://github.com/test/proj"
    class Mask:
        def text(self, s): return s.replace("hunter2", "[protected]")
    conn = cc.connect()
    cd.ensure_schema(conn); cd.ensure_schema(conn)
    check("스키마 보장은 두 번 해도 안전(멱등)", True)

    code, msg, act = cd.put(conn, URL, "plan", "a/b", "v1\n", "hostA", masker=Mask())
    check("put: 새 문서는 rev 1·active", code == 0 and act == "created" and cd.get(conn, URL, "plan", "a/b")["rev"] == 1 and cd.get(conn, URL, "plan", "a/b")["status"] == "active", msg)
    code, msg, act = cd.put(conn, URL, "plan", "a/b", "v1\n", "hostA", masker=Mask())
    check("put: 같은 내용은 rev 를 올리지 않는다", code == 0 and act == "same" and cd.get(conn, URL, "plan", "a/b")["rev"] == 1, msg)
    code, msg, act = cd.put(conn, URL, "plan", "a/b", "v2\n", "hostB", masker=Mask(), expect_rev=1)
    d = cd.get(conn, URL, "plan", "a/b")
    check("put: 기대 rev 가 맞으면 갱신(rev 2·수정 머신 기록)", code == 0 and act == "updated" and d["rev"] == 2 and d["updated_host"] == "hostB" and d["body"] == "v2\n", msg)
    code, msg, act = cd.put(conn, URL, "plan", "a/b", "v3-stale\n", "hostA", masker=Mask(), expect_rev=1)
    check("put: 낡은 rev 는 거부하고 그대로 둔다", code == 1 and act is None and cd.get(conn, URL, "plan", "a/b")["body"] == "v2\n", msg)
    code, msg, act = cd.put(conn, URL, "plan", "secret", "key=hunter2\n", "hostA", masker=Mask())
    check("put: 등록된 비밀이 든 본문은 거부", code == 1 and cd.get(conn, URL, "plan", "secret") is None, msg)
    check("put: 빈 본문 거부", cd.put(conn, URL, "plan", "e", " \n", "h")[0] == 1)
    check("put: kind 검사", cd.put(conn, URL, "zzz", "x", "a", "h")[0] == 1)
    check("put: 이름 검사", cd.put(conn, URL, "plan", "../x", "a", "h")[0] == 1)
    check("put: status 검사", cd.put(conn, URL, "plan", "x", "a", "h", status="bogus")[0] == 1)
    check("put: 없는 문서에 rev 기대는 거부", cd.put(conn, URL, "plan", "nope", "a", "h", expect_rev=3)[0] == 1)
    code, msg, act = cd.put(conn, URL, "plan", "a/b", "v2\n", "hostC", status="done")
    check("put: 본문은 같고 상태만 바뀌면 상태만 갱신(rev 유지)", code == 0 and cd.get(conn, URL, "plan", "a/b")["status"] == "done" and cd.get(conn, URL, "plan", "a/b")["rev"] == 2, msg)
    check("같은 이름이어도 kind 가 다르면 별개 문서", cd.put(conn, URL, "qa", "a/b", "qa 본문\n", "h")[0] == 0 and cd.get(conn, URL, "plan", "a/b")["body"] == "v2\n")
    check("같은 이름이어도 저장소가 다르면 별개 문서", cd.put(conn, URL + "-2", "plan", "a/b", "다른 저장소\n", "h")[0] == 0 and cd.get(conn, URL, "plan", "a/b")["body"] == "v2\n")

    code, msg = cd.set_status(conn, URL, "plan", "a/b", "dropped", "hostA")
    check("상태 변경", code == 0 and cd.get(conn, URL, "plan", "a/b")["status"] == "dropped")
    check("상태 변경: 없는 문서", cd.set_status(conn, URL, "plan", "none", "done", "h")[0] == 1)
    check("상태 변경: 잘못된 값", cd.set_status(conn, URL, "plan", "a/b", "xx", "h")[0] == 1)
    rows = cd.list_docs(conn, URL)
    check("list: 이 저장소 문서만, kind·이름 순", [(r[0], r[1]) for r in rows] == [("plan", "a/b"), ("qa", "a/b")], str(rows))
    check("list: kind·status·접두 필터", len(cd.list_docs(conn, URL, kind="qa")) == 1 and len(cd.list_docs(conn, URL, status="dropped")) == 1 and len(cd.list_docs(conn, URL, prefix="a/")) == 2 and len(cd.list_docs(conn, URL, prefix="b")) == 0)
    check("search: 본문·이름 일치", [r[1] for r in cd.search(conn, URL, "qa 본문")] == ["a/b"] and cd.search(conn, URL, "없는말") == [])
    check("snippet: 앞뒤 문맥", "qa 본문" in cd.snippet("앞" * 100 + "qa 본문" + "뒤" * 100, "qa 본문") and cd.snippet("abc", "zzz") == "")
    code, msg = cd.remove(conn, URL, "qa", "a/b")
    check("remove", code == 0 and cd.get(conn, URL, "qa", "a/b") is None and cd.remove(conn, URL, "qa", "a/b")[0] == 1)
    conn.commit()

    # import: 폴더 → 이름 = base 기준 상대 경로, 멱등, 이진·빈 파일 건너뜀, 비밀 거부
    src = os.path.join(TMP, "src"); os.makedirs(os.path.join(src, "sub"))
    open(f"{src}/one.md", "w").write("하나\n"); open(f"{src}/sub/two.md", "w").write("둘\n")
    open(f"{src}/sub/img.png", "wb").write(b"\x00\x01"); open(f"{src}/sub/empty.md", "w").close(); open(f"{src}/leak.md", "w").write("pw=hunter2\n")
    files = sorted(os.path.join(r, n) for r, _, ns in os.walk(src) for n in ns)
    res = {n: r for _, n, r in cd.import_files(conn, URL, "qa", files, src, "hostA", masker=Mask(), prefix="imp")}
    check("import: 새 파일은 created, 이름은 접두+상대경로", res.get("imp/one") == "created" and res.get("imp/sub/two") == "created", str(res))
    check("import: 이진·빈 파일은 건너뜀", res["imp/sub/img.png"].startswith("건너뜀") and res["imp/sub/empty"].startswith("건너뜀"), str(res))
    check("import: 비밀이 든 파일은 거부(DB 에 없다)", res["imp/leak"].startswith("거부") and cd.get(conn, URL, "qa", "imp/leak") is None, str(res))
    check("import: 원본 경로를 기록", cd.get(conn, URL, "qa", "imp/one")["origin_path"] == os.path.abspath(f"{src}/one.md"))
    res2 = {n: r for _, n, r in cd.import_files(conn, URL, "qa", files, src, "hostA", masker=Mask(), prefix="imp")}
    check("import: 두 번째는 전부 same(멱등, rev 그대로)", res2["imp/one"] == "same" and cd.get(conn, URL, "qa", "imp/one")["rev"] == 1, str(res2))
    open(f"{src}/one.md", "w").write("하나 수정\n")
    res3 = {n: r for _, n, r in cd.import_files(conn, URL, "qa", files, src, "hostA", masker=Mask(), prefix="imp")}
    check("import: 바뀐 파일은 updated(rev 2)", res3["imp/one"] == "updated" and cd.get(conn, URL, "qa", "imp/one")["rev"] == 2, str(res3))
    dr = {n: r for _, n, r in cd.import_files(conn, URL, "qa", files, src, "hostA", masker=Mask(), prefix="imp2", dry_run=True)}
    check("import --dry-run: 쓰지 않는다", dr["imp2/one"] == "created" and cd.get(conn, URL, "qa", "imp2/one") is None, str(dr))
    conn.commit()

    # CLI(별도 프로세스)
    REPO = os.path.join(TMP, "repo"); os.makedirs(REPO)
    subprocess.run(["git", "init", "-q", REPO]); subprocess.run(["git", "-C", REPO, "remote", "add", "origin", "git@github.com:test/cli.git"])
    CLI = lambda *a, **kw: subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "doc", *a], capture_output=True, text=True, cwd=kw.pop("cwd", REPO), env=pg.env(), **kw)
    p = CLI("set", "note", "n1", "--stdin", input="CLI 본문\n")
    check("CLI set: 현재 저장소(ssh URL 정규화)에 만든다", p.returncode == 0 and "만들었다" in p.stdout and cd.get(conn, "https://github.com/test/cli", "note", "n1") is not None, p.stdout + p.stderr)
    p = CLI("show", "note", "n1")
    check("CLI show: 머리 한 줄 + 본문", p.returncode == 0 and "note/n1" in p.stdout and "rev 1" in p.stdout and "CLI 본문" in p.stdout, p.stdout + p.stderr)
    p = CLI("show", "note", "n1", "--body-only")
    check("CLI show --body-only: 본문만", p.stdout == "CLI 본문\n", repr(p.stdout))
    p = CLI("set", "note", "nonl", "--stdin", input="끝 줄바꿈 없음")
    p = CLI("show", "note", "nonl", "--body-only")
    check("CLI show --body-only: 끝 줄바꿈이 없는 본문도 바이트 그대로(덧붙이지 않는다)", p.stdout == "끝 줄바꿈 없음", repr(p.stdout))
    p = CLI("show", "note", "zzz")
    check("CLI show: 없으면 종료 코드 1", p.returncode == 1 and "없다" in p.stderr, p.stdout + p.stderr)
    p = CLI("set", "note", "n1", "--stdin", "--expect-rev", "9", input="x\n")
    check("CLI set --expect-rev: 어긋나면 종료 코드 1", p.returncode == 1 and "바뀌었다" in p.stdout, p.stdout + p.stderr)
    p = CLI("list")
    check("CLI list", "note/n1: active · rev 1" in p.stdout, p.stdout + p.stderr)
    p = CLI("status", "note", "n1", "done"); p2 = CLI("list", "note", "--status", "done")
    check("CLI status → list --status", p.returncode == 0 and "note/n1" in p2.stdout, p.stdout + p2.stdout)
    p = CLI("search", "본문")
    check("CLI search", "note/n1" in p.stdout and "CLI 본문" in p.stdout, p.stdout + p.stderr)
    p = CLI("rm", "note", "n1")
    check("CLI rm: --yes 없이는 지우지 않는다", p.returncode == 1 and cd.get(conn, "https://github.com/test/cli", "note", "n1") is not None, p.stdout)
    p = CLI("rm", "note", "n1", "--yes")
    check("CLI rm --yes", p.returncode == 0 and cd.get(conn, "https://github.com/test/cli", "note", "n1") is None, p.stdout + p.stderr)
    import ctx_secrets as cs
    cs.add_secret(conn, "tpw", "literal", "hunter2-secret-xyz")      # 등록표에 실제로 넣어 CLI 가 등록표를 읽어 거부하는지 본다
    open(f"{src}/leak.md", "w").write("pw=hunter2-secret-xyz\n")
    p = CLI("import", "plan", src, "--base", src, "--prefix", "p", "--status", "unknown", "-v")
    check("CLI import: 폴더 재귀·상태 지정·요약(등록된 비밀 든 파일은 거부)", p.returncode == 1 and "거부 1" in p.stdout and "created 2" in p.stdout and cd.get(conn, "https://github.com/test/cli", "plan", "p/sub/two")["status"] == "unknown"
          and cd.get(conn, "https://github.com/test/cli", "plan", "p/leak") is None, p.stdout + p.stderr)
    p = CLI("set", "note", "n9", "--stdin", input="값 hunter2-secret-xyz 포함\n")
    check("CLI set: 등록표의 비밀이 든 본문은 거부", p.returncode == 1 and cd.get(conn, "https://github.com/test/cli", "note", "n9") is None, p.stdout + p.stderr)
    p = CLI("list", cwd=tempfile.gettempdir())
    check("CLI: git 저장소 밖이면 --repo 를 안내", p.returncode != 0 and "--repo" in (p.stdout + p.stderr), p.stdout + p.stderr)
    p = CLI("list", "--repo", URL, cwd=tempfile.gettempdir())
    check("CLI list --repo: git 밖에서도 된다", p.returncode == 0 and "plan/a/b" in p.stdout, p.stdout + p.stderr)
finally:
    pg.stop()
    import shutil; shutil.rmtree(TMP, ignore_errors=True)
finish("docs")
