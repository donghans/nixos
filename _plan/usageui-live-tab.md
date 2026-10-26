# usageui 「실시간」 탭 + 측정 모듈 분리 — 계획

상태: **구현·시험 완료, 아직 커밋·배포(`nixup` 적용) 전** — 결과는 문서 맨 아래 「구현 결과」. 작성 2026-10-26. 짝 문서: `_plan/procui.md`(프로세스 관리 별도 UI). 이 문서의 「단계 0」(측정 모듈 분리)은 두 문서가 함께 쓰는 선행 작업이다.

## 0. 이 문서를 읽기 전에 (용어)

| 이름 | 뜻 |
|---|---|
| usageui | 전력·자원 사용 **습관**을 시간축(7일 등)으로 보는 Textual(파이썬 TUI 라이브러리) 앱. 본체 `mods/_data/observe/usageui.py`. 수집기(observe)가 저장한 기록을 읽는다 |
| observe / observectl | 루트 수집기와 조회 CLI. 프로세스를 이름(comm·exe)만으로 기록하고 명령 인자·창 제목은 기록하지 않는다(개인정보 원칙) |
| hostres | Claude Code 스킬 `donghans-host-resources` 의 스크립트 `mods/_data/claude-skills/donghans-host-resources/scripts/hostres.py`(651줄). 이 호스트의 가용 자원을 5초 구간으로 재고 판정(여유/주의/압박/심각)·LLM 세션별 사용량을 낸다 |
| uikit | 우리 TUI 들이 공유하는 겉모습·공통 동작 `mods/_data/_uikit/uikit.py`(btop 같은 제목 테두리 박스, 도움말, 포커스 잃으면 갱신 멈춤) |
| PSI | 커널 압박 지표 `/proc/pressure/{memory,cpu,io}`. 「자원이 모자라 실제로 대기했는가」를 비율로 준다. 사용량(%)과 다르다 |
| PSS | 공유 페이지를 나눠 계산한 프로세스 메모리. 합계가 겹치지 않는다 |
| 보수적 가용 | 빈 메모리 + 식은(비활성) 파일 캐시. 커널 `MemAvailable` 은 활성 캐시까지 더한 낙관값이라 용량 계획에는 보수적 값을 쓴다 |

## 1. 배경 — 일어난 일(조사 이력)

이 절은 결정이 아니라 지금까지 알아낸 사실이다. 등급: **직접확인**=이 세션이 파일을 읽거나 명령을 실행해 확인, **미재확인**=기억·일반 지식으로 적었고 확인하지 않음.

1. 사용자는 이전에 htop 을 쓰다 네트워크 사용량이 안 보여 btop 으로 옮겼다(사용자 진술). 현재 btop 은 1.4.7(직접확인: `btop --version`). 설정은 `mods/sys/base/core.nix:126` 의 home-manager `programs.btop`(직접확인).
2. btop 의 메모리 칸은 `MemAvailable`·buff/cache 중심으로 보인다 — **미재확인**(btop 소스·화면을 이 세션에서 확인하지 않음). 반면 hostres 의 SKILL.md 는 buff/cache 에 tmpfs·공유메모리(Shmem)가 섞여 사실상 사용 중이므로 그 값만으로 압박을 판정하면 안 된다고 한다(직접확인: `~/.claude/skills/donghans-host-resources/SKILL.md` 「출력 읽는 법」). 이 때문에 「btop 같은 실시간 모니터에서도 진짜 여유를 직관적으로 보고 싶다」는 요구가 나왔다.
3. btop 에는 외부 스크립트·플러그인 위젯 기능이 없어 hostres 판정을 btop 화면에 넣을 수 없다고 판단했다 — **미재확인**(1.4.7 의 설정 항목 전체를 확인하지 않음).
4. 사용자 정정: usageui 는 **긴 호흡 주기**를 보는 도구로 만든 것이다. 그래서 usageui 의 기존 탭에 실시간 판정을 섞지 않고, **시간축 그래프가 없는 순간값만** 보이는 별도 탭으로 둔다(사용자 지시).
5. 현재 usageui 구조(직접확인): 탭 5개(대시보드·앱·원인·시스템·용어, `usageui.py:171-209`), 키 바인딩 `usageui.py:144-148`(1~5 탭 전환, `b` 로 btop 실행 = `action_btop` `usageui.py:450`), 탭은 처음 열 때 불러오는 지연 로딩(`_lazy`, `usageui.py:319`).
6. 설치 방식(직접확인): usageui 소스는 `mods/sys/services/observe.nix:18` 의 파일 목록을 store 로 복사해 `usageui` 실행 파일로 만든다(`observe.nix:24`, 런처 항목 `observe.nix:60`). uikit 도 같은 방식으로 복사한다(`observe.nix:20`).
7. hostres 구조(직접확인): 측정·판정 함수가 `hostres.py` 한 파일에 있고(`meminfo`·`vmstat`·`psi`·`swaps`·`tmpfs_use`·`cgroup_consumers`·`snapshot`·`verdict` 등), 같은 파일에 출력 조립(`render`·`summary`·`main`)이 있다. `--json` 출력이 이미 있다. 스킬 폴더는 `llm-cli.nix:353-354` 에서 통째로 `~/.claude/skills/` 에 링크된다.
8. SKILL.md 는 스크립트를 `python3 -I`(격리 모드)로 실행하도록 안내한다. 같은 폴더의 모듈을 import 하는 작은 임시 스크립트로 시험하면 `-I` 에서는 `ModuleNotFoundError`, `-I` 없이는 성공한다(무맥락 검증 에이전트가 직접 확인). 작업 폴더가 그 폴더여도 `-I` 에서는 실패한다. 따라서 hostres.py 는 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` 를 명시해야 한다.
9. 분리 대상 함수가 그대로 폴링에 쓸 수 있는 것은 아니다(무맥락 검증 에이전트가 hostres.py 를 읽고 확인, 이 세션이 `snapshot` 은 재확인): `snapshot(secs)` 는 `time.sleep(secs)` 를 내장하고 0 시점·1 시점 표본과 차이 계산을 한 함수에 담는다(`hostres.py:110-120`). `session_meta`·`ctx_last_chat` 은 transcript 를 읽고 없으면 `donghans ctx sql` 을 subprocess 로 부른다. `history` 는 Netdata 에 HTTP 요청을 보낸다. 1초 폴링에 그대로 넣으면 안 된다.
10. usageui 의 기존 원칙(직접확인: `usageui.py:3-4`): 「갱신은 수동만(타이머 없음 — r/F5)」. 실시간 탭은 이 원칙의 **예외**가 된다. 현재 `usageui.py` 에는 `set_interval`·`PauseOnBlurMixin` 사용이 없다(검증 에이전트 확인) — uikit 믹스인 적용은 새 작업이다.
11. `observe_apps.app_name` 은 electron 앱의 이름을 정하려고 루트 프로세스의 명령줄을 **읽는다**(저장·표시는 안 함, `observe_apps.py` 머리말). 이 문서·procui 에서 앱 규칙을 재사용할 때도 「읽되 저장·표시하지 않는다」를 지킨다.

## 2. 하기로 한 일(계획)

### 2.1 목표
usageui 에 **「실시간」 탭**을 추가한다. 화면은 btop 처럼 제목 달린 박스 몇 개. 모두 **지금 값**(최근 1~2초 변화율 포함)만 보여 주고 시간축 그래프(스파크라인 포함)는 넣지 않는다.

### 2.2 박스 구성(초안)
1. **판정**: 여유/주의/압박/심각 + 이유 한두 줄(hostres 의 `verdict` 와 같은 로직).
2. **메모리 구성**: 가로 막대 하나로 「실제 사용(anon) / 식은 캐시 / tmpfs·Shmem / 빈 메모리」, 아래에 보수적 가용 vs `MemAvailable` 두 값, 스왑 종류(zram/disk)·사용량.
3. **압박**: PSI(cpu·memory·io 의 some/full 최근 구간), pswpin/s·pswpout/s.
4. **CPU·IO·네트워크 속도**: 코어별 사용률 막대, 디스크 읽기/쓰기 B/s, 네트워크 인터페이스별 수신/송신 B/s.
5. **상위 소비자**: cgroup 기준 메모리 상위(hostres `cgroup_consumers`), 앱(observe 앱 규칙 `observe_apps.app_name`, 명령줄은 읽되 저장·표시 안 함) 기준 CPU 상위.
6. **LLM 세션**: hostres 의 세션 표 요약(작동중/대기, PSS, 서브에이전트 수).

### 2.3 동작 규칙
- 샘플링은 **이 탭이 활성일 때만** 돈다(1초 간격, 변경 가능). 다른 탭으로 가거나 창이 포커스를 잃으면 멈춘다(uikit 의 `PauseOnBlurMixin` 재사용).
- 읽기 전용. 아무것도 종료·변경하지 않는다. 프로세스 관리가 필요하면 `procui`(짝 문서)나 btop(`b` 키)로 넘긴다.
- 값은 증분(두 시점 차이)이 필요한 항목만 이전 표본을 기억한다. 이력은 저장하지 않는다.
- 권한: 일반 사용자 권한으로 읽는다. 다른 사용자 프로세스의 PSS 는 못 읽으므로(`/proc/<pid>/smaps_rollup` 권한 — 미재확인) 그 영역은 cgroup 메모리로 대신하고 화면에 「못 쟀음」으로 표시한다.

### 2.4 단계

**단계 0 — 측정 모듈 분리(두 계획의 선행 작업)**
- hostres.py 에서 **출력이 없는 측정·판정·세션 수집 함수**를 `scripts/hostmetrics.py` 로 옮긴다. hostres.py 는 이 모듈을 import 해 출력만 조립한다(print 는 `main` 에만 있음 — 검증 에이전트 확인).
- `snapshot(secs)` 는 그대로 옮기지 않고 **`begin()`(0 시점 표본)과 `end(begin)`(1 시점 표본·변화율)로 쪼갠다.** hostres 의 `snapshot(secs)` 는 둘을 이어 붙인 얇은 래퍼로 남긴다. 실시간 탭은 `end` 호출마다 직전 표본을 새 `begin` 으로 넘겨 1초 증분을 만든다.
- **폴링에 쓸 수 없는 것은 분리하되 실시간 탭이 호출하지 않는다**: Netdata 이력(`history`), ctx 보충(`donghans ctx sql` subprocess). 실시간 탭의 세션 박스는 로컬 `~/.claude/sessions/<pid>.json` 상태·프로세스 트리만 쓰고 ctx 는 부르지 않는다(보충 항목은 「—」). PSS 전체 순회(`pss_kib`)는 5초 간격으로 따로 돌려 값을 재사용한다.
- 정본은 스킬 폴더 안(`mods/_data/claude-skills/donghans-host-resources/scripts/hostmetrics.py`)에 둔다. `observe.nix` 의 복사 목록에서 이 파일을 같은 store 디렉터리로 복사해 usageui·procui 가 import 한다(복제본을 따로 두지 않는다 — 어긋남 방지).
- `python3 -I` 에서 import 가 되는지 먼저 확인하고, 안 되면 `sys.path.insert(0, 스크립트 폴더)` 를 hostres.py 에 명시한다.
- 합격 기준: ①분리 전후 `hostres.py --json --secs 0` 출력의 **키 구조가 동일**(값은 시점마다 다름; `--no-sessions` 는 세션 키가 비어 구조 비교가 안 되므로 쓰지 않는다. 세션 항목은 세션이 있을 때와 없을 때를 각각 비교) ②`hostres.py` 일반 실행 출력의 절 구성이 동일 ③측정 모듈에 print 가 없음 ④단위 시험(`mods/_data/observe/tests/` 형식) 추가.

**단계 1 — 실시간 탭**
- `usageui.py` 에 탭 추가(키 `6`; 기존 5개 키·순서는 바꾸지 않음), 박스 위젯은 `uikit.box` 사용.
- usageui 머리말 원칙 ②를 「갱신은 수동만(단, 실시간 탭만 타이머로 갱신하고 그 탭이 활성일 때만 돈다)」으로 고치고, 도움말(`?`)·용어 탭에도 같은 예외를 적는다. `PauseOnBlurMixin` 은 usageui 의 App 에 새로 적용한다.
- 샘플링 루프는 별도 모듈(`usagelive.py`)로 두어 위젯 없이 단위 시험 가능하게 한다.
- 합격 기준: ⓪실시간 탭 한 번 갱신에 걸리는 시간을 재고, 간격(1초)의 20%를 넘으면 간격을 늘리는 규칙을 기본값에 반영 ①Textual 헤드리스 시험(`App.run_test`)으로 탭 전환·샘플링 시작/정지(탭 이탈 시 타이머 정지) ②hostres 와 같은 시점 값 대조(판정·보수적 가용이 허용 오차 내 일치) ③실시간 탭 활성 상태에서 usageui 프로세스 CPU 를 hostres 의 프로세스 표 또는 `ps` 로 재서 기록 ④기존 `test_usage.py` 전부 통과.

**단계 2 — 문서화**
- usageui 를 언급하는 `_docs/content/explanation/observe.md`(검증 에이전트 확인: `observectl.md` 는 없음), `claude-sessions.md`, `power-evidence.md` 중 해당 부분에 탭이 하나 늘었고 「수동 갱신만」 원칙에 예외가 생겼음을 반영.
- **`observe.nix` 의 hostmetrics 복사(및 usageui·procui 가 같은 store 디렉터리를 쓰게 하는 일)는 이 문서의 단계 0 이 맡는다.** `_plan/procui.md` 는 이를 전제로만 한다.

## 3. 아직 안 정해진 일(열린 질문)

| 질문 | 기본값(사용자 답이 없으면 이대로 진행) |
|---|---|
| 노트북(msi-summit-me)에서도 이 탭을 쓰나? 관측 수집은 노트북에서 기본 꺼짐이고 전력 측정에 변수를 섞지 않으려는 정책이다. 이 탭은 UI 프로세스가 직접 샘플링하므로 사용 중에는 전력 시험에 영향을 줄 수 있다 | 탭은 모든 호스트에 두되, 전력 시험 중에는 열지 않는다고 도움말에 명시. 노트북 상시 폴링 없음(탭 활성 때만) |
| 샘플링 간격 | 1초 |
| 키 `6` 로 충분한가(도움말·용어 탭 번호 변동) | 용어 탭 `5` 는 그대로 두고 실시간은 `6` |
| 박스 6개 중 줄일 것 | 처음엔 6개 모두, 써 보고 정리 |

## 4. 범위 밖 / 확인하지 못한 것
- 프로세스 단위 관리(종료·필터·그룹)는 `_plan/procui.md`.
- btop 설정 변경은 하지 않는다. btop 의 `MemAvailable` 중심 표시를 실제 화면으로 확인하지 않았다(§1-2).
- 다른 머신(노트북·원격)에서의 동작은 확인하지 않았다. 이 세션의 호스트는 beelink 이다.
- 이 계획은 아직 구현·시험하지 않았다. 「합격 기준」은 목표이지 달성 결과가 아니다.
- 저장소에는 이 계획과 무관한 미커밋 변경(`mods/devel/apps/llm-cli.nix`)이 있다. 구현 중 그 파일을 되돌리거나 함께 커밋하지 않는다(단 단계 0 이 `observe.nix` 외에 `llm-cli.nix` 를 건드릴 필요는 없다).

## 5. 구현 결과 (2026-10-26, beelink-ser7-co 에서 직접 실행·확인)

이 절은 「일어난 일」이다. 위 절들의 「합격 기준」은 계획 당시의 목표였고, 아래가 실제 결과다.

**단계 0 — 측정 모듈 분리: 완료**
- `scripts/hostmetrics.py`(438줄, print 0건 — `test_hostmetrics.py` 가 확인) 신설, `hostres.py` 는 651 → 238줄. `snapshot(secs)` 는 `begin()`·`end(b, measured)` 로 쪼개고 얇은 래퍼로 남겼다. `session_meta(use_ctx=False)`·`sessions_end(..., use_ctx=False)` 옵션을 추가해 폴링에서 ctx 저장소를 부르지 않게 했다.
- 분리 전후 `python3 -I hostres.py --json --secs 0 --hist 0` 출력의 **키 구조 동일**(69개 키 경로, 차집합 0) · 일반 출력의 절 제목 구성 동일(요약·이 호스트·읽는 법·호스트 자원·LLM 세션). 세션이 있는 상태에서만 비교했다 — 세션이 하나도 없는 상태의 구조는 비교하지 못했다.
- `python3 -I hostres.py` 가 import 오류 없이 실행됨(`sys.path.insert` 로 해결, `test_hostmetrics.py` 가 `cwd=/` 에서 실행해 확인). `observe.nix` 가 `hostmetrics.py` 를 usageui·procui 디렉터리로 복사한다.
- 시험: `test_hostmetrics.py` 10 통과 / 0 실패.

**단계 1 — 실시간 탭: 완료(화면 실물 확인은 못 함)**
- `usagelive.py`(샘플러·표시 조각) + `usageui.py` 6번 탭(`--tab live` 도 가능). 판정 · 메모리 구성 막대(7구간: 실제 사용/tmpfs·Shmem/활성 캐시/식은 캐시/빈 메모리/**ZRAM 압축 점유**/기타 — ZRAM 은 처음 계획에 없었는데 실측에서 「기타」가 11 GiB 로 영문 모를 덩어리가 돼 따로 뺐다) · PSI·스왑 입출력 · 코어별 CPU·네트워크·디스크 초당 · 상위 소비자 · LLM 세션 6박스.
- usageui 머리말·`observe.md` 의 「갱신은 수동만」 원칙에 **예외 한 줄**(실시간 탭만 타이머)을 적었다. 기존 시험 한 줄(`앱: 타이머 없음`)은 「실시간 탭 밖에서는 타이머 없음」으로 바꿨다.
- 시험: `test_usagelive.py` 30 통과 / 0 실패(샘플러·표시 조각·Textual 헤드리스: 탭 진입 때만 타이머, 이탈 때 정지, 재개, 간격 자동 증가, `--tab live`·좁은 화면), 기존 `test_usage.py` 96 · `test_apps.py` 24 · `test_uikit.py` 7 통과(회귀 없음).
- **비용(이 호스트, 헤드리스 15초 측정)**: usageui 프로세스 CPU 4.0%(코어 1개=100%), 한 번 재는 데 150~240 ms, 20% 규칙에 따라 간격이 1.0 → 1.2 초로 자동 증가. 실제 터미널로 그리는 비용은 포함하지 않았다.
- 세션 박스는 ctx 를 부르지 않는다(`test_usagelive.py` 가 호출 횟수 0 을 확인).

**단계 2 — 문서: 완료** — `_docs/content/explanation/observe.md`(6번 탭·원칙 예외·procui 절), `donghans-host-resources/SKILL.md`(구조 메모).

**검증·배포 상태**
- `nixup check --fast` 통과(이 호스트 nixosConfiguration·home-manager eval, 41초). 이는 eval 검사이며 **`nixup` 적용(배포)은 하지 않았다.**
- 설치 디렉터리를 흉내 낸 임시 폴더(`observe.nix` 가 복사하는 파일만)에서 `usageui`·`procui`·`usagelive` 가 같은 폴더 모듈만으로 import·기동됨을 확인했다. 실제 `nixup` 으로 설치한 바이너리는 실행해 보지 않았다.
- **확인하지 못한 것**: 실제 터미널(kitty)에서의 화면 모양(정렬·색), 노트북(msi-summit-me)에서의 동작과 전력 영향, 열린 질문(§3)의 기본값에 대한 사용자 의견.
