---
name: donghans-procctl
description: 프로세스를 종료·정리할 때 pkill·killall·kill 대신 쓰는 procctl 사용법(plan → 사용자 확인 → apply → 필요하면 escalate). 「프로세스 죽여줘」「떠 있는 시험·서버·브라우저를 정리」「포트·메모리를 잡고 있는 프로세스」「좀비·멈춘 시험 프로세스」「pkill 해도 되나」를 하기 전에 먼저 읽는다. 자기 세션의 조상·다른 세션·시스템 프로세스를 죽이는 사고와 PID 재사용 오발송을 막고 모든 종료를 기록한다. 조회는 groups·show, 계획은 plan, 실행은 apply·escalate.
---

# donghans-procctl — 안전한 프로세스 정리 (LLM·사람용 비대화형 CLI)

`procctl` 은 사람용 TUI `procui` 와 **같은 코어**(스냅샷·그룹·보호·pidfd 종료·기록)를 명령줄로 연다. **프로세스를 종료할 때 `pkill`·`killall`·`kill`(이름·패턴·PID 직접 지정)을 쓰지 않는다.** 설계·배경: `_plan/procctl.md`, 구현 설명: `_docs/content/explanation/observe.md` 의 procctl 절.

## 순서 (반드시 plan → 확인 → apply)
```
procctl groups [--view 소유|앱|서비스|세션] [--filter 식] [--json]   # 무엇이 떠 있나(읽기 전용)
procctl show <pid|그룹> [--view V] [--json]                          # 세부 사용량·보호 사유(읽기 전용)
procctl plan --pid N … | --group 이름 | --filter 식 [--view V] [--with-children] [--scope session|user] [--ttl 초] [--json]
procctl apply <계획 ID> [--term-wait 3] [--json]                     # SIGTERM — 되돌릴 수 없음
procctl escalate <계획 ID> [--json]                                  # apply 뒤 살아남은 것에만 SIGKILL — 되돌릴 수 없음
procctl log [--tail N]                                               # 기록 조회
```
1. `plan` 은 **아무것도 죽이지 않는다.** 출력(대상·그룹·예상 확보 메모리·**보호로 제외된 것과 사유**·**범위 밖으로 제외된 것**·선택하지 않은 자식 수)을 사용자에게 그대로 보여 준다.
2. 사용자가 확인하면 `apply <ID>`. 이 도구와 Claude Code 권한 규칙 둘 다 apply·escalate 는 사용자 확인을 요구한다 — **확인 없이 우회하려 하지 말 것**(예: plan 을 건너뛰고 pkill, 다른 호출 경로로 같은 효과).
3. `apply` 뒤 「살아남음」이 있으면 그 목록을 보고하고 사용자가 원할 때만 `escalate <ID>`(SIGKILL).
4. 대상 지정은 **필수**다(전체 선택 없음). 이름 글롭만으로 곧바로 죽이는 명령은 없다.

## 에이전트(LLM 세션 안)의 제한 — 도구가 강제한다
- 기본 범위는 **자기 세션의 자식 트리**(자기가 띄운 시험·서버·모니터·브라우저). 그 밖(다른 세션의 자식·사용자의 앱)을 지정하면 「범위 밖」으로 제외되고 plan 이 거부(종료 코드 2)된다. 사용자 앱까지 정리해야 하면 `--scope user` 로 plan 을 만들되 반드시 사용자에게 먼저 물어본다.
- 대상은 한 번에 **최대 20개**(`--scope user` 로도 못 넘음). 넘으면 그룹·필터를 좁힌다.
- 자기가 만든 계획만 apply 할 수 있다(사람이 만든 계획·다른 세션의 계획은 거부).
- 보호는 **풀 수 없다**: 하드(PID 1·procui/procctl 자신과 그 모든 조상=터미널·tmux·이 세션·커널 스레드·다른 UID) + 소프트(컴포지터·패널·VM·컨테이너 데몬·nix 빌드·배포·세션 인프라·관측 수집기·LLM 세션 프로세스·`groups.toml` 의 `[protect]`). 소프트 보호 해제는 사람이 `procui` 에서만 한다. 「보호로 제외」가 나오면 그것을 죽이려고 다른 방법을 찾지 말고 사용자에게 알린다.
- 계획은 10분 뒤 만료되고, 파일을 고쳐 쓰면 거부된다(sig). 만료·거부되면 새로 plan 한다.

## 종료 코드와 JSON
0 성공 · 2 대상 없음/인자 오류/범위 밖·상한 초과 · 3 거부(만료·변조·이미 적용·호출자 권한·없는 계획) · 4 대상이 전부 보호로 제외 · 5 일부 거부·실패. `--json` 이면 같은 내용을 JSON 으로(plan: `targets`·`excluded`·`out_of_scope`·`children_separate`·`pss_kib`, apply: `sent`·`gone`·`refused`·`survivors`·`results`).

## 자주 쓰는 형태
- 내가 띄운 시험 서버 정리: `procctl groups --view 세션` 으로 자기 세션 그룹 확인 → `procctl plan --filter 이름 --json` (범위 기본이 자기 세션) → 사용자 확인 → `procctl apply <ID>`.
- 특정 pid 가 무엇인지: `procctl show <pid>` (그룹·보호 사유·세부 사용량).
- 자식까지: `plan --pid N --with-children` (선택하지 않은 자식은 부모가 죽어도 남는다 — 미리보기에 개수가 나온다).
- 무엇이 메모리를 먹나는 `donghans-host-resources`(「소비자 상위」·「메모리 대기를 만든 cgroup」) 로 먼저 본다. procctl 은 정리 도구다.

## 한계(있는 그대로 보고)
- 컨테이너(Docker)·incus VM 내부 프로세스는 호스트에서 보이는 만큼만 다룬다. 컨테이너 자체는 `docker`·`incus` 로(사용자 확인).
- 종료한 프로세스가 곧바로 다시 뜨는지(서비스 재시작 정책)는 모른다 — apply 뒤 `groups` 로 확인한다.
- 사람이 직접 보며 고르는 일은 `procui`(TUI)가 낫다. 소프트 보호 해제도 거기서만.
