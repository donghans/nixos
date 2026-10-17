# 자세(posture) — 힌지 각도로 사용 모드 판정, 입력 장치 자동 전환

MSI Summit E16 Flip(360도 힌지)에서 **힌지 각도 → 사용 모드(laptop / tent / tablet)** 를 판정해 한 곳에 발행하고, 소비자들이 그 값에 맞춰 동작한다. 2026-10-17 작업.

## 하드웨어 사실 (실측)
- 센서 허브(Intel ISH)에 IIO 장치 8개: `hinge`(힌지/화면/키보드 각도 3개, 드라이버 `hid_sensor_custom_intel_hinge`), `accel_3d`(1개 — 화면 쪽), `gyro_3d`, `gravity`, `dev_rotation`, `relative_orientation`, `geomagnetic_orientation`, `als`.
- **커널은 태블릿 모드 스위치(`SW_TABLET_MODE`)를 만들지 않는다.** 보이는 스위치는 `Lid Switch` 뿐이고 360도로 접어도 `open` 그대로. DMI 섀시 타입도 `10`(노트북). → 힌지 각도를 직접 읽어 판정해야 함.
- 평소 sysfs `in_angl*_raw` 는 **0**. 센서를 **버퍼(스트리밍) 모드로 켜야** 값이 옴(`scan_elements/in_angl*_en=1`, `buffer/enable=1`, `/dev/iio:deviceN` 읽기). 값이 바뀔 때(≥1°)만 샘플이 옴.
- 타임스탬프 채널을 켜지 않으면 **레코드는 12바이트**(s16 값이 32비트 칸 3개, 상위 비트는 쓰레기). 꺼진 채널까지 넣어 24바이트로 계산하면 못 읽음.
- 실측값(힌지 / 화면 / 키보드): 일반 열림 121/118/357, 약 90° 96/94/358, 약 180° 182/177/355, 텐트 약 270° 268/58/150, 360° 접음 359/179/178.
  **힌지 각도는 놓인 자세(베개 위 등)와 무관하게 정확**하고, `screen`/`keyboard` 각도는 자세에 따라 크게 달라진다(중력/가속도 기반으로 보이나 문서로 확인하지는 않음) → 판정에는 힌지 각도만 씀.

## 구조
```
[IIO 센서] → posture-daemon (root, system 서비스) → /run/posture/state.json → 경로 유닛 → posture-apply → 소비자들
                                                         ↑ `posture get mode` / `posture json` (가져가기)
```
- `mods/_data/posture/posture_daemon.py`: 센서를 한 프로세스만 읽고 값을 한 번만 해석(경계값/디바운스). 발행만 하고 소비자를 모름.
- `mods/_data/posture/posture`: 조회 CLI. **안전한 기본값 처리가 여기 한 곳**: 서비스 정지, 파일 없음/깨짐, 스키마 불일치 → `mode=laptop`.
- `mods/gui/base/core.posture.nix`: 서비스, 사용자 경로 유닛(`/run/posture/state.json` 변경 감시 → `posture-apply.service`), Nix 옵션 `posture.consumers`(소비자 명령 목록).
- 소비자는 "수준 기반 + 멱등": 이벤트를 놓쳐도 아무 때나 실행하면 현재 상태에 맞춰짐. 로그인(`hyprland.start`)/reload(`config.reloaded`)에도 같은 소비자를 실행(Hyprland 가 시작/reload 때 장치 상태를 초기화하므로).
- 현재 소비자: `hypr-input-policy`(입력 장치 정책, `mods/gui/base/core.bind.hwctl.nix`). 추가하려면 `posture.consumers` 에 명령 한 줄.
- 상태 스키마(`schema: 1`): `{"mode", "hinge": {"angle","screen","keyboard"}, "orientation": null, "sensors": {...}, "ts"}`. 같은 모드에서는 각도가 **5° 이상** 달라질 때만 다시 발행(소비자를 깨우는 횟수를 줄임).

## 모드 경계 (히스테리시스 + 디바운스)
`laptop → tent` 205° / `tent → laptop` 190° / `tent → tablet` 335° / `tablet → tent` 315°. 모드 변화는 1초 유지돼야 확정. 열린 채 시작해 이미 360도면 한 번에 tablet. 서비스가 멈추면(SIGTERM) 안전한 값 `laptop` 을 발행하고 켠 센서 설정을 모두 원복.

## 입력 장치 정책 (`hypr-input-policy`)
| 모드 | 내장 키보드 | 터치패드 | 터치스크린 |
|---|---|---|---|
| laptop | 켬 | **마지막 수동 상태**(메뉴에서 정한 값, 기록이 없으면 켬) | **마지막 수동 상태**(기록이 없으면 꺼짐) |
| tent / tablet | **끔(강제)** | **끔(강제)** | **켬(강제)** |
- 수동 상태 파일(`~/.local/state/hypr/touchpad_enabled`, `touchscreen_enabled`)은 텐트/태블릿에서 **건드리지 않아서** 노트북 모드로 돌아오면 원래 상태로 복원됨.
- 입력 장치 메뉴(wofi): 노트북 모드는 직접 토글, 텐트/태블릿은 "고정" 표시(선택해도 안내만). 토글 스크립트도 접힌 모드에서는 거부.
- 대상 키보드는 `at-translated-set-2-keyboard` 만(핫키 `msi-wmi-hotkeys` 등은 그대로). 펜(stylus)은 항상 켜짐.
- **복구**: 키보드가 꺼진 상태에서는 힌지를 190° 미만으로 열면 복원됨. 서비스가 멈추거나 센서가 없으면 CLI 가 laptop 을 돌려줘서 자동 복원. 최후의 수단은 외부 키보드 또는 `sudo systemctl stop posture-daemon`.
- 접힌 채 잠금 화면(hyprlock)이 뜨면 내장 키보드로 비밀번호를 칠 수 없음(얼굴 인식은 별개).

## 검증
- 자동 시험 `mods/_data/posture/tests/test_posture.py`(40개): 판정 경계/히스테리시스, 레코드 해석, 가짜 sysfs + FIFO 로 **데몬 프로세스 전체**(디바운스, 튐 무시, 다중 레코드, 종료 시 원복), CLI 안전한 기본값(깨진 파일/스키마/파일 없음/서비스 정지).
  `python3 -I mods/_data/posture/tests/test_posture.py`
- **실제 힌지로 종단 시험(사용자가 직접 접고 엶)**: 접는 도중 `laptop(190°) → tent(325°) → tablet(353°→358°)` 로 전환되며 `keyboard=false touchpad=false touchscreen=true` 가 적용됨(저널 `hypr-input-policy`).
  사용자가 키보드를 눌러 **입력이 실제로 막힌 것**과 **터치스크린이 켜진 것**을 확인. 열면(11:52:04) `mode=laptop keyboard=true touchpad=true touchscreen=false` 로 복원됨.
- 부하: posture-daemon CPU 0.0%(30초 평균), 메모리 약 13 MiB. 자세가 안 바뀌면 소비자는 깨어나지 않음.
- 미확인: 터치패드가 접힌 모드에서 실제로 막힌 것(키보드/터치스크린만 사용자가 직접 확인), 배터리 사용 시간에 미치는 영향(상시 스트리밍의 전력은 측정하지 않음).

## 다음 단계 (미구현)
- 화면 자동 회전: 상태 스키마의 `orientation` 자리는 비워 둠. 가속도로 방향을 판정하려면 센서 부호 교정이 필요하고, `displayctl` 이 모니터 규칙에 `transform` 을 넣지 않아 회전 후 `displayctl restore` 가 회전을 풀어버리므로 `displayctl` 에 회전 상태를 먼저 추가해야 함.
- 가상 키보드: 아래 조사 결과. 아직 설치/연결은 안 했음(결정 대기).

## 가상 키보드 조사 (2026-10-17)
기준: 텐트/태블릿에서는 내장 키보드가 꺼지므로 화면에서 입력할 수단이 필요. **한글 입력(fcitx5-hangul)과 충돌하지 않아야** 함.
Hyprland 0.55 가 노출하는 프로토콜(`wayland-info`로 확인): `zwp_virtual_keyboard_manager_v1`, `zwp_input_method_manager_v2`, `zwp_text_input_manager_v3`(+v1), `zwlr_virtual_pointer_manager_v1`.

| 후보 | 방식 | 한글 입력기와 | 비고 |
|---|---|---|---|
| **wvkbd 0.19.4** | 가상 키보드 프로토콜로 키 이벤트를 주입 | **충돌 없음(실측)**: 키를 보내면 fcitx5 가 일반 키보드처럼 받아 조합 | 아래 실측. nixpkgs 에 있음 |
| squeekboard 1.43.1 | input-method-v2 (입력기 자리 차지) | 충돌 가능성이 큼(추정): fcitx5 도 같은 프로토콜로 입력기 자리를 쓰는데 시트당 하나만 가능 | 시험하지 않음. 한글 배열이 있는지 확인하지 못함 |
| maliit-keyboard 2.3.1-unstable | Qt 입력기 | squeekboard 와 비슷한 이유로 충돌 가능(추정) | 시험하지 않음 |
| onboard 1.4.1 | GTK, X11 기반 | Wayland 네이티브 창에 입력되는지 불확실(추정) | 시험하지 않음 |
| fcitx5 내장 | `libvirtualkeyboard.so` 는 **D-Bus 백엔드뿐**(화면 UI 프로그램 없음) | - | nixpkgs 에 이 백엔드용 UI 패키지를 찾지 못함 → 단독 사용 불가 |
(표의 "추정"은 프로토콜 구조에서 짐작한 것이고 직접 시험하지 않은 항목.)

### wvkbd 실측
- 화면 하단 전체 폭(2560x360 으로 띄움)에 QWERTY 한 장: Esc, Tab, 방향키, Shift, Cmp(compose), Ctr, 쉼표/마침표/Enter, 백스페이스. 레이어에 숫자/특수/이모지/내비 등(`--list-layers`: full, fullwide, special, specialpad, simple, dialer, cyrillic … emoji, nav, landscape).
- **영문 입력 확인**: 포인터로 키를 눌러 테스트 창에 `a` 가 찍힘. 키보드 창을 눌러도 입력 창의 **포커스가 유지**됨.
- **한글 입력 확인**: fcitx5 를 한글로 두고 `g`, `k`, `s` 를 누르자 `한` 이 조합돼 찍힘(2벌식 배열 그대로).
- **한/영 전환 확인**: `Ctr` 다음 스페이스(= Ctrl+Space)로 fcitx5 가 `hangul` → `keyboard-us` 로 바뀜(fcitx5 전환키 `Control+space`). 한/영 전용 키는 없음.
- **보이기/숨기기 시그널 확인**: `--hidden` 으로 숨긴 채 시작 가능. `SIGUSR2` = 표시, `SIGUSR1` = 숨김, `SIGRTMIN` = 토글(레이어 서피스가 생기고 사라지는 것을 `hyprctl layers` 로 확인).
- 옵션: `-H`/`-L` 세로/가로 높이, `--fn` 글꼴, `--non-exclusive`(창과 겹침 허용, 아니면 작업 영역을 줄임), 색상 지정.
- 한계: 한/영 전환이 `Ctr`+스페이스 두 번 누름(전용 키 없음), 화면 폭 전체를 차지해서 크기/위치 조정 필요, 터치(손가락) 입력은 직접 시험하지 못함(포인터 클릭으로만 확인).

### 자세 허브와 연결하는 방법(구상, 미구현)
`wvkbd-mobintl --hidden` 을 사용자 서비스로 상시 띄워 두고(메모리만 차지), `posture.consumers` 에 "tent/tablet 이면 SIGUSR2, laptop 이면 SIGUSR1" 소비자를 추가. 멱등이라 reload/로그인에도 안전.
