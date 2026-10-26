---
name: donghans-host-resources
description: 이 호스트의 실제 가용 자원(메모리·스왑·CPU·IO)과 최근 이력, LLM 세션별 사용량을 노이즈 없이 한 번에 재는 스크립트. 「메모리 압박」「여유 부족」「동시에 몇 개까지 띄울 수 있나」「VM·스택·테스트를 더 올려도 되나」「OOM·스왑 상태」「호스트가 느려졌나」「LLM 세션이 자원을 얼마나 쓰나」를 판단하기 전, 그리고 VM·컨테이너 스택·병렬 시험을 새로 띄우기 전에 먼저 실행한다. free 의 available·buff/cache 한 값으로 판정하지 않기 위한 것이다.
---

# donghans-host-resources — 호스트 가용 자원 스냅샷

## 실행
```
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py            # 5초 구간 + 최근 3시간 이력
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --hist 12h # 이력 구간 늘리기(0 이면 생략)
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --secs 30  # 변화율 구간 늘리기
python3 -I ~/.claude/skills/donghans-host-resources/scripts/hostres.py --json     # 기계 판독
```
읽기 전용이다(캐시 비우기·프로세스 종료 없음). 표준 라이브러리만 쓴다. 시험 전·중·후에 각각 돌려 같은 표로 비교한다(램프업이면 단계마다).

## 출력 구성(위에서 아래로)
1. **요약**: 측정 시각·판정·바로 쓸 수 있는 메모리·큰 소비자·LLM 세션 작동 현황(자동 생성 한 단락).
2. **이 호스트**: 호스트명·CPU·RAM·스왑 구성·OS·커널·가동일수, 실행 중 incus VM(게스트 메모리)·Docker 컨테이너. 하드웨어·설정의 정본은 `~/nixos/hosts/<호스트>.nix|.toml` 이니 거기서 읽는다(추측 금지).
3. **읽는 법** 5줄(`--no-guide` 로 생략 — 반복 실행할 때).
4. 상세 측정 → 최근 이력 → LLM 세션.

## 출력 읽는 법
- **판정(여유/주의/압박/심각)** 과 이유. 판정은 아래 순서로 본다: 메모리 PSI full(구간) → 스왑 되읽기(pswpin) → 보수적 가용 → 스왑·ZRAM 여유 → IO PSI. 기준값은 **경험칙**이며 이 호스트의 실측으로 보정된 값이 아니다(full ≥1% 압박, ≥5% 심각, 보수적 가용 <2GiB 주의). **pswpin ≥1000 pages/s 는 PSI 가 함께 오를 때(full ≥0.5% 또는 some ≥3%)만 압박**이고, PSI 가 낮으면 「주의」로만 표시한다.
- **새로 쓸 수 있는 메모리(보수적)** = 빈 메모리 + 식은(비활성) 파일 캐시. 커널 `MemAvailable` 은 여기에 활성 파일 캐시·회수 가능 slab 을 더한 **낙관값**이라 두 값을 같이 보여 준다. 용량 계획(동시 스택·VM 수)은 보수적 값 기준으로 잡는다.
- **buff/cache 의 정체**: `Cached` 에는 tmpfs(`/tmp`·`/dev/shm`)와 VM·컨테이너 공유메모리(`Shmem`)가 섞여 있다. 이것은 캐시가 아니라 사실상 사용 중인 메모리다(`MemAvailable` 은 처음부터 Shmem 을 회수 가능으로 세지 않으므로 거기서 또 빼면 이중 차감이다). 출력의 「캐시가 아닌데 buff/cache 로 보이는 것」·tmpfs 줄이 그것이다.
- **스왑**: 종류(zram/disk)·사용량·ZRAM 압축 후 실제 RAM 점유. 사용량이 커도 pswpin/s 가 0 에 가까우면 압박이 아니다(식은 페이지가 밀려난 것). 반대로 ZRAM 이 가득이면 다음 스왑아웃은 디스크로 가므로 여유가 얇다는 경고가 붙는다.
- **변화율/s**: 구간 동안 `/proc/vmstat` 의 pswpin·pswpout·pgmajfault·workingset_refault_file·allocstall 증가량 ÷ 초. 누적값은 부팅 이후 합이라 현재 압박의 증거가 아니다.
- **소비자 상위**: cgroup 의 anon+shmem 에서 하위 cgroup 몫을 뺀 「자기 몫」(RSS 합산의 중복 없음). incus VM 은 `incus.service` 로 잡힌다.
- **최근 이력(스파크라인)**: 칸당 5분(기본), 왼쪽 과거 → 오른쪽 지금. 호스트 PSI·가용 메모리·스왑은 Netdata(127.0.0.1:19999, 보존 수일)에서 읽는다. 한 시점 값이 아니라 **직전에 순간 스파이크가 있었는지**를 이 줄로 본다(PSI 칸은 구간 최대).
- **LLM 세션**: claude 등 세션 프로세스와 자식 트리별로 다음을 보여 준다.
  - **작동중/대기**와 그 상태가 된 시각(`~/.claude/sessions/<pid>.json` 의 status). 세션 이름·ID 앞 8자·작업 디렉터리로 구분.
  - **마지막 사용자 입력·마지막 응답 시각**: 로컬 transcript 끝부분에서 읽고(도구 결과·시스템 주입 제외), 못 찾은 항목만 공유 ctx 저장소(`donghans ctx sql`, 읽기 전용)로 보충한다(`[ctx 보충]` 표시). ctx 접속이 실패하면 「못 쟀음」으로 표시한다. 시각은 `N분 전(HH:MM)` 형식.
  - **서브에이전트**: 실행 중 개수·설명(40자)·마지막 활동 시각, 완료 개수·마지막 종료 시각(`<세션>/subagents/*.meta.json` 의 finished). 세션이 대기인데 「실행 중」이 남아 있으면 비정상 종료 흔적일 수 있다.
  - **세션이 띄운 자식 프로세스**: 세션 프로세스 아래 트리를 프로세스 이름별로 묶어 개수·PSS·최장 가동 시간(명령줄은 읽지 않음). 세션이 지금 무엇을 돌리고 있는지(테스트·서버·모니터 스크립트 등)를 본다. **Docker 컨테이너·incus VM 은 데몬 소속이라 세션 아래에 안 잡힌다** — 어느 세션이 띄웠는지는 이 표로 알 수 없고 세션 기록(ctx)이나 컨테이너 이름으로 추정해야 하며, 추정이면 추정이라고 적는다.
  - PSS(공유 페이지를 나눠 계산해 합계가 겹치지 않음)·CPU(측정 구간)·가동 시간. 유휴 세션의 CPU 는 20초 평균 0.7~1% 가 평상시다(짧은 구간은 일시적으로 더 튈 수 있음).
  - 세션이 아닌 claude 프로세스(Vivaldi 의 Claude-in-Chrome 네이티브 호스트 `--chrome-native-host`)는 세션에서 빼고 한 줄로 따로 적는다.

## 구조 메모
- 측정·판정·세션 수집은 `scripts/hostmetrics.py`(출력 없음), 화면 조립·CLI 는 `scripts/hostres.py` 다. hostres 는 `python3 -I` 에서도 import 되도록 스크립트 폴더를 `sys.path` 에 직접 넣는다.
- `hostmetrics.py` 는 usageui 의 「실시간」 탭과 `procui` 도 같은 파일을 쓴다(`observe.nix` 가 설치 때 복사 — 정본은 이 폴더 하나). `begin()`/`end()` 로 증분 측정, `session_meta(use_ctx=False)` 면 ctx 저장소를 부르지 않는다(폴링용).

## 한계(있는 그대로 보고할 것)
- **세션별 이력은 기록되지 않는다.** 세션 표는 현재 시점 값(상태·마지막 대화·서브에이전트는 기록에서 읽은 값)뿐이다. 「언제까지 활성이었나」는 대기 세션의 `대기 …부터`·마지막 응답 시각으로 알 수 있다. 이 스킬은 **실행한 컴퓨터 한 대의 자원만** 다룬다: 세션 표도 이 호스트에서 실행 중인 세션만 나열하고(다른 머신·끝난 세션은 제외), ctx 보충도 이 호스트(`hostname`)의 기록만 조회한다.
- Netdata 가 꺼져 있거나 구간 밖이면 해당 줄만 생략된다(스크립트가 실패하지 않는다). 못 읽은 항목은 「못 쟀음」으로 적는다.
- 「압박」이라는 결론은 PSI·변화율이 뒷받침할 때만 쓴다. 가용 메모리 숫자가 작다는 이유만으로 쓰지 않는다(2026-10-19 에 근거 없이 「호스트 메모리 압박」으로 추정했다가 틀린 전례: 실제 원인은 Docker 재시작).
- `drop_caches` 로 캐시를 비우고 재지 않는다(다른 세션·VM 성능을 해치고 측정이 왜곡된다).

## 더 파고들 때(수동)
- 어떤 tmpfs 파일이 큰가: `du -xh /tmp | sort -h | tail` (삭제는 사용자 승인 후)
- 서비스별 anon/file/shmem: `systemd-cgtop -m` 또는 `/sys/fs/cgroup/<경로>/memory.stat`
- 앱(프로세스 이름) 단위 CPU 이력: `observectl top --by app --since 1h`, `observectl query app:claude.cpu --since 6h --step 10m` (스킬 `donghans-observe`)
