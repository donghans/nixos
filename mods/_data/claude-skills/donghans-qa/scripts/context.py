#!/usr/bin/env python3
"""QA 세션 시작 점검 + 프로젝트 지침 파일 초기화.

사용:
  context.py [저장소경로]          읽기 전용 점검(기본). 저장소 경로를 생략하면 현재 디렉터리의 저장소.
  context.py [저장소경로] --init   처음 보는 프로젝트용: `.claude/donghans-instructions.md` 틀을 만들고(있으면 건드리지 않음)
                                   `.git/info/exclude` 에 추적 제외 항목을 추가한다(멱등). 아무것도 덮어쓰거나 커밋하지 않는다.

출력(점검):
 - 저장소·브랜치·HEAD·미커밋 변경 수, git worktree 목록(QA 전용 작업 트리 확인용)
 - 프로젝트의 `.claude/donghans-instructions.md`(기본 원칙에 **추가 적용**)와 `.claude/donghans-override.md`(**충돌하면 이쪽이 우선**) 내용,
   실행 파일 `.claude/qa-extra` 가 있으면 그 출력(프로젝트 전용 사실 수집: 쓰는 스택·포트·열린 요청 등)
 - 이 파일들은 **추적 제외라서 메인 체크아웃에만 있다.** git worktree(예: QA 전용 작업 트리)에서 실행해도 메인 체크아웃에서 찾아 읽는다.
 - 파일이 있는데 추적 제외가 안 돼 있으면(실수로 커밋될 수 있음) 경고한다.
"""
import os
import subprocess
import sys

NAMES = ("donghans-instructions.md", "donghans-override.md", "qa-extra")
EXCLUDE_LINES = [f".claude/{n}" for n in NAMES]
WHY = {"donghans-instructions.md": "추가 지침 — 기본 원칙에 더해 적용", "donghans-override.md": "오버라이드 — 충돌하는 기본 원칙보다 우선"}

TEMPLATE = """# {proj} 추가 지침 (donghans 스킬에 더해 적용 — 이 머신 전용, 추적 제외)
<!-- 이 파일은 git 에 올리지 않는다(.git/info/exclude). 다른 머신·다른 사람에게는 보이지 않는다 — 공유해야 하는 프로젝트 사실은 추적되는 문서에 쓴다. -->
<!-- 아는 것만 쓰고, 모르는 칸은 「미확인」이라고 적는다(지어내지 않는다). 확인한 날짜를 붙이면 낡았는지 판단하기 쉽다. -->

## QA 할 때 (donghans-qa · donghans-qa-desktop 에 더해)
- **역할·보고**: 누가 고치고 누가 재나(수정 세션 주소는 `ListAgents`), 보고 문서 위치·형식, 시험 대상 커밋을 적는 곳:
- **대상과 기동**: 확인할 화면·API 의 주소, 스택을 띄우는 법(별도 compose 프로젝트명·포트 대역 규칙), 「시험할 수 있는 상태」 확인법(시드 로그·로그인):
- **계정·데이터 정책**: 쓸 수 있는 시험 계정(비밀번호는 여기 적지 말고 어디에 있는지만), 실데이터·외부 연동이 걸린 화면은 사용자 승인 전 금지인지, 되돌릴 수 없는 쓰기의 시험 규칙:
- **브라우저**: headless 는 어디서(호스트/Docker/VM), headed 확인은 qa-desktop VM 의 `--class=<이름>-qa` · 가상 데스크톱 번호:
- **커밋·푸시 규칙**: QA 문서 커밋 방식(경로만·브랜치·트레일러), 푸시 허가 범위:
- **알려진 미검증·함정**:
- **하네스·게이트 결함을 한 줄 남길 위치**:

<!-- 필요하면 `## resume 할 때`, `## handoff 할 때` 절을 추가한다(donghans-resume / donghans-handoff 가 읽는다). -->
"""


def sh(*cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return (r.stdout + r.stderr).strip(), r.returncode


def roots(start):
    """(현재 작업 트리 루트, 메인 체크아웃 루트, 공통 .git 디렉터리). 추적 제외 파일은 메인 체크아웃에만 있다."""
    top, rc = sh("git", "rev-parse", "--show-toplevel", cwd=start)
    if rc != 0:
        sys.exit(f"git 저장소가 아니다: {start}")
    common, _ = sh("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=start)
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else top
    return top, main, common


def find_file(name, top, main):
    for base in dict.fromkeys([top, main]):   # 현재 작업 트리 → 메인 체크아웃 순
        p = os.path.join(base, ".claude", name)
        if os.path.isfile(p):
            return p, base
    return None, None


def is_ignored(path, repo):
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=repo).returncode == 0


def is_tracked(path, repo):
    return subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=repo, capture_output=True).returncode == 0


def do_init(top, main):
    excl, _ = sh("git", "rev-parse", "--path-format=absolute", "--git-path", "info/exclude", cwd=main)
    os.makedirs(os.path.dirname(excl), exist_ok=True)
    cur = open(excl).read() if os.path.exists(excl) else ""
    add = [l for l in EXCLUDE_LINES if l not in cur.splitlines()]
    if add:
        with open(excl, "a") as f:
            if cur and not cur.endswith("\n"):
                f.write("\n")
            f.write("# donghans 워크스테이션 도구의 프로젝트별 지침(추적 제외, 이 머신 전용)\n" + "\n".join(add) + "\n")
    print(f"추적 제외 파일: {excl}  (추가 {len(add)}줄{'' if add else ' — 이미 있음'})")
    target = os.path.join(main, ".claude", "donghans-instructions.md")
    if os.path.exists(target):
        print(f"지침 파일이 이미 있어 건드리지 않음: {target}")
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "w").write(TEMPLATE.format(proj=os.path.basename(main)))
        print(f"틀을 만들었다: {target}  — 아는 사실만 채우고 모르는 칸은 「미확인」으로 둔다")
    for rel in EXCLUDE_LINES:
        p = os.path.join(main, rel)
        if is_tracked(p, main):
            print(f"! {rel} 는 이미 git 에 추적되고 있어 추적 제외가 적용되지 않는다(git rm --cached 가 필요 — 사용자와 상의)")
        elif not is_ignored(p, main):
            print(f"! {rel} 가 추적 제외로 인식되지 않는다 — {excl} 를 확인")
    print("확인: `git status --short` 에 .claude/donghans-* 가 나타나면 안 된다.")


def sync_instructions(cwd):
    """프로젝트 지침을 공유 저장소(ctx)와 맞춘다 — SessionStart 훅이 못 돌았을 때(래퍼 없이 시작한 세션 등)를 위한 보강. 접속 실패는 조용히 로컬 파일을 쓴다."""
    try:
        r = subprocess.run(['donghans', 'instr', 'sync', '--quiet'], cwd=cwd, capture_output=True, text=True, timeout=8)
        return r.stdout.strip() if r.returncode == 0 else '(공유 저장소 접속 실패 — 로컬 파일을 그대로 쓴다)'
    except Exception:
        return ''


def main_():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    init = "--init" in sys.argv[1:]
    start = os.path.abspath(args[0]) if args else os.getcwd()
    top, main, common = roots(start)
    if init:
        do_init(top, main)
        return

    print(f"# QA 시작 점검 — {top}" + (f"  (메인 체크아웃: {main})" if top != main else ""))
    br, _ = sh("git", "branch", "--show-current", cwd=top)
    head, _ = sh("git", "log", "-1", "--format=%h %s", cwd=top)
    print("브랜치:", br or "(detached)", "· HEAD:", head[:100])
    dirty = [l for l in sh("git", "status", "--porcelain", cwd=top)[0].splitlines() if l.strip()]
    print(f"미커밋 변경: {len(dirty)}건" + (" (QA 는 시험 대상 커밋을 고정한 전용 작업 트리에서 코드를 읽는다 — donghans-qa §3)" if dirty else ""))
    print("\n## git worktree")
    print(sh("git", "worktree", "list", cwd=top)[0])

    _sy = sync_instructions(main)
    if _sy:
        print("\n## 프로젝트 지침 동기화(공유 저장소)"); print(_sy)
    found = False
    for nm in NAMES[:2]:
        pf, base = find_file(nm, top, main)
        if not pf:
            continue
        found = True
        where = "" if base == top else f" — 메인 체크아웃에서 읽음: {pf}"
        print(f"\n## 프로젝트 지침: .claude/{nm} ({WHY[nm]}){where}")
        print(open(pf, errors="ignore").read().strip())
        if not is_ignored(pf, base):
            print(f"\n! 경고: {pf} 가 추적 제외로 인식되지 않는다 — 실수로 커밋될 수 있다. `context.py --init` 이 추적 제외 항목을 추가한다.")
    if not found:
        print("\n(프로젝트 지침 파일 없음 — 처음 보는 프로젝트이거나 이 머신에 아직 안 만들었다. "
              "`python3 <이 스킬>/scripts/context.py --init` 으로 틀과 추적 제외 설정을 만들 수 있다. "
              "다른 머신에서 만든 지침은 이 머신에 없다 — 파일은 머신마다 따로다.)")

    ex, base = find_file("qa-extra", top, main)
    if ex and os.access(ex, os.X_OK):
        print("\n## 프로젝트 추가 사실 (.claude/qa-extra)")
        print(sh(ex, cwd=base)[0])


main_()
