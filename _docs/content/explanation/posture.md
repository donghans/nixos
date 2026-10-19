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
- 화면 자동 회전: 위 설명 참고(미구현).

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

### 구현: `vkb` (접기/펴기, 크기, 창 가림 방지, 터치 버튼, 자세 연동)
`mods/_data/vkb/vkb.py`(명령 `vkb`), 서비스/연결은 `mods/gui/base/vkb.nix`, 버튼은 `mods/gui/base/waybar.nix` + `mods/_data/waybar/style.css`.
- **wvkbd 의 한계(소스 확인)**: 위치는 하단 전체 폭 고정, 높이는 시작할 때만 지정(`-H`/`-L`), 숨기기 전용 키 없음(`⌨` 키는 **레이어 전환**), 플로팅/폭 옵션 없음. 그래서 아래 패치로 플로팅을 추가하고, 접고 펴기는 시그널, 크기는 재시작으로 처리하며 그 위에 제어층(`vkb`)을 얹음.
  접기/펴기 전용 키는 두지 않음(waybar 버튼으로 충분). 대신 키보드 안에 도킹↔플로팅 전환 키(`⧉`)를 둠.
- `wvkbd.service`(사용자 서비스): `--hidden` 으로 상시 대기(메모리만 차지). 시작 인자는 `vkb args` 가 `~/.config/vkb/config.json`(크기/모드/레이어)과 화면 물리 크기로 계산.
- 명령: `vkb show|hide|toggle`, `vkb size small(8mm)|medium(10mm)|large(12.5mm)|4~30|up|down|cycle`, `vkb mode dock|float|toggle`, `vkb layers full,special,…`, `vkb auto on|off`, `vkb status [--json]`, `vkb waybar [size|mode]`, `vkb args`.
- **크기는 mm 기준(화면 dpi 반영)**: `hyprctl monitors` 의 `physicalWidth`(이 기기 340mm → 2560px, 7.53px/mm)로 계산. 키 한 줄 높이 medium 10mm(손가락 터치 최소 권장 9~10mm 근처) → 가로 배열 5줄 376px, 세로 배열 6줄 452px(화면 높이의 45% 상한). 플로팅 폭은 13키 × 14.5mm = 1419px(화면의 55%), 글자 크기는 줄 높이에 비례(18pt). 회전한 화면은 가로세로와 물리 크기를 바꿔서 계산(회전 자체는 미구현).
- **창 가림 방지**: wvkbd 는 기본으로 하단 배타 영역을 요청해서 **타일 창은 자동으로 줄어듦**. 떠 있는(floating) 창은 영역과 무관해 가려지므로 `vkb` 가 보일 때 **키보드 윗면 아래로 내려온 창만** 높이를 줄이고(260px 미만이 되면 위로 이동), 원본 지오메트리를 `~/.local/state/vkb/fit.json` 에 기록.
  숨길 때 **그 창이 맞춘 상태 그대로일 때만** 복원(그 사이 사용자가 옮기거나 크기를 바꿨으면 건드리지 않음, 닫힌 창은 무시).
- **터치 버튼(waybar, 모두 단일 탭)**: `⌨` 접기/펴기(펴지면 하늘색), `⧉` 하단 고정↔플로팅(플로팅이면 하늘색), 크기 `S`/`M`/`L`(탭하면 다음 크기). 세 버튼 모두 **노트북 모드에서는 키보드가 떠 있을 때만** 보이고 텐트/태블릿에서는 항상 보임(`⧉`/크기는 키보드가 보일 때만). `vkb waybar` 가 빈 출력을 내면 모듈이 사라지는 waybar 동작을 이용. 한/영 버튼은 시스템 트레이의 fcitx5 아이콘과 중복이라 없앰(키보드 안에 `한/영` 키가 있음).
  상태가 바뀌거나 자세가 바뀔 때(`apply-posture`)만 waybar 에 `RTMIN+8` 신호를 보내 다시 그려서 폴링이 없음.
- **자세 연동**: `posture.consumers` 에 `vkb apply-posture` 등록. 자동(기본 켜짐)이면 tent/tablet → 보임, laptop → 숨김. 멱등(이미 그 상태면 아무것도 안 함). `vkb auto off` 로 끔.
- 실제 화면 검증(2026-10-17): 보이기 → 타일 창(Zed/kitty)이 1570→1210 으로 자동으로 줄고 떠 있는 Thunar 는 693→417 로 맞춰짐, 숨기기 → 모두 원복(기록 비움).
  (2026-10-17 재확인) 도킹: 타일 창 1570→1194, 떠 있는 Thunar 693→401. 플로팅(`vkb mode float`): 창이 모두 원래 크기로 돌아오고 키보드(571,1212, 1419×376)가 위에 겹침. 도킹으로 복귀하면 다시 맞춰지고, 숨기면 원복. waybar 에서 `⧉` 를 포인터로 눌러 전환됨을 확인.
- **wvkbd 패치**(`mods/_data/wvkbd/float-mode.patch`(기능) + `pc-layout.patch`(배열), `vkb.nix` 의 `overrideAttrs`; 다시 만드는 법은 `mods/_data/wvkbd/README.md`):
  ① 플로팅 모드: `--float`, `--float-width`, `--float-margin`, 시그널 `RTMIN+1`(토글)/`+2`(도킹)/`+3`(플로팅). 플로팅이면 하단 가운데 고정 폭, 배타 영역 없음(창이 안 줄어듦). 새 키 종류 `Float`(`⧉`)가 자기 자신에게 `RTMIN+1` 을 보냄.
  ② 모드가 바뀐 뒤 `--on-mode <명령>` 을 실행(환경변수 `WVKBD_MODE`) → `vkb mode-changed` 가 설정 저장과 창 맞춤/복원을 처리(키 입력으로 바뀌어도 `vkb` 와 상태가 어긋나지 않게).
  ③ `한/영` 키(`KEY_HANGEUL`; fcitx5 전환키에 `Hangul` 이 이미 등록돼 있어 설정 변경 없음). ④ 가로 배열(`Landscape`)을 PC 표준 5줄(숫자 줄, Tab/CpL/Shift 줄, 아래줄 `Ctr Sup ⧉ ⌨ 한/영 Alt 스페이스 Esc ←↓↑→`)로 교체(합 15키 폭). `Sup`(Super)는 처음에 레이어를 전환해야만 있어서 메인 배열 아래줄로 옮김(Hyprland 단축키가 전부 Super 기반).
  함정: wvkbd 의 `die()` 매크로는 중괄호 없는 두 문장이라 `if (...) die(...)` 로 쓰면 조건과 무관하게 종료한다(처음 패치에서 겪음; 중괄호로 감쌈).
  실제 화면에서 `한/영` 탭으로 hangul↔keyboard-us 전환, `⧉` 탭으로 도킹↔플로팅 전환을 확인(포인터 클릭). 다른 레이어(`special` 등)의 숫자 줄과 세로 배열은 확인하지 않음. wvkbd 버전이 바뀌면 패치가 안 맞을 수 있음(빌드가 실패하므로 알 수 있음).
- 시험: `python3 -I mods/_data/vkb/tests/test_vkb.py`(25, 맞춤/복원/크기 계획/mm→px 계산), `test_vkb_cli.py`(45, 가짜 hyprctl/systemctl 로 전체 흐름).
- **미확인**: 손가락 터치로 waybar 버튼이 눌리는지(포인터 클릭만 확인, GTK 가 터치를 클릭으로 바꾸는 것으로 알려져 있으나 직접 확인 못 함), waybar 높이 24px 의 터치 적합성, 자세 연동의 실제 힌지 시험, 가상 키보드가 보이는 동안 잠금 화면/Hyprland reload 와의 상호작용.

### 알려진 한계: 터치스크린으로는 창 이동/크기 조절이 안 됨
Hyprland 의 제스처 클래스는 전부 터치패드용(`TrackpadGesture`)이고 터치스크린용은 워크스페이스 스와이프(`gestures:workspace_swipe_touch`)뿐이다. `Super`+드래그는 마우스 버튼 바인딩(`bindm`)이라 터치에는 적용되지 않고,
터치는 클라이언트에 터치 이벤트로 그대로 전달된다(그래서 클릭/우클릭이 섞여 들어가는 것처럼 보일 수 있음). 설정으로 고칠 수 없는 컴포지터의 한계라서, 태블릿 모드에서는 창을 옮길 일이 없게 만드는 쪽(창 최대화 등)이 대안.

### 화면 자동 회전 (2026-10-17)
tent/tablet 에서 기기를 돌리면 내장 화면과 터치가 같이 돈다. laptop 으로 돌아오면 항상 0(세로로 들어도 돌리지 않음).
- **방향 판정**(`posture_daemon.py`): 화면(뚜껑)의 가속도 센서(IIO `accel_3d`, sysfs 로 읽힘)를 tent/tablet 에서만 ~3Hz 로 읽음(laptop 에서는 읽지 않음). 발행: `orientation = {"rotation": 0|90|180|270, "flat": bool}`.
  rotation 은 **기기를 시계방향으로 돌린 각도**: `atan2(x, -y)`. 실측(태블릿 상태로 비스듬히 들고 잰 5자세): 정방향 가로 y=-8.4(0°), 윗변이 오른쪽 x=+8.8(90°), 거꾸로 y=+9.0(180°), 윗변이 왼쪽 x=-8.8(270°), 책상에 평평 z=-9.7.
  축 방향: +x=화면 왼쪽, +y=화면 아래, -z=화면 앞쪽(reading 이 위쪽을 가리킴).
  흔들림 방지: 현재 방향 중심에서 45+15=60° 넘게 벗어나야 바뀜, 새 방향이 0.8초 유지돼야 확정, 화면 평면 방향 중력 성분이 2.5m/s² 미만(≈15° 이내로 눕힘)이면 `flat` 으로 보고 마지막 방향 유지(3.5 이상이어야 해제).
- **화면 회전**(`displayctl rotate <0~3|auto>`, 자세 허브 소비자): `ROTATION_TO_TRANSFORM = {0:0, 90:1, 180:2, 270:3}`. 모니터별 transform 을 상태 파일에 기록해 `restore`/레이아웃 변경에도 유지되고, 회전된 논리 크기로 확장 배치를 다시 계산. 이미 그 방향이면 아무것도 적용하지 않음. 꺼진/미러 화면은 회전하지 않음.
- **터치 동기화**(`sync_touch`): Hyprland 는 터치 좌표를 `모니터 위치 + 정규화 좌표 × 모니터 크기` 로만 계산하고 모니터 회전을 반영하지 않는다(소스 `Touch.cpp`). 그래서 회전하면 터치가 어긋났다(실제로 가상 키보드가 엉뚱한 글자를 입력).
  장치별 `hl.device({name, transform = N})`(터치스크린 `input:touchdevice:transform`, 스타일러스 `input:tablet:transform`)을 모니터 transform 과 같은 값으로 맞춘다. reload 때 초기화되므로 `restore` 에서도 호출.
- **실제 화면 확인(사용자, 2026-10-17)**: 태블릿에서 시계방향 90° 돌리면 화면이 똑바로 서고, 터치/가상 키보드 입력도 맞음. 180°/270° 는 시험 항목으로는 확인 요청하지 않았고 사용자는 "된다"고만 답함.
- **버그 수정**: 센서는 값이 바뀔 때만 샘플을 줘서, 힌지를 가만히 둔 채 데몬이 (재)시작되면 첫 샘플이 오지 않아 `stopped/laptop` 으로 남았다(접은 채 부팅하면 모드를 모를 수 있음).
  시작할 때 장치 노드를 연 뒤 `in_angl_hysteresis` 를 0 으로 쓰고 **0.3초 뒤** 원래 값으로 되돌리면 샘플이 나온다(바로 되돌리면 안 나옴: 실측 0.2~0.5초 지연 필요). 가만히 둔 채 재시작해도 `tablet 360` 이 바로 채워지는 것을 확인.
- 시험: posture 60(방향 판정/디바운스/눕힘/레이스 포함), displayctl 코어 78 + TUI 53(회전/터치 동기화/restore 유지/꺼진 화면/미러).
- **미확인**: 가속도 폴링의 배터리 영향(tent/tablet 에서만 3Hz), 외장 모니터가 연결된 채 회전할 때 배치(시험은 가짜 hyprctl 로만), 회전 중 열려 있는 floating 창의 위치 보정, 터치 제스처로 창을 옮기는 것.

### 터치 제스처 플러그인(hyprgrass): 시도했으나 Hyprland 가 크래시해서 꺼 둠 (2026-10-17)
- 목적: 터치로 창 이동(3손가락 길게 눌러 끌기)/크기 조절/워크스페이스 스와이프. `mods/gui/base/core.touch.nix` 에 구성이 남아 있고 `enableHyprgrass = false` 로 비활성.
- nixpkgs 의 hyprgrass(2025-10)는 Hyprland 0.55 와 컴파일이 안 돼서, 업스트림 `hyprpm.toml` 이 "Hyprland v0.55.2(39d7e209) ↔ hyprgrass 3236fbb1" 로 고정한 커밋을 직접 빌드(wf-touch 는 테스트용 doctest 링크 때문에 `-Dtests=disabled`). 빌드와 생성된 Lua 문법은 통과.
- **결과**: 적용하자 실행 중이던 Hyprland 가 `SEGV`. 크래시 리포트 3건 모두 스택이 `libhyprgrass.so(pluginInit+0x61e)` ← `CPluginSystem::loadPlugin`(로드할 때마다 같은 위치, 재현됨). 설정에 로드가 남아 있어서 로그인(tuigreet)할 때마다 반복 크래시했다.
  `pcall` 로 감싸도 소용없다(Lua 오류가 아니라 네이티브 크래시).
- **원인 확정(2026-10-19, 중첩 Hyprland 로 재현)**: 이 고정 커밋은 Hyprlang 시절 코드다. `getConfigValue(PHANDLE, "plugin:touch_gestures:...")` 를 15곳 넘게 쓰는데 Lua 설정(0.55)에서는 이 값들이 등록되지 않아 nullptr 이고, 그 결과를 바로 역참조한다.
  디버그 빌드(`mesonBuildType=debug`, `dontStrip`) + `addr2line` 으로 줄을 확인: `main.cpp:380`(`getConfigValue(...)->getDataStaticPtr()`) → 그 줄을 널 검사로 막으면 `GestureManager.cpp:83`(생성자)에서 같은 유형으로 죽음. 한 줄 패치로는 해결 안 됨.
  `hyprpm.toml` 의 "Hyprland 커밋 ↔ hyprgrass 커밋" 고정은 컴파일 호환만 뜻하고 Lua 런타임 호환은 아니다.
- **버전별 비교(2026-10-19, 모두 중첩 Hyprland 로 시험)** — 핵심: 고정 커밋 3236fbb1(6/9)은 Hyprlang 시절, **바로 다음 날 d094a3e6(6/10)부터 Lua 방식**(getConfigValue 0곳). 업스트림 hyprpm 은 d094a3e6 을 Hyprland 0.55.1/0.55.4 에 고정해 둠.

  | 조합 | 빌드 | 로드 | 비고 |
  |---|---|---|---|
  | stable 0.55.2 + 3236fbb1 (Hyprlang 시절, 예전 시도) | 됨 | **SEGV** | getConfigValue null 역참조(main.cpp:380, GestureManager.cpp:83) |
  | **stable 0.55.2 + d094a3e6 (Lua)** | **됨** | **됨**, Lua 설정(hl.config, hyprgrass.bind/gesture)이 오류 없이 받아들여짐 | Hyprland 를 올릴 필요 없음. 실제 터치는 중첩 환경에서 못 시험 |
  | unstable 0.56.2 + nixpkgs 패키지(d094a3e6) | 실패 | - | `TouchVisualizer.cpp`: PI 미선언, `scheduleFrameForMonitor` 없음(API 변경). nixpkgs 는 broken 표시 안 함 |
  | unstable 0.56.2 + 8e605468(0.56.2 고정 커밋, 8/11) | 실패 | - | `PinchAction::exceeds_tolerance marked override` — wf-touch 인터페이스 불일치 |
  | unstable 0.56.2 + 6adcebc2(최신, 10/18) | 실패 | - | `ShimTrackpadGestures.cpp:228: 'LOG' was not declared` |
- 결론: **stable 유지 + hyprgrass d094a3e6**. unstable 로 올려도 어떤 변종도 그대로는 안 빌드돼서 소스를 따로 고쳐야 하고(wf-touch 버전, LOG 매크로), 컴포지터 업그레이드 위험까지 지게 된다. `core.touch.nix` 가 이 조합으로 준비돼 있고 `enableHyprgrass = false` 로 꺼져 있다. 켜기 전에 열린 작업을 저장할 것.
- 만약 unstable Hyprland 를 쓰게 되면: `nixup fix hyprland` 가 `.env` 의 `NIX_UNSTABLE_FALLBACK_REV/SHA` 에 "직전 커밋"을 기록하고 모듈에서 `unstable-fallback.hyprland` 로 쓰는 기존 고정 장치(core/lib/host.nix)를 그대로 쓸 수 있다.
- **격리 시험 방법(유효함)**: 현재 세션 안에서 `Hyprland -c <최소 설정>` 을 `systemd-run --user --unit=...` 로 중첩 실행하면 플러그인 로드 크래시를 실제 세션과 분리해 재현할 수 있다(`env -u LD_LIBRARY_PATH -u HYPRLAND_INSTANCE_SIGNATURE`, `WAYLAND_DISPLAY` 전달). 정리는 반드시 유닛/PID 로(이름으로 pkill 하면 실제 세션도 죽음 — 2026-10-19 실수).
- 교훈: 플러그인 로드는 **실행 중인 세션에서 시험하면 안 된다**. 이번엔 "적용 전 확인받기"로 해 둔 구성을 이미 커밋해 둔 상태에서 다른 변경(`nixup home`)을 적용하다가 같이 들어가 버렸다(적용 안 할 것은 커밋하지 않거나 처음부터 꺼 둘 것).

### 덮개를 열면 화면이 까만 채로 남던 문제 (2026-10-17)
- 증상: 덮개를 닫았다 열면 hyprlock 은 떠 있고(IR 카메라 불, 키보드 입력도 들어감) 화면에는 아무것도 안 보이고, tty 를 옮겼다 돌아오면 복구.
- 원인(재현·확인): 덮개 바인딩이 `hyprctl dispatch dpms disable/enable` 을 썼는데 **`dpms enable` 뒤에 화면이 다시 켜지지 않음**. 잠금 없이 `dpms disable` → `enable` 만 해도 재현됨.
  그때 커널 `/sys/class/drm/card1-eDP-1/dpms` 는 `On`, Hyprland `dpmsStatus=true`, 백라이트 96000 으로 모두 정상으로 보이는데 화면만 까맣다(tty 전환의 전체 모드 재설정이 복구).
  덤으로 화면이 꺼진 동안 hyprlock 이 해제를 마무리하지 못하고 화면이 켜지는 순간에야 끝났다(`authenticated` 와 `Unlocking session` 이 5초 차이).
  닫을 때 hyprlock 이 배경용 화면 캡처를 기다리다 `Gathering resources timed out after 2000 milliseconds` 로 2초 지연되는 것도 같은 원인(꺼진 화면은 캡처가 안 됨). dpms 없이 잠그면 17ms.
- 왜 dpms 가 안 켜지는지는 모름(i915 + `i915.enable_psr=1` + Hyprland 0.55.2. PSR 의심은 하지만 확인 안 함. 화면이 까만 동안 `grim` 으로 컴포지터가 그리는지 보는 시험은 하지 않았다).
- 조치: dpms 를 쓰지 않고 **백라이트만** 끄고 켬(`lid-screen off|on`, `brightnessctl` 사용, 닫을 때 밝기를 한 번만 저장해 닫힘이 두 번 와도 원래 밝기를 잃지 않음). 모드 재설정이 없어 이 경로의 문제가 생기지 않는다.
- 확인(사용자): 백라이트 시험 후 화면 정상, 실제 덮개를 닫았다 열어도 정상. 오래 닫아 둔 뒤 열기는 확인 중.

### 모듈 구성과 유지보수 규칙 (2026-10-19 점검)
| 모듈/파일 | 책임 | 소비자 등록 |
|---|---|---|
| `mods/gui/base/core.posture.nix` + `mods/_data/posture/` | 허브: 센서(힌지/가속도) → 상태 파일 → 소비자 호출. 소비자의 내용은 모름 | `posture.consumers` 옵션 |
| `mods/gui/base/core.bind.hwctl.nix` | 입력 장치 정책(`hypr-input-policy`)과 토글/메뉴, 덮개 동작(`lid-screen`) | 정책을 소비자로 등록 |
| `mods/gui/base/vkb.nix` + `mods/_data/vkb/` + `mods/_data/wvkbd/` | 가상 키보드 서비스와 제어 CLI, wvkbd 패치 | `vkb apply-posture` |
| `mods/gui/base/display-manager.nix` + `mods/_data/display/` | 화면 구성/회전(`displayctl rotate auto`), 터치 좌표 동기화 | `displayctl rotate auto` |
- 한 가지 일은 한 곳에서: 장치 켜기/끄기와 수동 상태 파일의 기본값은 `hypr-input-policy` 에만 있고, 터치패드/터치스크린 토글은 상태 파일만 뒤집고 정책을 부른다(예전에는 토글 두 개와 정책이 각자 같은 장치 선택/적용 코드를 가졌음). 메뉴 라벨도 정책의 `--print` 값을 쓴다.
- 두 곳에 같은 숫자가 있으면 시험이 지키게 한다: 가로 배열의 줄 수/폭 단위(5줄, 15)는 `pc-layout.patch` 와 `vkb.py`(`LAND_ROWS`/`LAND_UNITS`) 에 따로 있어서, `test_vkb.py` 가 원본 wvkbd 에 두 패치를 실제로 적용해 읽고 비교한다(패치가 안 맞아도 여기서 실패).
- 내장 키보드 이름은 공용 모듈이 아니라 호스트가 `wayland.windowManager.hyprland.internalKeyboardName` 로 지정한다(비어 있으면 정책이 키보드를 건드리지 않음).
- 아직 남은 것(위험 낮음, 필요할 때): `posture` CLI 를 소비자가 값마다 한 번씩 부름(파이썬 시작 + systemctl 확인이 매번);
  `_data/*/tests/` 마다 가짜 hyprctl/systemctl 을 따로 만들어 쓰는 중복; `displayctl.py` 가 1000줄이 넘는 단일 파일.
