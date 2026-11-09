# embedctl — 이 노트북의 EC 상태(충전 상한·성능 모드·Cooler Boost) 읽기/제어

MSI Summit E16Flip A12UDT(보드 `MS-1592`) **한 기종**의 EC 에 남는 상태를 허용 목록으로만 다루는 CLI(`embedctl`)와 TUI(`embedctlui`).
Windows 의 MSI Center 가 마지막으로 정한 값이 EC 에 남아 리눅스의 전력·소음·충전에 숨은 변수가 되는 문제를, 리눅스에서 보고·바꾸고·기록·복원하려는 도구다.

> **구현 상태 (계획 `plan/embedctl-구현`)**: 단계 1(읽기 전용 코어)·2(root helper + Nix 모듈)·3(쓰기 동작과 `restore`)·4(`embedctlui`)의 코드와 가짜 환경 시험이 있다. 쓰기 동작은 **실기에서 확인했다**(저장소 helper 를 root 로 직접 실행: 충전 80/100·범위 밖 거부, 모드 eco/sport/comfort, Cooler Boost on/off — 18개 모두 통과, 시작 값으로 복원·일치). 설치본(`nixup os --try` 로 임시 적용 중)은 아직 단계 2 코드라서 **helper 경유 쓰기와 TUI 의 실기 확인은 재적용 뒤**다. 호스트 정리와 정식 적용(`write_support=1`·`turbo-*` 제거, 세대 등록)은 단계 5.
> 설계·근거·검증 이력: ctx `plan/embedctl-구현`, 조사: ctx `note/msi-summit-me-ec-충전상한-성능모드-분석`.

## 사용

```
embedctl status   [--json]                   기종·펌웨어 게이트, 충전 상한, 성능 모드, Cooler Boost, 팬 RPM·온도, 전원 (읽기 전용)
embedctl snapshot [--out 파일] [--json]      위 상태를 스냅샷(JSON)으로. --out 없이는 표준출력, 자동 저장 없음
embedctl charge <50..100> [--json]           충전 상한(%). 100 이 「상한 없음」과 같다
embedctl mode sport|comfort|eco [--json]     성능 모드(하위 2비트만 바꾸고 나머지 비트는 보존). user 모드는 다루지 않는다
embedctl boost on|off [--json]               Cooler Boost(비트7 만 바꾼다)
embedctl restore <스냅샷> [--dry-run] [--json]   스냅샷의 충전 상한·성능 모드·Cooler Boost 로 되돌린다
```

- **쓰기는 root helper 가 한다**: `embedctl-root@<동작>.service`(polkit 이 로컬 활성 세션의 `start` 만 허용)가 ① 게이트(기종 + **방금 읽은** EC 펌웨어가 검증 목록에 있어야 함) ② 쓰기 ③ 되읽기 확인 순서로 실행한다. 어긋나면 종료 코드 5 이고, 모드·Cooler Boost 는 이전 값으로 되돌리려 시도한다(최선 노력; 충전 상한은 되돌리지 않고 before/after 만 보고).
- 충전 상한은 sysfs(`msi_ec` 의 `charge_control_end_threshold`)로 쓰고 커널이 EC `0xD7` 을 `0x80+N` 으로 바꾼다. 모드·Cooler Boost 는 MSI WMI `set_data` 다. **`ec_sys` 의 전역 쓰기 허용에 의존하지 않는다.**
- `charge` 는 TLP 설정(`/etc/tlp.conf`, `/etc/tlp.d/*.conf`)에 `STOP_CHARGE_THRESH_BAT0/1` 이 있으면 「TLP 가 다음 적용 때 덮어쓸 수 있다」고 경고한다(지금 이 호스트는 설정하지 않는다).
- `restore` 는 **먼저 전부 검증하고 하나라도 안 맞으면 아무것도 쓰지 않는다**: 스냅샷 형식(schema 1), 지금 게이트가 검증 상태, 스냅샷의 EC 펌웨어 == 지금 펌웨어, 충전 상한 50~100, 모드가 sport·comfort·eco, Cooler Boost 값 존재. 이미 같은 값인 항목은 건너뛴다. 적용 중 하나가 실패하면 거기서 멈추고 이미 적용된 것을 알린다(되돌리지 않는다). 스냅샷의 충전 상한이 「미설정」(end=0)이었으면 sysfs 로 0 을 쓸 수 없어 **100% 로 복원**한다(동작은 같다. `status` 에는 「100% 설정됨」으로 보인다).

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

## embedctlui (TUI)

`embedctlui` — 한 화면에서 보고 바꾼다(Textual + uikit). 위에서부터 ① 기종·펌웨어 게이트와 EC 접근 방식 ② **충전 상한**·**성능 모드** 드롭다운 ③ **Cooler Boost**(켜져 있으면 경고 색) ④ **스냅샷** 저장/복원 ⑤ 팬 RPM·온도·전원(2초 갱신, 창이 포커스를 잃으면 멈춤) ⑥ 마지막 동작 결과.

| 키 | 동작 |
|---|---|
| 드롭다운 선택 | 충전 상한(50~100)·성능 모드(sport/comfort/eco)를 바로 적용. 실패하면 메시지를 보이고 드롭다운을 **실제 상태로 되돌린다** |
| `F8` / 버튼 | Cooler Boost 토글 |
| `F6` | 스냅샷 저장(`~/.local/state/embedctl/snapshots/`, 이 키를 누를 때만) |
| `F7` | 스냅샷 복원: 목록 선택 → **계획을 보여 주는 확인창(기본 「취소」)** → 적용 |
| `F5` | EC 바이트 다시 읽기(EC 는 helper 를 부르므로 열 때·동작 뒤·F5 에서만 읽는다) |
| `?` / `F1` | 도움말 |
| `Esc` / `Ctrl+Q` | 종료 확인창(기본 「아니오」) / 즉시 종료 |

EC 접근이 「사용 불가」(세션 밖 프로세스 등)이거나 기종·펌웨어가 검증 상태가 아니면 드롭다운·버튼이 잠기고 값은 읽기만 된다. 현재 상태와 같은 선택은 무시한다(드롭다운이 되돌아올 때 쓰기가 다시 일어나지 않게).
주의(구현): `App.run_action` 은 Textual 이 모든 키 바인딩에 쓰는 내부 메서드라 같은 이름의 메서드를 만들면 앱이 망가진다 — 작업자 메서드 이름은 `act_worker`.

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
cd mods/_tools/desktop/embedctl && python3 -I tests/test_core.py && python3 -I tests/test_helper.py     # 또는 mods/_tools/run-tests.sh 의 embedctl 줄
<textual 이 있는 python> -I tests/test_embedctlui.py                                                   # run-tests.sh 의 embedui 줄(displayui 가 쓰는 python)
```
실제 EC·sysfs·systemctl 을 건드리지 않는다: 가짜 sysfs/hwmon/DMI 디렉터리(`EMBEDCTL_SYSFS_BAT`·`EMBEDCTL_SYSFS_AC`·`EMBEDCTL_HWMON`·`EMBEDCTL_DMI`·`EMBEDCTL_RUN`), 가짜 `systemctl`(`EMBEDCTL_SYSTEMCTL`, `tests/fake_systemctl.py`), 메모리 속 EC 에뮬레이터를 쓴다.
`python3 -I` 아래에서는 `sys.path` 를 시험이 직접 구성한다(`observe/process-manager/tests/test_procctl.py` 선례).

## 파일

| 파일 | 역할 |
|---|---|
| `embedlib.py` | 코어: 게이트, EC 읽기·쓰기(`apply_action`), 상태 모으기, 스냅샷, helper 호출·결과 파일, 인스턴스 이름 검증(`INSTANCE_RE`), TLP 설정 읽기 |
| `embedctl.py` | CLI 진입점(ctlkit 봉투, `Fail(코드, 메시지)`) |
| `embedhelper.py` | root helper(`embedctl-root@<동작>.service` 가 실행) |
| `embedctlui.py` | TUI(Textual). `embedlib` 의 `helper_call`·`restore_plan`·`save_snapshot` 을 CLI 와 같이 쓴다 |
| `tests/` | `test_core.py`(코어·CLI·열화), `test_helper.py`(helper·쓰기 동작·끝단·restore), `fake_systemctl.py`(정적 결과), `test_embedctlui.py`(헤드리스 Textual Pilot, 가짜 helper), `fake_systemctl_e2e.py`(실제 helper 코드를 EC 에뮬레이터 위에서 실행, 상태는 파일에 유지) |

시험의 신뢰도를 확인하려고 복사본에서 일부러 결함을 넣어 보았다(마스크 제거, 게이트 무력화, 범위 검사 제거, 되읽기 검사 제거, 정규식 `\Z`→`$`, 신선도 검사 완화, restore 의 펌웨어 일치·user 모드 거부 제거, 종료 코드 변경, 미설정 안내 제거 — 11가지). 처음에는 한 가지(EC 되읽기 검사)를 시험이 놓쳐서 그 시험을 추가했고, 지금은 11가지 모두 시험이 실패한다. TUI 시험도 같은 방식으로 확인했다(충전·모드의 「현재와 같은 선택 무시」·동기화 가드·실패 뒤 되돌림·게이트 무시·쓰기 전 writable 확인 제거·복원 확인창 생략·복원 취소 시에도 적용·Esc 즉시 종료·시작 때 자동 저장 — 의미 있는 변이 10가지, 동치 변이 1개는 제외; 처음에 둘을 놓쳐 시험을 고치고 추가했다: 드롭다운 값이 같으면 Textual 이 `Changed` 를 만들지 않아 가드가 시험되지 않았다).
