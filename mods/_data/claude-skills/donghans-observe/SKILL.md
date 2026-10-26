---
name: donghans-observe
description: 성능·자원·전력 문제를 추측하지 말고 observectl(관측 시스템) 기록으로 확인하는 방법. 「느리다」「CPU/메모리를 많이 쓴다」「누가 깨우나」「어느 앱에 시간을 썼나」「배터리가 빨리 닳는다」 같은 질문이나 observectl·usageui·전력·프로세스 비효율을 다룰 때 먼저 읽는다. 상위 프로세스·시간대별 집계·wakers·timeline·explain·trace·브라우저 탭별 CPU 조회 명령과 수집 기본값, 정밀 도구(bpf/ebpf) 사용 제한을 담는다.
---

# donghans-observe — 관측(observectl) 조회 방법

성능·자원·전력 문제는 **추측하기 전에 먼저 `observectl status` 로 수집이 켜져 있는지 보고 조회**한다.

- 수집 기본값: **노트북은 꺼짐**(전력 측정에 변수를 섞지 않으려고; 켜기 `observectl on`, 끄기 `observectl off`), 그 밖(데스크톱·서버)은 켜짐. 노트북에서 켜거나 수준(L1)·eBPF 를 올릴 때는 측정에 영향을 주니 먼저 사용자에게 말한다.
- 호스트 종류별 방향(`hostname` 으로 어느 쪽인지 확인): 노트북은 **전력→배터리 사용량 관리·개선**, 데스크톱은 **비효율 프로세스 관리와 집중할 곳에 자원 쓰기**(배터리·psys·Intel C-state 지표는 없거나 비어 있을 수 있음 — 값이 `None`/없음이면 없는 것이지 0 이 아님).

## 자주 쓰는 조회 (sudo 불필요, 개별 조건은 `observectl <명령> --help`)
- 상위 프로세스: `observectl top --by cpu|ctxsw|app --since 1h -n 15`(cpu 는 코어 1개=100%, ctxsw 는 자발적 문맥 전환/s)
- 시간대별·그룹별 집계: `observectl query app:<앱>.cpu proc:<comm>.cpu --since 6h --step 10m --agg mean`(신호 별칭은 `observectl query --help`)
- 누가 CPU 를 깨우나: `observectl wakers 10`  · 그 순간 무슨 일이: `observectl timeline --at 12:09:37 --span 60`
- 한 구간을 포커스·프로세스·스팬으로 묶어 기준 구간과 비교: `observectl explain …`  · 구간(스팬) 폭포: `observectl trace --since 1h`(nixup·덮개 정책 등)
- 브라우저 탭·확장별 CPU: `observectl browser top` / 폭주 기록 `observectl browser bursts`(Vivaldi 디버깅 포트 127.0.0.1:9222 필요) / 규칙적 반복 활동 `observectl browser periodic` / 확장 서비스 워커 `observectl browser sw`(스레드 CPU, 포트가 있으면 확장별 시작 횟수)
- 호스트 간 교차 확인(공유 저장소): `observectl fleet push|sync|status|compare <호스트>|inventory|hosts`(usageui `y` 키 = sync, 실패하면 쌓아 뒀다 다음에 같이) · usageui 5번 「호스트」 탭에서 전력 그래프·앱 비교·확장 차이를 본다 · `fleet changes`(nixup 전후 변화, 다른 호스트가 대조군) · `fleet priority <기준호스트>`(포커스 비중×초과 CPU) · `fleet periodic|units` — 한 호스트에서만 높은 앱·한쪽에만 있는 확장을 후보로 뽑는다(원본·이름·주소는 올리지 않음)
- 실험 전후 비교는 `observectl mark` 로 조건 표지를 붙이고 `observectl window --by mark`.

## 측정(A/B)과 시험 틀 — 효과를 확인할 때
- 절차: `observectl on L0` 로 켜고 안정화 → 조건을 번갈아(ABAB, 쌍 3 이상·구간 5분 이상 권장) → `observectl ab` 로 판정. 틀은 `mods/_data/observe/examples/abab_lib.sh`(`abab_set_a/b`·`abab_verify_a/b`·`abab_restore`; 환경변수 `SEG`·`PAIRS`·`SETTLE`·`ABAB_ALT=1`·`ABAB_AC_MODE=1`·`ABAB_LOCK_CMD`·`AB_ARGS`).
- `observectl ab` 는 psys·패키지·순간 V×I·누적 계량을 한꺼번에 비교하고 지표끼리 어긋나면 알린다. 경고: 구간 시작 직후 표본이 높으면 「안정화 부족 의심」, 한 구간에서만 CPU 가 튄 앱은 「교란 의심」.
- **verify 는 조건을 건 API 의 응답이 아니라 효과를 보는 독립 신호로 한다**(확장을 `chrome.management` 로 껐다는 응답이 거짓이었던 사례 — `observectl browser sw` 로 서비스 워커가 실제로 멈췄는지 본다).
- 상태 지표(PSR 잔류·flip/s·깨움/s·C-state)를 먼저, 와트는 확인용. 시험 중에는 노트북에 ssh 폴링을 하지 않는다. 전력 시험 절차 전체는 호스트 로컬 스킬 `power-test`(`.claude/skills/power-test/SKILL.md`).
- 한계: `browser periodic` 은 15초 폴이라 그보다 짧은 주기는 못 본다. `fleet` 은 서버(`claude-ctx`)에 표가 있어야 하고(서버 `nixup`) 호스트가 `allowedClients` 에 있어야 접속된다. 호스트 간 전력(W) 절댓값 비교는 하드웨어가 달라 하지 않는다.

## 출력은 `--json` 으로 (LLM·스크립트용 — 표 모양은 무시)
모든 `observectl` 하위 명령이 `--json` 을 받는다(`observectl top --by app --json`). 사람이 보는 표의 정렬·모양에는 신경 쓰지 말고 **JSON 을 읽는다.** 봉투: `{"command", "ok", "structured", "exit_code", "data"|"text", "notes", "error"}`.
- `structured:true` 명령(`status`·`top`·`states`·`events`·`query`·`wakers`·`energy`): `data` 에 구조화 값. 예) `top` → `data.rows[{name, cpu_core_pct, ctxsw_vol_per_s, appearances, of_samples}]`, `query` → `data.rows[{label, n, values:{신호: 값}}]`, `status` → `data.{enabled, level, collector, samples_24h, last_sample.age_s, …}`. `explain` 은 기존 자체 `--json`.
- `structured:false` 명령(나머지): `text` 에 사람용 출력 그대로. 필요한 값이 구조화돼 있지 않으면 사용자에게 말해 그 명령을 구조화한다.
- 표 위에 괄호로 찍던 참고 문구(옛 형식 표본 제외, 값이 하나도 없는 신호 등)는 **`notes`** 에 온다 — 값이 `null` 이면 측정이 없는 것이지 0 이 아니다. 실패는 `ok:false` + `error` + 종료 코드(0 이 아님).

## 제한·주의
- 정밀 도구(`observectl bpf <프리셋>`, `observectl ebpf on …`)는 요청할 때만 N초 실행되고 시간이 제한된다. 오래 켜 두지 않는다. `observectl display` 는 읽는 것이 디스플레이를 깨울 수 있어 노트북 전력 측정 중에는 쓰지 않는다.
- 개인정보: 프로세스는 comm·exe 이름만, 창 제목·URL·명령 인자·입력 내용은 기록하지 않는다. 조회 결과를 외부로 보낼 때도 이 원칙을 지킨다.
- 앱별 전력량 추정(Wh)은 psys 센서가 있는 호스트에서만 의미가 있다. 자세한 설명·한계는 `~/nixos/_docs/content/explanation/observe.md`.
