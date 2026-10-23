---
name: donghans-observe
description: 성능·자원·전력 문제를 추측하지 말고 observectl(관측 시스템) 기록으로 확인하는 방법. 「느리다」「CPU/메모리를 많이 쓴다」「누가 깨우나」「어느 앱에 시간을 썼나」「배터리가 빨리 닳는다」 같은 질문이나 observectl·usageui·전력·프로세스 비효율을 다룰 때 먼저 읽는다. 상위 프로세스·시간대별 집계·wakers·timeline·explain·trace·브라우저 탭별 CPU 조회 명령과 수집 기본값, 정밀 도구(bpf/ebpf) 사용 제한을 담는다.
---

# donghans-observe — 관측(observectl) 조회 방법

성능·자원·전력 문제는 **추측하기 전에 먼저 `observectl status` 로 수집이 켜져 있는지 보고 조회**한다.

- 수집 기본값: **노트북은 꺼짐**(전력 측정에 변수를 섞지 않으려고; 켜기 `observectl on`, 끄기 `observectl off`), 그 밖(데스크톱·서버)은 켜짐. 노트북에서 켜거나 수준(L1)·eBPF 를 올릴 때는 측정에 영향을 주니 먼저 사용자에게 말한다.
- 이 호스트의 방향: 노트북은 **전력→배터리 사용량 관리·개선**, 데스크톱은 **비효율 프로세스 관리와 집중할 곳에 자원 쓰기**(배터리·psys·Intel C-state 지표는 없거나 비어 있을 수 있음 — 값이 `None`/없음이면 없는 것이지 0 이 아님).

## 자주 쓰는 조회 (sudo 불필요, 개별 조건은 `observectl <명령> --help`)
- 상위 프로세스: `observectl top --by cpu|ctxsw|app --since 1h -n 15`(cpu 는 코어 1개=100%, ctxsw 는 자발적 문맥 전환/s)
- 시간대별·그룹별 집계: `observectl query app:<앱>.cpu proc:<comm>.cpu --since 6h --step 10m --agg mean`(신호 별칭은 `observectl query --help`)
- 누가 CPU 를 깨우나: `observectl wakers 10`  · 그 순간 무슨 일이: `observectl timeline --at 12:09:37 --span 60`
- 한 구간을 포커스·프로세스·스팬으로 묶어 기준 구간과 비교: `observectl explain …`  · 구간(스팬) 폭포: `observectl trace --since 1h`(nixup·덮개 정책 등)
- 브라우저 탭·확장별 CPU: `observectl browser top` / 폭주 기록 `observectl browser bursts`(Vivaldi 디버깅 포트 127.0.0.1:9222 필요)
- 실험 전후 비교는 `observectl mark` 로 조건 표지를 붙이고 `observectl window --by mark`.

## 제한·주의
- 정밀 도구(`observectl bpf <프리셋>`, `observectl ebpf on …`)는 요청할 때만 N초 실행되고 시간이 제한된다. 오래 켜 두지 않는다. `observectl display` 는 읽는 것이 디스플레이를 깨울 수 있어 노트북 전력 측정 중에는 쓰지 않는다.
- 개인정보: 프로세스는 comm·exe 이름만, 창 제목·URL·명령 인자·입력 내용은 기록하지 않는다. 조회 결과를 외부로 보낼 때도 이 원칙을 지킨다.
- 앱별 전력량 추정(Wh)은 psys 센서가 있는 호스트에서만 의미가 있다. 자세한 설명·한계는 `~/nixos/_docs/content/explanation/observe.md`.
