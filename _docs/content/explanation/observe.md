# observectl / observe — 관측 시스템 (전력·프로세스 프로파일, 유틸리티 이벤트 로그)

전력 측정과 우리가 만든 유틸리티(displayui, dispctl, posture 등)를 **추정이 아니라 기록으로** 확인하기 위한 도구 묶음. 본체는 `mods/_data/observe/`, NixOS 모듈은 `mods/sys/services/observectl.nix`(호스트 toml 의 `[mods.sys.services] observectl = true`).
Netdata(1초/10초 시스템 지표, 7일)는 그대로 쓰고, observectl 는 Netdata 가 못 보는 것을 맡는다: 스레드 단위 깨어남, **누가 CPU 를 깨우는지(ftrace)**, 패키지 C-state(MSR), 유틸리티 이벤트, 실험 표지와 통계 판정.

## 켜고 끄기 (오버헤드 0 설계)
- `observectl on [L0|L1]` / `observectl off` — 제어 파일(`/var/lib/observe/control.json`, 그룹 users 쓰기 가능)만 바꾼다. sudo 불필요.
- 수집기(root)는 systemd **path 유닛**이 제어 파일 변경이나 `requests/` 에 파일이 생길 때만 띄우고, 꺼져 있고 할 일이 없으면 15초 뒤 스스로 종료한다. 꺼져 있는 동안은 **프로세스 자체가 없다**.
- 수준: **L0** 30초 간격(전력, 패키지 C-state, IRQ/GPE, 프로세스별 CPU·깨어남·RSS, 장치 상태) / **L1** 5초 간격 + 스레드별 상위, 프로세스별 IO. 표본은 `/var/lib/observe/data/samples-YYYYMMDD.jsonl`(보존 14일·1GiB, 재부팅해도 남음).
- 개인정보: 프로세스는 comm 과 exe 이름만 기록. 명령 인자·URL·입력한 글자는 기록하지 않는다.

## 자주 쓰는 명령
| 하고 싶은 것 | 명령 |
|---|---|
| 지금 상태 | `observectl status` |
| 구간 요약(상태/VT/SSID/덮개/AC/표지별) | `observectl window --since 11:00 --until 11:30 --by state` |
| 낮은 전력 상태(low) 전환 시각 | `observectl states --since 3h` |
| 상위 프로세스·스레드 | `observectl top --by wake` / `--by cpu` / `--by thr`(L1) / `--by io`(L1) |
| **누가 CPU 를 깨우나**(타이머/하이타이머 함수, IRQ, workqueue) | `observectl wakers 10` (`--waking` 이면 깨우는 쪽 프로세스도) |
| 그 순간 무슨 일이 있었나 | `observectl timeline --at 12:09:37 --span 60` (표본 + 유틸리티 이벤트 + journal + 커널 로그를 시간순으로 합침) |
| 유틸리티 이벤트 | `observectl events --comp displayui --level debug --grep key` |
| 이벤트 로그 수준 변경(재시작 없이) | `observectl level displayui trace` |
| drm.debug 잠깐 켜기 | `observectl drmdebug 15` → `observectl timeline --at <중간시각> --journal all` |
| Hyprland TRACE 로그(다음 로그인부터) | `observectl hyprtrace on` (로그량이 많아 전력 측정과 동시에 쓰지 말 것) |
| 디스플레이 debugfs 스냅샷 | `observectl display` — **읽는 것이 디스플레이를 깨워 낮은 상태를 깨뜨릴 수 있음** |

## 전력 A/B 측정 절차 (이 절차로 잰 것만 "측정"으로 표기)
1. `observectl on L0`(또는 L1)을 켜고 안정화(≥ 2분). 어댑터/덮개/VT/Wi-Fi 상태를 `observectl status` 로 확인.
2. **A 와 B 를 번갈아 최소 2쌍(ABAB)**: `observectl mark A` → 조건 A 를 60초 유지 → `observectl mark B` → 조건 B 를 60초 유지 → `observectl mark A` → … (조건을 바꾸는 작업은 표지 직후 settle 로 제외됨).
3. `observectl ab --metric psys_w --threshold 0.3 --settle 20` 으로 판정. **쌍이 모두 같은 부호이고 평균 효과가 임계 이상일 때만 "확인(측정)"**, 아니면 "불확실". 불확실한 효과로는 코드를 바꾸지 않는다.
4. 같은 구간에 low/high 상태가 섞였다는 경고가 나오면 `observectl window --by state` 로 확인 — 낮은 상태 전환이 효과를 가렸을 수 있다(2026-10-20 사무실 Wi-Fi 시험이 그랬음).
5. 결과는 `power-evidence.md` 의 장부에 근거 수준과 함께 기록.

## 낮은/높은 상태 분류(휴리스틱)
`state = low` ⇔ 패키지 pc10 잔여율 ≥ 5%. 근거: powertop 측정에서 낮은 상태 pc10 17~24%, 높은 상태 0%. 낮은 상태의 하드웨어 정체는 "eDP 파이프 꺼짐"(display_snap 비교)이지만 pc10 은 그 결과 지표다. 이 분류가 틀리는 경우가 보이면 기준을 조정한다.

## 우리 유틸리티에 이벤트 로그 붙이기
- Python: `from observe_events import Events; ev = Events("컴포넌트"); ev.debug("key", key="enter")`, `with ev.span("apply"): …`. 수준은 제어 파일에서 읽어 1초 캐시 → `observectl level` 로 즉시 변경. 기록 실패는 호출자를 죽이지 않는다.
- 셸: `observe-emit lid-policy info lid lid=closed`.
- 위치: `~/.local/state/observe/events-YYYYMMDD.jsonl`(재부팅해도 남음, 줄마다 즉시 기록되어 크래시 직전까지 남음).
- **붙어 있는 곳**: `displayui`(키 이름과 포커스 위젯, 포커스 이동, 모드 선택, 확인 창 결과), `dispctl`(모든 hyprctl 호출, 적용 계획·규칙, 창 이동, 트랜잭션). 다른 유틸리티(posture-daemon, hypr-input-policy, lid-policy, notif)는 같은 방식으로 붙이면 된다(아직 안 붙음).
- 시험은 `OBSERVE_STATE_DIR`/`OBSERVE_DATA_DIR` 로 경로를 격리한다(tests/run.sh 가 설정).

## 한계
- 수집기 자체의 **CPU 비용(측정)**: L0(30초) 코어 1개의 약 0.35%, L1(5초+스레드 스캔) 약 1.9%. `observectl off` 뒤 15초 안에 프로세스가 사라진다. **전력(W)으로의 비용은 아직 측정하지 않았다** — 독립 계량(Netdata 의 RAPL/배터리 차트)으로 켬/끔을 번갈아 재야 한다. 그때까지 **전력 A/B 에는 L0 만 쓰고**(L1 은 프로파일링 전용), 표본에 수집기가 켜져 있었다는 사실이 남으므로(`observectl status`) 결과 해석에 반영한다.
- **측정 환경 자체의 부하**: 이 기기에서는 Claude Code(TUI)가 kmscon 위에서 돌고, 작업 중에는 kmscon 이 CPU 36%·Claude 가 32% 안팎을 쓴다(L1 스레드 표, 80초). 쉬는 전력 비교 때 Claude 가 출력 중인지 대기 중인지가 결과에 섞일 수 있으니 `observectl top --by cpu` 로 같이 본다.
- MSR PC-state 는 `msr` 모듈이 필요(`boot.kernelModules`), 패키지 값만 본다(코어별 C-state 는 cpuidle 의 평균).
- `observectl wakers` 는 ftrace 이벤트 4종(timer, hrtimer, irq, workqueue; `--waking` 시 sched_waking)을 N초 켠다 — 이벤트 수가 많은 시스템에서는 8MiB/CPU 버퍼가 넘칠 수 있다(결과의 총 건수가 매우 크면 `sec` 를 줄일 것).
