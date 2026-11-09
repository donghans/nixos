# embedctl — 이 노트북의 EC 상태(충전 상한·성능 모드·Cooler Boost) 읽기/제어

MSI Summit E16Flip A12UDT(보드 `MS-1592`) **한 기종**의 EC 에 남는 상태를 허용 목록으로만 다루는 CLI(`embedctl`)와 TUI(`embedctlui`).
Windows 의 MSI Center 가 마지막으로 정한 값이 EC 에 남아 리눅스의 전력·소음·충전에 숨은 변수가 되는 문제를, 리눅스에서 보고·바꾸고·기록·복원하려는 도구다.

> **구현 상태 (계획 `plan/embedctl-구현` 의 단계 1 완료)**: 읽기 전용(`status`, `snapshot`)만 있다. root helper·Nix 패키징(단계 2), 쓰기 동작과 `restore`(단계 3), `embedctlui`(단계 4)는 아직 없다.
> 설계·근거·검증 이력: ctx `plan/embedctl-구현`, 조사: ctx `note/msi-summit-me-ec-충전상한-성능모드-분석`.

## 사용 (현재)

```
embedctl status   [--json]               기종·펌웨어 게이트, 충전 상한, 성능 모드, Cooler Boost, 팬 RPM·온도, 전원
embedctl snapshot [--out 파일] [--json]  위 상태를 스냅샷(JSON)으로. --out 없이는 표준출력, 자동 저장 없음
```

- EC 바이트(`0xD7`·`0xD2`·`0x98`)와 펌웨어 문자열은 root 만 읽는 debugfs 에 있어서, 일반 사용자는 **root helper**(단계 2)를 거친다. helper 가 없거나 거부되면(SSH 세션 등) `status` 는 사용자 권한으로 읽히는 부분(DMI 보드, sysfs 충전 상한, hwmon 팬·온도, AC/배터리)만 내고 EC 항목은 「알 수 없음」, 종료 코드는 0 이다.
- root 로 실행하면 debugfs 를 직접 읽는다(`access: "direct"`).
- `--json` 은 ctlkit 공통 봉투(`command/ok/structured/exit_code/data/notes/error`)다. `data` 의 모양:

```
gate    {board, board_ok, fw, fw_date, fw_verified, state}   state: verified | unverified_fw | unsupported_board | unknown
access  direct | helper | unavailable
ec      {d7, d2, b98} | null            EC[0xD7] · EC[0xD2] · EC[0x98] 원시 값(10진 정수)
charge  {end, start, set, limit}        sysfs 값. end=0 이면 미설정(set=false) → limit=100 으로 동작
mode    {name, supported, active, raw} | null     name: sport | comfort | eco | user
boost   true | false | null
fans    [RPM…] | null      temp_pkg  °C | null      power {ac, status, capacity}      warnings […]
```

종료 코드: 0 성공 · 2 입력/사용법 오류 · 3 게이트·허용 목록 거부 · 4 권한(polkit)·helper 실패 · 5 되읽기 값 불일치. (3·4·5 는 쓰기 단계에서 쓰인다.)

## 기종 게이트

쓰기 전·EC 해석 전에 `board_name == "MS-1592"` 이고 EC 펌웨어 문자열이 **검증된 목록**(`embedlib.VERIFIED_FW`, 지금 `1592EMS1.111`)에 있는지 본다. 하나라도 아니면 읽기만 하고 쓰기는 거부한다.
**강제 옵션은 없다.** 새 펌웨어는 그 위에서 주소 의미를 실제로 확인한 뒤 목록에 추가하는 코드 변경으로만 허용한다. (펌웨어는 2026-11 BIOS 업데이트로 `1592EMS1.109` → `.111` 이 되었고 확인은 `.111` 에서만 했다.)

## EC 주소 (이 기종, 펌웨어 1592EMS1.111)

| 주소 | 의미 |
|---|---|
| `0xD7` | 충전 상한. 하위 7비트=상한 %, 비트7 보존. sysfs `charge_control_end_threshold`(msi_ec)와 같은 값 |
| `0xD2` | 성능 모드. 비트7=지원, 비트6=활성, 하위 2비트: 0 sport · 1 comfort · 2 eco · 3 user |
| `0x98` 비트7 | Cooler Boost |

EC 는 같은 바이트를 두 창구로 보여 준다(`ec_sys` 의 `ec0/io` 와 MSI WMI `get_data` — 7개 오프셋 일치 확인). 이 도구는 WMI 쪽만 쓴다(`ec_sys` 쓰기에 의존하지 않는다).

## 시험

```
cd mods/_tools/desktop/embedctl && python3 -I tests/test_core.py     # 또는 mods/_tools/run-tests.sh 의 embedctl 줄
```
실제 EC·sysfs·systemctl 을 건드리지 않는다: 가짜 sysfs/hwmon/DMI 디렉터리(`EMBEDCTL_SYSFS_BAT`·`EMBEDCTL_SYSFS_AC`·`EMBEDCTL_HWMON`·`EMBEDCTL_DMI`·`EMBEDCTL_RUN`), 가짜 `systemctl`(`EMBEDCTL_SYSTEMCTL`, `tests/fake_systemctl.py`), 메모리 속 EC 에뮬레이터를 쓴다.
`python3 -I` 아래에서는 `sys.path` 를 시험이 직접 구성한다(`observe/process-manager/tests/test_procctl.py` 선례).

## 파일

| 파일 | 역할 |
|---|---|
| `embedlib.py` | 코어: 게이트, EC 읽기(직접/helper), 상태 모으기, 스냅샷, helper 호출·결과 파일, 인스턴스 이름 검증(`INSTANCE_RE`) |
| `embedctl.py` | CLI 진입점(ctlkit 봉투) |
| `tests/` | `test_core.py`, `fake_systemctl.py` |
