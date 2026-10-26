---
name: donghans-host-resources
description: 이 NixOS 워크스테이션(beelink-ser7-co 실측으로 보정)의 실제 가용 자원(메모리·스왑·CPU·IO)·메모리 대기 주체·최근 이력·LLM 세션별 사용량을 한 번에 재고, 「더 띄워도 되나」에 쓸 수용량 표와 속도·용량 두 축 판정을 낸다. 「메모리 압박」「여유 부족」「동시에 몇 개까지 띄울 수 있나」「VM·스택·테스트를 더 올려도 되나」「OOM·스왑·ZRAM 상태」「호스트가 느려졌나」「LLM 세션이 자원을 얼마나 쓰나」를 판단하기 전, 그리고 VM·컨테이너 스택·병렬 시험을 새로 띄우기 전에 먼저 실행한다. free 의 available·buff/cache·스왑 사용량 한 값으로 판정하지 않기 위한 것이다.
---

# donghans-host-resources — 이 워크스테이션의 자원 스냅샷·판정

이 스킬은 **현재 NixOS 워크스테이션(주 대상 beelink-ser7-co)** 용이다. 판정 기준·해석은 이 호스트의 실측(`_plan/host-memory-verdict.md`, 2026-10-26)으로 보정했고, 다른 호스트에서 돌리면 「스왑 기준점 없음」이 출력에 뜬다(§새 호스트에 쓸 때).

## 실행
```
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py            # 5초 구간 + 최근 3시간 이력
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --hist 12h # 이력 구간 늘리기(0 이면 생략)
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --secs 30  # 변화율 구간 늘리기
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --no-guide --no-sessions  # 반복 실행용 짧은 출력
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --json     # 기계 판독(verdict·axes·info·capacity 포함)
```
읽기 전용이다(캐시 비우기·프로세스 종료 없음). 표준 라이브러리만 쓴다. 시험 전·중·후에 각각 돌려 같은 표로 비교한다(램프업이면 단계마다).

## 이 호스트의 사실 (실측 2026-10-26 — 추측하지 말고 이 표를 쓴다)
| 항목 | 값 |
|---|---|
| 구성 | AMD Ryzen 7 7840HS 16스레드 · RAM 30 GiB · NVMe(SAMSUNG MZVL21T0HCLR) · 정본 `~/nixos/hosts/beelink-ser7-co.nix\|.toml` |
| 스왑 계층 | ① ZRAM(우선순위 100, zstd, 슬롯 15 GiB = 압축 전 기준, 압축률 약 2.6, 백업 장치 없음) → ② NVMe 스왑파일 `/var/lib/swapfile` 24 GiB(우선순위 10). 합계 39 GiB |
| ZRAM 「가득」 | 슬롯(압축 전)이 찬 것이지 RAM 을 다 쓴 게 아니다(RAM 점유 약 5.4 GiB). 새로 밀려나는 페이지는 ②로 가고, ZRAM 안의 페이지는 그대로 남는다. **위험 신호가 아니다** |
| 스왑 접근 비용(벤치마크) | 한 번 접근 p99 약 270~345 µs(디스크 경로), p50 은 ZRAM 적중 여부에 따라 8~48 µs, RAM 상주 0.3 µs. 순차 약 120~166 MiB/s. 스왑 약 100 MiB/s 폭주 중에도 **무관한 프로세스의 지연은 거의 불변**(sleep 1ms 초과 p99 38~58 → 40~69 µs) |
| 예약분 | 워터마크 합 약 0.3 GiB(`min_free_kbytes` 66 MiB), HugePages 0, CMA 0, cgroup `memory.min/low/high` 없음, THP madvise, swappiness 60. 사실상 예약 없음 |
| 실질적 「예약」 | incus VM(qa-desktop 한도 8 GiB, win11) 게스트 RAM — 호스트에서는 `incus.service` 의 anon+shmem 약 4~5 GiB 로 보이고 게스트 안 캐시는 호스트가 회수 못 한다 |
| buff/cache 의 정체 | `Cached` 에 tmpfs(`/tmp` 약 8 GiB, 스왑에 나간 몫 포함)와 VM 공유메모리(Shmem 약 4~5 GiB)가 섞여 있다 — 캐시가 아니다 |

## 판정 (속도 · 용량 두 축, 높은 쪽)
| 축 | 근거 | 주의 | 압박 | 심각 |
|---|---|---|---|---|
| 속도 | 메모리 PSI **avg60**(지속) | full ≥1% 또는 full 순간 ≥5% | full ≥3% 또는 some ≥20% | full ≥10% |
| 용량 | **OOM 까지 여유** = MemAvailable + 스왑 여유 | <8 GiB | <3 GiB | <1 GiB |
- 임계값 출처(Netdata 유효 4일 이력의 5분 버킷 1142개): full avg60 ≥1% 2.2%, ≥3% 0.1%; full avg10 ≥5% 1.0%. **사용자 체감으로 교정되지 않았다** — 값은 `hostmetrics.CALIB`(호스트별 `HOST_CALIBRATION[...]["thresholds"]` 로 덮어씀).
- 판정에 **쓰지 않는 것**(정보 줄로만 나옴): ZRAM 가득, 디스크 스왑 사용량, 스왑 되읽기(이력의 58% 구간이 ≥4 MiB/s), 보수적 가용 크기. 이들만으로 「압박」이라고 쓰지 말 것.
- 시스템 전체 PSI 는 cgroup 하나가 혼자 스왑을 두드려도 오른다. 출력의 **「메모리 대기를 만든 cgroup」**(가장 깊은 쪽)로 누구 때문인지 본 뒤, 그 주체가 사용자의 앞 작업인지 시험·백그라운드인지 구분해서 보고한다.

## 질문별 사용법
- **「더 띄워도 되나」**: 출력의 「새 작업이 쓸 메모리별 영향」 표를 그대로 인용한다 — 보수적 가용 이하는 바로, 낙관 가용까지는 캐시를 밀어내며(약간 느려짐), 그 위는 스왑 의존(식은 페이지는 NVMe 로, 작업집합이 크면 느려짐), 그 이상은 OOM 위험. 활성 작업집합이 큰 것(DB·빌드·VM)은 한 단계 낮춰 본다. 이미 떠 있는 큰 소비자(incus VM·LLM 세션 각 약 0.3 GiB·docker 스택)는 「소비자 상위」 줄.
- **「느려졌나」**: 판정의 속도 축과 avg60 → 대기 주체 cgroup → 이력 스파크라인(직전 스파이크 여부) 순. PSI 가 낮고 대기 주체가 시험·스레셔면 「호스트 압박 아님」이라고 말한다.
- **「LLM 세션이 자원을 얼마나 쓰나」**: 아래 LLM 세션 표(PSS 합·작동중/대기·서브에이전트·자식 프로세스).
- **「압박」이라는 결론**은 PSI 지속값이 뒷받침할 때만 쓴다. 가용 메모리 숫자가 작다는 이유만으로 쓰지 않는다(2026-10-19 에 근거 없이 「호스트 메모리 압박」으로 추정했다가 틀린 전례: 실제 원인은 Docker 재시작).

## 출력 구성(위에서 아래로)
1. **요약**: 측정 시각·판정(두 축)·OOM 까지 여유·새 작업 수용 한도·큰 소비자·메모리 대기 주체·LLM 세션 현황.
2. **이 호스트**: 호스트명·CPU·RAM·스왑 구성·OS·커널·가동일수, 실행 중 incus VM(게스트 메모리)·Docker 컨테이너.
3. **읽는 법** 5줄(`--no-guide` 로 생략 — 반복 실행할 때).
4. 호스트 자원(판정·이유·OOM 여유·보수적/낙관 가용·PSI(구간·avg10·avg60)·대기 주체·변화율·CPU·tmpfs·소비자 상위·**참고 정보**(ZRAM·디스크 스왑·스왑 기준점·보수적 가용)·**수용량 표**) → 최근 이력 → LLM 세션.

## 출력 읽는 법 세부
- **새로 쓸 수 있는 메모리(보수적)** = 빈 메모리 + 식은(비활성) 파일 캐시. 커널 `MemAvailable` 은 여기에 활성 파일 캐시·회수 가능 slab 을 더한 **낙관값**이라 둘을 같이 보여 준다(이 호스트에서 meminfo 필드로 MemAvailable 공식을 재현하면 오차 약 0.15 GiB — 필드는 서로 일관됨).
- **buff/cache 의 정체**: tmpfs(`/tmp`·`/dev/shm`)와 VM·컨테이너 공유메모리(`Shmem`)는 사실상 사용 중인 메모리다(`MemAvailable` 은 처음부터 Shmem 을 회수 가능으로 세지 않으므로 거기서 또 빼면 이중 차감). tmpfs 사용량은 스왑에 나간 몫을 포함해 Shmem 보다 클 수 있다.
- **변화율/s**: `/proc/vmstat` 의 pswpin·pswpout·pgmajfault·workingset_refault_file·allocstall 증가량 ÷ 초. 누적값은 부팅 이후 합이라 현재 압박의 증거가 아니다.
- **소비자 상위**: cgroup 의 anon+shmem 에서 하위 cgroup 몫을 뺀 「자기 몫」. incus VM 은 `incus.service` 로 잡힌다.
- **최근 이력(스파크라인)**: 칸당 5분(기본), 왼쪽 과거 → 오른쪽 지금. 호스트 PSI·가용 메모리·스왑은 Netdata(127.0.0.1:19999, **유효 보존 약 4일** — 그 앞은 공백이라 0 으로 채워지니 해석 금지)에서 읽는다.
- **LLM 세션**: claude 등 세션 프로세스와 자식 트리별 — 작동중/대기와 그 시각(`~/.claude/sessions/<pid>.json`), 마지막 사용자 입력·응답 시각(transcript, 못 찾으면 공유 ctx 저장소 `[ctx 보충]`, 접속 실패는 「못 쟀음」), 서브에이전트 실행·완료, 세션이 띄운 자식 프로세스(이름별 개수·PSS·최장 가동, 명령줄은 읽지 않음), PSS·CPU·가동 시간(유휴 세션 CPU 는 20초 평균 0.7~1% 가 평상시). 세션이 아닌 claude 프로세스(Vivaldi 의 `--chrome-native-host`)는 한 줄로 따로. **Docker 컨테이너·incus VM 은 데몬 소속이라 세션 아래에 안 잡힌다** — 어느 세션이 띄웠는지는 이 표로 알 수 없고 추정이면 추정이라고 적는다.

## 새 호스트에 쓸 때 (다른 워크스테이션·NVMe 가 아닌 곳)
이 판정의 전제(스왑이 빠르다)는 이 호스트에서 **측정**한 것이다. 다른 호스트에는 그대로 적용하지 말고:
1. 출력에 「스왑 기준점 없음」이 뜨면 `python3 -I ~/.claude/skills/donghans-host-resources/scripts/swapbench.py --bystander --entry` 를 **조용할 때** 돌린다(cgroup 300 MiB 제한 안에서 1.5 GiB 를 스왑 경로로 강제 — 약 1분, 호스트가 바쁘거나 스왑 여유 <4 GiB 면 거부). 출력의 항목을 `hostmetrics.py` 의 `HOST_CALIBRATION` 에 추가·커밋한다(`rotational` 은 직접 확인해 채움).
2. 출력의 「경고: 회전 디스크 스왑」이 뜨면 이 호스트의 NVMe 기준(한 번 접근 약 50µs)이 틀리다 — 스왑 되읽기·사용을 정보로 두지 말고 속도 축 근거로 본다.
3. 실측한 p99·순차 속도가 이 호스트의 값(약 300µs·120 MiB/s)보다 훨씬 나쁘면 `thresholds` 를 더 보수적으로(예: `headroom_warn` 상향, `full60_warn` 하향) 조정한다.
기준점이 있으면 출력의 「스왑 기준점(실측 …)」 줄이 그 호스트의 숫자를 인사이트에 쓰게 한다.

## 한계(있는 그대로 보고할 것)
- **세션별 이력은 기록되지 않는다.** 세션 표는 현재 시점 값뿐이다. 이 스킬은 **실행한 컴퓨터 한 대의 자원만** 다룬다(다른 머신·끝난 세션 제외, ctx 보충도 이 호스트 기록만).
- 임계값은 사용자 체감과 대조해 교정되지 않았다(§판정). 앞 창 앱이 스왑을 쓸 때의 체감 지연, 제한 없는 전역 스왑 폭주는 측정하지 않았다(다른 세션·VM 에 피해).
- Netdata 가 꺼져 있거나 구간 밖이면 해당 줄만 생략된다. 못 읽은 항목은 「못 쟀음」으로 적는다.
- `drop_caches` 로 캐시를 비우고 재지 않는다(다른 세션·VM 성능을 해치고 측정이 왜곡된다).

## 더 파고들 때(수동)
- 어떤 tmpfs 파일이 큰가: `du -xh /tmp | sort -h | tail` (삭제는 사용자 승인 후)
- 서비스별 anon/file/shmem: `systemd-cgtop -m` 또는 `/sys/fs/cgroup/<경로>/memory.stat`; cgroup 별 대기: `/sys/fs/cgroup/<경로>/memory.pressure`
- 앱(프로세스 이름) 단위 CPU 이력: `observectl top --by app --since 1h`, `observectl query app:claude.cpu --since 6h --step 10m` (스킬 `donghans-observe`)
- 실시간 화면: `usageui`(옵션 없이 열면 실시간 쪽 — 같은 `hostmetrics.py` 를 쓴다), 프로세스 정리: `procui`(사람)·`procctl`(LLM, 스킬 `donghans-procctl`)

## 구조 메모
- 측정·판정·세션 수집은 `scripts/hostmetrics.py`(출력 없음), 화면 조립·CLI 는 `scripts/hostres.py`, 스왑 기준점 측정은 `scripts/swapbench.py` 다. hostres 는 `python3 -I` 에서도 import 되도록 스크립트 폴더를 `sys.path` 에 직접 넣는다.
- `hostmetrics.py` 는 usageui 의 「실시간」 쪽과 procui·procctl 도 같은 파일을 쓴다(`observe.nix` 가 설치 때 복사 — 정본은 이 폴더 하나). `begin()`/`end()` 로 증분 측정, `session_meta(use_ctx=False)` 면 ctx 저장소를 부르지 않는다(폴링용). `verdict_axes`·`info_lines`·`capacity_guide` 가 판정의 본체.
