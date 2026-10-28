#!/usr/bin/env python3
"""ctx doc CLI·훅 시험 — 임시 Postgres(비밀 검사)와 임시 문서 저장소. psycopg·postgres 17 이 없으면 건너뛴다.
`donghans ctx doc list|read|path|find|propose|status|init` 를 실제 프로세스로 돌리고, ctx_toolhook(PreToolUse 차단·PostToolUse 알림)과 SessionStart·SessionEnd 훅을 확인한다."""
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


# push: 매니페스트에 remote 가 있는 프로젝트만, push 직전 비밀 검사(등록된 비밀이 든 파일이 있으면 거부)
BARE = f"{TMP}/bare.git"
subprocess.run(["git", "init", "-q", "--bare", BARE], check=True)
open(f"{STORE}/manifest.toml", "a").write(f'\n[projects.pushy]\nrepo_url = "https://github.com/test/pushy"\nremote = "{BARE}"\n')
rc, out, err = run("propose", "note", "p1", "--stdin", "--project", "pushy", sid=A, stdin="푸시 시험 문서\n")
check("push: 제안이 반영된다(원격이 있어도 propose 는 push 하지 않는다)", rc == 0 and "반영했다" in out, out + err)
check("push: propose 만으로는 원격이 비어 있다", subprocess.run(["git", "-C", BARE, "rev-list", "--all", "--count"], capture_output=True, text=True).stdout.strip() == "0")
rc, out, err = run("sync", "--push", sid=A)
check("push: sync --push 가 remote 가 있는 프로젝트만 보낸다", rc == 0 and "push pushy: ok" in out and "push proj" not in out, out + err)
check("push: 원격에 커밋이 올라갔다", subprocess.run(["git", "-C", BARE, "rev-list", "--all", "--count"], capture_output=True, text=True).stdout.strip() != "0")
open(f"{STORE}/pushy/note/leak.md", "w").write(st.compose({}, "비밀번호 hunter2 가 새었다\n"))
st.commit_file(STORE, "pushy", "note/leak.md", "leak")
before = subprocess.run(["git", "-C", BARE, "rev-list", "--all", "--count"], capture_output=True, text=True).stdout.strip()
rc, out, err = run("sync", "--push", sid=A)
check("push: 추적 파일에 등록된 비밀이 있으면 push 하지 않는다", "못 함" in out and "leak.md" in out, out + err)
check("push: 거부됐으니 원격은 그대로", subprocess.run(["git", "-C", BARE, "rev-list", "--all", "--count"], capture_output=True, text=True).stdout.strip() == before)

# 파편화 정리: import-docs · import-files · files · audit · 무시 경로 Write 안내
IMP = f"{TMP}/imp"; os.makedirs(f"{IMP}/qa/e"); os.makedirs(f"{IMP}/.draft")
open(f"{IMP}/a.md", "w").write("반입할 문서 A\n"); open(f"{IMP}/qa/e/b.md", "w").write("QA 문서 B\n"); open(f"{IMP}/.draft/c.md", "w").write("숨김 폴더 문서\n")
open(f"{IMP}/sec.md", "w").write("계정 비밀번호 적힘\n"); open(f"{IMP}/data.json", "w").write('{"v": 1}\n'); open(f"{IMP}/shot.png", "wb").write(b"\x89PNG")
rc, out, err = run("import-docs", IMP, "--origin-label", "docs", "--dry-run", sid=A)
check("import-docs: dry-run 은 쓰지 않고 목록만(비밀 패턴 문서는 보류)", rc == 0 and "반영할 것 3" in out and "보류 1" in out and "sec.md" in out and not os.path.exists(f"{STORE}/proj/note/local/a.md"), out + err)
rc, out, err = run("import-docs", IMP, "--origin-label", "docs", "--manifest", f"{TMP}/m.tsv", sid=A)
check("import-docs: 반영(qa/ 는 qa 종류, 숨김 폴더 점은 뗀다)", rc == 0 and os.path.isfile(f"{STORE}/proj/note/local/a.md") and os.path.isfile(f"{STORE}/proj/qa/local/qa/e/b.md") and os.path.isfile(f"{STORE}/proj/note/local/draft/c.md"), out + err)
h, body = st.split_header(open(f"{STORE}/proj/note/local/a.md").read())
check("import-docs: 본문 바이트 그대로 + origin_path 머리말", body == "반입할 문서 A\n" and h["origin_path"] == "docs/a.md" and "이관" in h["provenance"], h)
check("import-docs: 목록 파일", "held\tsec.md" in open(f"{TMP}/m.tsv").read())
rc, out, err = run("import-docs", IMP, "--origin-label", "docs", sid=A)
check("import-docs: 다시 해도 이미 있음(멱등)", rc == 0 and "반영 0" in out and "이미 있음 3" in out, out + err)
rc, out, err = run("import-files", IMP, "--to", "imp", sid=A, cwd=WORK, env={"CTX_ALLOW_FILES_WRITE": "0"})
check("import-files: 서버 호스트가 아니면 거부(동기화 담당 없음)", rc != 0 and "서버 호스트" in (out + err), out + err)
rc, out, err = run("import-files", IMP, "--to", "imp", sid=A, env={"CTX_ALLOW_FILES_WRITE": "1"})
check("import-files: json 만 복사(md 는 .md 도 텍스트라 같이 — 이미지는 저장 안 함)", rc == 0 and os.path.isfile(f"{STORE}/proj/files/imp/data.json") and not os.path.exists(f"{STORE}/proj/files/imp/shot.png") and "스크린샷(저장 안 함) 1" in out, out + err)
rc, out, err = run("files", "imp", sid=A)
check("files: 목록", rc == 0 and "imp/data.json" in out, out + err)
check("files: 바깥 저장소는 files 를 추적하지 않는다", "files/" not in subprocess.run(["git", "-C", f"{STORE}/proj", "ls-files"], capture_output=True, text=True).stdout)
PROJ = f"{TMP}/projwork"; os.makedirs(f"{PROJ}/docs")
subprocess.run(["git", "init", "-q", PROJ], check=True); open(f"{PROJ}/.gitignore", "w").write("/docs/\n")
open(f"{PROJ}/docs/new.md", "w").write("아직 ctx 에 없는 문서\n")
rc, out, err = run("audit", "--project", "proj", "--root", PROJ, sid=A)
check("audit: ctx 에 없는 파일이 있으면 종료 코드 2 와 안내", rc == 2 and "docs/new.md" in out and "import-docs" in out, out + err)
os.remove(f"{PROJ}/docs/new.md")
rc, out, err = run("audit", "--project", "proj", "--root", PROJ, sid=A)
check("audit: 없으면 0", rc == 0 and "없음 0" in out, out + err)

# 무시 경로에 Write → 안내(차단하지 않음, 폴더당 한 번)
os.makedirs(f"{PROJ}/docs/sub", exist_ok=True)
w1 = {"session_id": A, "tool_name": "Write", "tool_input": {"file_path": f"{PROJ}/docs/sub/r.md"}}
r = th("PostToolUse", json.dumps(w1)); j = json.loads(r.stdout) if r.stdout.strip() else {}
check("PostToolUse: git 이 무시하는 경로에 Write 하면 ctx 로 두라고 안내(차단 아님)", "ctx doc" in j.get("hookSpecificOutput", {}).get("additionalContext", "") and "permissionDecision" not in r.stdout, r.stdout)
check("PostToolUse: 같은 폴더는 두 번 안내하지 않는다", th("PostToolUse", json.dumps(w1)).stdout.strip() == "")
w2 = {"session_id": A, "tool_name": "Write", "tool_input": {"file_path": f"{PROJ}/tracked.md"}}
check("PostToolUse: 추적되는(무시되지 않는) 경로는 안내하지 않는다", th("PostToolUse", json.dumps(w2)).stdout.strip() == "")
w3 = {"session_id": A, "tool_name": "Write", "tool_input": {"file_path": f"{TMP}/outside.md"}}
check("PostToolUse: git 저장소 밖은 안내하지 않는다", th("PostToolUse", json.dumps(w3)).stdout.strip() == "")

pg.stop(); shutil.rmtree(TMP, ignore_errors=True)
sys.exit(finish("ctx doc CLI"))
