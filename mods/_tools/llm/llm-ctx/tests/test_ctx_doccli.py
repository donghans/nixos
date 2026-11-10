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
mp = f"{VIEWS}/{A}/msg/aaaaaaaa-0000-0000-0000-000000000001.txt"
d = deny(mp, "Write")
rsn = d.get("hookSpecificOutput", {}).get("permissionReason", d.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))
check("PreToolUse(P1b): msg/ 파일도 막고, propose 가 아니라 ctx msg 재실행을 안내", d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny" and "ctx msg" in rsn and "propose" not in rsn, d)
check("PreToolUse(P1b): msg/ 가 아닌 뷰 경로는 여전히 propose 안내", "propose" in deny(f"{root}/proj/note/m/msg.md")["hookSpecificOutput"]["permissionDecisionReason"])
check("PreToolUse: Read 는 막지 않는다", deny(vp, "Read") == {})
check("PreToolUse: Bash 는 막지 않는다(문자열 패턴은 오탐·미탐)", json.loads(th("PreToolUse", hook_in("PreToolUse", tool_name="Bash", tool_input={"command": f"echo x >> {vp}"})).stdout or "{}") == {})
check("훅: 깨진 입력도 조용히 통과", th("PreToolUse", "not json").returncode == 0)
sym = f"{TMP}/link.md"; os.symlink(vp, sym)
check("PreToolUse: 심볼릭 링크로 돌아가도 막는다(realpath)", deny(sym).get("hookSpecificOutput", {}).get("permissionDecision") == "deny")

# path 를 다시 부르면 직접 수정은 되돌려지고 보관된다
rc, out, err = run("path", sid=A)
check("path: 직접 고친 뷰 파일은 원본으로 되돌리고 보관 사실을 알린다", rc == 0 and "되돌렸다" in err and "메모 0" in open(vp).read() and "직접 고침" not in open(vp).read(), err)

# init: 사람 확인은 하네스 ask 규칙이 강제하므로 CLI 자체는 TTY 를 요구하지 않는다
rc, out, err = run("init", "newproj", sid=A)
check("init: TTY 없이도 실행된다(확인은 하네스 ask 규칙의 몫)", rc == 0 and "newproj" in open(f"{STORE}/manifest.toml").read(), out + err)
rc, out, err = run("init", "newproj", sid=A)
check("init: 다시 하면 이미 등록(멱등)", rc == 0 and "이미 등록" in out, out + err)
check("ask 규칙: init·delete·import-held 가 llm-cli.nix 에 있다", all(f'"Bash(donghans ctx doc {c}:*)"' in open(os.path.join(ROOT, "../../../devel/apps/llm-cli.nix")).read() for c in ("init", "delete", "import-held")))

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
open(f"{IMP}/sec.md", "w").write("계정 비밀번호: abc12345\n"); open(f"{IMP}/data.json", "w").write('{"v": 1}\n'); open(f"{IMP}/shot.png", "wb").write(b"\x89PNG")
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
open(f"{IMP}/blob.bin", "wb").write(b"\x00\x01bin")
rc, out, err = run("import-files", IMP, "--to", "imp", sid=A, env={"CTX_ALLOW_FILES_WRITE": "1"})
check("import-files: 검사 불가 blob.bin 은 보류", "보류: blob.bin" in out and not os.path.exists(f"{STORE}/proj/files/imp/blob.bin"), out + err)
rc, out, err = run("import-held", IMP, "--to", "imp", "--files", "blob.bin", sid=A, env={"CTX_ALLOW_FILES_WRITE": "1"})
check("import-held: 사유(--reason) 없으면 거부", rc != 0 and "--reason" in (out + err), out + err)
rc, out, err = run("import-held", IMP, "--to", "imp", "--files", "blob.bin", "--reason", "시험용 이진", sid=A, env={"CTX_ALLOW_FILES_WRITE": "0"})
check("import-held: 서버 호스트가 아니면 거부", rc != 0 and "서버 호스트" in (out + err), out + err)
rc, out, err = run("import-held", IMP, "--to", "imp", "--files", "blob.bin", "--reason", "시험용 이진", sid=A, env={"CTX_ALLOW_FILES_WRITE": "1"})
check("import-held: 허용한 보류 파일만 받는다", rc == 0 and os.path.isfile(f"{STORE}/proj/files/imp/blob.bin") and "사용자 허용으로 검사 없이 받음: blob.bin" in out, out + err)
os.remove(f"{IMP}/blob.bin")
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

# ---------------------------------------------------------------- DB 대기열(읽기 뷰 호스트의 쓰기 경로) — 계획 plan/ctx-doc-db-queue
import time as _time, types
import ctx_docqueue as dq
import ctx_doccli as dc

ENV_Q = {"CTX_IS_WRITER": "0", "CTX_PROPOSE_WAIT": "1"}      # 노트북 역할 모의: 동기화 담당 없음 + 인라인 처리 끔


def run_q(*args, sid=None, cwd=WORK, stdin=None, env=None):
    e = dict(BASE, **ENV_Q, **(env or {}))
    e.pop("CTX_SYNC_INLINE", None)
    if sid:
        e["CLAUDE_CODE_SESSION_ID"] = sid
    r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "doc", *args], capture_output=True, text=True, input=stdin, cwd=cwd, env=e, timeout=60)
    return r.returncode, r.stdout, r.stderr


def sql1(q, *args):
    r = conn.execute(q, args).fetchone(); conn.commit(); return r


def rows_of(target):
    r = conn.execute("SELECT id, status, msg, commit_sha, doc_hash, body, session_id FROM doc_proposals WHERE target=%s ORDER BY created_at", (target,)).fetchall(); conn.commit(); return r


masker = csec.load_masker(conn)
QS = "cccccccc-0000-0000-0000-00000000000c"
n_before = sql1("SELECT count(*) FROM doc_proposals")[0]
rc, out, err = run("propose", "note", "writer-path", "--stdin", sid=QS, stdin="정본 호스트 경로\n")
check("T8 정본 호스트(CTX_SYNC_INLINE)의 propose 는 DB 대기열을 쓰지 않고 지금 경로(파일 인박스)로 반영된다", rc == 0 and "반영했다" in out and sql1("SELECT count(*) FROM doc_proposals")[0] == n_before, out + err)

# T1 노트북 역할 propose → 대기 → 서버 동기화 → 반영
rc, out, err = run_q("propose", "note", "q1", "--stdin", sid=QS, stdin="노트북에서 쓴 문서\n")
check("T1 노트북 역할 propose: 서버가 아직 처리하지 않으면 「아직 반영되지 않았다」로 끝나고 문서는 생기지 않는다", rc == 0 and "아직 반영되지 않았다" in out and not os.path.exists(f"{STORE}/proj/note/q1.md"), out + err)
r1 = rows_of("proj/note/q1")
check("T1 DB 에 queued 행이 생긴다(본문 포함)", len(r1) == 1 and r1[0][1] == "queued" and "노트북에서 쓴 문서" in (r1[0][5] or ""), str(r1))
rc, out, err = run_q("propose", "note", "q1", "--stdin", sid=QS, stdin="두 번째\n")
check("T1 같은 세션·같은 target 의 이전 제안이 처리 중이면 거부", rc != 0 and "처리 중" in err, out + err)
rc, out, err = run_q("status", sid=QS)
check("T9→T1 status 에 「대기열」 줄과 대기 1 이 보인다", "[대기열]" in out and "대기 1" in out, out + err)
rc, out, err = run("sync")
check("T1 서버 동기화(`ctx doc sync`)가 대기열에서 가져와 처리한다", rc == 0 and "대기열에서 1건" in out and "반영했다" in out, out + err)
r1 = rows_of("proj/note/q1")
d1 = st.read_doc(STORE, "proj", "note", "q1")
check("T1 반영: 행 applied·doc_hash=문서 해시·commit_sha, 본문은 비워진다, 문서가 커밋됐다", r1[0][1] == "applied" and d1 and r1[0][4] == d1["hash"] and r1[0][3] and r1[0][5] is None and "q1" in subprocess.run(["git", "-C", f"{STORE}/proj", "log", "--oneline", "-3"], capture_output=True, text=True).stdout + os.listdir(f"{STORE}/proj/note").__str__(), str(r1))
rc, out, err = run_q("status", sid=QS)
check("T9→T1 반영 뒤 status 는 대기 0", "대기 0" in out, out)

# T4 같은 행을 두 번 가져와도 한 번만 반영(재시작 모의)
tgt4 = "proj/note/q4"; pid4 = st.proposal_id("proj", "note", "q4")
dq.enqueue(conn, pid4, QS, "testhost", tgt4, "write", None, "T4 문서\n"); conn.commit()
got1 = dq.pull_queue(STORE, cc.connect); got2 = dq.pull_queue(STORE, cc.connect)
check("T4 두 번째 pull_queue 는 이미 가져간 행을 다시 가져오지 않는다", got1 == [pid4] and got2 == [], f"{got1} {got2}")
st.process_inbox(STORE, masker)
# 재시작 모의: 행을 다시 queued 로 되돌려 같은 행을 또 가져오게 한다 — 이미 처리된 제안(결과 파일 존재)은 파일을 다시 만들지 않아야 한다
conn.execute("UPDATE doc_proposals SET status='queued' WHERE id=%s", (pid4,)); conn.commit()
dq.pull_queue(STORE, cc.connect)
check("T4 이미 처리된 제안은 재가져오기에서 파일 인박스를 다시 만들지 않는다(이중 반영 방지)", st.pending_proposals(STORE, QS, tgt4) == [], str(st.pending_proposals(STORE, QS, tgt4)))
res = dq.collect_results(STORE, cc.connect); dq.record_results(STORE, cc.connect, res)
check("T4 결과 기록 후 행이 applied", rows_of(tgt4)[0][1] == "applied", str(rows_of(tgt4)))
n_commits = int(subprocess.run(["git", "-C", f"{STORE}/proj", "rev-list", "--count", "HEAD", "--", "note/q4.md"], capture_output=True, text=True).stdout.strip() or 0)
check("T4 문서 q4 의 커밋은 한 번뿐", n_commits == 1, str(n_commits))

# T2 충돌: 본문 보관, 알림
tgt2 = "proj/note/q1"; pid2 = st.proposal_id("proj", "note", "q1") + "-c"
dq.enqueue(conn, pid2, QS, "testhost", tgt2, "write", "deadbeef" * 8, "낡은 판 위의 수정\n"); conn.commit()
dq.pull_queue(STORE, cc.connect); st.process_inbox(STORE, masker); dq.record_results(STORE, cc.connect, dq.collect_results(STORE, cc.connect))
r2 = [r for r in rows_of(tgt2) if r[0] == pid2][0]
check("T2 읽은 판이 다르면 conflict — 자동으로 덮지 않고 본문은 7일 보관, 문서는 그대로", r2[1] == "conflict" and "바뀌었다" in (r2[2] or "") and r2[5] and st.read_doc(STORE, "proj", "note", "q1")["hash"] == d1["hash"], str(r2))
rc, out, err = run_q("status", sid=QS)
check("T9→T2 status 에 충돌 1 과 알림 줄이 보인다", "충돌 1" in out and "conflict:" in out, out)

# T3 비밀: 클라이언트가 넣기 전에 막고, 서버에 직접 들어온 행도 거부·본문 비움
n0 = sql1("SELECT count(*) FROM doc_proposals")[0]
rc, out, err = run_q("propose", "note", "q3", "--stdin", sid=QS, stdin="비밀 hunter2 가 들어 있다\n")
check("T12 클라이언트 비밀 검사: 등록 비밀이 든 본문은 거부되고 DB 에 행이 생기지 않는다", rc != 0 and "비밀" in err and sql1("SELECT count(*) FROM doc_proposals")[0] == n0, out + err)
pid3 = st.proposal_id("proj", "note", "q3s")
dq.enqueue(conn, pid3, QS, "testhost", "proj/note/q3s", "write", None, "서버에 직접 들어온 hunter2\n"); conn.commit()
dq.pull_queue(STORE, cc.connect); st.process_inbox(STORE, masker); dq.record_results(STORE, cc.connect, dq.collect_results(STORE, cc.connect))
r3 = rows_of("proj/note/q3s")[0]
check("T3 서버 검사: 비밀이 든 제안은 rejected 이고 DB 본문이 즉시 비워진다", r3[1] == "rejected" and r3[5] is None and not os.path.exists(f"{STORE}/proj/note/q3s.md"), str(r3))

# T5 복구(시계 주입)
pid5 = st.proposal_id("proj", "note", "q5")
dq.enqueue(conn, pid5, QS, "testhost", "proj/note/q5", "write", None, "T5\n"); conn.commit()
dq.pull_queue(STORE, cc.connect)
os.remove(os.path.join(st.inbox_dir(STORE), QS, pid5 + ".proposal.md"))   # 가져간 뒤 죽어 파일도 결과도 없는 상태
conn.execute("UPDATE doc_proposals SET fetched_at = to_timestamp(%s) WHERE id=%s", (1000.0, pid5)); conn.commit()
check("T5 30분이 안 지났으면 되돌리지 않는다", dq.maintenance(STORE, cc.connect, now=1000.0 + 60)["requeued"] == 0 and rows_of("proj/note/q5")[0][1] == "fetched")
check("T5 30분이 지나면 queued 로 되돌린다", dq.maintenance(STORE, cc.connect, now=1000.0 + dq.FETCHED_RECOVER_SEC + 5)["requeued"] == 1 and rows_of("proj/note/q5")[0][1] == "queued")
os.makedirs(os.path.join(st.inbox_dir(STORE), "_results"), exist_ok=True)
json.dump({"status": "applied", "msg": "x", "commit": "abc1234"}, open(os.path.join(st.inbox_dir(STORE), "_results", pid5 + ".json"), "w"))
dq.pull_queue(STORE, cc.connect)
check("T5 결과 파일이 있는 fetched 행은 결과로 수집된다(재시작 후 복구)", [p for p, _o, _r in dq.collect_results(STORE, cc.connect)] == [pid5])
conn.execute("UPDATE doc_proposals SET status='conflict', resolved_at=to_timestamp(%s), body='보관' WHERE id=%s", (1000.0, pid2)); conn.commit()
check("T5 충돌 행 본문은 7일 뒤 비워진다", dq.maintenance(STORE, cc.connect, now=1000.0 + 8 * 86400)["body_cleared"] >= 1 and rows_of(tgt2)[1 if rows_of(tgt2)[0][0] != pid2 else 0][5] is None)
conn.execute("UPDATE doc_proposals SET status='applied' WHERE id=%s", (pid5,)); conn.commit()

# T6 서버 불가 → outbox 보관 → 다음 ctx doc 실행 때 재전송
BAD = {"CLAUDE_CTX_DSN": "host=/nonexistent-ctx-socket dbname=claude_ctx user=claude_ctx connect_timeout=1"}
rc, out, err = run_q("propose", "note", "q6", "--stdin", sid=QS, stdin="서버 불가 중에 쓴 문서\n", env=BAD)
ob = dq.outbox_files(STORE)
check("T6 DB 에 못 붙으면 outbox 에 보관하고 「보관만 했다(아직 반영되지 않았다)」를 알린다", rc == 0 and "보관만 했다" in out and len(ob) == 1, out + err)
rc, out, err = run_q("status", sid=QS, env=BAD)
check("T6 status 가 보관 중인 제안 수를 알린다", "보관 중인 제안 1개" in out, out + err)
check("T6 DB 로 아직 안 들어갔다", rows_of("proj/note/q6") == [])
rc, out, err = run_q("list", sid=QS)
r6 = rows_of("proj/note/q6")
check("T6 서버가 돌아온 뒤 다음 `ctx doc` 실행이 outbox 를 대기열로 보내고 파일을 지운다", len(r6) == 1 and r6[0][1] == "queued" and dq.outbox_files(STORE) == [], f"{r6} {dq.outbox_files(STORE)} {err}")
old = dq.outbox_put(STORE, QS, "x-old", "내용"); os.utime(old, (1000.0, 1000.0))
check("T6 7일 넘은 outbox 파일은 경고 대상", dq.outbox_old(STORE) == [old]); os.remove(old)

# T7 import-inbox: 옛 방식 제안 파일 → 대기열
OLD = f"{TMP}/oldinbox/{QS}"; os.makedirs(OLD)
pid7 = st.proposal_id("proj", "note", "imp7")
open(f"{OLD}/{pid7}.proposal.md", "w").write(st.render_proposal("proj/note/imp7", "write", None, QS, "oldhost", "옛 인박스에서 온 제안\n"))
open(f"{OLD}/broken.proposal.md", "w").write("머리말 없음\n")
rc, out, err = run("import-inbox", f"{TMP}/oldinbox")
check("T7 import-inbox: 새 1·올바르지 않음 1", rc == 0 and "대기열에 넣음 1" in out and "올바르지 않음 1" in out, out + err)
rc, out, err = run("import-inbox", f"{TMP}/oldinbox")
check("T7 import-inbox 재실행은 이미 있는 것을 건너뛴다", "대기열에 넣음 0" in out and "이미 있음 1" in out, out)
check("T7 원본 파일은 건드리지 않는다", os.path.exists(f"{OLD}/{pid7}.proposal.md"))
rc, out, err = run("sync")
check("T7 서버 동기화 뒤 옛 제안이 새 경로로 반영된다(host 는 원래 호스트)", rows_of("proj/note/imp7")[0][1] == "applied" and (st.read_doc(STORE, "proj", "note", "imp7") or {}).get("meta", {}).get("updated_host") == "oldhost", out + err)

# T11 import-docs 제출도 대기열을 쓴다
SRC = f"{TMP}/impdocs"; os.makedirs(SRC); open(f"{SRC}/a.md", "w").write("# 가져올 문서 A\n내용\n")
rc, out, err = run_q("import-docs", SRC, "--prefix", "qimp", "--wait", "1", sid=QS)
check("T11 import-docs 도 읽기 뷰 호스트에서는 DB 대기열 행을 만든다(로컬 인박스에 쌓이지 않는다)", len(rows_of("proj/note/qimp/a")) == 1 and st.pending_proposals(STORE, QS, "proj/note/qimp/a") == [], out + err)
run("sync")

# T15 delete: 대기열 경유 삭제, doc_hash 는 null·commit_sha 로 확인
run_q("read", "note", "imp7", sid=QS)
rc, out, err = run_q("delete", "note", "imp7", sid=QS)
check("T15 delete 제출 후 서버가 아직이면 「아직 반영되지 않았다」", "아직 반영되지 않았다" in out, out + err)
run("sync")
r15 = [r for r in rows_of("proj/note/imp7") if r[0] != pid7][0]
check("T15 delete 반영: 문서가 지워지고 doc_hash 는 null·commit_sha 가 있다", r15[1] == "applied" and r15[4] is None and r15[3] and not os.path.exists(f"{STORE}/proj/note/imp7.md"), str(r15))

# T10 연속 쓰기: 반영 뒤 읽기 뷰 맞추기(서버 저장소 + 노트북 클론 + 같은 bare 원격)
BARE = f"{TMP}/t10.git"; subprocess.run(["git", "init", "-q", "--bare", "-b", "main", BARE], check=True)
S_SRV, S_LAP = f"{TMP}/t10srv", f"{TMP}/t10lap"
for d in (S_SRV, S_LAP):
    os.makedirs(d)
    open(f"{d}/manifest.toml", "w").write(f'[projects.proj]\nrepo_url = "{URL}"\nowner = "personal"\nremote = ""\n')
st.ensure_repo(f"{S_SRV}/proj"); os.makedirs(f"{S_SRV}/proj/note")
open(f"{S_SRV}/proj/note/seed.md", "w").write(st.compose({}, "seed\n")); st.commit_file(S_SRV, "proj", "note/seed.md", "seed")
subprocess.run(["git", "-C", f"{S_SRV}/proj", "remote", "add", "origin", BARE], check=True); subprocess.run(["git", "-C", f"{S_SRV}/proj", "push", "-q", "origin", "HEAD"], check=True)
subprocess.run(["git", "clone", "-q", BARE, f"{S_LAP}/proj"], check=True)
os.environ["CTX_IS_WRITER"] = "0"; os.environ.pop("CTX_NO_PULL", None)
st.propose(S_SRV, QS, "lap", "proj", "note", "t10", "첫 판\n", None); st.process_inbox(S_SRV, masker)
newh = st.read_doc(S_SRV, "proj", "note", "t10")["hash"]
row10 = {"status": "applied", "doc_hash": newh, "commit": None}
check("T10 push 전에는 노트북 클론이 낡았다(읽기 뷰를 맞출 수 없다 — 마감 0 이면 곧바로 False)", dq.sync_view(S_LAP, "proj", "note", "t10", "write", row10, deadline=0, step=0, sleep=lambda s: None) is False)
subprocess.run(["git", "-C", f"{S_SRV}/proj", "push", "-q", "origin", "HEAD"], check=True)
check("T10 push 뒤에는 pull 재시도로 doc_hash 가 나타나 읽기 뷰가 맞춰진다", dq.sync_view(S_LAP, "proj", "note", "t10", "write", row10, deadline=5, step=0, sleep=lambda s: None) is True and st.read_doc(S_LAP, "proj", "note", "t10")["hash"] == newh)
sidv = "dddddddd-0000-0000-0000-00000000000d"
st.ensure_in_view(S_LAP, VIEWS, sidv, "proj", "note", "t10")
base_ok = st.base_hash_for(VIEWS, sidv, "proj", "note", "t10")
st.propose(S_SRV, sidv, "lap", "proj", "note", "t10", "둘째 판\n", base_ok); st.process_inbox(S_SRV, masker)
check("T10 맞춰진 읽기 뷰의 읽은 판으로 이어서 수정하면 충돌 없이 반영된다(거짓 충돌 없음)", st.read_doc(S_SRV, "proj", "note", "t10")["body"].strip() == "둘째 판")
newh2 = st.read_doc(S_SRV, "proj", "note", "t10")["hash"]
st.propose(S_SRV, sidv, "lap", "proj", "note", "t10", "낡은 판 위의 셋째\n", base_ok); res = st.process_inbox(S_SRV, masker)
check("T10 읽기 뷰를 못 맞춘 채(낡은 읽은 판) 또 제안하면 서버가 충돌로 거부한다(덮어쓰지 않음)", res and res[0][1] == "conflict" and st.read_doc(S_SRV, "proj", "note", "t10")["hash"] == newh2, str(res))
row10d = {"status": "applied", "doc_hash": None, "commit": "0000000000000000000000000000000000000000"}
check("T10 delete 는 commit 도착으로 확인한다(없는 커밋이면 False, pull 도 소용없으면 즉시 포기)", dq.view_in_sync(S_LAP, "proj", "note", "t10", "delete", row10d) is False)
os.environ["CTX_NO_PULL"] = "1"
check("T10 CTX_NO_PULL=1 이면 기다리지 않고 바로 포기한다(can_pull False)", dq.can_pull(S_LAP, "proj") is False)
os.environ.pop("CTX_NO_PULL", None)

# T14 `_sync_once` 재구성: 할 일이 없으면 masker 를 읽지 않고, push 필요면 읽고, 로드 실패면 1
T14 = f"{TMP}/t14"; os.makedirs(T14)
open(f"{T14}/manifest.toml", "w").write(f'[projects.p14]\nrepo_url = "https://github.com/test/p14"\nowner = "personal"\nremote = "{TMP}/t14.git"\n')
st.ensure_repo(f"{T14}/p14")
dc.H = types.SimpleNamespace(connect=cc.connect, load_masker=csec.load_masker, HOST="testhost")
calls = {"masker": 0, "push": 0}
def _fake_masker():
    calls["masker"] += 1; return masker
orig_lm, orig_push = dc._load_masker_or_none, st.push_project
dc._load_masker_or_none = _fake_masker
st.push_project = lambda store, proj, m, man=None: (calls.__setitem__("push", calls["push"] + 1) or (True, "fake"))
dc._last_push.clear(); dc._last_push["p14"] = _time.time()          # 방금 push 한 것으로
conn.execute("DELETE FROM doc_proposals WHERE status IN ('queued','fetched')"); conn.commit()
rc14 = dc._sync_once(T14, True, False)
check("T14 대기열·인박스·push 필요가 모두 없으면 비밀 검사기를 읽지 않고 끝난다", rc14 == 0 and calls["masker"] == 0 and calls["push"] == 0, str(calls))
dc._last_push["p14"] = _time.time() - dc.PUSH_EVERY - 5
rc14 = dc._sync_once(T14, True, False)
check("T14 제안이 없어도 push 주기가 되면 검사기를 읽고 push 한다(따라잡기 push 를 끊지 않는다)", rc14 == 0 and calls["masker"] == 1 and calls["push"] == 1, str(calls))
dq.enqueue(conn, st.proposal_id("p14", "note", "z"), QS, "h", "p14/note/z", "write", None, "z\n"); conn.commit()
dc._load_masker_or_none = lambda: None
check("T14 대기열에 할 일이 있는데 검사기를 못 얻으면 1 을 돌려주고 아무것도 가져오지 않는다(fail-closed)", dc._sync_once(T14, False, False) == 1 and sql1("SELECT status FROM doc_proposals WHERE target='p14/note/z'")[0] == "queued")
dc._load_masker_or_none, st.push_project = orig_lm, orig_push
conn.execute("DELETE FROM doc_proposals WHERE target='p14/note/z'"); conn.commit()

# T13 표가 없는 옛 스키마에서도 파일 인박스 경로는 막히지 않는다(마지막 시험 — 표를 지운다)
conn.execute("DROP TABLE doc_proposals"); conn.commit()
st.propose(STORE, QS, "testhost", "proj", "note", "t13", "옛 스키마에서도 반영\n", None)
rc, out, err = run("sync")
check("T13 doc_proposals 표가 없어도 동기화 담당이 죽지 않고 파일 인박스 제안을 반영한다", rc == 0 and st.read_doc(STORE, "proj", "note", "t13") is not None, out + err)

pg.stop(); shutil.rmtree(TMP, ignore_errors=True)
sys.exit(finish("ctx doc CLI"))
