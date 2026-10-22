---
name: donghans-handoff
description: 어느 저장소에서든 세션을 닫거나 /clear 하기 전에, 다음 세션이 되묻지 않고 이어갈 수 있도록 현재 상태·상시 지시·열린 결정·다음 단계를 HANDOFF 문서로 정리하고, 현재 세션 ID 를 고유번호로 등록해 `/donghans-resume <고유번호>` 안내를 출력한다. 사용자가 「인수인계」「handoff」「세션 정리」라고 하거나 컨텍스트가 커져 /clear 직전일 때 호출한다.
---

# donghans-handoff — 세션 인수인계 작성 (범용)

**원칙: 다음 세션이 사용자에게 되묻지 않고 이어갈 수 있을 만큼의 확실한 정보만, 오해 없는 표현으로.** 사실(코드·git 으로 확인) / 추정 / 사용자 발언 / 에이전트 보고를 섞지 않는다.


## 프로젝트별 지침 (선택, 보통 `.git/info/exclude` 로 추적 제외)
저장소 루트의 `.claude/donghans-instructions.md`(기본 절차에 **추가 적용**)와 `.claude/donghans-override.md`(기본 절차와 **충돌하면 이쪽이 우선**)가 있으면 따른다. **절차 시작 전에 두 파일이 있으면 읽는다**(`cat <저장소>/.claude/donghans-{instructions,override}.md`). 문서 형식·커밋 규약·갱신할 상태 파일 등 저장소 고유 규칙은 여기에 있다. resume 쪽도 같은 파일을 읽으므로 인수인계에 적을 때 그 전제를 두어도 된다.

## 절차
1. **지금의 사실을 먼저 얻는다(기억으로 쓰지 않는다):** `git status --short`, `git log -1`, `git worktree list`, 미병합 브랜치(`git log --oneline HEAD..<br>`), 진행 중 백그라운드 작업. 
2. **상시 지시를 모은다:** 이 대화에서 사용자가 준 방침·금지·선호를 원문에 가깝게. 직전 HANDOFF 문서의 상시 지시 중 아직 유효한 것은 유지. 사용자의 환경 규칙은 `~/.claude/CLAUDE.md` 가 이미 로드되므로 반복하지 않는다.
3. **문서를 쓴다:** 기본 위치는 **저장소의 추적 제외 경로 `.claude/handoffs/HANDOFF-<세션ID>.md`** (`echo $CLAUDE_CODE_SESSION_ID` 전체 — **날짜가 아니라 세션 ID 로 이름을 짓는다**: 같은 저장소에서 여러 세션(수정·QA 등)이 동시에 인수인계해도 서로 덮어쓰지 않는다) (없으면 만들고 `.git/info/exclude` 에 `.claude/handoffs/` 가 있는지 확인해 없으면 추가). 이 스킬의 목적은 *이 머신에서 빠르게 컨텍스트를 복원*하는 것이지 이력 공개가 아니다. 프로젝트 지침 파일이 다른 위치를 지정할 때만 따른다. 같은 세션에서 다시 인수인계하면 그 파일을 갱신한다. 이어받은 이전 인수인계가 있으면 frontmatter `supersedes` 에 그 ID 를 적는다. **최대 약 120줄.**
   - frontmatter: `version`, `updated`, `status`, `handoff_id: $CLAUDE_CODE_SESSION_ID`(`echo $CLAUDE_CODE_SESSION_ID`), `branch/HEAD(푸시 여부)`, `supersedes`
   - 본문: 0 상시 지시 · 1 현재 상태(확인 방법/날짜) · 2 미병합·미완 작업(브랜치·SHA·검증 여부) · 3 다음 할 일(순서·예상 비용·위험) · 4 열린 결정(추천 답 포함) · 5 함정과 환경 팁 · 6 다른 세션/사람과의 연결 · 7 못 쟀거나 낡았을 수 있는 것
   - 채팅에서만 있던 결정·전언은 출처를 붙인다. 코드로 확인하지 않은 것은 「추정」.
4. **커밋·푸시하지 않는다**(추적 제외 문서이므로 커밋할 것이 없다). 저장소의 추적 파일(상태 문서 등)은 사용자가 요청하거나 프로젝트 지침이 명시할 때만 고친다.
5. **등록하고 안내한다:** `python3 ~/.claude/skills/donghans-handoff/scripts/register.py --doc <문서경로> [--note "한 줄"]` — 이 세션 ID 를 고유번호로 `~/.claude/handoffs/<ID>.json` 에 (저장소·문서·HEAD)를 기록하고 아래 문구를 출력한다. **출력된 문구를 그대로 사용자에게 전달**한다:
   > 새 세션에서 `/donghans-resume <고유번호>` 를 입력해주세요!
   그리고 새 세션에서 달라지는 것(세션 ID, 백그라운드 작업·워크플로우 resume 불가, 다른 세션과의 연결 주소)을 한 줄씩 알린다.
