# 시스템 모니터링 (btop, Netdata)

## btop — 실시간 확인 (htop 대체)
`btop` 한 화면에서 CPU(코어별), 메모리, 디스크, 네트워크, 프로세스를 그래프로 본다. 시스템 공통 패키지(`mods/sys/base/core.nix`)이고 htop 은 뺐다.
- 색은 lazygit/clipui/displayui 와 같은 팔레트(회색 둥근 테두리, 하늘색 단축키, 선택 줄 `#268bd2`). 설정은 Home Manager(`programs.btop`)로 선언.
- NVIDIA GPU 는 안 보임(`shown_boxes = "cpu mem net proc"`). 이 PC 는 NVIDIA 가 상시 비활성이라 필요 없음. btop 은 NVML 을 못 찾으면 NVIDIA 를 건너뜀(빌드는 GPU 지원).
- htop 에만 있는 것: `nice` 조절, `strace`/`lsof` 연결, 열 구성. 필요하면 `nix shell nixpkgs#htop`.

## Netdata — 과거 구간 기록 (이 노트북만 켬)
`mods/sys/services/netdata.nix`, 호스트 파일 `hosts/msi-summit-me.toml` 의 `[mods.sys.services] netdata = true`. 프리셋에서는 모두 꺼져 있음.
- 웹 화면 `http://localhost:19999` (로컬에서만 열림 — `127.0.0.1`/`::1` 리스닝 확인, 외부로 나가는 TCP 연결 없음 확인).
- **전원 정책**: AC 연결 시 1초 간격, 배터리일 땐 10초 간격. 수집 주기는 서비스 시작 때 정해지므로(시작 직전에 `/run/netdata/netdata.conf` 를 만들어 `@EVERY@` 를 바꿈) 어댑터를 꽂거나 뽑으면 udev 규칙이 서비스를 재시작함(몇 초 공백).
  전원 판별은 `/sys/class/power_supply/*/type == Mains` 의 `online`. 이 PC 는 `ADP1`. Mains 가 없으면(데스크탑) AC 로 취급.
  - 완전히 끄지 않고 10초로 늘린 이유: 배터리에서 TLP 상한(CPU 30%)으로 느려진 때의 기록이 쓸모 있기 때문. 끄고 싶으면 `ConditionACPower` 방식으로 바꾸면 됨.
- 보존: 초 단위 7일(최대 1GiB), 더 거친 단계는 기본값. 머신러닝(이상 탐지), 알람(health)은 끔.
- 익명 통계는 NixOS 모듈 기본값으로 꺼짐(`DO_NOT_TRACK`), 클라우드는 연결(claim)하지 않음(`agent-claimed: False`).
- **`freeipmi.plugin` 은 끔**: 서버 메인보드(BMC) 센서용인데 이 노트북에서는 대상이 없는데도 계속 찾아서 **CPU 를 약 38%(코어 1개 기준) 썼음**(실측). 끈 뒤 평균 약 9%(코어 1개 기준, 16코어 전체의 약 0.6%), 메모리 약 160 MiB(AC, 1초 간격).
- **배터리 동작 확인(2026-10-17, 어댑터를 뽑아서)**: 뽑은 직후 udev 가 Netdata 를 재시작했고(약 9초 공백), 수집 주기가 `update_every = 10` 으로 바뀜.
- **전력 소모(배터리 방전 중, `current_now × voltage_now`, 켬/끔 60초 구간 3쌍 교대, 켠 뒤 90초 안정화 후 측정, 2초 간격 29샘플)**:
  Netdata 켬 평균 **14.71 W**, 끔 평균 **14.56 W** → 차이 **약 +0.15 W(+1%)**. 구간 쌍별 차이는 +0.01/+0.29/+0.14 W 로 흔들리고 샘플 표준편차가 약 0.5 W 라 오차는 대략 ±0.1 W 수준(통계적으로 강한 결론은 아님).
  Netdata 자체 CPU 는 코어 1개의 약 5.0%(10초 간격), 전체 CPU 사용률 차이는 +0.7%p(16코어 기준 0.12코어분). 배터리(약 57 Wh, `charge_full × 전압`) 기준 사용 시간 차이는 약 2~3분/4시간 정도로 추정.
  - 1차 측정(켠 뒤 25초만 제외)은 +0.62 W 로 더 크게 나왔는데, 시작 직후의 초기화 부하가 섞인 값이었음. 그래서 어댑터를 뽑거나 꽂을 때마다 하는 재시작은 몇십 초 동안 부하가 큼(1회 비용은 작음).
  - AC(1초 간격)의 전력은 배터리 계측으로 잴 수 없어 측정하지 못함. CPU 만 9%(코어 1개) — 위 비율로 단순 환산하면 +0.3 W 안팎이지만 환산값일 뿐 실측이 아님.
  - 더 줄이려면: 배터리 주기를 30초로 늘리거나 배터리에서 `apps.plugin`(프로세스별 통계)을 끄는 방법이 있음(시험 안 함).
- 미확인(남은 것): 어댑터를 다시 꽂을 때(AC 로 돌아가 1초 간격이 되는 쪽)의 동작, 로컬 웹 화면이 nixpkgs 빌드에서 어떻게 나오는지.

### 전력 / 배터리 / CPU 를 그래프로 — `power-report`
`mods/sys/services/netdata.nix` 가 설치하는 명령(스크립트 `mods/_data/netdata/power_report.py`, matplotlib). Netdata API 의 기록을 읽어 **같은 시간축** 그래프(PNG)와 요약 표를 만든다.
```
power-report                    # 최근 6시간, ~/Pictures/power-report/<시각>.png 로 저장
power-report --hours 1
power-report --from "2026-10-17 10:00" --to "2026-10-17 10:40" -o /tmp/x.png
power-report --no-plot          # 요약만
```
그래프(위→아래): 배터리 잔량(%) / 전력(W: 배터리 전력, RAPL 패키지, RAPL psys) / CPU 사용률+평균 주파수 / 패키지 온도. 노란 배경=방전, 초록 배경=충전(**잔량 변화로 추정**).
방전 중이면 최근 평균 전력과 잔량으로 **남은 시간**을 추정해서 출력(전체 용량 = `charge_full × 평균 전압`).
- Netdata 가 이미 수집하는 것(차트 이름): `powersupply_capacity.BAT1`(잔량), `sensors.voltage_BAT1-acpi-0_in0_input`/`sensors.curr_BAT1-acpi-0_curr1_input`(배터리 전압/전류 → 전력 = 곱),
  `cpu.powercap_intel_rapl_zone_package-0`/`..._zone_psys`(RAPL), `cpu.cpufreq`, `system.cpu`, `sensors.temperature_*`, 팬 4개, `cpu.core_throttling`.
- 배터리 전류에는 충전/방전 부호가 없다(크기). 그래서 충전 중인지는 잔량 변화로 추정. 전압/전류/온도는 `sensors` 수집기라 선이 드문드문 끊길 수 있음(RAPL, 잔량은 연속).
- **실측으로 본 것(2026-10-17)**: 배터리 방전 구간(10:07~10:33)에서 **배터리 전력(전압×전류)과 RAPL psys 가 거의 겹침(14~17 W)**. psys 는 AC 에서도 읽히므로 배터리 계측이 안 되는 AC 상태의 전력 비교에 쓸 수 있음.
  AC 에서는 같은 유휴 상태에서 psys 가 약 17 W, 배터리에서는 약 14.5~15 W 였다(TLP 설정 차이 등으로 보이나 원인은 확인하지 않음).

### RAPL 은 왜 일반 사용자가 못 읽나
`/sys/class/powercap/intel-rapl:0/energy_uj` 가 `-r-------- root root` 라서 일반 사용자는 `Permission denied` (하드웨어가 없는 게 아님 — `sudo` 로는 값이 읽힘).
리눅스 5.10 부터 RAPL 에너지 카운터를 root 전용으로 바꿨다(PLATYPUS 라는 전력 측정 기반 부채널 공격 CVE-2020-8694 완화). Netdata 는 `debugfs.plugin` 에 `CAP_DAC_READ_SEARCH`(파일 읽기 권한 우회)를 줘서
(NixOS 가 `/run/wrappers/bin/debugfs.plugin` 으로 처리, 프로세스 `CapEff` 에서 확인) 읽는다. 그래서 Netdata 에서는 값이 나오고 내 셸에서는 안 됨.

### 웹 대시보드는 이 빌드에 없음
`http://127.0.0.1:19999/` 는 404. nixpkgs netdata 는 `withCloudUi = false` 가 기본이고 대시보드 화면 파일이 이 옵션일 때만 들어간다(`ENABLE_DASHBOARD = withCloudUi`, Netdata 가 따로 배포하는 UI 를 받아옴 — 라이선스는 확인하지 않음).
API 는 대시보드와 무관하게 동작해서 `power-report` 와 Claude 의 조회에는 문제가 없음. 화면을 꼭 쓰고 싶으면 `services.netdata.package = pkgs.netdata.override { withCloudUi = true; }` 를 시험할 수 있음(라이선스 확인 필요).

### API 로 조회 (Claude 가 과거를 확인할 때)
```
curl -s 'localhost:19999/api/v1/info'                                    # 버전/상태
curl -s 'localhost:19999/api/v1/chart?chart=system.cpu'                  # 차트 정보(update_every 등)
curl -s 'localhost:19999/api/v1/data?chart=system.cpu&after=-600&points=60&format=json'   # 최근 10분 CPU
curl -s 'localhost:19999/api/v1/charts' | jq '.charts | keys[]'          # 차트 이름 목록
```
켜져 있던 동안만 기록이 있고 꺼져 있던 시간은 비어 있음.

## 이 PC 의 도커 Prometheus/Grafana 스택은 쓰지 않음
프로젝트(genple) 스택의 node-exporter 는 컨테이너 안에서 돌아서 네트워크는 `eth0`(컨테이너)/`lo` 만 보이고 호스트의 와이파이는 안 보임. 보존 15일이지만 스택을 재시작하면 끊기고, 작업 스택이라 같이 꺼질 수 있어서 개인 모니터링에는 부적합하다고 판단함.
