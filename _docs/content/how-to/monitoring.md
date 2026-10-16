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
- 미확인: **배터리 상태(10초)의 실제 동작·부하**(어댑터를 뽑아 보지 않음, 전원 판별 스크립트만 가짜 sysfs 로 AC/배터리/어댑터 없음 3가지를 시험), udev 재시작이 실제로 불리는지, 로컬 웹 화면이 nixpkgs 빌드에서 어떻게 나오는지.

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
