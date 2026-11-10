#!/usr/bin/env python3
"""ctx_store 시험 — 작업 문서의 파일 저장소·읽기 뷰·제안(인박스)·동기화 담당. DB·네트워크 없이 임시 폴더와 git 만 쓴다.
1부 순수(이름·머리말·매니페스트) 2부 제안→커밋·충돌·비밀·머리말 검사 3부 읽기 뷰(복사·직접 수정 감지·정리) 4부 push 검사 5부 inotify 감시."""
import os, shutil, subprocess, sys, tempfile, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctx_store as cs

TMP = tempfile.mkdtemp(prefix="ctxstore-test-")
STORE, VIEWS = f"{TMP}/ctx", f"{TMP}/views"
os.makedirs(STORE)
open(f"{STORE}/manifest.toml", "w").write('[projects.nixos]\nrepo_url = "github.com/donghans/nixos"\nowner = "personal"\n\n[projects.tot]\nrepo_url = "example.com/tot"\n')


class FakeMasker:
    def text(self, s):
        return s.replace("SECRET123", "[protected]")


# ---------------------------------------------------------------- 1부: 순수
check("이름: 정상(경로꼴)", cs.valid_name("repo-restructure-2/README") is None)
for bad in ("", " ", "/abs", "a/../b", "..", "a//b", "x" * 301, "a.md", ".hidden/x", "a/.b"):
    check(f"이름 거부: {bad[:14]!r}", cs.valid_name(bad) is not None)
check("프로젝트: 정상", cs.valid_project("nixos") is None and cs.valid_project("a.b-c_d") is None)
for bad in ("", "_inbox", "a/b", "-x", "x" * 70):
    check(f"프로젝트 거부: {bad[:10]!r}", cs.valid_project(bad) is not None)
check("대상 검사: kind", cs.check_target("nixos", "bogus", "a") is not None and cs.check_target("nixos", "plan", "a") is None)
check("문서 경로", cs.doc_path("/s", "nixos", "plan", "a/b") == "/s/nixos/plan/a/b.md")

man = cs.load_manifest(STORE)
check("매니페스트: 프로젝트 2개", sorted(man) == ["nixos", "tot"])
check("매니페스트 없으면 빈 표", cs.load_manifest(f"{TMP}/none") == {})
check("프로젝트 결정: 이름 명시", cs.resolve_project(man, "nixos") == ("nixos", None))
check("프로젝트 결정: repo_url", cs.resolve_project(man, None, "example.com/tot") == ("tot", None))
p, err = cs.resolve_project(man, None, "other")
check("프로젝트 결정: 못 찾으면 추측하지 않고 실패", p is None and "--project" in err)
p, err = cs.resolve_project(man, "ghost")
check("프로젝트 결정: 없는 이름은 실패", p is None and "ghost" in err)

meta, body = cs.split_header("본문만\n")
check("머리말 없음", meta is None and body == "본문만\n")
doc = cs.compose({"status": "done", "scope": "personal"}, "---\nname: x\n---\n본문 한글\n")
m2, b2 = cs.split_header(doc)
check("머리말 왕복: 값 보존", m2["status"] == "done" and m2["scope"] == "personal" and m2["state"] == "unknown")
check("본문의 자기 --- 머리말과 충돌하지 않고 바이트 그대로", b2 == "---\nname: x\n---\n본문 한글\n")
check("머리말 검증: 정상", cs.validate_meta(m2) == [])
check("머리말 검증: 잘못된 값", len(cs.validate_meta({"state": "weird"})) == 1)
check("머리말 검증: 모르는 칸", len(cs.validate_meta({"foo": "1"})) == 1)
check("닫히지 않은 머리말은 머리말이 아님", cs.split_header("<!-- ctx\nstatus: done\n본문")[0] is None)

# ---------------------------------------------------------------- 2부: 제안 → 커밋
S1, S2 = "11111111-aaaa", "22222222-bbbb"
code, msg, pid = cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "첫 본문\n", None)
check("제안: 새 문서 제안이 남는다", code == 0 and pid and cs.pending_proposals(STORE, S1), msg)
check("제안: 저장소 문서는 아직 없다(직접 쓰지 않음)", not os.path.exists(cs.doc_path(STORE, "nixos", "plan", "x/a")))
code, msg, _ = cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "또\n", None)
check("제안: 같은 세션이 같은 문서에 대기 중 제안이 있으면 거부", code == 1 and "처리 중" in msg)
check("제안: 이름 검사", cs.propose(STORE, S1, "h", "nixos", "plan", "../x", "b\n", None)[0] == 1)
check("제안: 빈 본문 거부", cs.propose(STORE, S1, "h", "nixos", "plan", "e", "  \n", None)[0] == 1)

res = cs.process_inbox(STORE, FakeMasker())
check("처리: 반영됨 + 커밋", len(res) == 1 and res[0][1] == "applied" and res[0][3], res)
d = cs.read_doc(STORE, "nixos", "plan", "x/a")
check("문서가 파일로 생겼다(본문 그대로)", d and d["body"] == "첫 본문\n")
check("머리말: updated_host·provenance 기록", d["meta"]["updated_host"] == "hostA" and "11111111" in d["meta"]["provenance"])
log = subprocess.run(["git", "-C", f"{STORE}/nixos", "log", "--oneline"], capture_output=True, text=True).stdout
check("프로젝트별 독립 git 저장소에 커밋됨", "ctx: nixos/plan/x/a" in log, log)
check("제안 파일은 처리 뒤 사라진다", not cs.pending_proposals(STORE))
rj = cs.wait_result(STORE, pid, 1)
check("결과 파일(propose 가 기다리는 것)", rj and rj["status"] == "applied" and rj["commit"])

# 수정 — 읽은 판 기준
h1 = d["hash"]
code, msg, pid2 = cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "고친 본문\n", h1)
check("제안: 읽은 판을 주면 수정 제안", code == 0)
res = cs.process_inbox(STORE, FakeMasker())
check("수정 반영", res[0][1] == "applied" and cs.read_doc(STORE, "nixos", "plan", "x/a")["body"] == "고친 본문\n")
check("수정 시 머리말(provenance 등)은 유지", "11111111" in cs.read_doc(STORE, "nixos", "plan", "x/a")["meta"]["provenance"])
h2 = cs.read_doc(STORE, "nixos", "plan", "x/a")["hash"]

# 같은 내용
cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "고친 본문\n", h2)
res = cs.process_inbox(STORE, FakeMasker())
check("같은 내용이면 커밋하지 않는다", res[0][1] == "same")

# 읽지 않고 덮어쓰기 거부
code, msg, _ = cs.propose(STORE, S2, "hostB", "nixos", "plan", "x/a", "몰래\n", None)
check("제안: 있는 문서를 읽지 않고(base 없이) 덮어쓰기는 거부", code == 1 and "먼저" in msg)
code, msg, _ = cs.propose(STORE, S2, "hostB", "nixos", "plan", "x/none", "x\n", "deadbeef")
check("제안: 없는 문서에 base 를 주면 거부", code == 1)

# 충돌: 두 세션이 같은 판에서 시작
cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "A 가 고침\n", h2)
cs.propose(STORE, S2, "hostB", "nixos", "plan", "x/a", "B 가 고침\n", h2)
res = cs.process_inbox(STORE, FakeMasker())
st = {r[1] for r in res}
check("충돌: 먼저 온 것은 반영, 뒤의 것은 충돌로 멈춘다", [r[1] for r in res] == ["applied", "conflict"], res)
check("충돌: 문서는 먼저 온 본문", cs.read_doc(STORE, "nixos", "plan", "x/a")["body"] == "A 가 고침\n")
check("충돌: 제안은 _conflicts 로 옮겨지고 이유가 남는다", os.path.exists(f"{STORE}/_inbox/_conflicts/{S2}") and any(f.endswith(".reason") for f in os.listdir(f"{STORE}/_inbox/_conflicts/{S2}")))
ss = cs.session_status(STORE, S2)
check("상태: 충돌 1·알림 줄", ss["conflict"] == 1 and any("conflict" in n for n in ss["notices"]), ss)
check("상태: 다른 세션은 영향 없음", cs.session_status(STORE, S1)["conflict"] == 0)

# 비밀
h3 = cs.read_doc(STORE, "nixos", "plan", "x/a")["hash"]
cs.propose(STORE, S1, "hostA", "nixos", "plan", "x/a", "토큰 SECRET123 포함\n", h3)
res = cs.process_inbox(STORE, FakeMasker())
check("비밀: 등록된 비밀이 든 제안은 거부", res[0][1] == "rejected" and "비밀" in res[0][2], res)
check("비밀: 문서는 바뀌지 않았다", cs.read_doc(STORE, "nixos", "plan", "x/a")["hash"] == h3)
check("비밀: 거부된 제안이 _rejected 에 남는다", os.path.isdir(f"{STORE}/_inbox/_rejected/{S1}"))

# 머리말 검사
bad = cs.compose({"state": "adopted"}, "본문\n").replace("state: adopted", "state: wrong")
cs.propose(STORE, S1, "hostA", "nixos", "note", "m/new", bad, None)
res = cs.process_inbox(STORE, FakeMasker())
check("머리말: 잘못된 값이 든 제안은 거부", res[0][1] == "rejected" and "state" in res[0][2], res)
good = cs.compose({"state": "reviewed", "scope": "personal"}, "본문\n")
cs.propose(STORE, S1, "hostA", "nixos", "note", "m/new", good, None)
res = cs.process_inbox(STORE, FakeMasker())
check("머리말: 올바른 머리말은 그대로 반영", res[0][1] == "applied" and cs.read_doc(STORE, "nixos", "note", "m/new")["meta"]["state"] == "reviewed")

# 프로젝트가 매니페스트에 없는 제안
os.makedirs(f"{STORE}/_inbox/{S1}", exist_ok=True)
open(f"{STORE}/_inbox/{S1}/20260101T000000000Z-ghost-plan-a.proposal.md", "w").write(cs.PROP_OPEN + "target: ghost/plan/a\nbase_hash: none\nsession: x\nhost: h\ncreated: now\n-->\n본문\n")
res = cs.process_inbox(STORE, FakeMasker())
check("없는 프로젝트의 제안은 거부", res[0][1] == "rejected" and "매니페스트" in res[0][2], res)
open(f"{STORE}/_inbox/{S1}/20260101T000000001Z-nixos-plan-a.proposal.md", "w").write("머리말 없는 이상한 파일\n")
res = cs.process_inbox(STORE, FakeMasker())
check("머리말 없는 제안 파일은 거부(멈추지 않는다)", res and res[0][1] == "rejected")

# 목록·검색
rows = cs.list_docs(STORE, "nixos")
check("목록: 문서 2개", sorted((r["kind"], r["name"]) for r in rows) == [("note", "m/new"), ("plan", "x/a")], rows)
check("목록: 종류 필터", len(cs.list_docs(STORE, "nixos", "note")) == 1)
check("목록: 이름 접두 필터", len(cs.list_docs(STORE, "nixos", None, None, "x/")) == 1)
check("검색: 본문", [r["name"] for r in cs.find_docs(STORE, "nixos", "고침")] == ["x/a"])
check("검색: 머리말은 검색 대상이 아니다", cs.find_docs(STORE, "nixos", "provenance") == [])
check("검색: 없으면 빈 목록", cs.find_docs(STORE, "nixos", "없는말없는말") == [])

# ---------------------------------------------------------------- 3부: 읽기 뷰
for i in range(3):
    open(f"{STORE}/nixos/plan/v{i}.md", "w").write(cs.compose({"status": "active"}, f"뷰 문서 {i}\n"))
r = cs.build_view(STORE, VIEWS, "sess-view", "nixos")
check("뷰: 문서가 복사된다", len(r["copied"]) >= 4 and os.path.isfile(f"{VIEWS}/sess-view/nixos/plan/v0.md"), r["copied"])
check("뷰: 파일은 0444", (os.stat(f"{VIEWS}/sess-view/nixos/plan/v0.md").st_mode & 0o777) == 0o444)
check("뷰: 내용이 원본과 같다", open(f"{VIEWS}/sess-view/nixos/plan/v0.md").read() == open(f"{STORE}/nixos/plan/v0.md").read())
check("뷰: 원본과 다른 inode(별개 파일)", os.stat(f"{VIEWS}/sess-view/nixos/plan/v0.md").st_ino != os.stat(f"{STORE}/nixos/plan/v0.md").st_ino)
check("뷰: 기준 해시 파일과 INDEX", os.path.isfile(f"{VIEWS}/sess-view/.ctx-base.json") and "nixos/plan/v0.md" in open(f"{VIEWS}/sess-view/INDEX.md").read())
check("뷰: _inbox·.git 은 복사하지 않는다", not os.path.exists(f"{VIEWS}/sess-view/_inbox") and not os.path.exists(f"{VIEWS}/sess-view/nixos/.git"))
r2 = cs.build_view(STORE, VIEWS, "sess-view", "nixos")
check("뷰: 두 번째는 아무것도 다시 복사하지 않는다(멱등)", r2["copied"] == [] and r2["restored"] == [])
check("뷰: 수정 없음", cs.modified_in_view(f"{VIEWS}/sess-view") == [])
check("뷰: 세션별로 분리", not os.path.exists(f"{VIEWS}/other"))

# 직접 수정 감지·보관·복원
vp = f"{VIEWS}/sess-view/nixos/plan/v1.md"
os.chmod(vp, 0o644); open(vp, "a").write("에이전트가 몰래 고침\n")
mods = cs.modified_in_view(f"{VIEWS}/sess-view")
check("직접 수정 감지", mods == [("nixos/plan/v1.md", "modified")], mods)
os.remove(f"{VIEWS}/sess-view/nixos/plan/v2.md")
check("삭제 감지", ("nixos/plan/v2.md", "deleted") in cs.modified_in_view(f"{VIEWS}/sess-view"))
r3 = cs.build_view(STORE, VIEWS, "sess-view", "nixos")
check("갱신: 직접 수정은 원본으로 되돌리고", open(vp).read() == open(f"{STORE}/nixos/plan/v1.md").read() and "nixos/plan/v1.md" in r3["restored"], r3)
kept = [f for f in os.listdir(f"{VIEWS}/sess-view/.ctx-rejected/nixos/plan")]
check("갱신: 되돌리기 전 직접 수정본은 .ctx-rejected 에 보관(잃지 않음)", kept and "몰래" in open(f"{VIEWS}/sess-view/.ctx-rejected/nixos/plan/{kept[0]}").read())
check("갱신: 삭제된 파일도 복원", os.path.isfile(f"{VIEWS}/sess-view/nixos/plan/v2.md"))
check("갱신 뒤 수정 없음", cs.modified_in_view(f"{VIEWS}/sess-view") == [])

# 원본이 바뀌면 뷰 갱신(base 도 같이)
open(f"{STORE}/nixos/plan/v0.md", "w").write(cs.compose({"status": "done"}, "원본이 바뀜\n"))
r4 = cs.build_view(STORE, VIEWS, "sess-view", "nixos")
check("원본 변경이 뷰에 반영", r4["copied"] == ["nixos/plan/v0.md"] and "원본이 바뀜" in open(f"{VIEWS}/sess-view/nixos/plan/v0.md").read())
check("자기 갱신은 직접 수정으로 오인하지 않는다", cs.modified_in_view(f"{VIEWS}/sess-view") == [])

# read → 읽은 판 기록 → propose
bh = cs.ensure_in_view(STORE, VIEWS, "sess-read", "nixos", "plan", "v0")
check("읽기: 뷰에 넣고 읽은 판 해시를 돌려준다", bh == cs.read_doc(STORE, "nixos", "plan", "v0")["hash"] and cs.base_hash_for(VIEWS, "sess-read", "nixos", "plan", "v0") == bh)
check("읽기: 문서 하나만 뷰에 들어간다", not os.path.exists(f"{VIEWS}/sess-read/nixos/plan/v1.md"))
check("읽기: 읽지 않은 문서의 base 는 없다", cs.base_hash_for(VIEWS, "sess-read", "nixos", "plan", "v1") is None)

# 정리
cs.mark_ended(VIEWS, "sess-view")
gone = cs.cleanup_views(VIEWS)
check("정리: 종료 표식이 있는 세션의 뷰를 지운다", "sess-view" in gone and not os.path.exists(f"{VIEWS}/sess-view"), gone)
check("정리: 살아 있는 세션의 뷰는 둔다", os.path.isdir(f"{VIEWS}/sess-read"))
cs.build_view(STORE, VIEWS, "sess-live", "nixos", pid=os.getpid())
cs.mark_ended(VIEWS, "sess-live")
check("정리: 종료 표식이 있어도 세션 프로세스가 살아 있으면 둔다", "sess-live" not in cs.cleanup_views(VIEWS))
cs.build_view(STORE, VIEWS, "sess-old", "nixos")
old = time.time() - 9 * 86400
os.utime(f"{VIEWS}/sess-old/.ctx-base.json", (old, old)); os.utime(f"{VIEWS}/sess-old", (old, old))   # 나이 = 뷰 폴더·base·msg/ 중 최근(P1b)
check("정리: 오래되고 죽은 세션의 뷰를 지운다", "sess-old" in cs.cleanup_views(VIEWS))
cs.build_view(STORE, VIEWS, "sess-restart", "nixos"); cs.mark_ended(VIEWS, "sess-restart")
cs.build_view(STORE, VIEWS, "sess-restart", "nixos")
check("재개: 뷰를 다시 만들면 종료 표식이 지워진다", not os.path.exists(f"{VIEWS}/sess-restart/.ctx-ended"))

# ---------------------------------------------------------------- 4부: push 검사
check("push: remote 가 없으면 하지 않는다", cs.push_project(STORE, "nixos", FakeMasker())[0] is False)
BARE = f"{TMP}/bare.git"
subprocess.run(["git", "init", "-q", "--bare", BARE], check=True)
open(f"{STORE}/manifest.toml", "a").write(f'\n[projects.pushy]\nremote = "{BARE}"\n')
cs.ensure_repo(f"{STORE}/pushy")
os.makedirs(f"{STORE}/pushy/note"); open(f"{STORE}/pushy/note/a.md", "w").write(cs.compose({}, "깨끗한 문서\n"))
cs.commit_file(STORE, "pushy", "note/a.md", "init")
ok, msg = cs.push_project(STORE, "pushy", None)
check("push: 비밀 검사기가 없으면(DB 불가) 거부 — fail-closed", ok is False and "검사기" in msg, msg)
open(f"{STORE}/pushy/note/leak.md", "w").write(cs.compose({}, "SECRET123 이 새었다\n"))
cs.commit_file(STORE, "pushy", "note/leak.md", "leak")
ok, msg = cs.push_project(STORE, "pushy", FakeMasker())
check("push: 이력에 비밀이 든 파일이 있으면 push 하지 않는다", ok is False and "leak.md" in msg, msg)
check("push: 거부됐으니 원격은 비어 있다", subprocess.run(["git", "-C", BARE, "rev-list", "--all", "--count"], capture_output=True, text=True).stdout.strip() == "0")
os.remove(f"{STORE}/pushy/note/leak.md"); subprocess.run(["git", "-C", f"{STORE}/pushy", "rm", "-q", "--cached", "note/leak.md"], check=True)
subprocess.run(["git", "-C", f"{STORE}/pushy", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "rm leak"], check=True)
ok, msg = cs.push_project(STORE, "pushy", FakeMasker())
check("push: 현재 파일이 깨끗하면 push 한다(이력의 비밀은 별개 — 이 검사는 현재 추적 파일)", ok is True, msg)
open(f"{STORE}/pushy/note/원칙-후보-초안.md", "w").write(cs.compose({}, "한글 이름 문서\n"))
cs.commit_file(STORE, "pushy", "note/원칙-후보-초안.md", "korean name")
ok, msg = cs.push_project(STORE, "pushy", FakeMasker())
check("push: 한글 파일명이 있어도 비밀 검사를 하고 push 한다(git 의 따옴표 처리 경로로 못 열어 막히던 회귀)", ok is True, msg)
open(f"{STORE}/pushy/note/bin.dat", "wb").write(b"\x00\x01\x02png")
cs.commit_file(STORE, "pushy", "note/bin.dat", "binary")
ok, msg = cs.push_project(STORE, "pushy", FakeMasker())
check("push: 비밀 검사를 할 수 없는 추적 파일(이진)이 있으면 거부 — 검사 없이 통과시키지 않는다", ok is False and "bin.dat" in msg and "검사를 할 수 없는" in msg, msg)
subprocess.run(["git", "-C", f"{STORE}/pushy", "rm", "-q", "-f", "note/bin.dat"], check=True)
subprocess.run(["git", "-C", f"{STORE}/pushy", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "rm bin"], check=True)
open(f"{STORE}/pushy/note/big.md", "w").write("x" * (cs.MAX_BYTES + 10))
cs.commit_file(STORE, "pushy", "note/big.md", "big")
ok, msg = cs.push_project(STORE, "pushy", FakeMasker())
check("push: 한도를 넘는 큰 추적 파일도 거부", ok is False and "big.md" in msg, msg)

# ---------------------------------------------------------------- 4-2부: 자료 영역(files)·탐지기
SRC = f"{TMP}/src"; os.makedirs(f"{SRC}/sub/node_modules/x"); os.makedirs(f"{SRC}/shots")
w = lambda rel, data, mode="w": (os.makedirs(os.path.dirname(f"{SRC}/{rel}"), exist_ok=True), open(f"{SRC}/{rel}", mode).write(data))
w("a.json", '{"ok": 1}\n'); w("sub/run.log", "정상 로그\n"); w("sub/node_modules/x/i.js", "skip\n"); w("shots/s.png", b"\x89PNG", "wb")
w(".env", "A=1\n"); w("leak.json", '{"password": "hunter2hunter"}\n'); w("kr.txt", "비밀번호: abc12345\n"); w("deck.pptx", b"PK\x03", "wb"); w("big.json", "x" * (cs.FILE_MAX_BYTES + 1))
w("reg.json", "SECRET123\n"); os.symlink(f"{SRC}/a.json", f"{SRC}/ln.json")
check("분류: 정상 json", cs.classify_file(f"{SRC}/a.json", FakeMasker())[0] == "ok")
check("분류: 이미지는 저장하지 않는다", cs.classify_file(f"{SRC}/shots/s.png")[0] == "image")
for rel, why in ((".env", "비밀·키 이름"), ("leak.json", "비밀 패턴"), ("kr.txt", "비밀 패턴"), ("deck.pptx", "검사할 수 없는"), ("big.json", "한도"), ("ln.json", "심볼릭"), ("reg.json", "등록된 비밀")):
    k, r = cs.classify_file(f"{SRC}/{rel}", FakeMasker())
    check(f"분류: {rel} 는 보류({why})", k == "held" and why in r, (k, r))
rep = cs.import_files(STORE, "nixos", SRC, "proj", FakeMasker(), dry_run=True)
check("files: dry-run 은 쓰지 않는다", not os.path.exists(cs.files_dir(STORE, "nixos")) and len(rep["imported"]) == 2, rep["imported"])
rep = cs.import_files(STORE, "nixos", SRC, "proj", FakeMasker())
check("files: 정상 2개만 복사(재생성 폴더·이미지·비밀·검사 불가는 제외)", sorted(r for r, _ in rep["imported"]) == ["a.json", "sub/run.log"], rep)
check("files: 이미지 1개는 저장 안 함으로 센다", [r for r, _ in rep["images"]] == ["shots/s.png"])
check("files: 보류 7개", len(rep["held"]) == 7, rep["held"])
check("files: 바이트 동일", cs.file_hash(f"{STORE}/nixos/files/proj/a.json") == cs.file_hash(f"{SRC}/a.json"))
check("files: 별도 저장소로 커밋", rep["commit"] and subprocess.run(["git", "-C", cs.files_dir(STORE, "nixos"), "log", "--oneline"], capture_output=True, text=True).stdout.count("\n") == 1)
check("files: 바깥 저장소가 files/ 를 무시한다", "/files/" in open(f"{STORE}/nixos/.gitignore").read().splitlines() and subprocess.run(["git", "-C", f"{STORE}/nixos", "check-ignore", "-q", "files/proj/a.json"]).returncode == 0)
check("files: 바깥 저장소 추적 목록에 자료가 없다", "files/" not in subprocess.run(["git", "-C", f"{STORE}/nixos", "ls-files"], capture_output=True, text=True).stdout)
check("files: 다시 하면 전부 같음(멱등)", len(cs.import_files(STORE, "nixos", SRC, "proj", FakeMasker())["same"]) == 2)

# ---- 압축 파일 검사(풀지 않고 구성원마다) · 사용자 허용(import-held)
import zipfile, tarfile, io
AR = f"{TMP}/arch"; os.makedirs(AR)
def mkzip(name, members):
    with zipfile.ZipFile(f"{AR}/{name}", "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in members:
            z.writestr(n, d)
mkzip("good.pptx", [("[Content_Types].xml", "<a/>"), ("ppt/slides/slide1.xml", "<p><a:t>안녕</a:t></p>"), ("ppt/media/image1.png", b"\x89PNG\x00"), ("docProps/thumbnail.jpeg", b"\xff\xd8\x00")])
mkzip("split.pptx", [("ppt/slides/slide1.xml", "<a:t>비밀번호: </a:t><a:t>abc12345</a:t>")])
mkzip("split2.pptx", [("ppt/slides/slide1.xml", "<a:t>pass</a:t><a:t>word=hunter2hunter</a:t>")])
mkzip("keyed.zip", [("a/.env", "A=1")])
mkzip("binmem.zip", [("tool.exe", b"MZ\x00\x00")])
mkzip("slip.zip", [("../evil.txt", "x")])
inner = io.BytesIO()
with zipfile.ZipFile(inner, "w") as z: z.writestr("k.txt", "password=hunter2hunter")
mkzip("nest_secret.zip", [("in.zip", inner.getvalue())])
mkzip("bomb.zip", [(f"z{i}.txt", "0" * 4_000_000) for i in range(30)])
with tarfile.open(f"{AR}/good.tar.gz", "w:gz") as t:
    ti = tarfile.TarInfo("d/a.txt"); data = b"fine\n"; ti.size = len(data); t.addfile(ti, io.BytesIO(data))
with tarfile.open(f"{AR}/link.tar", "w") as t:
    ti = tarfile.TarInfo("l"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"; t.addfile(ti)
open(f"{AR}/corrupt.zip", "wb").write(b"PK\x03\x04junk")
def cls(n): return cs.classify_file_ex(f"{AR}/{n}", FakeMasker())
check("압축: 정상 pptx(xml·이미지)는 통과", cls("good.pptx")[0] == "ok", cls("good.pptx"))
check("압축: 태그로 쪼개진 한글 비밀번호도 잡는다(허용 불가)", cls("split.pptx")[0] == "held" and cls("split.pptx")[2] is False, cls("split.pptx"))
check("압축: 태그로 쪼개진 password= 도 잡는다", cls("split2.pptx")[0] == "held" and cls("split2.pptx")[2] is False, cls("split2.pptx"))
check("압축: 구성원의 비밀 이름(.env)은 허용 불가", cls("keyed.zip")[0] == "held" and cls("keyed.zip")[2] is False, cls("keyed.zip"))
check("압축: 검사할 수 없는 구성원은 보류하되 허용 가능", cls("binmem.zip")[0] == "held" and cls("binmem.zip")[2] is True, cls("binmem.zip"))
check("압축: 위험한 구성원 경로(..)는 허용 불가", cls("slip.zip")[0] == "held" and cls("slip.zip")[2] is False, cls("slip.zip"))
check("압축: 중첩 압축 안의 비밀도 잡는다", cls("nest_secret.zip")[0] == "held" and cls("nest_secret.zip")[2] is False and "in.zip" in cls("nest_secret.zip")[1], cls("nest_secret.zip"))
check("압축: 압축 폭탄(풀린 크기 합 한도)은 보류, 허용 가능", cls("bomb.zip")[0] == "held" and "폭탄" in cls("bomb.zip")[1], cls("bomb.zip"))
check("압축: tar.gz 정상은 통과", cls("good.tar.gz")[0] == "ok", cls("good.tar.gz"))
check("압축: tar 의 링크 구성원은 허용 불가", cls("link.tar")[0] == "held" and cls("link.tar")[2] is False, cls("link.tar"))
check("압축: 손상 압축은 보류(검사할 수 없는)", cls("corrupt.zip")[0] == "held" and "검사할 수 없는" in cls("corrupt.zip")[1] and cls("corrupt.zip")[2] is True, cls("corrupt.zip"))
rep = cs.import_files(STORE, "nixos", AR, "arch", FakeMasker())
check("압축: 폴더 반입은 통과한 것만(good.pptx·good.tar.gz)", sorted(r for r, _ in rep["imported"]) == ["good.pptx", "good.tar.gz"], rep["imported"])
rep = cs.import_files(STORE, "nixos", AR, "arch", FakeMasker(), allow=("binmem.zip", "split.pptx", "good.pptx", "nope.zip"), reason="시험")
check("허용: 검사만 못 한 binmem.zip 만 받는다", [r for r, _ in rep["overridden"]] == ["binmem.zip"] and os.path.exists(f"{STORE}/nixos/files/arch/binmem.zip"), rep)
check("허용: 비밀 후보(split.pptx)는 허용해도 안 받는다", any(r == "split.pptx" and "허용해도" in w for r, w in rep["refused"]) and not os.path.exists(f"{STORE}/nixos/files/arch/split.pptx"), rep["refused"])
check("허용: 보류 아닌 파일·없는 파일 허용은 거부로 보고", {r for r, _ in rep["refused"]} >= {"good.pptx", "nope.zip"}, rep["refused"])
check("허용: 커밋 메시지에 허용한 파일과 사유가 남는다", "binmem.zip" in subprocess.run(["git", "-C", cs.files_dir(STORE, "nixos"), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout and "사유: 시험" in subprocess.run(["git", "-C", cs.files_dir(STORE, "nixos"), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout)
check("files: 원본은 그대로", os.path.exists(f"{SRC}/a.json") and os.path.exists(f"{SRC}/shots/s.png"))
try:
    cs.import_files(STORE, "nixos", SRC, "../x", FakeMasker()); bad = False
except ValueError:
    bad = True
check("files: dest 에 .. 불가", bad)
check("files: 목록", sorted(r for r, _ in cs.list_files(STORE, "nixos", "proj")) == ["proj/a.json", "proj/sub/run.log"])

# 탐지기: 무시되는 비재생성 파일 중 ctx 에 없는 것
PR = f"{TMP}/projroot"; os.makedirs(f"{PR}/docs"); os.makedirs(f"{PR}/node_modules/q"); os.makedirs(f"{PR}/.claude/handoffs")
subprocess.run(["git", "init", "-q", PR], check=True)
open(f"{PR}/.gitignore", "w").write("/docs/\nnode_modules/\n/.claude/handoffs/\n/out.json\n")
open(f"{PR}/docs/n1.md", "w").write("문서 하나\n"); open(f"{PR}/docs/n2.md", "w").write("이미 ctx 에 있는 문서\n"); open(f"{PR}/docs/shot.png", "wb").write(b"\x89PNG")
open(f"{PR}/docs/data.json", "w").write("{}\n"); open(f"{PR}/node_modules/q/i.js", "w").write("x"); open(f"{PR}/.claude/handoffs/h.md", "w").write("캐시\n"); open(f"{PR}/out.json", "w").write("[]\n")
cs.propose(STORE, "sess-aud", "hostA", "nixos", "note", "aud/n2", cs.compose({"origin_path": "docs/n2.md"}, "이미 ctx 에 있는 문서\n"), None)
cs.process_inbox(STORE, FakeMasker())
res = cs.audit_project(STORE, "nixos", PR)
check("탐지: ctx 에 없는 문서·자료만 「없음」", sorted(res["missing"]) == ["docs/data.json", "docs/n1.md", "out.json"], res)
check("탐지: ctx 에 본문이 있는 문서는 「있음」, 이미지는 따로, 재생성물·캐시는 건너뜀", res["present"] == 1 and res["images"] == 1 and res["skipped"] >= 2, res)
os.makedirs(f"{PR}/docs/locked"); open(f"{PR}/docs/locked/x.json", "w").write("{}"); os.chmod(f"{PR}/docs/locked", 0)
try:
    res2 = cs.audit_project(STORE, "nixos", PR); ok_locked = res2["skipped"] >= 3
finally:
    os.chmod(f"{PR}/docs/locked", 0o755)
check("탐지: 권한이 없는 폴더에서 죽지 않고 건너뛴다", ok_locked)
shutil.copy(f"{PR}/docs/data.json", f"{STORE}/nixos/files/data.json") if False else None
os.makedirs(f"{STORE}/nixos/files/docs"); shutil.copy(f"{PR}/docs/data.json", f"{STORE}/nixos/files/docs/data.json")
check("탐지: files 에 같은 바이트가 있으면 「있음」", "docs/data.json" not in cs.audit_project(STORE, "nixos", PR)["missing"])

# ---------------------------------------------------------------- 5부: inotify 감시
VR = f"{VIEWS}/sess-watch"
cs.build_view(STORE, VIEWS, "sess-watch", "nixos")
lines = []
th = threading.Thread(target=lambda: cs.watch_view(VR, lines.append, poll=0.2, debounce=0.2), daemon=True)
th.start(); time.sleep(0.5)
wp = f"{VR}/nixos/plan/v0.md"
os.chmod(wp, 0o644); open(wp, "a").write("감시 시험\n")
t0 = time.time()
while not lines and time.time() - t0 < 5: time.sleep(0.1)
check("감시: 직접 수정이 즉시(수 초 안에) 한 줄로 알려진다", lines and "v0.md" in lines[0] and "propose" in lines[0], lines)
n = len(lines); open(wp, "a").write("또\n"); time.sleep(1.0)
check("감시: 같은 파일의 추가 수정도 새 해시면 다시 알린다", len(lines) == n + 1, lines)
check("감시: 뷰 갱신(자기 복사)은 알리지 않는다", (cs.build_view(STORE, VIEWS, "sess-watch", "nixos") and time.sleep(1.0) is None) and len(lines) == n + 1, lines)
open(f"{VR}/{cs.ENDED_FILE}", "w").write("1")
th.join(5)
check("감시: 종료 표식이 생기면 스스로 끝난다", not th.is_alive())

# 세션 프로세스가 죽으면 끝난다
cs.build_view(STORE, VIEWS, "sess-pid", "nixos")
proc = subprocess.Popen(["sleep", "30"])
res_box = []
th2 = threading.Thread(target=lambda: res_box.append(cs.watch_view(f"{VIEWS}/sess-pid", lambda s: None, pid=proc.pid, poll=0.2)), daemon=True)
th2.start(); time.sleep(0.5)
proc.kill(); proc.wait()
th2.join(5)
check("감시: 세션 프로세스(pid)가 죽으면 끝난다", not th2.is_alive() and res_box == [0])

# 동기화 담당 반복: 제안이 오면 처리한다
handled = []
stop = {"v": False}
w = threading.Thread(target=lambda: cs.watch_inbox(STORE, lambda: handled.append(cs.process_inbox(STORE, FakeMasker())), stop=lambda: stop["v"], poll=0.3), daemon=True)
w.start(); time.sleep(0.5)
hh = cs.read_doc(STORE, "nixos", "note", "m/new")["hash"]
code, msg, pid3 = cs.propose(STORE, "sess-watch2", "hostW", "nixos", "note", "m/new", "감시 중 제안\n", hh)
rj = cs.wait_result(STORE, pid3, 5)
check("동기화 담당: 제안이 오면 곧바로 처리해 결과를 남긴다(propose 가 기다리는 경로)", rj and rj["status"] == "applied", rj)
check("동기화 담당: 반영된 본문", cs.read_doc(STORE, "nixos", "note", "m/new")["body"] == "감시 중 제안\n")
stop["v"] = True; w.join(3)

# ---------------------------------------------------------------- 6부: 삭제 제안
code, msg, _ = cs.propose(STORE, "sess-del", "hostD", "nixos", "note", "m/new", "", None, op="delete")
check("삭제: 읽지 않은 문서는 거부", code == 1 and "읽어" in msg, msg)
check("삭제: 없는 문서는 거부", cs.propose(STORE, "sess-del", "hostD", "nixos", "note", "m/none", "", "abc", op="delete")[0] == 1)
code, msg, pid = cs.propose(STORE, "sess-del", "hostD", "nixos", "note", "m/new", "", "0" * 64, op="delete")
check("삭제: 오래된 판이면 충돌(지우지 않음)", code == 0 and cs.process_inbox(STORE, FakeMasker())[-1][1] == "conflict" and os.path.exists(cs.doc_path(STORE, "nixos", "note", "m/new")))
hh = cs.read_doc(STORE, "nixos", "note", "m/new")["hash"]
code, msg, pid = cs.propose(STORE, "sess-del", "hostD", "nixos", "note", "m/new", "", hh, op="delete")
res = cs.process_inbox(STORE, FakeMasker())[-1]
check("삭제: 읽은 판이 같으면 지우고 커밋", res[1] == "applied" and res[3] and not os.path.exists(cs.doc_path(STORE, "nixos", "note", "m/new")), res)
check("삭제: 비게 된 폴더 정리·프로젝트 폴더는 유지", not os.path.exists(f"{STORE}/nixos/note/m") and os.path.isdir(f"{STORE}/nixos"))
log = subprocess.run(["git", "-C", f"{STORE}/nixos", "log", "--oneline", "-1"], capture_output=True, text=True).stdout
check("삭제: git 이력에 삭제 커밋", "삭제 nixos/note/m/new" in log, log)
check("삭제: 이력에서 복구 가능", "감시 중 제안" in subprocess.run(["git", "-C", f"{STORE}/nixos", "show", "HEAD~1:note/m/new.md"], capture_output=True, text=True).stdout)

# ---------------------------------------------------------------- 6부: 읽기·쓰기 앞의 최신화(git pull --ff-only)
def _g(d, *a):
    return subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a], capture_output=True, text=True)

R = f"{TMP}/pull"; os.makedirs(R)
BARE, SRV, LAP = f"{R}/origin.git", f"{R}/srv", f"{R}/lap"
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", BARE], check=True)
subprocess.run(["git", "clone", "-q", BARE, SRV], capture_output=True)
os.makedirs(f"{SRV}/note"); open(f"{SRV}/note/a.md", "w").write("v1\n")
_g(SRV, "checkout", "-q", "-B", "main"); _g(SRV, "add", "-A"); _g(SRV, "commit", "-q", "-m", "c1"); _g(SRV, "push", "-q", "origin", "main")
os.makedirs(f"{R}/store")
subprocess.run(["git", "clone", "-q", BARE, f"{R}/store/proj"], capture_output=True)
PS = f"{R}/store"
os.environ["CTX_IS_WRITER"] = "0"; os.environ.pop("CTX_NO_PULL", None)

def push_new(text, msg):
    open(f"{SRV}/note/a.md", "w").write(text); _g(SRV, "add", "-A"); _g(SRV, "commit", "-q", "-m", msg); _g(SRV, "push", "-q", "origin", "main")

check("최신화: 받을 게 없으면 조용히(None)", cs.refresh_project(PS, "proj", force=True) is None)
push_new("v2\n", "c2")
check("최신화: 간격 안이면 읽기 앞에서는 건너뜀(낡은 채)", cs.refresh_project(PS, "proj", now=time.time()) is None and open(f"{PS}/proj/note/a.md").read() == "v1\n")
msg = cs.refresh_project(PS, "proj", now=time.time() + cs.PULL_INTERVAL + 1)
check("최신화: 간격이 지나면 받고 한 줄로 알림", msg and "커밋 1개" in msg and open(f"{PS}/proj/note/a.md").read() == "v2\n", msg)
push_new("v3\n", "c3")
msg = cs.refresh_project(PS, "proj", force=True)
check("최신화: force(쓰기 앞)는 간격과 무관하게 받는다", msg and open(f"{PS}/proj/note/a.md").read() == "v3\n", msg)
os.environ["CTX_IS_WRITER"] = "1"; push_new("v4\n", "c4")
check("최신화: 정본 호스트는 건드리지 않는다", cs.refresh_project(PS, "proj", force=True) is None and open(f"{PS}/proj/note/a.md").read() == "v3\n")
os.environ["CTX_IS_WRITER"] = "0"; os.environ["CTX_NO_PULL"] = "1"
check("최신화: CTX_NO_PULL=1 이면 건너뜀", cs.refresh_project(PS, "proj", force=True) is None and open(f"{PS}/proj/note/a.md").read() == "v3\n")
os.environ.pop("CTX_NO_PULL")
# 로컬 분기 — 덮어쓰지 않고 실패만 알림(--ff-only)
open(f"{PS}/proj/note/local.md", "w").write("로컬\n"); _g(f"{PS}/proj", "add", "-A"); _g(f"{PS}/proj", "commit", "-q", "-m", "local")
msg = cs.refresh_project(PS, "proj", force=True)
check("최신화: 로컬 분기면 덮지 않고 낡았을 수 있다고 알림", msg and "로컬 커밋" in msg and open(f"{PS}/proj/note/local.md").read() == "로컬\n", msg)
# 오프라인(원격이 사라짐) — 예외 없이 알림, 직후 읽기 앞에서는 다시 시도하지 않음
shutil.rmtree(BARE)
t0 = time.time(); msg = cs.refresh_project(PS, "proj", force=True)
check("최신화: 원격에 못 닿아도 예외 없이 알림", msg and "원격에 닿지 못했다" in msg and time.time() - t0 < cs.PULL_TIMEOUT + 5, msg)
check("최신화: 실패 직후 읽기 앞에서는 다시 기다리지 않는다", cs.refresh_project(PS, "proj", now=time.time()) is None)
# origin 이 없거나 저장소가 아니면 아무것도 안 한다
os.makedirs(f"{PS}/plain"); subprocess.run(["git", "init", "-q", f"{PS}/plain"], capture_output=True)
check("최신화: origin 없는 저장소는 건너뜀", cs.refresh_project(PS, "plain", force=True) is None)
check("최신화: 저장소가 아닌 폴더·없는 프로젝트는 건너뜀", cs.refresh_project(PS, "ghost", force=True) is None)
os.environ.pop("CTX_IS_WRITER", None)

# --- P1b: ctx msg 뷰 파일(msg/) — 쓰기·낡음 삭제·정리 기준
MV = f"{TMP}/msgviews"
S1, S2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
U1, U2 = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002"
p1 = cs.write_msg_file(MV, S1, U1, "h1", "# 머리", "본문 전체", pid=os.getpid())
check("msg 파일: 경로 <뷰>/<세션>/msg/<uuid>.txt", p1 == f"{MV}/{S1}/msg/{U1}.txt" and open(p1).read().splitlines()[0] == cs.MSG_HEAD + "h1")
check("msg 파일: 본문 전체가 들어 있다", "본문 전체" in open(p1).read() and "# 머리" in open(p1).read())
check("msg 파일: 파일 0400·폴더 0700", (os.stat(p1).st_mode & 0o777) == 0o400 and (os.stat(f"{MV}/{S1}/msg").st_mode & 0o777) == 0o700)
check("msg 파일: 임시 파일이 남지 않는다", not [f for f in os.listdir(f"{MV}/{S1}/msg") if f.endswith(".ctx-tmp")])
p1b = cs.write_msg_file(MV, S1, U1, "h2", "# 머리", "새 본문")
check("msg 파일: 같은 uuid 는 한 파일로 덮어쓴다", p1b == p1 and len(os.listdir(f"{MV}/{S1}/msg")) == 1 and "새 본문" in open(p1).read())
check("msg 파일: pid 가 있으면 .ctx-pid 기록, 이미 있으면 덮지 않는다", open(f"{MV}/{S1}/.ctx-pid").read() == str(os.getpid()))
cs.write_msg_file(MV, S1, U2, "h2", "# 머리", "둘째", pid=1); 
check("msg 파일: 기존 .ctx-pid 는 덮지 않는다", open(f"{MV}/{S1}/.ctx-pid").read() == str(os.getpid()))
for bad in ("../x", "x", "", None, S1 + "/.."):
    try:
        cs.write_msg_file(MV, bad, U1, "h", "", "x"); ok = False
    except ValueError:
        ok = True
    check(f"msg 파일: UUID 아닌 세션 {bad!r} 거부", ok)
try:
    cs.write_msg_file(MV, S1, "../../evil", "h", "", "x"); ok = False
except ValueError:
    ok = True
check("msg 파일: UUID 아닌 메시지 uuid 거부", ok and not os.path.exists(f"{MV}/evil"))
check("msg_files: 목록", sorted(cs.msg_files(MV)) == sorted([p1, f"{MV}/{S1}/msg/{U2}.txt"]))
gone = cs.sweep_stale_msgs(MV, "h2")
check("낡은 해시 삭제: 해시가 같은 파일은 둔다", gone == [] and len(cs.msg_files(MV)) == 2)
gone = cs.sweep_stale_msgs(MV, "h3")
check("낡은 해시 삭제: 해시가 다르면 모두 지운다", len(gone) == 2 and cs.msg_files(MV) == [])
cs.write_msg_file(MV, S1, U1, "h3", "", "x")
open(f"{MV}/{S1}/msg/{U2}.txt", "w").write("머리 없는 파일\n")
check("낡은 해시 삭제: 머리가 없거나 깨진 파일도 지운다", cs.sweep_stale_msgs(MV, "h3") == [f"{MV}/{S1}/msg/{U2}.txt"])
# 정리 기준: 오래된 .ctx-base.json 이 있어도 msg/ 에 새 파일을 쓰면 7일 뒤에도 안 지운다(.ctx-pid 없음 — CLAUDE_PID 가 빈 경우)
cs.build_view(STORE, MV, S2, "nixos")
old = time.time() - 9 * 86400
for r_, ds, fs in os.walk(f"{MV}/{S2}"):
    for x in ds + fs:
        os.utime(os.path.join(r_, x), (old, old))
os.utime(f"{MV}/{S2}", (old, old))
cs.write_msg_file(MV, S2, U1, "h3", "", "x")
os.utime(f"{MV}/{S2}", (old, old)); os.utime(f"{MV}/{S2}/.ctx-base.json", (old, old))
check("정리: base 가 오래돼도 msg/ 에 최근 파일이 있으면 둔다", S2 not in cs.cleanup_views(MV) and os.path.isdir(f"{MV}/{S2}"))
for f in os.listdir(f"{MV}/{S2}/msg"):
    os.utime(f"{MV}/{S2}/msg/{f}", (old, old))
os.utime(f"{MV}/{S2}/msg", (old, old))
check("정리: 전부 오래되고 프로세스도 없으면 지운다(msg/ 포함)", S2 in cs.cleanup_views(MV) and not os.path.exists(f"{MV}/{S2}"))
# base 없이 msg/ 만 있는 세션
S3 = "33333333-3333-3333-3333-333333333333"
cs.write_msg_file(MV, S3, U1, "h3", "", "x")
os.utime(f"{MV}/{S3}", (old, old))
check("정리: base 없이 msg/ 만 있고 방금 쓴 세션은 둔다", S3 not in cs.cleanup_views(MV))
cs.mark_ended(MV, S3)
check("정리: 종료 표식 뒤엔 msg/ 째 지운다", S3 in cs.cleanup_views(MV) and not os.path.exists(f"{MV}/{S3}"))

import shutil; shutil.rmtree(TMP, ignore_errors=True)
sys.exit(finish("ctx_store"))
