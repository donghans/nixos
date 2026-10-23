#!/usr/bin/env python3
"""QA 세션 시작 점검(읽기 전용). 사용: context.py [저장소경로]   (생략하면 현재 디렉터리의 저장소)

출력:
 - 저장소·브랜치·HEAD·미커밋 변경 수, git worktree 목록(QA 전용 작업 트리 확인용)
 - 저장소의 `.claude/donghans-instructions.md`(기본 원칙에 **추가 적용**)와 `.claude/donghans-override.md`(**충돌하면 이쪽이 우선**) 내용
   — 프로젝트 고유 QA 지침(계정·포트·스택 기동·결함 모양·커밋 규칙)을 추적 제외 파일에 두는 약속이다(donghans-handoff/resume 과 같은 규약).
 - 실행 파일 `.claude/qa-extra` 가 있으면 저장소 루트에서 실행해 출력을 덧붙인다(프로젝트 전용 사실 수집: 쓰는 스택·포트·열린 요청 등)
"""
import os
import subprocess
import sys


def sh(*cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return (r.stdout + r.stderr).strip()


start = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
repo = sh("git", "rev-parse", "--show-toplevel", cwd=start)
if not repo or repo.startswith("fatal"):
    sys.exit(f"git 저장소가 아니다: {start}")

print(f"# QA 시작 점검 — {repo}")
print("브랜치:", sh("git", "branch", "--show-current", cwd=repo) or "(detached)", "· HEAD:", sh("git", "log", "-1", "--format=%h %s", cwd=repo)[:100])
dirty = [l for l in sh("git", "status", "--porcelain", cwd=repo).splitlines() if l.strip()]
print(f"미커밋 변경: {len(dirty)}건" + (" (QA 는 시험 대상 커밋을 고정한 전용 작업 트리에서 코드를 읽는다 — donghans-qa §3)" if dirty else ""))
print("\n## git worktree")
print(sh("git", "worktree", "list", cwd=repo))

found = False
for nm, why in (("donghans-instructions.md", "추가 지침 — 기본 원칙에 더해 적용"), ("donghans-override.md", "오버라이드 — 충돌하는 기본 원칙보다 우선")):
    pf = os.path.join(repo, ".claude", nm)
    if os.path.isfile(pf):
        found = True
        print(f"\n## 프로젝트 지침: .claude/{nm} ({why})")
        print(open(pf, errors="ignore").read().strip())
if not found:
    print("\n(프로젝트 지침 파일 없음 — `.claude/donghans-instructions.md` 에 「QA 할 때」 절을 만들어 프로젝트 고유 QA 지침을 두면 다음 QA 세션이 이 출력으로 바로 받는다. "
          "추적 제외는 `.git/info/exclude` 에 `.claude/donghans-instructions.md` 추가)")

ex = os.path.join(repo, ".claude", "qa-extra")
if os.path.isfile(ex) and os.access(ex, os.X_OK):
    print("\n## 프로젝트 추가 사실 (.claude/qa-extra)")
    print(sh(ex, cwd=repo))
