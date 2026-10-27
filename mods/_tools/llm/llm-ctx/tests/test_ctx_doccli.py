#!/usr/bin/env python3
"""ctx doc CLI·훅 시험 — 임시 Postgres(비밀 검사·옛 문서 이관)와 임시 문서 저장소. psycopg·postgres 17 이 없으면 건너뛴다.
`donghans ctx doc list|read|path|find|propose|status|init|import-db` 를 실제 프로세스로 돌리고, ctx_toolhook(PreToolUse 차단·PostToolUse 알림)과 SessionStart·SessionEnd 훅을 확인한다."""
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
try:
    import psycopg  # noqa: F401
    import pgscratch
    pg = pgscratch.start()
except ImportError:
    pg = None
if not pg:
    print("psycopg/postgres 가 없어 건너뜀"); finish("ctx doc CLI")
import ctx_store as st

TMP = tempfile.mkdtemp(prefix="doccli-test-")
STORE, VIEWS = f"{TMP}/ctx", f"{TMP}/views"
URL = "https://github.com/test/proj"
os.makedirs(STORE)
open(f"{STORE}/manifest.toml", "w").write(f'[projects.proj]\nrepo_url = "{URL}"\nowner = "personal"\n')
WORK = f"{TMP}/work"; os.makedirs(WORK)
subprocess.run(["git", "init", "-q", WORK], check=True); subprocess.run(["git", "-C", WORK, "remote", "add", "origin", URL + ".git"], check=True)
NOGIT = f"{TMP}/nogit"; os.makedirs(NOGIT)

BASE = pg.env(CTX_STORE_DIR=STORE, CTX_VIEWS_DIR=VIEWS, CTX_SYNC_INLINE="1", CTX_PROPOSE_WAIT="5")
for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID"):
    BASE.pop(k, None)


def run(*args, sid=None, cwd=WORK, stdin=None, env=None):
    e = dict(BASE, **(env or {}))
    if sid:
        e["CLAUDE_CODE_SESSION_ID"] = sid
    r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "doc", *args], capture_output=True, text=True, input=stdin, cwd=cwd, env=e, timeout=60)
    return r.returncode, r.stdout, r.stderr


# 비밀 등록
import llm_ctx as cc
os.environ.update(pg.env())
conn = cc.connect()
import ctx_secrets as csec
csec.ensure_schema(conn)
csec.add_secret(conn, "TESTPW", "literal", "hunter2")
conn.commit()

A, B = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"

rc, out, err = run("list", sid=A)
check("list: 저장소 git 의 repo_url 로 프로젝트를 찾는다(--project 없이)", rc == 0 and "프로젝트 proj" in out and "(문서 없음)" in out, out + err)
rc, out, err = run("list", sid=A, cwd=NOGIT)
check("list: 프로젝트를 못 찾으면 추측하지 않고 --project 를 요구한다", rc != 0 and "--project" in (out + err), out + err)
rc, out, err = run("list", "--project", "ghost", sid=A, cwd=NOGIT)
check("list: 없는 프로젝트 이름은 실패하고 등록된 목록을 알려 준다", rc != 0 and "proj" in (out + err))
rc, out, err = run("list", "--project", "proj", sid=A, cwd=NOGIT)
check("list: --project 로 지정하면 어느 폴더에서나 된다", rc == 0, out + err)

# 새 문서 제안 (inline 동기화)
rc, out, err = run("propose", "plan", "a/first", "--stdin", sid=A, stdin="첫 계획\n내용\n")
check("propose: 새 문서가 반영된다(커밋)", rc == 0 and "반영했다" in out and "커밋" in out, out + err)
check("propose: 저장소에 파일이 생겼다", os.path.isfile(f"{STORE}/proj/plan/a/first.md"))
rc, out, err = run("list", sid=A)
check("list: 새 문서가 보인다", "plan/a/first" in out and "active" in out, out)
rc, out, err = run("read", "plan", "a/first", sid=A)
check("read: 머리 한 줄 + 본문", rc == 0 and out.startswith("# proj/plan/a/first") and "첫 계획" in out, out)
rc, out, err = run("read", "plan", "a/first", "--body-only", sid=A)
check("read --body-only: 본문만(머리말·머리 줄 없음)", out == "첫 계획\n내용\n", repr(out))
rc, out, err = run("read", "plan", "none", sid=A)
check("read: 없는 문서", rc == 1 and "없다" in err)
check("read: 읽은 판이 이 세션의 뷰에 기록된다", st.base_hash_for(VIEWS, A, "proj", "plan", "a/first") is not None)

# 읽지 않은 세션의 덮어쓰기는 거부
rc, out, err = run("propose", "plan", "a/first", "--stdin", sid=B, stdin="몰래\n")
check("propose: 읽지 않고 덮어쓰기는 거부", rc == 1 and "먼저" in err, out + err)
# 읽고 고치기
rc, out, err = run("read", "plan", "a/first", "--body-only", sid=B)
rc, out, err = run("propose", "plan", "a/first", "--stdin", sid=B, stdin="B 가 고침\n")
check("propose: 읽은 뒤에는 수정이 반영된다", rc == 0 and "반영했다" in out, out + err)
rc, out, err = run("read", "plan", "a/first", "--body-only", sid=B)
check("propose 뒤 읽으면 새 본문", out == "B 가 고침\n", out)
check("propose: 자기 제안 반영분을 직접 수정으로 오인하지 않는다(뷰 기준 해시 갱신)", st.modified_in_view(f"{VIEWS}/{B}") == [])
# 충돌: A 는 낡은 판으로 제안
rc, out, err = run("propose", "plan", "a/first", "--stdin", sid=A, stdin="A 의 늦은 수정\n")
check("propose: 읽은 뒤 다른 세션이 고쳤으면 충돌로 멈춘다", rc == 1 and "바뀌었다" in out, out + err)
check("propose: 충돌이면 문서는 그대로", st.read_doc(STORE, "proj", "plan", "a/first")["body"] == "B 가 고침\n")
rc, out, err = run("status", sid=A)
check("status: 이 세션의 충돌 1·알림", "충돌 1" in out and "conflict" in out, out)
rc, out, err = run("status", sid=B)
check("status: 다른 세션은 충돌 0", "충돌 0" in out, out)

# 비밀 거부
rc, out, err = run("read", "plan", "a/first", "--body-only", sid=A)
rc, out, err = run("propose", "plan", "a/first", "--stdin", sid=A, stdin="비밀번호 hunter2\n")
check("propose: 등록된 비밀이 든 본문은 거부", rc == 1 and "비밀" in out and "hunter2" not in out + err, out + err)
check("propose: 거부됐으니 문서는 그대로", "hunter2" not in open(f"{STORE}/proj/plan/a/first.md").read())

# 뷰·검색
for i in range(3):
    run("propose", "note", f"m/n{i}", "--stdin", sid=A, stdin=f"메모 {i} 검색어-별\n")
rc, out, err = run("path", sid=A)
root = out.strip().splitlines()[0]
check("path: 뷰 경로를 첫 줄에 출력(stdout)하고 안내는 stderr", rc == 0 and root == f"{VIEWS}/{A}" and "읽기 전용" in err, out + err)
check("path: 문서가 뷰에 있다", os.path.isfile(f"{root}/proj/note/m/n1.md") and os.path.isfile(f"{root}/proj/plan/a/first.md"))
check("path: 첫 사용 안내에 Monitor 로 watch 를 띄우라고 한다", "ctx doc watch" in err and "Monitor" in err, err)
rc, out, err = run("path", "note", sid=A)
check("path: 종류를 주면 그 종류만 갱신(이미 있는 것은 그대로)", rc == 0)
rc, out, err = run("find", "검색어-별", sid=A)
check("find: 본문 검색", rc == 0 and out.count("note/m/n") == 3, out)
rc, out, err = run("find", "없는말없는말", sid=A)
check("find: 없으면 안내", "(일치하는 문서 없음)" in out)

# 직접 수정 → 알림(도구 훅)
vp = f"{root}/proj/note/m/n0.md"
hook_in = lambda ev, **k: json.dumps({"session_id": A, "hook_event_name": ev, **k})
th = lambda ev, payload: subprocess.run([sys.executable, os.path.join(ROOT, "ctx_toolhook.py"), ev], input=payload, capture_output=True, text=True, env=BASE)
r = th("PostToolUse", hook_in("PostToolUse", tool_name="Bash"))
check("PostToolUse: 수정이 없으면 아무 출력도 없다", r.returncode == 0 and r.stdout.strip() == "", r.stdout)
os.chmod(vp, 0o644); open(vp, "a").write("직접 고침\n")
r = th("PostToolUse", hook_in("PostToolUse", tool_name="Bash"))
j = json.loads(r.stdout) if r.stdout.strip() else {}
check("PostToolUse: 직접 수정이 있으면 additionalContext 로 알린다", "n0.md" in j.get("hookSpecificOutput", {}).get("additionalContext", ""), r.stdout)
r = th("PostToolUse", hook_in("PostToolUse", tool_name="Bash"))
check("PostToolUse: 같은 수정은 두 번 알리지 않는다", r.stdout.strip() == "", r.stdout)
check("PostToolUse: 다른 세션의 뷰에는 영향 없다", th("PostToolUse", json.dumps({"session_id": B, "tool_name": "Bash"})).stdout.strip() == "")

# 도구 훅: 차단
deny = lambda path, tool="Edit": json.loads((th("PreToolUse", hook_in("PreToolUse", tool_name=tool, tool_input={"file_path": path})).stdout or "{}") or "{}")
d = deny(vp)
check("PreToolUse: 뷰 파일의 Edit 를 막고 propose 를 안내", d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny" and "propose" in d["hookSpecificOutput"]["permissionDecisionReason"], d)
check("PreToolUse: Write 도 막는다", deny(vp, "Write").get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
check("PreToolUse: 저장소 파일도 막는다", deny(f"{STORE}/proj/plan/a/first.md").get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
check("PreToolUse: 다른 경로는 막지 않는다", deny(f"{TMP}/work/x.py") == {})
check("PreToolUse: Read 는 막지 않는다", deny(vp, "Read") == {})
check("PreToolUse: Bash 는 막지 않는다(문자열 패턴은 오탐·미탐)", json.loads(th("PreToolUse", hook_in("PreToolUse", tool_name="Bash", tool_input={"command": f"echo x >> {vp}"})).stdout or "{}") == {})
check("훅: 깨진 입력도 조용히 통과", th("PreToolUse", "not json").returncode == 0)
sym = f"{TMP}/link.md"; os.symlink(vp, sym)
check("PreToolUse: 심볼릭 링크로 돌아가도 막는다(realpath)", deny(sym).get("hookSpecificOutput", {}).get("permissionDecision") == "deny")

# path 를 다시 부르면 직접 수정은 되돌려지고 보관된다
rc, out, err = run("path", sid=A)
check("path: 직접 고친 뷰 파일은 원본으로 되돌리고 보관 사실을 알린다", rc == 0 and "되돌렸다" in err and "메모 0" in open(vp).read() and "직접 고침" not in open(vp).read(), err)

# 사람 전용
rc, out, err = run("init", "newproj", sid=A)
check("init: 사람이 아니면(TTY 없음) 거부 — 매니페스트의 remote 는 외부 전송 경로라서", rc != 0 and "사람이" in (out + err), out + err)
check("init: 거부됐으니 매니페스트는 그대로", "newproj" not in open(f"{STORE}/manifest.toml").read())

# 훅: SessionStart 안내·SessionEnd 표식
HOOK_ENV = dict(BASE, CLAUDE_CTX_HOST="testhost")
r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionStart"], input=json.dumps({"session_id": A, "cwd": WORK, "hook_event_name": "SessionStart"}), capture_output=True, text=True, env=HOOK_ENV, cwd=WORK, timeout=60)
j = json.loads(r.stdout) if r.stdout.strip() else {}
check("SessionStart 훅: 문서는 ctx doc 로 읽고 propose 로 고친다는 안내가 나간다", "ctx doc" in j.get("hookSpecificOutput", {}).get("additionalContext", "") and "propose" in j["hookSpecificOutput"]["additionalContext"], r.stdout + r.stderr)
check("SessionStart 훅: 출력은 JSON 하나", r.stdout.strip().count("\n") == 0, r.stdout)
r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionEnd"], input=json.dumps({"session_id": A, "cwd": WORK, "hook_event_name": "SessionEnd"}), capture_output=True, text=True, env=HOOK_ENV, cwd=WORK, timeout=60)
check("SessionEnd 훅: 뷰에 종료 표식을 남긴다", os.path.exists(f"{VIEWS}/{A}/{st.ENDED_FILE}"), r.stderr)
bad_env = dict(HOOK_ENV, CLAUDE_CTX_DSN="host=/nonexistent dbname=x user=x")
r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "hook", "SessionStart"], input=json.dumps({"session_id": B, "cwd": WORK, "hook_event_name": "SessionStart"}), capture_output=True, text=True, env=bad_env, cwd=WORK, timeout=60)
j = json.loads(r.stdout) if r.stdout.strip() else {}
check("SessionStart 훅: DB 에 못 붙어도 문서 안내는 나간다(입력을 막지도 않는다)", r.returncode == 0 and "ctx doc" in j.get("hookSpecificOutput", {}).get("additionalContext", ""), r.stdout + r.stderr)

# 옛 DB 문서 이관
import ctx_docs as cd
cd.ensure_schema(conn)
cd.put(conn, URL, "plan", "old/p1", "옛 계획 본문\n끝\n", "hostX", status="done", origin_path="/x/p1.md")
cd.put(conn, URL, "note", "old/한글 이름", "---\nname: 자기 머리말\n---\n본문\n", "hostX")
cd.put(conn, URL + "-other", "plan", "skipme", "다른 저장소\n", "hostX")
conn.commit()
rc, out, err = run("import-db", "--dry-run", sid=A)
check("import-db --dry-run: 파일을 만들지 않는다", rc == 0 and "created 2" in out and not os.path.exists(f"{STORE}/proj/plan/old/p1.md"), out + err)
rc, out, err = run("import-db", sid=A)
check("import-db: 문서 2개를 내보내고 매니페스트에 없는 저장소는 건너뛴다", rc == 0 and "created 2" in out and "skipped 1" in out and "대조 실패 0" in out, out + err)
d = st.read_doc(STORE, "proj", "plan", "old/p1")
check("import-db: 본문은 바이트 그대로, 메타(status·원본 경로·이관 출처)는 머리말로", d["body"] == "옛 계획 본문\n끝\n" and d["meta"]["status"] == "done" and d["meta"]["origin_path"] == "/x/p1.md" and "이관" in d["meta"]["provenance"], d["meta"])
d2 = st.read_doc(STORE, "proj", "note", "old/한글 이름")
check("import-db: 본문의 자기 --- 머리말과 한글 이름도 그대로", d2 and d2["body"] == "---\nname: 자기 머리말\n---\n본문\n")
check("import-db: 한 번의 커밋으로 저장소에 기록", "DB(project_docs)에서 문서 이관" in subprocess.run(["git", "-C", f"{STORE}/proj", "log", "--oneline"], capture_output=True, text=True).stdout)
rc, out, err = run("import-db", sid=A)
check("import-db: 두 번째는 멱등(모두 same)", rc == 0 and "same 2" in out and "created 0" in out, out + err)
open(f"{STORE}/proj/plan/old/p1.md", "w").write(st.compose({}, "나중에 사람이 고친 본문\n"))
rc, out, err = run("import-db", sid=A)
check("import-db: 이미 다른 내용이 있으면 덮어쓰지 않고 실패로 알린다", rc == 1 and "어긋남" in err, out + err)
check("import-db: 어긋난 파일은 그대로", st.read_doc(STORE, "proj", "plan", "old/p1")["body"] == "나중에 사람이 고친 본문\n")

pg.stop(); shutil.rmtree(TMP, ignore_errors=True)
sys.exit(finish("ctx doc CLI"))
