# embedctl — 이 노트북의 EC 상태(충전 상한·성능 모드·Cooler Boost) 읽기/제어

MSI Summit E16Flip A12UDT(보드 `MS-1592`) **한 기종**의 EC 에 남는 상태를 허용 목록으로만 다루는 CLI(`embedctl`)와 TUI(`embedctlui`).
Windows 의 MSI Center 가 마지막으로 정한 값이 EC 에 남아 리눅스의 전력·소음·충전에 숨은 변수가 되는 문제를, 리눅스에서 보고·바꾸고·기록·복원하려는 도구다.

> **sysfs 전환 (2026-11-12, 계획 `plan/embedctl-lockdown`)**: 이 노트북은 lockdown(integrity)이 항상 켜져 **debugfs 를 읽고 쓸 수 없다**. 그래서 원래 설계(MSI WMI debugfs 로 EC 바이트 읽기·쓰기, 계획 `plan/embedctl-구현`)를 버리고
> **커널 모듈 `msi-ec` 의 sysfs(`/sys/devices/platform/msi-ec/`)만** 쓰도록 바꿨다. 코드와 가짜 sysfs 시험은 끝났고, **실기 확인도 했다**(2026-11-12 세대 540, 계획 P4: 읽기·충전 80↔100·모드 eco/comfort/turbo·Cooler Boost·restore 가 helper+polkit 을 거쳐 lockdown 아래에서 동작, 쓴 항목 외 값 불변). turbo 는 유휴에서 comfort 와 팬·온도가 같았고 **부하 시 차이는 아직 측정 전**이다.
> 설계·근거·검증 이력: ctx `plan/embedctl-lockdown`, 원래 설계 `plan/embedctl-구현`, 조사: ctx `note/msi-summit-me-ec-충전상한-성능모드-분석`.

## 사용

```
embedctl status   [--json]                   기종·펌웨어 게이트, 충전 상한, 성능 모드, Cooler Boost, 팬 RPM·온도, 전원 (읽기 전용, 일반 사용자 권한)
embedctl snapshot [--out 파일] [--json]      위 상태를 스냅샷(JSON, schema 2)으로. --out 없이는 표준출력, 자동 저장 없음
embedctl charge <50..100> [--json]           충전 상한(%). 100 이 「상한 없음」과 같다
embedctl mode turbo|comfort|eco [--json]     성능 모드. turbo=과전압·오버클럭, comfort=균형, eco=저전력. sport 는 사용 불가(아래)
embedctl boost on|off [--json]               Cooler Boost(비트7 만 바뀐다)
embedctl restore <스냅샷> [--dry-run] [--json]   스냅샷의 충전 상한·성능 모드·Cooler Boost 로 되돌린다
```

- **읽기는 helper 없이** 일반 사용자가 sysfs 를 직접 읽는다(`msi-ec` 의 `fw_version`·`shift_mode`·`cooler_boost`·`available_shift_modes`, BAT1 충전 임계값, hwmon 팬·온도, DMI). 세션 밖(SSH 등)에서도 된다.
- **쓰기는 root helper 가 한다**: `embedctl-root@<동작>.service`(polkit 이 로컬 활성 세션의 `start` 만 허용)가 ① 게이트(기종 + **방금 읽은** msi-ec 펌웨어가 검증 목록에 있어야 함) ② 쓰기 ③ 되읽기 확인 순서로 실행한다.
  쓴 항목만 바뀌고 나머지는 그대로여야 한다. 어긋나면 종료 코드 5 이고, 모드·Cooler Boost 는 이전 값으로 되돌리려 시도한다(최선 노력; 이전 값이 `unknown (N)` 처럼 쓸 수 없는 값이면 시도하지 않는다. 충전 상한은 되돌리지 않고 before/after 만 보고).
  쓰는 값은 msi-ec 가 `available_shift_modes` 로 광고하는 이름 ∩ embedctl 의 정적 목록(turbo·comfort·eco)뿐이다.
- 쓰기가 EC 에 닿는 방식(msi-ec 소스 `CONF_G2_1`, 이 펌웨어): 충전 상한 EC `0xD7`(커널이 `0x80+N`), Cooler Boost EC `0x98` 의 비트7 만(`ec_set_bit`), 성능 모드 EC `0xD2` 에 **turbo=0xC4 · eco=0xC2 · comfort=0xC1 을 통째로** 쓴다. **`ec_sys` 나 debugfs 에 의존하지 않는다.**
- **sport 는 비활성이다**: 예전 embedctl 의 `sport` 는 EC `0xC0` 이었는데 msi-ec 가 이 펌웨어에서 광고하지 않아 sysfs 로 쓸 수 없다. `embedctl mode sport` 는 이유와 함께 거부(종료 코드 2)하고, TUI 는 안내 줄(「sport — 사용 불가」)만 보인다.
  EC 에 `0xC0` 이 남아 있으면(Windows MSI Center 가 Sport 로 남긴 경우) msi-ec 는 `unknown (192)` 로 읽으므로 `status` 는 「sport(레거시 값, 변경 불가)」로 보여 준다. turbo/comfort/eco 로 바꾸면 **sport 로는 되돌릴 수 없다**(문구로 알린다).
  turbo(`0xC4`)는 이 도구에서 아직 측정한 적이 없는 값이다(팬·온도·전력 — 계획 P4에서 확인).
- `charge` 는 TLP 설정(`/etc/tlp.conf`, `/etc/tlp.d/*.conf`)에 `STOP_CHARGE_THRESH_BAT0/1` 이 있으면 「TLP 가 다음 적용 때 덮어쓸 수 있다」고 경고한다(지금 이 호스트는 설정하지 않는다).
- `restore` 는 **먼저 전부 검증하고 하나라도 안 맞으면 아무것도 쓰지 않는다**: 스냅샷 형식(**schema 2**; WMI/EC 바이트 시절의 schema 1 은 거부), 지금 게이트가 검증 상태, 스냅샷의 EC 펌웨어 == 지금 펌웨어, 충전 상한 50~100, 모드가 turbo·comfort·eco(그리고 지금 msi-ec 가 광고), Cooler Boost 값 존재.
  이미 같은 값인 항목은 건너뛴다. 적용 중 하나가 실패하면 거기서 멈추고 이미 적용된 것을 알린다(되돌리지 않는다). 스냅샷의 충전 상한이 「미설정」(end=0)이었으면 sysfs 로 0 을 쓸 수 없어 **100% 로 복원**한다(동작은 같다. `status` 에는 「100% 설정됨」으로 보인다).
- **msi-ec 가 없을 때**(`/sys/devices/platform/msi-ec` 없음): 게이트가 `no_msi_ec` 이고 `status` 는 이유(모듈 미적재 — kernel-lockdown mod 꺼짐·서명 거부 / EC 펌웨어가 모듈 허용 목록 밖이라 모듈이 거부 — `journalctl -k | grep -i msi-ec`)와 함께 종료 코드 0 으로 읽히는 부분(충전 파일·팬·전원)만 보이며, 모든 쓰기는 종료 코드 3 으로 거부한다. Nix 쪽에서는 `kernel-lockdown` 없이 embedctl 만 켜면 빌드가 assertion 으로 실패한다(`mods/gui/apps/embedctl.nix`).
- `--json` 은 ctlkit 공통 봉투(`command/ok/structured/exit_code/data/notes/error`)다. `data` 의 모양:

```
gate    {board, board_ok, fw, fw_date, fw_verified, state}   state: verified | unverified_fw | unsupported_board | no_msi_ec
msi_ec  {present, available_modes}      available_modes: msi-ec 가 광고하는 모드 목록 | null
charge  {end, start, set, limit}        sysfs 값. end=0 이면 미설정(set=false) → limit=100 으로 동작
mode    {name, raw, text, known} | null     text: msi-ec shift_mode 원문. known: turbo|comfort|eco 면 true(이때 raw 는 null). name 은 그 이름, `unknown (192)` 는 "sport"(known=false, raw=192), 그 밖은 "unknown"/"unspecified"
modes   {writable: [쓸 수 있는 모드…], disabled: ["sport"]}
boost   true | false | null
fans    [RPM…] | null      temp_pkg  °C | null      power {ac, status, capacity}      warnings […]
```

(예전 `access`·`ec` 필드는 사라졌다 — 읽기에 helper 도 EC 원시 바이트도 쓰지 않는다. 이 필드를 읽는 외부 코드는 없었다.)

종료 코드: 0 성공 · 2 입력/사용법 오류 · 3 게이트·허용 목록 거부 · 4 권한(polkit)·helper 실패 · 5 되읽기 값 불일치. (3·4·5 는 쓰기 단계에서 쓰인다.)

## embedctlui (TUI)

`embedctlui` — 한 화면에서 보고 바꾼다(Textual + uikit). 위에서부터 ① 기종·펌웨어 게이트 ② **충전 상한**·**성능 모드** 드롭다운(모드 아래에 「sport — 사용 불가」 안내 줄) ③ **Cooler Boost**(켜져 있으면 경고 색) ④ **스냅샷** 저장/복원 ⑤ 팬 RPM·온도·전원(2초 갱신, 창이 포커스를 잃으면 멈춤) ⑥ 마지막 동작 결과.

| 키 | 동작 |
|---|---|
| 드롭다운 선택 | 충전 상한(50~100)·성능 모드(turbo/comfort/eco)를 바로 적용. 실패하면 메시지를 보이고 드롭다운을 **실제 상태로 되돌린다**. 지금 값이 레거시 sport 면 「sport(레거시 값, 변경 불가) (현재)」 항목이 보이고 다른 모드로는 바꿀 수 있다 |
| `F8` / 버튼 | Cooler Boost 토글 |
| `F6` | 스냅샷 저장(`~/.local/state/embedctl/snapshots/`, 이 키를 누를 때만) |
| `F7` | 스냅샷 복원: 목록 선택 → **계획을 보여 주는 확인창(기본 「취소」)** → 적용 |
| `F5` | 모드·부스트·충전 다시 읽기(열 때·동작 뒤·F5 에서만; 2초 갱신은 팬·온도·전원뿐) |
| `?` / `F1` | 도움말 |
| `Esc` / `Ctrl+Q` | 종료 확인창(기본 「아니오」) / 즉시 종료 |

msi-ec 가 없거나 기종·펌웨어가 검증 상태가 아니면 드롭다운·버튼이 잠기고 값은 읽기만 된다(msi-ec 없음이면 상태 줄에 이유). 현재 상태와 같은 선택은 무시한다(드롭다운이 되돌아올 때 쓰기가 다시 일어나지 않게).
주의(구현): `App.run_action` 은 Textual 이 모든 키 바인딩에 쓰는 내부 메서드라 같은 이름의 메서드를 만들면 앱이 망가진다 — 작업자 메서드 이름은 `act_worker`.

## 기종 게이트

쓰기 전·해석 전에 `board_name == "MS-1592"` 이고 msi-ec 의 `fw_version` 이 **검증된 목록**(`embedlib.VERIFIED_FW`, 지금 `1592EMS1.111`)에 있는지 본다. 하나라도 아니면 읽기만 하고 쓰기는 거부한다.
msi-ec 모듈 자신도 자기 허용 목록에 없는 펌웨어면 올라오지 않으므로 게이트는 이중이다.
**강제 옵션은 없다.** 새 펌웨어는 그 위에서 값의 의미를 실제로 확인한 뒤 목록에 추가하는 코드 변경으로만 허용한다. (펌웨어는 2026-11 BIOS 업데이트로 `1592EMS1.109` → `.111` 이 되었고 확인은 `.111` 에서만 했다.)

## EC 주소 (이 기종, 펌웨어 1592EMS1.111) — 참고

이 도구는 더 이상 EC 주소를 직접 다루지 않는다(msi-ec 가 한다). 아래는 msi-ec 소스(`BeardOverflow/msi-ec`, `CONF_G2_1`)와 이전 WMI 실험으로 확인한 대응이다.

| 주소 | 의미 |
|---|---|
| `0xD7` | 충전 상한. 하위 7비트=상한 %. sysfs `charge_control_end_threshold` 와 같은 값 |
| `0xD2` | 성능 모드. msi-ec: turbo `0xC4` · eco `0xC2` · comfort `0xC1` (예전 embedctl 은 하위 2비트로 sport `0xC0`/comfort/eco/user 를 다뤘다) |
| `0x98` 비트7 | Cooler Boost |

## 시험

```
cd mods/_tools/desktop/embedctl && python3 -I tests/test_core.py && python3 -I tests/test_helper.py     # 또는 mods/_tools/run-tests.sh 의 embedctl 줄
<textual 이 있는 python> -I tests/test_embedctlui.py                                                   # run-tests.sh 의 embedui 줄(displayui 가 쓰는 python)
```
실제 sysfs·systemctl 을 건드리지 않는다: 가짜 msi-ec/BAT/AC/hwmon/DMI 디렉터리(`EMBEDCTL_MSIEC`·`EMBEDCTL_SYSFS_BAT`·`EMBEDCTL_SYSFS_AC`·`EMBEDCTL_HWMON`·`EMBEDCTL_DMI`·`EMBEDCTL_RUN`), 가짜 `systemctl`(`EMBEDCTL_SYSTEMCTL`, `tests/fake_systemctl.py`)을 쓴다.
쓰기 경로는 전부 `embedlib.sysfs_write` 하나라서 시험이 이 함수를 대체해 msi-ec 의 부수 효과(충전 end 를 쓰면 start 가 end-10 으로 따라감 등)를 흉내 낸다.
`python3 -I` 아래에서는 `sys.path` 를 시험이 직접 구성한다(`observe/process-manager/tests/test_procctl.py` 선례).

## 파일

| 파일 | 역할 |
|---|---|
| `embedlib.py` | 코어: 게이트, sysfs 읽기, 쓰기(`apply_action`), 상태 모으기, 스냅샷(schema 2), helper 호출·결과 파일, 인스턴스 이름 검증(`INSTANCE_RE`), TLP 설정 읽기 |
| `embedctl.py` | CLI 진입점(ctlkit 봉투, `Fail(코드, 메시지)`) |
| `embedhelper.py` | root helper(`embedctl-root@<동작>.service` 가 실행; 쓰기 동작만) |
| `embedctlui.py` | TUI(Textual). `embedlib` 의 `helper_call`·`restore_plan`·`save_snapshot` 을 CLI 와 같이 쓴다 |
| `tests/` | `test_core.py`(코어·CLI·msi-ec 없음·스냅샷·restore 계획·인자 검증), `test_helper.py`(helper·쓰기 동작·끝단·restore), `fake_systemctl.py`(정적 결과), `test_embedctlui.py`(헤드리스 Textual Pilot, 가짜 상태/helper), `fake_systemctl_e2e.py`(실제 helper 코드를 가짜 sysfs 트리 위에서 실행, 상태는 파일에 유지) |

**시험의 신뢰도에 대하여**: 원래 WMI 판 시험은 복사본에서 일부러 결함을 넣어(마스크 제거, 게이트 무력화, 범위 검사 제거, 되읽기 검사 제거, 정규식 `\Z`→`$` 등) 시험이 잡는지 확인했다. 2026-11-12 sysfs 전환에서는 시험을 새로 썼고, 무맥락 검증자가 복사본에서 변이 10개(되읽기 검사 제거·게이트 무력화·`\Z`→`$`·쓰지 않은 항목 불변 검사 제거·`writable_modes` 교집합 제거·모드 허용 목록 검사 제거·충전 범위 검사 제거·롤백 제거·결과 신선도 검사 제거·unknown 롤백 가드 제거)를 넣어 **모두 시험이 잡는 것**을 확인했다(신선도 검사는 처음에 전용 시험 없이 다른 항목이 우연히 잡아 전용 시험을 추가했다). TUI 시험은 그 환경에 textual 이 없어 변이를 하지 않았다.
