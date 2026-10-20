# 사용 모드(posture) — 힌지 각도로 laptop/tent/tablet 판정, 입력 장치 자동 전환

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
[IIO 힌지/가속도 센서] ┐
[덮개 스위치(evdev)]   ┴→ posture-daemon (root, system 서비스) → /run/posture/state.json     → 경로 유닛 → posture-apply → 소비자들
                                                           └→ /run/posture/telemetry.json (힌지 각도; 감시 안 함)
                          `posture get mode|lid|rotation|angle` / `posture json` (가져가기: 두 파일을 합쳐 보여 줌)
```
- `mods/_data/posture/posture_daemon.py`: 센서와 덮개 스위치를 한 프로세스만 읽고 값을 한 번만 해석(경계값/디바운스). 발행만 하고 소비자를 모름. 힌지 센서가 없는 일반 노트북에서도 덮개 때문에 돈다(둘 다 없으면 종료).
- `mods/_data/posture/posture`: 조회 CLI. **안전한 기본값 처리가 여기 한 곳**: 서비스 정지, 파일 없음/깨짐, 스키마 불일치 → `mode=laptop`, 덮개는 `open`(화면이 꺼진 채 남지 않는 쪽).
- `mods/gui/base/core.posture.nix`: 서비스, 사용자 경로 유닛(`/run/posture/state.json` 변경 감시 → `posture-apply.service`), Nix 옵션 `posture.consumers`(소비자 명령 목록).
- 소비자는 "수준 기반 + 멱등": 이벤트를 놓쳐도 아무 때나 실행하면 현재 상태에 맞춰짐. 로그인(`hyprland.start`)/reload(`config.reloaded`)에도 같은 소비자를 실행(Hyprland 가 시작/reload 때 장치 상태를 초기화하므로).
- 현재 소비자(실행 순서): `lid-policy`(덮개 닫힘/열림 → 백라이트 끄기/켜기 + 호스트 추가 명령, `core.bind.hwctl.nix`), `vkb apply-posture`(`vkb.nix`), `displayctl rotate auto`(`display-manager.nix`), `hypr-input-policy`(입력 장치 정책, `core.bind.hwctl.nix`). 추가하려면 `posture.consumers` 에 명령 한 줄.
- 적용 범위: 허브/덮개/입력 정책은 모든 노트북(`type = "laptop"`), 가상 키보드·화면 자동 회전·터치 제스처·waybar 키보드 버튼은 **2-in-1 호스트만**(`hosts/<호스트>.toml` 의 `convertible = true`).
- `state.json`(`schema: 1`): `{"mode", "orientation": {"rotation","flat"}, "lid": "open|closed|null", "sensors": {...}, "ts"}` — **소비자가 알아야 하는 값이 변할 때만** 갱신하고 경로 유닛은 이 파일만 본다.
  `telemetry.json`: `{"hinge": {"angle","screen","keyboard"}, "ts"}` — 각도는 **5° 이상** 달라질 때 갱신하지만 감시하지 않아 소비자를 깨우지 않는다. (분리 이유: 각도를 상태 파일에 두었을 때 덮개를 여는 몇 초 동안 5° 마다 모든 소비자가 5번 넘게 다시 실행됐다. 2026-10-17 저널로 확인)
- **덮개**: 허브가 `Lid Switch`(evdev SW_LID)를 읽어 `lid` 를 발행하고(시작 값은 `/proc/acpi/button/lid/*/state`), `lid-policy` 가 바뀔 때만 백라이트와 추가 명령(이 기기는 `tlp bat`/`tlp start`)을 처리한다.
  **잠금은 허브를 거치지 않고 Hyprland 덮개 바인딩(`loginctl lock-session`)에 둔다** — 허브 데몬이 죽어 있어도 덮개를 닫으면 잠겨야 하기 때문. 허브가 안 돌면 `lid` 는 open 이라 화면은 켜진 쪽으로 복구된다.

## 모드 경계 (히스테리시스 + 디바운스)
`laptop → tent` 205° / `tent → laptop` 190° / `tent → tablet` 335° / `tablet → tent` 315°. 모드 변화는 1초 유지돼야 확정. 열린 채 시작해 이미 360도면 한 번에 tablet. 서비스가 멈추면(SIGTERM) 안전한 값 `laptop` 을 발행하고 켠 센서 설정을 모두 원복.

## 입력 장치 정책 (`hypr-input-policy`)
| 모드 | 내장 키보드 | 터치패드 | 터치스크린 |
|---|---|---|---|
| laptop | 켬 | **마지막 수동 상태**(메뉴에서 정한 값, 기록이 없으면 켬) | **마지막 수동 상태**(기록이 없으면 꺼짐) |
| tent / tablet | **끔(강제)** | **끔(강제)** | **켬(강제)** |
- 수동 상태 파일(`~/.local/state/hypr/touchpad_enabled`, `touchscreen_enabled`)은 텐트/태블릿에서 **건드리지 않아서** 노트북 모드로 돌아오면 원래 상태로 복원됨.
- 입력 장치 메뉴(wofi): 노트북 모드는 직접 토글, 텐트/태블릿은 "고정" 표시(선택해도 안내만). 토글 스크립트도 접힌 모드에서는 거부.
- 대상 키보드는 호스트가 `wayland.windowManager.hyprland.internalKeyboardName` 로 지정한 것만(이 기기는 `at-translated-set-2-keyboard`; 핫키 `msi-wmi-hotkeys` 등은 그대로, 지정하지 않으면 키보드는 건드리지 않음). 펜(stylus)은 항상 켜짐.
- **복구**: 키보드가 꺼진 상태에서는 힌지를 190° 미만으로 열면 복원됨. 서비스가 멈추거나 센서가 없으면 CLI 가 laptop 을 돌려줘서 자동 복원. 최후의 수단은 외부 키보드 또는 `sudo systemctl stop posture-daemon`.
- 접힌 채 잠금 화면(hyprlock)이 뜨면 내장 키보드로 비밀번호를 칠 수 없음(얼굴 인식은 별개).

## 검증
- 자동 시험 `mods/_data/posture/tests/test_posture.py`(75개): 판정 경계/히스테리시스, 방향 판정, 레코드 해석, 가짜 sysfs + FIFO 로 **데몬 프로세스 전체**(디바운스, 튐 무시, 다중 레코드, 각도/상태 파일 분리, 덮개 이벤트와 중복 무시, 종료 시 원복), 힌지 없는 노트북(덮개만)과 아무 센서도 없을 때 종료, CLI 안전한 기본값(깨진 파일/스키마/파일 없음/서비스 정지/덮개 모름).
  `python3 -I mods/_data/posture/tests/test_posture.py`
- **실제 힌지로 종단 시험(사용자가 직접 접고 엶)**: 접는 도중 `laptop(190°) → tent(325°) → tablet(353°→358°)` 로 전환되며 `keyboard=false touchpad=false touchscreen=true` 가 적용됨(저널 `hypr-input-policy`).
  사용자가 키보드를 눌러 **입력이 실제로 막힌 것**과 **터치스크린이 켜진 것**을 확인. 열면(11:52:04) `mode=laptop keyboard=true touchpad=true touchscreen=false` 로 복원됨.
- 부하: posture-daemon CPU 0.0%(30초 평균), 메모리 약 13 MiB. 사용 모드가 안 바뀌면 소비자는 깨어나지 않음.
- 미확인: 터치패드가 접힌 모드에서 실제로 막힌 것(키보드/터치스크린만 사용자가 직접 확인), 배터리 사용 시간에 미치는 영향(상시 스트리밍의 전력은 측정하지 않음).

## 다음 단계
- 화면 자동 회전은 구현됨(아래 "화면 자동 회전" 절).
- lid-policy 의 실제 덮개 시험(닫아서 백라이트가 꺼지고 열어서 복구되는지, 오래 닫아 둔 뒤)은 사용자 확인 대기.

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

### 구현: `vkb` (접기/펴기, 크기, 창 가림 방지, 터치 버튼, 사용 모드 연동)
`mods/_data/vkb/vkb.py`(명령 `vkb`), 서비스/연결은 `mods/gui/base/vkb.nix`, 버튼은 `mods/gui/base/waybar.nix` + `mods/_data/waybar/style.css`.
- **wvkbd 의 한계(소스 확인)**: 위치는 하단 전체 폭 고정, 높이는 시작할 때만 지정(`-H`/`-L`), 숨기기 전용 키 없음(`⌨` 키는 **레이어 전환**), 플로팅/폭 옵션 없음. 그래서 아래 패치로 플로팅을 추가하고, 접고 펴기는 시그널, 크기는 재시작으로 처리하며 그 위에 제어층(`vkb`)을 얹음.
  접기/펴기 전용 키는 두지 않음(waybar 버튼으로 충분). 대신 키보드 안에 도킹↔플로팅 전환 키(`⧉`)를 둠.
- `wvkbd.service`(사용자 서비스): `--hidden` 으로 상시 대기(메모리만 차지). 시작 인자는 `vkb args` 가 `~/.config/vkb/config.json`(크기/모드/레이어)과 화면 물리 크기로 계산.
- 명령: `vkb show|hide|toggle`, `vkb size small(8mm)|medium(10mm)|large(12.5mm)|4~30|up|down|cycle`, `vkb mode dock|float|toggle`, `vkb layers full,special,…`, `vkb auto on|off`, `vkb status [--json]`, `vkb waybar [size|mode]`, `vkb args`.
- **크기는 mm 기준(화면 dpi 반영)**: `hyprctl monitors` 의 `physicalWidth`(이 기기 340mm → 2560px, 7.53px/mm)로 계산. 키 한 줄 높이 medium 10mm(손가락 터치 최소 권장 9~10mm 근처) → 가로 배열 5줄 376px, 세로 배열 6줄 452px(화면 높이의 45% 상한). 플로팅 폭은 13키 × 14.5mm = 1419px(화면의 55%), 글자 크기는 줄 높이에 비례(18pt). 회전한 화면은 가로세로와 물리 크기를 바꿔서 계산(회전 자체는 미구현).
- **창 가림 방지**: wvkbd 는 기본으로 하단 배타 영역을 요청해서 **타일 창은 자동으로 줄어듦**. 떠 있는(floating) 창은 영역과 무관해 가려지므로 `vkb` 가 보일 때 **키보드 윗면 아래로 내려온 창만** 높이를 줄이고(260px 미만이 되면 위로 이동), 원본 지오메트리를 `~/.local/state/vkb/fit.json` 에 기록.
  숨길 때 **그 창이 맞춘 상태 그대로일 때만** 복원(그 사이 사용자가 옮기거나 크기를 바꿨으면 건드리지 않음, 닫힌 창은 무시).
- **터치 버튼(waybar, 모두 단일 탭)**: `⌨` 접기/펴기(펴지면 하늘색), `⧉` 하단 고정↔플로팅(플로팅이면 하늘색), 크기 `S`/`M`/`L`(탭하면 다음 크기). 세 버튼 모두 **노트북 모드에서는 키보드가 떠 있을 때만** 보이고 텐트/태블릿에서는 항상 보임(`⧉`/크기는 키보드가 보일 때만). `vkb waybar` 가 빈 출력을 내면 모듈이 사라지는 waybar 동작을 이용. 한/영 버튼은 시스템 트레이의 fcitx5 아이콘과 중복이라 없앰(키보드 안에 `한/영` 키가 있음).
  상태가 바뀌거나 사용 모드가 바뀔 때(`apply-posture`)만 waybar 에 `RTMIN+8` 신호를 보내 다시 그려서 폴링이 없음.
- **사용 모드 연동**: `posture.consumers` 에 `vkb apply-posture` 등록. 자동(기본 켜짐)이면 tent/tablet → 보임, laptop → 숨김. 멱등(이미 그 상태면 아무것도 안 함). `vkb auto off` 로 끔.
- 실제 화면 검증(2026-10-17): 보이기 → 타일 창(Zed/kitty)이 1570→1210 으로 자동으로 줄고 떠 있는 Thunar 는 693→417 로 맞춰짐, 숨기기 → 모두 원복(기록 비움).
  (2026-10-17 재확인) 도킹: 타일 창 1570→1194, 떠 있는 Thunar 693→401. 플로팅(`vkb mode float`): 창이 모두 원래 크기로 돌아오고 키보드(571,1212, 1419×376)가 위에 겹침. 도킹으로 복귀하면 다시 맞춰지고, 숨기면 원복. waybar 에서 `⧉` 를 포인터로 눌러 전환됨을 확인.
- **wvkbd 패치**(`mods/_data/wvkbd/float-mode.patch`(기능) + `pc-layout.patch`(배열), `vkb.nix` 의 `overrideAttrs`; 다시 만드는 법은 `mods/_data/wvkbd/README.md`):
  ① 플로팅 모드: `--float`, `--float-width`, `--float-margin`, 시그널 `RTMIN+1`(토글)/`+2`(도킹)/`+3`(플로팅). 플로팅이면 하단 가운데 고정 폭, 배타 영역 없음(창이 안 줄어듦). 새 키 종류 `Float`(`⧉`)가 자기 자신에게 `RTMIN+1` 을 보냄.
  ② 모드가 바뀐 뒤 `--on-mode <명령>` 을 실행(환경변수 `WVKBD_MODE`) → `vkb mode-changed` 가 설정 저장과 창 맞춤/복원을 처리(키 입력으로 바뀌어도 `vkb` 와 상태가 어긋나지 않게).
  ③ `한/영` 키(`KEY_HANGEUL`; fcitx5 전환키에 `Hangul` 이 이미 등록돼 있어 설정 변경 없음). ④ 가로 배열(`Landscape`)을 PC 표준 5줄(숫자 줄, Tab/CpL/Shift 줄, 아래줄 `Ctr Sup ⧉ ⌨ 한/영 Alt 스페이스 Esc ←↓↑→`)로 교체(합 15키 폭). `Sup`(Super)는 처음에 레이어를 전환해야만 있어서 메인 배열 아래줄로 옮김(Hyprland 단축키가 전부 Super 기반).
  함정: wvkbd 의 `die()` 매크로는 중괄호 없는 두 문장이라 `if (...) die(...)` 로 쓰면 조건과 무관하게 종료한다(처음 패치에서 겪음; 중괄호로 감쌈).
  실제 화면에서 `한/영` 탭으로 hangul↔keyboard-us 전환, `⧉` 탭으로 도킹↔플로팅 전환을 확인(포인터 클릭). 다른 레이어(`special` 등)의 숫자 줄과 세로 배열은 확인하지 않음. wvkbd 버전이 바뀌면 패치가 안 맞을 수 있음(빌드가 실패하므로 알 수 있음).
- 시험: `python3 -I mods/_data/vkb/tests/test_vkb.py`(25, 맞춤/복원/크기 계획/mm→px 계산), `test_vkb_cli.py`(45, 가짜 hyprctl/systemctl 로 전체 흐름).
- **미확인**: 손가락 터치로 waybar 버튼이 눌리는지(포인터 클릭만 확인, GTK 가 터치를 클릭으로 바꾸는 것으로 알려져 있으나 직접 확인 못 함), waybar 높이 24px 의 터치 적합성, 사용 모드 연동의 실제 힌지 시험, 가상 키보드가 보이는 동안 잠금 화면/Hyprland reload 와의 상호작용.

### 알려진 한계: 터치스크린으로는 창 이동/크기 조절이 안 됨
Hyprland 의 제스처 클래스는 전부 터치패드용(`TrackpadGesture`)이고 터치스크린용은 워크스페이스 스와이프(`gestures:workspace_swipe_touch`)뿐이다. `Super`+드래그는 마우스 버튼 바인딩(`bindm`)이라 터치에는 적용되지 않고,
터치는 클라이언트에 터치 이벤트로 그대로 전달된다(그래서 클릭/우클릭이 섞여 들어가는 것처럼 보일 수 있음). 설정으로 고칠 수 없는 컴포지터의 한계다. 창 자동 최대화는 오히려 불편해서(사용자 판단, 2026-10-19) 하지 않기로 했고, 창 이동은 hyprgrass 의 길게 누르고 끌기로 해결한다(아래 "터치 제스처 실기 시험 결과").

### 화면 자동 회전 (2026-10-17)
tent/tablet 에서 기기를 돌리면 내장 화면과 터치가 같이 돈다. laptop 으로 돌아오면 항상 0(세로로 들어도 돌리지 않음).
- **방향 판정**(`posture_daemon.py`): 화면(뚜껑)의 가속도 센서(IIO `accel_3d`, sysfs 로 읽힘)를 tent/tablet 에서만 ~3Hz 로 읽음(laptop 에서는 읽지 않음). 발행: `orientation = {"rotation": 0|90|180|270, "flat": bool}`.
  rotation 은 **기기를 시계방향으로 돌린 각도**: `atan2(x, -y)`. 실측(태블릿 상태로 비스듬히 들고 잰 5자세): 정방향 가로 y=-8.4(0°), 윗변이 오른쪽 x=+8.8(90°), 거꾸로 y=+9.0(180°), 윗변이 왼쪽 x=-8.8(270°), 책상에 평평 z=-9.7.
  축 방향: +x=화면 왼쪽, +y=화면 아래, -z=화면 앞쪽(reading 이 위쪽을 가리킴).
  흔들림 방지: 현재 방향 중심에서 45+15=60° 넘게 벗어나야 바뀜, 새 방향이 0.8초 유지돼야 확정, 화면 평면 방향 중력 성분이 2.5m/s² 미만(≈15° 이내로 눕힘)이면 `flat` 으로 보고 마지막 방향 유지(3.5 이상이어야 해제).
- **화면 회전**(`displayctl rotate <0~3|auto>`, 사용 모드 허브 소비자): `ROTATION_TO_TRANSFORM = {0:0, 90:1, 180:2, 270:3}`. 모니터별 transform 을 상태 파일에 기록해 `restore`/레이아웃 변경에도 유지되고, 회전된 논리 크기로 확장 배치를 다시 계산. 이미 그 방향이면 아무것도 적용하지 않음. 꺼진/미러 화면은 회전하지 않음.
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
- **unstable(0.56.2)에서 빌드되는 fallback 찾기(2026-10-19)**: 실패 원인 하나는 nixpkgs 의 `wf-touch` 가 업스트림이 쓰는 것과 달라서였다. 업스트림이 자기 `nix/wf-touch.nix`(WayfireWM/wf-touch `8974eb0f` + 패치)를 쓰므로 그 커밋 자신의 `nix/wf-touch.nix` 를 `callPackage` 해서 `buildInputs` 의 wf-touch 를 바꾸면 된다.
  그렇게 해도 최신(`6adcebc2`, `LOG` 매크로 미선언)과 9/4 이후는 실패하고, **이분 탐색 결과 0.56.2 헤더로 빌드되는 가장 새 커밋은 `56473e9e`(2026-08-13)**, 처음 깨지는 커밋은 `a5e206bb`(8/19, "hacky hyprland 0.53 compat" — 업스트림이 Hyprland 개발판 리팩터링을 따라가기 시작).
  중첩 Hyprland 0.56.2 에서 `56473e9e` 는 크래시 없이 로드되고 Lua 설정(hl.config, hyprgrass.bind/gesture)이 오류 없이 받아들여졌다(`configerrors` 비어 있음). 실제 터치는 미확인. 26.11 로 올릴 때 Hyprland 가 0.56.x 이면 이 조합이 출발점이다(상위 버전이면 업스트림 `hyprpm.toml` 의 고정표를 다시 확인).
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
- 왜 dpms 가 안 켜지는지는 모름(i915 + `i915.enable_psr=1` + Hyprland 0.55.2. PSR 의심은 했으나 아래 "PSR 조사"에서 PSR 은 애초에 꺼져 있었음을 확인. 화면이 까만 동안 `grim` 으로 컴포지터가 그리는지 보는 시험은 하지 않았다).
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
- 아직 남은 것(위험 낮음, 필요할 때): `displayui` 의 시험(`test_ui.py`)은 자체 `check()` 형식(`PASS/FAIL` 한 줄씩)이라 공용 하네스로 옮기지 않음, `posture` CLI 는 호출마다 파이썬 시작(~50ms)이 들어서 소비자가 값을 한 번에 읽도록 `get <키> <키>` 를 추가했지만 시작 비용 자체는 그대로.

### 알려진 함정과 점검 방법 (2026-10-19)
- **깨어남 유실(고침)**: 경로 유닛(`posture-apply.path`)은 이미 실행 중인 `posture-apply.service` 를 다시 시작하지 못해(start 요청이 무시됨) 실행 도중에 온 상태 변경을 놓친다.
  실제로 덮개를 닫고 1초 안에 열면 닫힘 처리(`lid-policy`) 중에 온 열림이 유실돼 백라이트가 0 인 채 남았고(로그에 `lid=closed` 만 있고 `lid=open` 이 없음), 다음 이벤트가 와서야 복구됐다. 모드 변경 등 모든 소비자가 같은 위험이었다.
  → `posture-apply` 가 시작 때와 끝날 때의 `posture sig`(모드/덮개/회전/눕힘, 각도 제외)를 비교해 같아질 때까지 반복한다(최대 5회). 소비자가 멱등이라 다시 돌려도 안전하다. 가짜 소비자로 검증(도중에 바뀌면 2패스 8회, 안 바뀌면 1패스 4회).
- **중첩 Hyprland 시험이 사용자 서비스 환경을 오염시킨다**: 시험 뒤 `systemctl --user show-environment` 에서 `WAYLAND_DISPLAY` 가 죽은 `wayland-2` 로 바뀌고 `HYPRLAND_INSTANCE_SIGNATURE`/`HYPRLAND_CMD`/`DISPLAY` 가 사라져,
  서비스(`posture-apply` 등)에서 부르는 모든 `hyprctl` 이 실패했다(`jq: parse error` 가 소비자 실행마다 3번, 입력 정책/회전/가상 키보드가 아무것도 적용 못 함). 시험이 끝났을 때 아래로 확인하고 복구한다(재로그인해도 복구됨):
  ```sh
  systemctl --user show-environment | grep -E 'WAYLAND_DISPLAY|HYPRLAND_INSTANCE_SIGNATURE'
  systemctl --user set-environment WAYLAND_DISPLAY="$WAYLAND_DISPLAY" HYPRLAND_INSTANCE_SIGNATURE="$HYPRLAND_INSTANCE_SIGNATURE" HYPRLAND_CMD="$HYPRLAND_CMD" DISPLAY="$DISPLAY"
  dbus-update-activation-environment --systemd WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE HYPRLAND_CMD DISPLAY
  ```
- **저널 시각이 부팅 직후 약 30초간 9시간 앞선다**(RTC 가 로컬 시각 + 윈도우 듀얼부팅, "윈도우 시각 문제" 참고): `journalctl --since "-5min"` 같은 창에 부팅 초기의 옛 기록이 "미래 시각"으로 섞여 들어온다(실제로 옛 오류를 지금 오류로 오판할 뻔함). 시각이 아니라 PID/순서로 판단할 것.
- **`lid-policy` 의 추가 명령(`tlp bat`/`tlp start`)은 root 권한이 없어 `Error: missing root privilege.` 로 실패**한다(로그에 `추가 명령 실패`). 예전 구조(Hyprland 바인딩에서 사용자 권한으로 실행)도 같았을 가능성이 크지만 당시 오류 출력이 저널에 남지 않아 확인은 못 함.

## Hyprland 버전을 올릴 때 점검표 (예: nixpkgs 26.05 → 26.11)
Hyprland 는 변화가 빠르고 이 저장소의 여러 곳이 그 API 에 직접 붙어 있다. 올리면 **아래를 순서대로** 확인한다. (stable 26.05 는 0.55.2, 2026-10 의 unstable 은 0.56.2)
1. **플러그인(hyprgrass)**: 꺼 둔 상태(`core.touch.nix` 의 `enableHyprgrass`)에서 시작. 새 Hyprland 헤더로 빌드가 되는지부터 확인 — unstable 0.56.2 에서는 패키지/고정 커밋/최신 모두 컴파일 실패였다(API 변경, wf-touch 불일치, LOG 매크로). 업스트림 `hyprpm.toml` 의 "Hyprland 커밋 ↔ hyprgrass 커밋" 고정표에서 맞는 커밋을 찾되, 그 고정은 컴파일 호환일 뿐 Lua 런타임 호환은 아니다(3236fbb1 이 그 예).
   실제 세션에서 켜기 전에 반드시 중첩 Hyprland(`systemd-run --user`)로 로드해 본다. 정리는 유닛 이름/PID 로만, 끝나면 위의 환경 오염을 확인.
2. **우리가 쓰는 Lua API**(`hl.*`): `hl.on`, `hl.bind`, `hl.window_rule`, `hl.device`, `hl.monitor`, `hl.config`, `hl.exec_cmd`, `hl.dsp.{exec_cmd,window.move/resize/float/close/drag/alter_zorder,focus,workspace.*,exit}`, `hl.plugin.load`.
   `hyprctl eval '<lua>'` 로 쓰는 곳: `displayctl`(`hl.monitor`, `hl.device`), 입력 정책(`hl.device`), `vkb`(`hl.dsp.window.resize/move` 를 `hyprctl dispatch` 로). 올린 뒤 `hyprctl configerrors` 가 비어 있는지 본다.
3. **자동 시험**: `mods/_data/{posture,vkb,display}/tests` 전부(가짜 hyprctl 이라 실제 API 변화는 못 잡는다 — 4 로 보완).
4. **실기 확인**: `displayctl status`/`displayctl rotate 1` 후 `rotate 0`, `vkb show`/`vkb mode toggle`/`vkb hide`, 덮개 닫기/열기, 터치패드 토글, waybar 버튼.
5. **함께 움직이는 것들**: `wvkbd` 패치(`mods/_data/wvkbd/README.md` 의 재생성 방법 + `test_vkb.py` 가 적용 여부를 검사), hyprlock/hypridle 설정 옵션(0.9.5 에서 `grace` 등이 사라져 오류가 났던 전례), xdg-desktop-portal-hyprland.
6. 올리기 전 `nixup` 의 `unstable-fallback` 고정 장치(`nixup fix <패키지>`)로 되돌릴 수 있는 커밋을 확보해 둔다(`core/lib/host.nix`).

### 점검 도구와 시험 구성 (2026-10-19)
- **`posture-doctor`**(`mods/_data/posture/doctor.py`, 사용자 PATH 에 설치): 서비스 환경의 `WAYLAND_DISPLAY`/`HYPRLAND_INSTANCE_SIGNATURE` 가 살아 있는 인스턴스를 가리키는지, 허브 데몬/센서/`posture-apply.path`, 마지막 소비자 실행의 실패, 허브의 덮개와 ACPI 의 불일치, 덮개가 열렸는데 백라이트가 0인 화면을 점검해 OK/WARN/FAIL 과 해결 힌트를 낸다(문제가 있으면 종료 코드 1, `--json` 지원).
  이날 실제로 겪은 통합 단계 고장(환경 오염, 깨어남 유실로 꺼진 화면, 소비자 실패)을 잡으려는 것이라 시험(가짜 도구)이 못 잡는 영역을 맡는다. 문제가 의심되면 먼저 `posture-doctor`.
- **공용 시험 도구 상자 `mods/_data/_testkit/`**: `harness.py`(`checker()`: 시험마다 따로 있던 `check()`/카운터/종료 처리, `script()`), `fake_cmd.py` + `fakes.py`(`Sandbox`: 데이터 기반 가짜 `hyprctl`/`systemctl`/`pkill`/`posture`/`journalctl` — 응답과 상태를 `FAKE_DIR` 아래 파일로 정함, 동작 정의는 `fake_cmd.py` 머리말).
  vkb CLI 시험, posture 시험, doctor 시험이 이것을 쓴다(예전에는 도구마다 가짜 `hyprctl`/`systemctl` 을 따로 만들어 Hyprland 명령 형식이 바뀌면 여러 곳을 고쳐야 했음). displayctl 시험의 `fake_hyprctl.py` 는 모니터 배치를 시뮬레이션하는 도메인 전용이라 그대로 두고 `checker()` 만 공유한다.
- **전체 시험**: `mods/_data/run-tests.sh` (vkb 29 + vkb CLI 48 + posture 77 + doctor 11 + displayctl 코어 79 + TUI 53).
- **중첩 Hyprland 시험 도구 `mods/_data/hyprland-nested/hypr-nested`**: `hypr-nested <시험할 Hyprland store 경로> <시험 설정.lua> [--wait|초]`. 유닛 이름으로만 정리하고, 시작 전 서비스 환경을 기록했다가 끝나면 복구·확인한다(위의 "환경 오염" 함정을 막음). `--wait` 는 Enter 까지 유지해서 중첩 창을 손가락/마우스로 직접 시험할 때 쓴다.
- **displayctl 구조**: 1044줄 단일 파일을 패키지 `mods/_data/display/dispctl/`(`config`/`hypr`/`state`/`layout`/`apply`/`transaction`/`ops`/`cli`, 위에서 아래로만 import)로 나누고 `displayctl.py` 는 얇은 진입점으로 남겼다(`import displayctl as dc` 와 서브프로세스 호출이 그대로 동작).
  나누면서 시험이 실제 버그를 잡았다: 되돌리기 타이머가 `__file__` 로 진입 스크립트를 찾는데 분리 후 `dispctl/transaction.py` 를 가리켜 `revert-pending` 이 아무 일도 안 했다 → `ENTRY`(패키지 한 단계 위의 `displayctl.py`)로 고침. Nix 자리표시자는 `dispctl/config.py` 한 곳.
- **덮개 TLP 프로필**: `tlp bat`(배터리 프로필 + 수동 모드: 전원이 바뀌어도 다음 부팅/`tlp start` 까지 무시)/`tlp start`(실제 전원에 맞는 프로필 + 수동 모드 해제)는 root 가 필요해서 `hosts/msi-summit-me.nix` 에 root 유닛 `tlp-lid-closed`/`tlp-lid-open` + polkit 규칙(로컬 활성 사용자만, 해당 두 유닛만)을 두고 `lid-policy` 의 추가 명령이 `systemctl start --no-block` 으로 시작한다. 확인: 사용자 권한으로 시작해 `balanced/BAT (manual)` ↔ `performance/AC (auto)` 전환.
  **주의: 시험하다 `tlp ac`/`tlp bat` 를 직접 실행하면 수동 모드가 남아 전원이 바뀌어도 무시된다** — 2026-10-19 에 이 실수로 TLP 가 2시간 반 동안 `performance/AC (manual)` 에 머물렀다(`tlp start` 로 해제). 시험 뒤에는 `sudo tlp-stat -s` 로 `(manual)` 이 없는지 확인할 것.

### 터치 제스처 실기 시험 결과 (2026-10-19, hyprgrass d094a3e6 + Hyprland 0.55.2)
켜서 실제 터치로 시험했다(중첩 Hyprland 는 터치를 받지 못해 불가능). 최종 구성(`core.touch.nix`)과 결과:

| 제스처 | 방식 | 결과 |
|---|---|---|
| 2손가락 길게 누르고 끌기 → 창 이동 | `bind` longpress 2, `mouse = true` | **됨** (3손가락과 비슷) |
| 3손가락 길게 누르고 끌기 → 창 이동 | `bind` longpress 3 | 되지만 끌다가 인식이 풀림 |
| 창 테두리/틈새 길게 눌러 끌기 → 크기 조절 | `resize_on_border_long_press` | **됨** |
| 가장자리(끝에서 ~2cm 안쪽)에서 안쪽으로 쓸기 → 이전/다음 워크스페이스 | `bind` edge | **됨**(짧은 거리, 완료형) |
| 3손가락 좌우 스와이프 → 이전/다음 워크스페이스 | `bind` swipe 3 | 손가락이 안정적으로 잡힐 때만 |

원인을 원시 입력으로 찾았다(`mods/_data/touch-trace/touch_trace.py`, libinput debug-events 기록 분석; Hyprland 의 DEBUG 로그는 `debug:disable_logs=false` 로도 파일/저널에 안 남아 로그 진단은 불가):
- **3손가락을 대고 끌면 접촉이 자주 끊겼다 다시 잡혔다**: 3손가락 묶음 15개 중 14개에서 재접촉, 간격 중앙값 0.04초(최대 0.39초). 손가락 하나만 끊겨도 플러그인은 손가락 수가 바뀐 것으로 보고 제스처를 끝낸다. 손의 습기/힘 때문인지 패널이 가까운 손가락(12~20mm)을 못 따라가는지는 데이터만으로 구분 못 함. 이 패널은 동시 10점까지 지원.
- **3손가락 스와이프는 세 손가락이 함께 움직이지 않았다**: 크게 움직인 건 한 손가락이고 나머지는 이동 0이거나 아예 닿지 않은 경우가 많았다.
- **맨 가장자리에서 시작한 접촉은 ~0.1초 뒤 끝났다**(최대 41px 이동): 패널은 끝(0~2.7%, 98.7~99.97%)까지 닿지만 안쪽으로 미는 손가락을 계속 따라가지 못한다.
- **`gesture`(손가락을 따라 화면이 연속으로 움직이는 방식)는 이 패널에서 안 되고 `bind`(스와이프가 끝나면 한 번 실행)는 된다**: 가장자리 스와이프를 `gesture`+`workspace` 로 했을 때는 10cm 넘게 해도 반응이 없었고(`edge_margin` 을 10→40→160px 로 넓혀도), 같은 동작을 `bind`+`hl.dsp.focus({workspace="r+1"})` 로 바꾸자 짧은 거리로 바로 됐다. 연속 추적형은 긴 이동과 안정적인 접촉 추적이 필요한 것으로 보인다(왜 실패했는지 로그가 없어 확정은 못 함).
- 중첩 시험으로는 터치 시험이 불가능(aquamarine 의 Wayland 백엔드는 키보드/포인터만 구현). 터치가 꺼져 있으면(노트북 모드의 마지막 수동 상태) 제스처도 안 들어오므로 시험 때 `hypr-toggle-touchscreen` 으로 켰다 — 텐트/태블릿에서는 강제로 켜진다.
- 설정을 다시 읽어도(`hyprctl reload`) `hl.plugin.load` 는 이미 로드된 플러그인에서 오류 없이 지나가고 등록도 유지됨을 확인.

### 윈도우 시각 문제: 하드웨어 시계(RTC)를 UTC 로 통일하기 (할 일, 윈도우를 새로 설치할 때)
- **증상**: 부팅 후 약 30초(NTP 가 처음 맞추기 전)와 네트워크 없이 부팅한 동안 시스템 시각이 **9시간 앞선다**(로그 시각이 뒤섞이고 `journalctl --since` 에 옛 기록이 "미래 시각"으로 섞임). `timedatectl` 은 시간대를 `Asia/Seoul (Asia, +0000)` 로 잘못 표시하고 `RTC in local TZ: yes`.
- **원인**: 듀얼부팅 때문에 `hosts/msi-summit-me.nix` 에 `time.hardwareClockInLocalTime = true`(RTC 에 로컬 시각 기록)가 있는데, 커널이 부팅할 때 RTC 를 UTC 로 읽어 시스템 시각을 먼저 맞추므로(`rtc_cmos: setting system clock to 2026-10-19T10:34:04 UTC`) 9시간 앞서고, `timesyncd` 가 처음 동기화할 때 바로잡힌다. systemd 가 "RTC configured in localtime, applying delta of 540 minutes" 라고 로그를 남기는데도 실제로 보정되지 않는 이유는 모른다.
- **해결(윈도우를 지우고 새로 설치할 때 같이)**: 외장 USB 로 부팅해도 같은 하드웨어 시계를 쓰므로 **새 윈도우에도 필요**하다. 순서가 중요하다:
  1. 새 윈도우를 설치한 직후 관리자 명령 프롬프트에서  
     `reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f`  
     그리고 윈도우 시간 동기화(설정 → 시간 및 언어 → 지금 동기화).
  2. NixOS: `hosts/msi-summit-me.nix` 에서 `time.hardwareClockInLocalTime = true;` 줄(과 그 주석)을 지우고 `nixup` 으로 적용(기본값 false = RTC 는 UTC).
  3. 적용 직후 한 번: `sudo hwclock --systohc` (NTP 로 맞은 시스템 시각을 UTC 로 RTC 에 기록).
  4. 확인: 재부팅 후 `journalctl -b -o short-iso | head -3` 의 시각이 실제 시각과 같고 `timedatectl` 에서 `RTC in local TZ: no`.
- 윈도우를 먼저 바꾸지 않고 Linux 만 바꾸면 윈도우에서 시각이 9시간 어긋난다(윈도우가 NTP 로 다시 맞추면 Linux 쪽이 어긋난다). 윈도우를 지울 예정이 없어지면 현재 설정(로컬 RTC)을 유지해도 되고, 대가는 위의 "부팅 직후 30초".

### posture-doctor 를 언제 쓰나 (레포를 고치는 사람/Claude 용)
상시 백그라운드로 돌리지 않고, **"실행 중인 세션이 지금 제대로 이어져 있나"가 의심될 때 한 번 실행**하는 점검 도구다(`posture-doctor`, 문제가 있으면 종료 코드 1). 시험(`mods/_data/run-tests.sh`)이 *코드*가 맞는지 본다면, 이쪽은 *지금 떠 있는 시스템*이 맞는지 본다. `nixup check` 는 빌드 가능 여부만 보므로 둘 다 이 문제는 못 잡는다.

| 상황 | 이 도구가 잡는 것 |
|---|---|
| `nixup home/os` 직후, 허브·덮개·회전·가상 키보드 관련 모드를 고친 뒤 | 허브 데몬이 떠 있는지, `posture-apply.path` 가 상태 변경을 감시하는지, 소비자(lid-policy/vkb/displayctl/입력 정책) 중 마지막 실행에서 실패한 것이 있는지 |
| 중첩 Hyprland(`hypr-nested`)로 시험한 뒤 | user manager 환경(`HYPRLAND_INSTANCE_SIGNATURE`/`WAYLAND_DISPLAY`)이 죽은 인스턴스를 가리키는 오염 — 서비스의 `hyprctl` 이 조용히 실패하는 원인(`jq: parse error`) |
| 덮개 개폐/화면 문제를 건드렸거나 증상이 있을 때 | 허브와 ACPI 의 덮개 상태 불일치, 백라이트가 0 으로 남은 상태(까만 화면의 원인) |
| "뭔가 이상한데 어디서부터 볼지 모르겠다" | 위 항목을 한 번에 훑어 어느 단계에서 끊겼는지 + 힌트를 알려줌 |

**Claude 로 레포를 고칠 때 권장 순서**: (1) `mods/_data/run-tests.sh` (2) `nixup check` (3) `nixup home`/`os` 적용 (4) `posture-doctor`. 문제가 나오면 출력의 힌트대로 고치고, 시험으로 못 잡는 종류(환경 오염, 서비스 비활성화)는 이 도구에 점검 항목으로 추가한다(`mods/_data/posture/doctor.py`, 시험 `tests/test_doctor.py`). 로그인 때 자동 실행/알림은 일부러 넣지 않았다: 문제는 대부분 우리가 손댄 직후에 생기고, 그때는 직접 실행하는 편이 확실하다.

### PSR(패널 자체 갱신) 조사 (2026-10-19)
**결론: `i915.enable_psr=1` 은 6.18 에서 PSR 을 켜 주지 않고, 켜도 이 패널은 실제로 자체 갱신에 들어가지 않는다. 전력 이득을 기대할 수 없어 그대로 둔다.**
- 증상: 패널은 PSR 을 지원하는데(`Sink support: PSR = yes`) `i915_edp_psr_status` 가 `PSR mode: disabled`.
- 원인(커널 6.18.35 `intel_psr.c` 소스로 확인): `psr_global_enabled()` 가 eDP 에서는 **펌웨어 VBT 의 PSR 허용 비트**(`connector->panel.vbt.psr.enable`)만 본다. 예전 커널에서는 `enable_psr=1` 이 이를 덮어썼지만 지금은 `enable_psr` 이 PSR2 사용 여부(`==1` 이면 PSR2 금지)만 정한다. 이 노트북의 VBT 는 PSR 을 허용하지 않아 컴퓨트 단계에서 `PSR disabled by flag`(`drm.debug=0x4` 로 확인) 로 거부된다. `enable_psr=1` 은 부팅 때 "dangerous option - tainting kernel" 만 남긴다.
- 사용자 지정 48Hz 모드나 화면 주사율 문제가 아니다: 60Hz/165Hz 표준 모드에서도 같다.
- 강제 시험: `echo 2 | sudo tee /sys/kernel/debug/dri/1/i915_edp_psr_debug`(ENABLE, VBT 무시) 후 모드 변경 → `PSR1 enabled`. 하지만 정지 화면 12초 동안 소스 상태는 `IDLE`, 싱크는 `inactive` 로 **자체 갱신에 한 번도 들어가지 않았다**(Busy frontbuffer 0). 즉 강제해도 얻는 게 없다(VBT 가 끄는 데는 이유가 있을 수 있음). 시험 후 `0` 으로 되돌렸고 debugfs 값은 재부팅하면 초기화된다.
- 후속 선택지: `hosts/msi-summit-me.nix` 의 `"i915.enable_psr=1"` 은 효과 없이 커널 taint 만 만드니 지워도 된다(다음 `nixup os` + 재부팅 때). 지우기 전까지 해는 없음.

### 전력 측정: power-ab (2026-10-19)
`power-report` 가 Netdata 에 쌓인 과거 기록을 보여준다면, `power-ab` 는 **지금 이 순간** 설정별 소비 전력을 번갈아 재서 비교한다(`mods/_data/power-ab/power_ab.py`, 시험 12개).
- **어댑터를 뽑은 상태(방전 중)에서만** 동작한다: 소비 전력 = 배터리 전압 × 전류(sysfs)인데 어댑터가 꽂혀 있으면 전류가 0 이다. 방전 중이 아니면 안내하고 거부한다. 재는 도중 어댑터가 다시 꽂히면 중단한다.
- 기본: 165Hz → 60Hz → 48Hz(저장된 구성) 순으로 각 90초(+안정화 15초)를 2바퀴(약 11분). 번갈아 재는 이유는 배터리 온도/잔량에 따른 느린 변화가 한 설정에 몰리지 않게 하려는 것. 표에는 "바퀴 간 차이"를 같이 보여주며, 이 값이 설정 간 차이보다 크면 측정 잡음이다. 측정 중 CPU 평균 사용률이 10% 를 넘으면 표시한다.
- 끝나거나 중단되면 `displayctl restore` 로 저장된 화면 설정으로 되돌린다. 밝기는 건드리지 않으므로 비교할 때는 같은 밝기로 둔다.
- 예상 사용시간은 `charge_full` × 15.2V(설계 전압)를 그 전력으로 쓴다고 가정한 값. 이 노트북의 배터리는 만충 3615mAh/설계 5280mAh 로 설계 용량의 약 68%(2026-10-19 측정, `cycle_count` 는 0 으로 보고돼 쓸 수 없음).
- 충전 한도(예: 80%)는 쓸 수 없다: TLP 가 이 기종에서 "지원 기능 없음" 으로 보고하고 `charge_control_*_threshold` 파일도 없다.

#### power-ab 측정 결과 (2026-10-19, msi-summit-me, 배터리 방전 중, TLP `balanced/BAT`)
백그라운드에 낮은 우선순위의 컨테이너(node, cadvisor, mongod, dockerd)가 돌아 CPU 평균이 항상 약 15% 였다(모든 측정에 공통이라 비교에는 영향이 작지만 절대값은 그만큼 높음). 각 값은 중앙값 평균, 90초 × 2~3바퀴.

| 조건 | 165Hz | 60Hz | 48Hz(사용자 지정) |
|---|---|---|---|
| 밝기 100%, 정지 화면 | 15.13 W | 14.87 W | 14.83 W |
| 밝기 50%, 정지 화면 | 12.42 W | 12.34 W | 12.35 W |
| 밝기 50%, 60Hz, **포인터를 원 둘레로 계속 움직임**(`--mouse`) | — | 13.03 W | — |

- **밝기가 가장 큰 변수**: 100% → 50% 에서 약 2.5~2.7 W(약 18%) 감소, 예상 사용시간 약 3.7 → 4.4시간(배터리 만충 3615mAh = 설계의 68%, 54.9Wh 기준).
- **주사율은 거의 차이가 없다**: 165 → 60 → 48Hz 에서 0.06~0.3 W, 바퀴 간 흔들림(0.05~0.5 W)과 비슷한 크기. 그래서 저장된 화면 설정을 48Hz 에서 **60Hz 로 바꿨다**(`displayctl set eDP-1 --res 2560x1600 --hz 60`; 되돌리려면 `--hz 48`).
- **화면이 계속 바뀌면 약 0.7 W(5%) 더**: 정지 12.34 W → 포인터 이동 13.03 W. 이 중 일부는 CPU(평균 14.9% → 16.9%, 포인터를 움직이는 스크립트와 컴포지터) 때문이라 디스플레이만의 몫은 더 작다. 정지/이동 측정은 시각과 배터리 잔량이 달라(각각 약 84%, 79%) 엄밀한 A/B 는 아니다.
- 한 번 밝기가 40% 로 읽혀(사용자는 50% 로 설정했다고 생각) 측정을 중단하고 다시 했다 — 측정 전에 `/sys/class/backlight/intel_backlight` 의 brightness/max_brightness 로 실제 값을 확인할 것.
- PSR 이 꺼져 있어서 패널은 화면 내용과 상관없이 매 프레임 스캔아웃한다(위 "PSR 조사") — 정지 화면이어도 큰 이득이 없는 이유로 보인다(이 해석은 확인하지 못함).
- **밝기 5% 추가 측정** (같은 날 18:16~18:30, 60/48Hz 번갈아 2바퀴씩. 48Hz 는 `power-ab` 가 이때부터 `hl.monitor` 로 직접 지정):

| 밝기 5% | 60Hz | 48Hz | 48Hz − 60Hz | 바퀴 간 차이 |
|---|---|---|---|---|
| 정지 화면 | 10.01 W | 9.84 W | −0.18 W | 0.14 / 0.35 W |
| 포인터 이동 | 10.78 W | 10.68 W | −0.10 W | 0.15 / 0.02 W |

  - 밝기별 소비(60Hz, 정지): 100% 14.87 W → 50% 12.34 W → **5% 10.01 W**. 거의 직선이라 밝기 1% 당 약 0.05 W. 5% 에서도 약 10 W 가 남는데, 이는 밝기와 무관한 부분(CPU 평균 15% 의 컨테이너 부하 등, 추정)이 대부분이라는 뜻이다. 5% 정지 기준 예상 사용시간은 약 5.5시간(100% 밝기 3.7시간).
  - **48Hz 와 60Hz 의 차이(−0.1~−0.2 W)는 바퀴 간 흔들림(0.02~0.35 W) 안**이라 의미 있는 절전으로 볼 수 없다. 모든 밝기·화면 조건에서 같은 결론(주사율은 절전 수단이 아님)이어서 저장 설정을 60Hz 로 유지한다.
  - 포인터 이동은 5% 밝기에서도 +0.77 W(10.01 → 10.78 W, CPU +1.5%p) — 50% 밝기에서의 +0.7 W 와 일치한다.
- **컨테이너를 일시정지(`docker pause`)하고 측정** (밝기 5%, 60Hz, 방전 중, 2바퀴씩, `power-ab --containers`; 18:43~18:54). 이 노트북에는 약 30개의 컨테이너(`genple`, `genple-new-*` 등)가 항상 도는데, 그중 `genple` 하나가 순간 CPU 약 80% 를 쓴다.

| 상태 | 소비전력(배터리 전압×전류) | psys(플랫폼 전체, Netdata RAPL) | CPU 패키지(RAPL) | CPU 사용률 | 예상 사용시간 |
|---|---|---|---|---|---|
| 전부 실행 | 10.05 W | 10.16 W | 4.42 W | 15.0% | 5.5시간 |
| `genple` 만 정지 | 9.10 W (−0.95) | 9.25 W (−0.91) | 4.00 W (−0.42) | 8.2% | 6.0시간 |
| 전부 정지 | **7.61 W (−2.44)** | 7.83 W (−2.33) | 3.35 W (−1.07) | 1.3% | **7.2시간** |

  - **컨테이너가 소비의 약 24%(2.4 W)**: 밝기 5% 에서도 남던 약 10 W 의 큰 부분이 이 컨테이너들이었다. `genple` 하나가 그 약 40%(0.95 W).
  - **교차 확인**: 배터리 기반 변화(−0.95/−2.44 W)와 RAPL psys(플랫폼 전체)의 변화(−0.91/−2.33 W)가 0.1 W 안에서 일치하고 절대값(10.05 vs 10.16 W 등)도 비슷하다 → 측정을 믿을 수 있다. CPU 패키지는 줄어든 전력의 약 45%(−1.07 W)만 설명하고 나머지(약 1.2 W)는 메모리·전원부 손실 등 CPU 밖에서 줄었다(이 분해는 추정).
  - **이 값은 사후에 구했다**: 처음 도구가 `sudo -n` 으로 RAPL 을 읽으려 했으나, 이 시스템의 sudo 는 비밀번호가 필요해서(`sudo -n` 은 인증 캐시가 있을 때만 통함) 10분짜리 측정 중 캐시가 만료돼 RAPL 열이 비었다. 그래서 같은 구간의 Netdata 기록(`cpu.powercap_intel_rapl_zone_package-0`, `…_psys`)에서 구간별 평균을 다시 구했다(구간 경계는 시작 시각 + 시나리오당 약 107초로 추정, 평탄 구간의 안쪽만 사용). 이후 도구는 처음부터 Netdata 에서 구간 평균을 읽는다(`netdata_power`, sudo 불필요).
  - 일시정지가 끝나 `docker unpause` 한 뒤 `genple` 과 `genple-new-cadvisor` 가 잠시 `unhealthy` 로 보였다가 헬스체크 주기 뒤 회복됐다(unhealthy 0개 확인). 장시간 멈추면 컨테이너 안의 연결 시간 초과 같은 부작용이 있을 수 있다.
  - 정리: **효과 순서 — 밝기(100→5%: −4.9 W) ≈ 컨테이너 전체(−2.4 W) > 화면 갱신(+0.7 W) > 주사율(차이 없음)**.
- 아직 측정하지 못한 것: TLP 설정별 차이, `genple` 이 실제로 필요한지에 따라 배터리 때만 멈추는 방법(예: 배터리 전환 때 `docker pause`, 어댑터 연결 때 `unpause`)의 실효.

### 쉬는 상태 전력 조사: 패키지가 깊은 절전에 못 들어가는 이유 (2026-10-19)
> **⚠ 정정 (같은 날 늦게)**: 이 절과 "tty2 시험" 절의 **절대 수치(쉬는 바닥 약 6.4~7 W, 패키지가 C2 에만 머묾)는 재부팅 직후 14~30분 시점에서 잰 것이라 과대평가**였다. 부팅 후 시간이 지나 백그라운드 작업이 잦아들면 같은 조건(덮개 닫힘, 방전)에서 **약 4.3 W**(psys 약 3.9 W)까지 내려가고 패키지도 C8 에 30% 이상 머문다. 아래 "안정된 뒤의 ABAB 시험" 절이 올바른 값이고, 이 절의 **상대 비교**(Netdata −0.3 W, 그래픽 세션 영향 없음 등)는 같은 시간대의 번갈아 비교라 방향은 유효하다. 또 누적 이분 탐색(bisect)의 "단계별 효과"는 시간 흐름과 섞여 있어 쓰지 않는다.
컨테이너를 멈춘 뒤에도 남는 소비를 찾았다. 도구: `powertop`(일회성, `nix shell nixpkgs#powertop`), `/sys/kernel/debug/pmc_core/*`, `/sys/firmware/acpi/interrupts/*`, 커널 kprobe 추적.

**핵심 관찰**: 각 코어는 85~95% 를 깊은 절전(C6/C7)에 있는데 **패키지는 C2 에만 머물고 C3~C10 은 0%**(부팅 후 누적 카운터도 C6 약 1만 6천 번, C7 이상 0). 코어가 쉬는데 패키지가 못 자면 코어 밖의 무언가가 막고 있다는 뜻이다. **덮개를 닫아 화면이 꺼진 상태에서도 똑같았다(pc2 54~83%, pc3 이상 0%)** → 디스플레이(PSR)가 원인이 아니다. 시스템 전체 깨어남은 초당 약 1,770회(쉬는 노트북 기준 많음; 덮개 닫은 상태 약 450~740).

**원인 후보를 하나씩 확인한 결과**
| 후보 | 결과 |
|---|---|
| PCIe ASPM(`pcie_aspm=off`) | **아님.** `pcie_aspm=off` 여도 링크 ASPM L1 과 L1 하위 상태(L1.1/L1.2)가 펌웨어 설정으로 모든 장치에 켜져 있음(`lspci -vv`). 장치들의 LTR 합계도 약 1초로 느슨해서 막지 않음 |
| 외장 NVIDIA GA107M | **아님.** 드라이버 없이도 D3cold(꺼진 시간 약 8.5시간 대 켜진 시간 약 5초) |
| 오디오 코덱 | **아님.** `snd_hda_intel power_save=1`, `power_save_controller=Y`, SOF 컨트롤러 `suspended` |
| ACPI GPE 0x6E 초당 36~43회 | **EC(임베디드 컨트롤러)의 이벤트선**이다(`/sys/kernel/debug/ec/ec0/gpe` = 0x6e). EC 이벤트(쿼리)는 없고(SCI_EVT 0건) **EC 레지스터 읽기가 초당 약 10번**(주소 0x30 이 대부분) 일어나며 읽기마다 인터럽트 여러 개가 생긴다. kprobe 6초 추적: `systemd-logind` 44, waybar 15, Netdata 계열(LIBSENSORS, P[proc]) 약 30, `cat` 16 — 배터리 정보를 읽을 때마다 EC 접근이 15번쯤. **EC GPE 를 끄는 시험은 하지 않았다**(덮개/어댑터/배터리/단축키 이벤트 통로라 런타임에 끄면 덮개를 열어도 인식 못 하는 사고가 날 수 있음). Netdata 를 멈추면 GPE 가 41 → 25/s 로 줄지만 0 이 되지는 않음(logind/waybar 가 남음) |
| USB 호스트(xHCI) | **일부 맞음**(아래 시험). 전원 게이팅 안 된 블록은 XHCI, LPSS 등이었고, ELAN 터치스크린(USB 3-8)만 절전이 꺼져(`control=on`) 항상 활성이라 xHCI 도 활성 |
| LPSS(I2C) 항상 켬 | **터치패드 수정의 대가**: `RUNTIME_PM_DENYLIST="00:12.0 00:15.0"` 와 udev 룰이 LPSS I2C 컨트롤러(00:15.0, 8086:51e8)를 항상 켬. 끄면 터치패드가 안 잡혀서 건드리지 않음(시험하지 않음) |

**`irqpoll` 의 이력과 배경** (사용자가 "터치패드 먹통 + 껐을 때 심한 발열"로 넣었다고 기억)
- 2026-04-06 `c3af14e`(리팩터링 커밋)에 `irqpoll "(이유: 노트북 터치패드 인터럽트 충돌 방지 및 하드웨어 응답성 향상)"` 로 처음 등장.
- 2026-07-08 `ffac2d7` 에서 근본 원인 분석: **`idma64.0` 과 `i2c_designware.0` 이 IRQ 27 을 공유**한다. DMA 모드에서 spurious interrupt 가 생기면 `irqpoll` 이 없을 때는 발열/배터리 문제(인터럽트 폭주), 있을 때는 I2C 상태머신 타이밍이 어긋나 "controller timed out" storm. 그래서 udev 룰로 `idma64.0` 을 unbind 해 `i2c_designware` 를 PIO 모드로 강제하고 IRQ 27 을 단독 소유하게 해 **둘 다 해결**하려 했다(이때 irqpoll 은 일단 유지).
- **현재 상태: 그 해결이 실제로는 적용돼 있지 않다.** `/sys/bus/platform/drivers/idma64/` 에 `idma64.0` 이 그대로 붙어 있고 `/proc/interrupts` 의 IRQ 27 은 여전히 `idma64.0, i2c_designware.0` 둘이 공유한다(udev 룰의 `ACTION=="bind"` 가 platform 장치에 안 걸리거나 타이밍 문제로 보이지만 원인은 확인하지 못함). IRQ 27 의 spurious 통계는 `unhandled 0`(최근 구간 기준)이라 지금은 조용하다.
- 결론: `irqpoll` 을 지워도 되는지는 **판단할 수 없다**(unbind 가 안 되는 상태에서 지우면 원래의 발열 문제가 되살아날 수 있음). 비용(전력)도 측정하지 못했다 — 지우는 시험은 재부팅이 필요. 먼저 unbind 룰이 실제로 동작하게 만든 뒤 제거 시험을 해야 한다.

**배터리 방전 + 덮개 닫힘(화면 꺼짐) 에서의 A/B** — `mods/_data/power-ab/idle_ab.py`(root 로 `systemd-run`, 구간 90초 × 2바퀴 번갈아; 구간마다 배터리 전압×전류, RAPL, powertop 의 C-state/깨어남, GPE 비율). 일회성 실험용이라 시험은 없고, 저장된 스크립트는 실제로 돌린 두 스크립트를 합친 것이라 합친 뒤 다시 실행해 보지는 않았다.
| 비교 | 배터리 소비 | psys | CPU 패키지 | 깨어남/s | GPE/s | 패키지 pc2 |
|---|---|---|---|---|---|---|
| Netdata 실행 | 7.23 W | 7.57 W | 3.49 W | 705~740 | 41~43 | 66~68% |
| Netdata 정지 | 7.00 W (**−0.23 W, −3%**) | 7.36 W | 3.34 W | 459~547 | 24~27 | 79~83% |
| 터치스크린 USB 절전 꺼짐(`on`) | 7.39 W | 7.71 W | 3.55 W | 685~716 | 40 | 58~61% |
| 터치스크린 USB 절전 켬(`auto`; 터치스크린·xHCI `suspended`) | 6.86 W (**−0.53 W, −7%**) | 7.11 W | 3.17 W | 700~710 | 33~37 | 54~65% |
- 터치스크린 USB 절전의 효과는 두 바퀴 모두 같은 방향이었지만(−0.35, −0.71 W) 바퀴 간 흔들림(최대 0.32 W)이 있어 정확한 값은 대략 −0.4~−0.7 W 로 본다. **패키지는 여전히 pc2 에만 머물렀다**(xHCI 를 재워도 C3 이상 진입 없음 → xHCI 가 유일한 방해자는 아님).
- **터치스크린이 `auto` 에서 터치로 깨어나는지는 확인하지 못했다**(덮개가 닫혀 터치할 수 없었음). 그래서 **터치를 쓰지 않는 동안에만 재우도록 구현했다**(2026-10-19): `hypr-input-policy`(`core.bind.hwctl.nix`)가 호스트 옵션 `wayland.windowManager.hyprland.touchscreenUsbId`(msi-summit-me: `04f3:2ffa`)의 USB 장치에 대해 **터치스크린을 켜기 전에 `power/control=on`(깨움), 끈 뒤에 `auto`(절전)** 로 쓴다. **덮개를 닫았을 때도 `auto`**: 덮개를 닫으면 힌지가 0°/360° 경계라 **359° 로 읽히면 `tablet`(터치 강제 켜짐), 3° 로 읽히면 `laptop`** 으로 분류된다(2026-10-19 에 두 값을 모두 관측; 어느 쪽이든 화면이 꺼져 터치할 수 없다). 덮개 스위치는 360° 로 접어도 `open` 이라(위 첫 항목) 닫힘이면 실제로 닫은 것이다. 켜진 채로는 절대 재우지 않는다(`TLP USB_DENYLIST` 는 그대로).
  - 권한: `power/control` 은 root 소유라 호스트의 udev 규칙이 해당 장치(04f3:2ffa)의 파일을 `users` 그룹이 쓸 수 있게 한다(`chgrp users` + `chmod g+w`, `udevadm test` 로 매칭 확인). 이번 부팅에서는 규칙이 아직 안 돌아서 같은 명령을 직접 한 번 실행했다(다음 부팅부터는 규칙이 처리).
  - 시험(자세 CLI 를 가짜로 바꾼 복사본으로 정책을 실행, 실제 sysfs 확인): 노트북+터치 꺼짐 → `auto`/`suspended`; 노트북+터치 켬 → `on`/`active`; 접은 태블릿(덮개 open) → `on`; **덮개 닫힘(힌지 359°) → `auto`/`suspended`**; 덮개 다시 열면 `on`. 실제 사용 모드로 복원한 뒤 `auto`/`suspended` 확인(지금 덮개가 닫혀 있음). **터치로 깨어나는지 자체는 여전히 시험하지 못했지만, 터치를 켜기 전에 먼저 깨우므로 이 설계에서는 필요 없다.**

**프로세스 기준 소비**(powertop, 어댑터 연결 상태, 컨테이너 정지 후): `claude --resume`(이 세션) CPU 약 15%·깨어남 116/s(가장 큼; 스피너 애니메이션 때문일 가능성, 확인 못함), Netdata 합쳐서 CPU 약 4~5%·깨어남 약 250/s, kitty 3.5%·26/s, `irq/9-acpi` 1%·32/s, Hyprland 4%·15/s. 디스플레이 갱신 커밋(`intel_atomic_commit`)이 초당 약 12회(터미널 애니메이션).

#### idma64 unbind 규칙이 안 먹는 이유 조사 (2026-10-19)
- `/etc/udev/rules.d/99-local.rules` 에 규칙이 들어 있고 `udevadm test --action=bind /sys/bus/platform/devices/idma64.0` 시뮬레이션에서는 `RUN+=… echo idma64.0 > …/unbind` 가 실행되도록 **매칭된다**. 그런데 실제로는 `idma64.0` 의 드라이버 링크 시각이 부팅 시각과 같고(한 번도 unbind 되지 않음), `/proc/interrupts` 의 IRQ 27 은 `idma64.0, i2c_designware.0` 둘이 공유한다. 커널/저널에는 idma64 관련 기록이 없어서 **규칙이 안 돌았는지, 돌았는데 쓰기가 막혔는지 구분하지 못했다.**
- 런타임에 직접 `udevadm trigger --action=bind` 로 실행해 보면 안 되는 이유: 이미 DMA 모드로 쓰고 있는 I2C 컨트롤러 밑의 DMA 컨트롤러를 떼면 터치패드가 죽을 수 있다(원래 설계는 `i2c_designware` 가 probe 되기 **전** 에 떼는 것).
- 그래서 **진단 로그를 규칙에 추가**했다(`systemd-cat -t idma64-unbind`: `rule-ran` → `unbind-ok`/`unbind-failed`). **다음 부팅 뒤 `journalctl -b -t idma64-unbind`** 로 확인: `rule-ran` 이 없으면 bind 이벤트가 규칙에 안 걸린 것(이벤트가 안 오거나 다른 장치 이름), `unbind-failed` 면 쓰기가 막힌 것, `unbind-ok` 인데도 IRQ 27 이 공유 중이면 unbind 후 다시 붙은 것(예: `touchpad-reset`). 이 결과를 보기 전에는 `irqpoll` 제거 시험을 하지 말 것.

#### idma64 규칙이 부팅 때만 안 도는 이유: 실험으로 확인 (2026-10-19 20:08, 덮개 닫힘/원격 중이라 터치패드가 죽어도 되는 상태)
- 터치패드 폭주 감시 서비스(`touchpad-watchdog`)의 복구 절차와 같은 방식으로 **`intel-lpss` 드라이버를 내렸다 올려**(`echo 0000:00:15.0 > /sys/bus/pci/drivers/intel-lpss/{unbind,bind}`) `idma64.0`/`i2c_designware.0` 을 새로 만들어 보았다.
- 결과: **규칙이 돈다** — 저널에 `idma64-unbind: rule-ran` → `unbind-ok`(20:08:56). 이후 `idma64` 바인딩 0개, **IRQ 27 은 `i2c_designware.0` 단독**(PIO 모드), 터치패드(`ELAN0305:00 04F3:31FD Touchpad`)는 정상으로 다시 잡혔고 커널 로그에 오류 없음. 즉 규칙의 방식(bind 이벤트 때 idma64.0 unbind) 자체는 동작한다.
- **부팅 때만 안 되는 이유(추정)**: 호스트 설정이 `initrd.availableKernelModules` 에 `intel_lpss_pci` 를 넣어(부팅 초기에 LPSS 가 올라옴) `idma64.0` 이 **initrd 단계에서 이미 바인딩**된다. 그 단계의 udev 에는 `/etc/udev/rules.d/99-local.rules` 가 없고, 루트로 전환한 뒤의 udev coldplug 는 `add` 만 다시 보내고 `bind` 는 다시 보내지 않아서 규칙이 한 번도 걸리지 않는다. 런타임에 드라이버를 다시 올리는(= 감시 서비스가 복구할 때) 경우에만 규칙이 걸린다. 이 추정은 **다음 부팅 때 `journalctl -b -t idma64-unbind` 가 비어 있는지**로 확인할 수 있다(비어 있으면 맞음).
- 따라서 부팅 직후 상태는 "IRQ 27 공유(DMA 모드)"이고, 폭주(`controller timed out`)가 나서 감시 서비스가 복구하면 그때 비로소 "단독(PIO 모드)"이 된다. **감시 서비스가 지금까지 복구한 6번(2026-07-01, 07-03, 07-08, 08-21, 09-10, 09-22; 약 2~3주에 한 번)은 모두 `irqpoll` 이 켜진 상태에서 일어났다** — `irqpoll` 이 있어도 폭주가 막히지는 않았다.
- 해결 후보(아직 구현 안 함): (a) 부팅 후 한 번 `intel-lpss` 를 다시 올리는 oneshot 서비스(위에서 검증한 절차 그대로, 터치패드가 몇 초 안 잡힘), (b) `intel_lpss_pci` 를 initrd 에서 빼서 루트 udev 가 규칙을 가진 상태에서 올라오게 함(재부팅 시험 필요, 터치패드 초기화 순서가 바뀜). 그다음에야 `irqpoll` 제거 시험이 의미가 있고, 폭주가 2~3주에 한 번이라 효과 확인에는 몇 주가 걸린다.
- 지금(2026-10-19 20:08 이후)의 실행 중 상태는 이미 "단독(PIO)"이다 — 앞으로 폭주가 생기는지는 `ls /var/log/touchpad-watchdog/` 와 `journalctl -k | grep "controller timed out"` 로 볼 수 있다.


#### 재부팅 직후 확인 체크리스트와 tty2 시험 계획 (2026-10-19 작성, 다음 세션용)
**상황(수정됨)**: 처음에는 `boot.blacklistedKernelModules` 로 `idma64` 를 막았으나 **첫 재부팅에서 효과가 없었다**(아래 결과). 그래서 `boot.kernelParams` 의 `module_blacklist=idma64` 로 바꿨다(세대 449, `nixup os` 완료, 효과는 **다음** 재부팅부터). 사용자는 재부팅 → Hyprland 로그인 → tty2 로 옮겨 Claude 를 새로 켠다(그래픽 세션에 안 묶인 세션; tty2 에는 fcitx5 가 없어 영어로 입력할 수 있음).

**1) 재부팅 직후 확인할 것(idma64 차단 성공 여부)**
```
ls /sys/bus/platform/drivers/idma64/        # idma64.0 이 없어야 함(드라이버 자체가 없을 수 있음)
awk '$1=="27:"' /proc/interrupts             # 끝이 i2c_designware.0 단독이어야 함
journalctl -b -t idma64-unbind               # 비어 있어야 정상(idma64 가 안 붙으니 bind 이벤트가 없음; 비어 있으면 "initrd 에서 이미 바인딩" 추정과도 일치)
grep -c 'ELAN0305' /proc/bus/input/devices   # 터치패드 입력장치가 있어야 함(여러 개)
sudo dmesg | grep -iE "idma64|i2c_designware|controller timed out"   # 오류 없어야 함
lsmod | grep idma64                          # 비어 있어야 함
```
성공이면: `hosts/msi-summit-me.nix` 의 idma64 udev unbind 규칙(진단 로그 포함)을 지워도 된다. 실패(터치패드가 안 잡히거나 IRQ 27 이 여전히 공유)면 되돌리고(블랙리스트 항목 삭제) 후보 (a)(부팅 후 `intel-lpss` 재바인드 oneshot 서비스)로 간다. 이 결과는 **며칠 쓴 뒤 폭주(`ls /var/log/touchpad-watchdog/`)가 없는지**로 장기 확인하고, 그 다음에야 `irqpoll` 제거를 시험한다(재부팅 두 번째; 한 번에 같이 바꾸지 않는다).

**2) tty2 에서 할 쉬는 전력 시험(그래픽 세션을 끈 상태)** — 어댑터 분리 + 방전 중, 덮개는 닫아도/열어도 되지만 조건을 기록한다. 열린 작업은 사라지니 사용자가 저장한 뒤 시작.
- 목적: 패키지가 C2 에서 못 내려가는 원인이 그래픽 세션(컴포지터/waybar/kitty/Netdata 등)인지 가른다. 지금까지: 코어는 깊게 자는데 패키지는 pc2 뿐(덮개를 닫아 화면이 꺼져도 동일), 시스템 깨어남 약 450~740/s, EC GPE 초당 25~43회(EC 레지스터 읽기 초당 약 10번: `systemd-logind` 44/6s, waybar 15/6s, Netdata 계열 약 30/6s).
- 방법: `sudo -v` 를 사용자가 한 번 입력(이 시스템의 sudo 는 비밀번호 필요, 캐시 5분) → root 서비스로 한 번에 실행(`sudo systemd-run --unit=... --collect <python3> mods/_data/power-ab/idle_ab.py <powertop 경로> <모드>`; powertop 은 `nix shell nixpkgs#powertop` 로 받은 경로). 구간별(90초×2바퀴 번갈아) 배터리 전력/RAPL/powertop(pc 상태·깨어남)/GPE 비율을 기록하는 틀은 `idle_ab.py` 에 있고, 모드는 `netdata`, `usb-ts` 가 있으니 필요한 모드(예: 그래픽 세션 정지/시작, waybar 정지/시작)를 추가해 쓴다.
- 순서 제안: (i) 그래픽 세션이 떠 있는 기준 구간(아직 Hyprland 가 살아 있는 tty1) (ii) Hyprland 세션 종료(`loginctl terminate-session`) 후 구간 (iii) 가능하면 Netdata 도 정지한 구간. 각 구간에서 pc2/pc3+/깨어남/GPE/배터리 W 를 비교.
- **EC GPE 0x6E(`/sys/firmware/acpi/interrupts/gpe6E`)를 끄는 시험은 하지 않는다**(덮개/어댑터/배터리/단축키 이벤트의 통로; 하려면 자동 복구 타이머 필수). 폴러(waybar/logind/Netdata)를 멈춰 GPE 비율이 어떻게 바뀌는지만 본다.
- 끝나면 반드시 원복: Netdata `systemctl start netdata`, 사용자가 다시 Hyprland 로그인. 터치스크린 USB `power/control` 은 정책(`hypr-input-policy`)이 관리한다.

#### 첫 재부팅 결과: modprobe blacklist 는 효과가 없었다 (2026-10-19 20:27 부팅)
- 재부팅 직후: `lsmod` 에 **`idma64` 가 로드됨**, `idma64.0` 이 드라이버에 바인딩, **IRQ 27 은 `idma64.0, i2c_designware.0` 공유**, `journalctl -b -t idma64-unbind` 는 비어 있음(= udev 규칙은 부팅 때 안 걸림, "initrd 에서 이미 바인딩" 추정과 일치). 터치패드는 정상, 오류 로그 없음.
- 원인: 부팅 initrd(`/run/booted-system/initrd`)에 `idma64.ko.xz` 가 **들어 있고**(`intel_lpss` 의 `softdep pre: platform:idma64` 때문에 모듈 closure 에 포함), initrd 의 `etc/modprobe.d/nixos.conf` 에 `blacklist idma64` 가 **있는데도** 커널 로그상 부팅 2.0초(initrd 단계)에 `idma64 idma64.0: Found Intel integrated DMA 64-bit` 가 찍혔다. softdep 이 모듈 이름을 별칭(`platform:idma64`)으로 해석하는 경로라 modprobe 의 `blacklist` 가 걸러주지 못한 것으로 보인다(정확한 kmod 내부 동작은 확인하지 못함).
- 대책: **`boot.kernelParams = ["module_blacklist=idma64"]`** — 커널이 직접 그 이름의 모듈 로드를 거부(누가 요청하든, initrd 의 modprobe 포함). 부팅 항목(세대 449)의 `options` 에 들어간 것을 확인했고, `modprobe blacklist` 항목은 효과가 없어 제거했다. **다음 재부팅에서** 위 체크리스트(`lsmod | grep idma64` 가 비어야 함, IRQ 27 이 `i2c_designware.0` 단독)로 확인한다. 이번에도 안 되면 후보 (a)(부팅 후 `intel-lpss` 재바인드 oneshot).
- 부수 확인: 이 initrd 는 microcode cpio 뒤에 zstd 로 압축된 cpio 가 이어지는 구조(`zstd` 매직 오프셋부터 잘라 `zstd -dc | cpio -t` 로 목록을 볼 수 있다).

#### tty2(그래픽 세션에 안 묶인 Claude)에서 한 쉬는 전력 시험 결과 (2026-10-19 20:41~20:53)
이 Claude 는 `login ← kmscon`(VT2, 자체 `session-5.scope`) 아래에서 돌아 Hyprland 세션(VT1)을 종료해도 살아남는다. 덮개를 닫은 채(화면 꺼짐) 방전 중, `idle_ab.py ... session` 모드(구간 90초 × 2, 그래픽 켜짐 → `wayland-wm@hyprland\x2duwsm.desktop.service` 정지 → 그래픽 꺼짐 → Netdata 정지). 첫 시도는 root 서비스의 PATH 에 `pgrep` 이 없어서 첫 구간 뒤에 중단됐고(PATH 와 프로세스 이름 검사 `.Hyprland-wrapped` 를 고쳐 다시 실행), 아래는 두 번째 실행.
| 상태 | 배터리 소비 | psys | CPU 패키지 | GPE/s | pc2 | pc8 |
|---|---|---|---|---|---|---|
| 그래픽 세션 켜짐 | 6.79 W (6.93, 6.65) | 7.08 W | 3.21 W | 39.0 | 48.5% | 2.0% |
| **그래픽 세션 꺼짐** | **6.77 W** (6.79, 6.76) | 6.98 W | 3.13 W | 38.6 | 57.2% | 2.1% |
| 그래픽 꺼짐 + **Netdata 정지** | **6.44 W** (6.43, 6.45) | 6.64 W | 2.99 W | 22.8 | 61.9% | 4.7% |
- **그래픽 세션(Hyprland, waybar, kitty 등)은 덮개를 닫은 쉬는 상태에서 거의 영향이 없다**: 6.79 → 6.77 W(−0.02 W, 켜짐 두 구간의 차이 0.28 W 안). 패키지 C-state 도 달라지지 않았다. → 패키지가 깊이 못 자는 원인은 그래픽이 아니다(앞의 "덮개 닫아도 동일" 관찰을 확정).
- **Netdata 는 약 0.33 W(−4.9%)**: 배터리 −0.33 W, psys −0.34 W, 패키지 −0.14 W, GPE −16/s(−41%), pc8 2.1 → 4.7%. 앞선 A/B(−0.23 W)와 같은 방향.
- 그래픽도 Netdata 도 없는 쉬는 바닥은 약 **6.4 W** 이고 깨어남은 여전히 초당 약 650 회: `tick_nohz_handler` 332/s, sched softirq 47/s, `tailscaled` 32/s, `hrtimer_wakeup` 17/s, **`intel_ish_ipc` 인터럽트 17/s(+`ishtp_bus_event_work` 10/s)**, `claude`(이 세션, 그래픽 안의 kitty 에서보다 훨씬 작음), `irq/9-acpi` 8/s, `containerd`, `irq/211-AudioDS`, `irq/178-iwlwifi`. 패키지 pc3 이상은 여전히 pc8 5% 정도뿐이라 **남은 방해자는 아직 못 찾았다**(타이머 틱 331/s 가 큼 — 코어가 쉬는데도 틱이 도는 이유는 확인 못함).
- 한 구간의 `wakeups` 값이 6.0 으로 파싱된 것은 powertop 헤더 값이 이상하게 나온 것으로 보고 무시했다.

**ISH 인터럽트 단서 → 수정**: 위 목록의 `intel_ish_ipc`(Intel Sensor Hub: 힌지/가속도 센서가 붙어 있음)가 쉬는 상태에서도 초당 약 17 회였다. 원인으로 **posture 데몬이 덮개를 닫아도 가속도 센서를 0.33 초마다 읽고 있었다**(`mode != "laptop"` 이면 읽는데, 덮개를 닫아 힌지가 359° 로 읽히면 `tablet` 이라 계속 읽음). 덮개를 닫으면 화면이 꺼져 방향이 필요 없으므로 **덮개가 닫혀 있는 동안은 읽지 않고, 다시 열면 즉시 한 번 읽도록** 고쳤다(`posture_daemon.py`; 시험 2개 추가: 고치기 전 코드에서는 두 시험이 실패하고 고친 뒤 79개 모두 통과). **전력 효과는 측정하지 못했다**(기대되는 변화는 ISH 깨움 약 17/s 로 0.1 W 미만일 가능성이 커서 측정 잡음 0.3 W 아래; 힌지가 3° 로 읽히는 지금은 어차피 `laptop` 이라 폴링을 안 해 현장에서 전/후 비교도 못 함).

**잘못된 의심의 정정**: 재부팅 뒤 `always` 컨테이너 5개가 "Up Less than a second" 로 계속 보여 재시작 반복을 의심했으나 **재시작 횟수는 0** 이었다. 부팅 직후 약 30초 동안 시스템 시계가 9시간 앞서(RTC 문제) 컨테이너의 `StartedAt` 이 미래(20:26 UTC)로 기록돼 도커가 지금(약 12:12 UTC)과 비교해 "1초 미만" 으로 표시한 것이다. 부팅 때 `always` 컨테이너 5개(LibreChat, rag_api, vectordb, chat-mongodb, chat-meilisearch)만 되살아났고 CPU 는 각각 1% 미만이다(80% 를 쓰던 `genple` 은 `unless-stopped` 라 멈춘 채 유지됨). 따라서 오늘 밤 측정에는 그 큰 컨테이너 부하가 섞이지 않았다.

#### 두 번째 재부팅 결과: `module_blacklist=idma64` 성공 (2026-10-19 22:42 부팅)
- 부팅 명령줄에 `module_blacklist=idma64 irqpoll`. 커널 로그에 `Module idma64 is blacklisted`(2.05, 2.11, 5.17초 — initrd 단계 포함)가 찍혔고 **`lsmod` 에 idma64 없음**, `/sys/bus/platform/drivers/idma64/` 없음, `idma64.0` 장치는 있으나 드라이버 없음, **IRQ 27 은 `i2c_designware.0` 단독**, 터치패드 입력장치 6개(ELAN0305)로 정상, `controller timed out` 오류 없음. `posture-doctor` 7개 OK, 실패한 유닛 없음, 알림 센터/장치 감시/Netdata 정상. 터치스크린 USB 는 `auto`/`suspended`(노트북 모드, 터치 꺼짐).
- 이로써 첫 번째 재부팅의 "modprobe blacklist 는 initrd 의 softdep 앞에서 무효" 가설이 확인됐다(커널 인자 방식은 initrd 포함 모든 로드를 막음). **필요 없어진 `idma64` udev unbind 규칙(과 진단 로그)은 제거했다.**
- **남은 일(장기 확인)**: 이 상태(IRQ 27 단독, PIO)에서 폭주(`controller timed out`)가 사라졌는지는 몇 주 지켜봐야 한다(예전엔 2~3주에 한 번, `ls /var/log/touchpad-watchdog/` 에 쌓임). 폭주가 없다는 확신이 선 뒤에 **`irqpoll` 제거 시험**(재부팅 한 번, 따로)을 한다. `irqpoll` 이 없으면 과거엔 "발열/배터리 문제"(IRQ 폭주)가 있었다고 기록돼 있으므로, 제거 후 발열/`irq/…` CPU 사용·`/proc/irq/*/spurious` 를 같이 본다.

#### 안정된 뒤의 쉬는 전력: ABAB 시험으로 가린 결과 (2026-10-19 22:42 부팅, 23:08~23:40 측정)
덮개 닫힘, 어댑터 분리(독 없음), 방전 중, **`idle_ab.py` 의 `bisect`(누적) → `ab2`(ABAB) 모드**. 구간 45초(+안정화 15초), RAPL(psys/패키지)은 root 스크립트가 직접 `energy_uj` 로 읽음, 배터리 전력은 전압×전류.
- **누적(bisect) 시험의 함정**: 한 가지씩 계속 끄며 이어 재면 시간 흐름이 효과와 섞인다. 마지막에 전부 되돌린 기준이 처음 기준보다 약 2 W(psys) 낮게 나왔다(s0 7.19 → s9 5.21 W) — 같은 구성인데 시간이 지나며 저절로 내려간 것이다(부팅 직후 컨테이너/서비스 시작 작업이 잦아듦; `hypridle` 은 타이머 없이 잠금 명령만 있어서 화면 끄기 영향은 아님). 이 시험의 단계별 값은 **효과로 해석하지 않는다**.
- 그래서 후보마다 **기준(A)-변경(B)-기준(A)-변경(B)** 로 번갈아 쟀다(안정된 뒤):
| 후보 | 배터리 B−A | psys B−A | 그 외 | 판단 |
|---|---|---|---|---|
| **Wi-Fi 절전 켬**(`iw dev wlan0 set power_save on`) | 약 −0.6 W (4.37 → 3.74) | 약 −0.4 W (3.81 → 3.39) | **패키지가 pc10 에 들어감(약 21~22%, 꺼두면 0%)**, 두 번 다 재현 | **효과 있음** |
| **Netdata 정지** | −0.7 W (4.34 → 3.63) | −1.0 W (3.90 → 2.89) | 깨어남 1054 → 641/s(−414), GPE 36 → 20/s, pc8 +21%p, 두 번 다 재현 | **효과 큼**(쉬는 전력의 약 16%) |
| LPSS(00:15.0)/ISH(00:12.0) 런타임 PM `auto` | −0.2 W | −0.3 W | 같은 상태 A1→A2 변화(0.64 W)보다 작음 | 효과 없음(터치패드/힌지만 위험) |
| EDAC, Thunderbolt NHI, proc_thermal 드라이버 해제, tailscaled 정지, 컨테이너 pause | 변화 0.05~0.2 W | | 누적 시험의 한 단계였고 변화가 잡음 수준 | 효과 없음으로 봄 |
- **안정된 쉬는 상태의 기준값**(전부 기본, 덮개 닫힘, 방전): 배터리 약 **4.3~4.4 W**, psys 약 3.9 W, 패키지 약 2.0 W, 깨어남 약 1,050/s, 패키지 pc2 약 20%·pc8 약 33%·pc10 0%. 즉 앞의 "패키지가 C2 에만 머문다"는 **부팅 직후 한정**이었다(안정되면 C8 까지 간다). 부팅 후 약 40분 지나서 재야 한다.
- **Wi-Fi 절전이 꺼져 있는 이유**: TLP `laptopSettings`(`mods/sys/base/core.power.nix`, 모든 노트북 공통)에 `WIFI_PWR_ON_AC/BAT = "off"`("Wi-Fi 절전 시 주기적 연결 끊김 방지"), NetworkManager 도 `wifi.powersave = false`(TLP 값을 NM 이 덮어쓰지 못하게). 이 기종에서 연결 끊김이 실제로 있었다는 기록은 없다(일반 노트북 공통 안전 설정). 켜려면 TLP 는 `WIFI_PWR_ON_BAT = "on"`(배터리만), NM 쪽은 `wifi.powersave` 를 TLP 가 제어하게 비워야 하고, 대가는 지연(핑)이 늘 수 있음 — **아직 적용하지 않았다**(사용자 결정 대기).
- **Netdata 가 큰 이유는 아직 모른다**: 수집기 중 `idlejitter`(20 ms 마다 깨어나는 것으로 악명 높음)를 끄는 것을 시험했으나 **효과 없음**(ABAB: 4.42 W vs 기본 4.34 W, 깨어남 1113 vs 1054/s, 정지는 여전히 −0.66 W) → 설정을 되돌렸다. 남은 후보: `apps.plugin`(프로세스 스캔), `go.d`, `proc`(2,121개 차트 × 10초), `nfacct`, `timex`, `debugfs`. Netdata 는 `power-report`/이번 조사의 RAPL 기록원이라 통째로 끄는 대신 수집기를 하나씩 줄이는 방향이 낫다(배터리일 때만 끄는 방법도 있음).
- 시험 중 알게 된 것: `hypridle.conf` 는 `general { lock_cmd }` 뿐이라 유휴 타이머가 없다. `iw` 는 시스템에 없어서 일회성(`nix shell nixpkgs#iw`)으로 받아 `IDLE_AB_EXTRA_PATH` 로 넘겼다. 이 시험들의 틀은 `mods/_data/power-ab/idle_ab.py`(`bisect`, `ab2` 모드, 환경변수 `IDLE_AB_CANDS`/`IDLE_AB_SETTLE`).
- 아직 못 한 것: Wi-Fi 절전을 켠 채 실제 사용(지연/끊김) 확인, Netdata 수집기별 기여, 부팅 인자(`acpi_osi=Linux`, `pcie_aspm=off`, `irqpoll`) 제거 시험(재부팅 필요).

### 후속 조사 (2026-10-20 새벽): 안정화 가설 철회, Wi-Fi 절전 적용, 키보드 문제, 아침 자동 측정
**1. "부팅 후 40분이 지나야 안정화된다"는 틀렸다** — 재부팅 직후(4분)부터 1시간(`boot_settle.py`, 30초 간격, 프로세스별 CPU/깨어남과 RAPL) 기록: 쉬는 전력(덮개 닫힘, 방전)이 **10분 만에 약 6.7 W 로 안정되고 이후 60분간 변하지 않았다**(배터리 6.66~6.86 W, psys 6.73~6.78 W, 패키지 약 2.9 W). 줄지 않는 상시 소비자: `electron`(Bitwarden 데스크톱) CPU 9~10%·깨어남 약 257/s, `netdata` 깨어남 약 341/s. 부팅 직후 이 Claude 세션 자체가 60% CPU 까지 쓰지만(긴 세션 재개 + 명령 실행) 가만히 두면 2~4%.
- **Electron 을 SIGSTOP 으로 얼려 ABAB**: 배터리 −0.20 W, psys −0.25 W, 깨어남 −20/s — 깨어남 257/s 가 실제 전력으로는 크게 이어지지 않는다.
**2. 어제 저녁의 약 4.3 W 상태는 이 조작들의 지속 효과가 아니다**: (a) 조작을 **하나씩 적용했다 되돌린 뒤** 구간을 잰 `cycles` 시험(posture-daemon/tailscaled 재시작, 컨테이너 pause→unpause, Netdata 재시작, Wi-Fi 절전 켰다 끔, EDAC/proc_thermal/Thunderbolt 재바인드, LPSS/ISH auto→원래)에서 어느 단계도 전력이 내려가지 않았다(6.80~6.93 W). (b) 어제의 **누적(bisect) 시험을 그대로 재현**해도 되돌린 기준(s9 6.87 W)이 처음 기준(s0 6.89 W)과 같았다. 재현에서의 단계별 효과는 번갈아 재기 결과와 일치(Wi-Fi 절전 약 −0.5 W, Netdata 약 −0.6 W, LPSS/ISH·EDAC·열관리 등은 효과 없음).
- 사용자 가설 "Wayland 를 끄고 Claude 만 남아서"는 기록으로 반증됐다: 지난 부팅(22:42)의 로그인 기록에 Hyprland 세션(3번)이 만들어진 뒤 23:50 종료(재부팅)까지 로그아웃이 없다(Wayland 가 계속 떠 있었음).
- **남은 가설: 독(어댑터) 연결/분리 이력.** 장치 감시 알림 기록: 22:40:57 AC 연결(부팅 22:41 에 독이 붙어 있었음), 22:43:22 분리, 22:46:31 연결, 22:55:20 분리 — 그 뒤 약 4.3 W 상태가 나타났다. 오늘 부팅(독 없이 시작)은 6.8 W. 독의 붙고 떨어짐이 Thunderbolt/USB4·PCIe 컨트롤러의 절전 상태를 바꿀 수 있다는 가설이고 **아직 검증 전**. `pm_snapshot.py`(PCI/USB 런타임 절전 상태 저장/비교; 독 연결 전 저장본 `/tmp/pm-before-dock.json`, 활성 장치 15개)와 아침 자동 측정(아래)이 이를 확인한다.
**3. Wi-Fi 절전 — 적용(배터리 전용)과 지연 시험**: `hosts/msi-summit-me.nix` 에서 `services.tlp.settings.WIFI_PWR_ON_BAT = mkForce "on"`, `networking.networkmanager.wifi.powersave = mkForce null`(예전: false). TLP 는 AC=off, 배터리=on 이고 NM 이 덮어쓰지 않는다. `tlp-stat -c` 로 확인(`WIFI_PWR_ON_AC="off"`, `WIFI_PWR_ON_BAT="on"`), NM 설정에서 powersave 줄 제거 확인. 이 설정이 배터리 전환 때 실제로 `iw ... power_save on` 으로 적용되는지는 **아침 측정이 로그로 확인**한다.
- 지연/손실(`wifi_latency.py`, AC 연결 상태, 5GHz 신호 −34 dBm 160MHz HE, 절전 끔-켬-끔-켬 각 45초 핑, 손실 0%):
| 절전 | 게이트웨이 중앙 / 평균 / 95% | 1.1.1.1 중앙 / 평균 / 95% |
|---|---|---|
| 끔 | 1.1 / 1.2 / 1.7 ms (3구간: 평균 6.5, 95% 42.8, 최대 111 — 우연한 튐) | 3.3 / 3.3 / 4.1 ms |
| 켬 | 2.5 / 2.2 / 3.5 ms | 4.6 / 4.4 / 5.8 ms |
  절전을 켜면 **중앙값 약 +1.3 ms**, 손실 없음. Claude 원격 세션은 시험 내내 유지됐다(연결이 끊기는 것이 아니라 지연이 늘 뿐, 신호가 강하고 공유기가 절전을 잘 지원하는 환경). **핫스팟은 시험하지 못했다**(휴대폰 핫스팟이 절전 단말의 버퍼링을 잘못 처리하면 멈칫/끊김이 있을 수 있음 — 핫스팟에서 문제가 생기면 위 두 줄을 지우면 된다).
**4. 내장 키보드: Backspace 와 →(Right)가 신호를 안 보낸다** (사용자: 이 작업보다 훨씬 전부터 안 됐다고 함)
- `key_probe.py`(지정한 키의 눌림 횟수와 전체 키 이벤트 개수만 셈, 내용 비기록): 요청한 횟수만큼 눌렀을 때 **Backspace 0건, →  0건**, ←/↑/↓ 는 정상 건수(재연결 후), 글자 키 등 다른 이벤트는 정상. 커널 로그에는 부팅 약 100분 시점에 `atkbd serio0: Unknown key pressed (translated set 2, code 0xf0 ...)` 한 쌍만 있고 Backspace/→ 를 누를 때마다 새 오류가 쌓이지는 않았다 → 키보드 컨트롤러가 이 두 키의 신호를 **아예 안 올리는** 것(소프트웨어(입력기/터미널/Hyprland 설정)가 아님; 설정에 Backspace 리맵도 없음).
- `echo -n reconnect > /sys/bus/serio/devices/serio0/drvctl` 로 키보드를 재초기화해도 Backspace/→ 는 그대로(0건).
- 사용자 가설 "hyprlock/덮개 관련": hyprlock 은 커널 입력 이벤트보다 위 단계라서 커널 카운터 0 을 설명하지 못한다. 다만 **덮개 닫고 열기(EC 이벤트) 뒤에 키가 죽는 것**일 수는 있다 — 아침에 `key_probe` 를 켜 둔 채 덮개를 한 번 닫았다 열어 건수가 바뀌는지 보면 된다.
- 임시 우회: `hyprctl eval 'hl.config({ input = { kb_options = "korean:ralt_hangul,korean:rctrl_hanja,caps:backspace" } })'`(Caps Lock = Backspace, 런타임이라 설정을 다시 읽으면 원래대로). →는 Ctrl+F 등으로.
- 다음 시험(권장 순서): ① **EC 초기화**: 완전 종료 → 어댑터 분리 → 전원 버튼 30~40초 → 부팅 ② 그래도 안 되면 **`no-quirks` 임시 부팅 항목**(아래)으로 한 번 부팅해 `pcie_aspm=off`/`acpi_osi=Linux`/`irqpoll` 없이 키가 돌아오는지 ③ 그래도 안 되면 키보드 하드웨어 점검.
**5. 임시 부팅 항목 `no-quirks`**(세대 454): 기본 항목은 그대로 두고 `pcie_aspm=off`, `acpi_osi=Linux`, `irqpoll` 을 뺀 항목(`nowatchdog i915.enable_psr=1 module_blacklist=idma64 lsm=landlock,yama,bpf`)이 추가됐다. 선택: 부팅 메뉴에서 `…specialisation-no-quirks`, 또는 `sudo bootctl set-oneshot nixos-generation-454-specialisation-no-quirks.conf` 후 재부팅(**한 번만** 쓰고 다음 부팅은 자동으로 기본으로 돌아옴). 시험이 끝나면 `hosts/msi-summit-me.nix` 의 `specialisation.no-quirks` 블록을 지운다.
**6. 아침 자동 측정(예약됨)**: `idle-morning` 서비스(root, `idle_ab.py morning`)가 **어댑터(독)를 뽑고 덮개를 닫을 때까지 최대 12시간 기다렸다가** (150초 안정화 뒤) ① 장치 절전 스냅샷(`/tmp/pm-after-dock.json`; 비교: `pm_snapshot.py diff /tmp/pm-before-dock.json /tmp/pm-after-dock.json`) + Wi-Fi 절전을 끈 채 구간 2개(독을 뺀 뒤 전력이 낮아지는지: 기준 6.8 W 와 비교), ② Wi-Fi 절전 끔/켬 ABAB 4구간으로 실제 효율을 잰다. 결과 `/tmp/idle-ab-morning.json`, 로그 `/tmp/idle-ab-morning.log`. **재부팅하면 이 예약과 `/tmp` 의 저장본이 사라진다**(EC 초기화를 하려면 이 측정을 먼저 끝낼 것).

### 아침 자동 측정 결과 (2026-10-20 07:35~07:44, 덮개 닫힘, 독 분리 직후)
- **독을 뗀 뒤에도 전력은 낮아지지 않았다**: 독(어댑터)을 약 6시간 꽂아 두었다가 뽑은 직후 Wi-Fi 절전을 끈 채 잰 두 구간이 배터리 6.92 / 6.99 W, psys 7.20 / 7.24 W, 패키지 3.13 / 3.15 W, pc8 약 2%로 평소(약 6.8~7.0 W)와 같다. → **"독을 붙였다 뗀 한 번의 사이클이 컨트롤러 절전 상태를 바꿔 전력을 낮춘다"는 가설은 이 한 번의 사이클에서는 기각**됐다. (어제 낮은 상태는 독을 단 채 부팅 + 22:43, 22:46, 22:55 의 연결/분리를 거친 뒤였으므로 "독을 단 채 부팅"이나 "여러 번 반복"은 아직 못 가렸다.) **어제 약 4.3 W 상태의 원인은 아직 모른다**(재현 실패: 조작 하나씩 되돌리기, 누적 시험 재현, 독 사이클 모두 해당 없음). 장치 절전 스냅샷(`/tmp/pm-before-dock.json` ↔ `/tmp/pm-after-dock.json`)을 `pm_snapshot.py diff` 로 비교하면 독 사이클 전후로 바뀐 장치를 볼 수 있다.
- **Wi-Fi 절전 설정이 실제로 적용된다**: 독을 뽑자 TLP 가 Wi-Fi 절전을 **자동으로 켰다**(150초 뒤 확인 시 `Power save: on`, 측정 뒤에도 on 유지, AC 로 돌아가면 TLP 가 off). NM 이 덮어쓰지도 않았다.
- **Wi-Fi 절전 효과(ABAB, 덮개 닫힘 쉬는 상태)**: 절전 끔 7.01 / 6.97 W, **켬 6.39 / 6.34 W** → **배터리 −0.62 W(−8.9%)**, psys −0.62 W(7.25 → 6.60), 패키지 −0.20 W(3.16 → 2.94). 쉬는 상태에서 만충(54.9 Wh) 기준 이론상 약 7.8시간 → 8.6시간(+0.77시간, +10%). 어제 안정 상태에서 봤던 "패키지가 pc10 에 들어간다"는 이번에는 재현되지 않았다(pc10 0%, pc8 약 2%) — 전력 이득만 확인됨. 실제 사용 중에는 Wi-Fi 트래픽이 있어 이득이 이보다 작을 것이다.
- 키보드: 아침에 **Backspace 가 다시 눌린다**고 함 → 죽은 키가 아니라 **간헐적/상태 의존** 문제. 안 될 때 그 순간에 `key_probe.py` 를 켜서 신호가 안 오는 중인지 확인하고, 조건(덮개 닫았다 연 직후, 독 연결/분리 직후, 오래 켠 뒤 등)을 기록할 것.

### 활성 VT 비교 (2026-10-20 07:53~07:58, `idle_ab.py vt`)
사용자 가설: "어제 4.3 W 는 화면에 떠 있던 게 Wayland/Hyprland 가 아니라 pts/0(= kmscon, VT2)이어서일 것." 활성 VT 를 `chvt` 로 tty2(kmscon) ↔ tty1(Hyprland) 번갈아 ABAB(덮개 닫힘, **AC 연결**이라 배터리 전력은 못 재고 RAPL psys/패키지로 비교):
| 구간 | 활성 VT | psys | 패키지 | 깨어남/s | pc2 | pc8 |
|---|---|---|---|---|---|---|
| v1 | tty2 | 7.89 W | 3.30 W | 1173 | 37.3% | 1.6% |
| v2 | tty1 | 8.08 W | 3.35 W | 1241 | 36.3% | 1.1% |
| v3 | tty2 | 7.84 W | 3.29 W | 1166 | 38.3% | 1.6% |
| v4 | tty1 | 8.06 W | 3.34 W | 1105 | 37.4% | 1.2% |
- **tty2 가 활성일 때 psys 약 −0.2 W(−2.5%), 패키지 −0.05 W**로 일관되지만 작다. 어제 4.3 W ↔ 6.8 W 차이(약 2.5 W)를 설명하지 못한다 → **이 가설만으로는 기각**(작은 기여는 있음).
- 한계: 덮개를 닫아 패널이 꺼진 상태(백라이트 0)라서 "패널을 실제로 켠 채 어느 쪽이 그리느냐"는 못 쟀다. 어제 낮은 상태가 패널이 켜진 상태였는지는 기록이 없다(당시도 덮개 닫힘 시험이었음).
- 이 시험 후 활성 VT 는 tty2 로 복구됨.

### 용어 정리와 이전 서술 정정 (2026-10-20, 프로세스 트리로 확인)
이 문서와 대화에서 `tty2`, `kmscon`, `pts/N`, "콘솔", "Wayland 세션"을 섞어 썼다. 실제 구조:
```
tty1 (VT1) ── greetd ── 로그인 화면(greeter, logind 세션 6) / 로그인 뒤 Hyprland 세션(logind 세션 3→8, Type=wayland)
tty2 (VT2) ── kmsconvt@tty2.service ── kmscon ── login ── zsh ── claude   (logind 세션 5, Type=tty)
                 └ kmscon 이 만든 pty 의 slave = /dev/pts/N
```
| 이름 | 정체 | 비고 |
|---|---|---|
| `tty1`, `tty2` (VT) | 커널 가상 터미널 번호 = 화면 "채널". **한 번에 하나만 활성**이고 그 채널의 프로그램이 화면(DRM master)을 쓴다 | `cat /sys/class/tty/tty0/active` |
| `kmscon` | VT2 위에서 도는 **사용자 공간 터미널 에뮬레이터**(DRM/KMS 로 직접 그림) | `kmsconvt@tty2.service` |
| `pts/N` | kmscon 이 만든 **pty slave**(프로세스와 통신하는 통로, 화면 아님). 번호는 로그인마다 달라짐(예전 pts/0, 지금 pts/3) | |
| "Wayland 세션" | tty1 의 greetd 가 띄운 Hyprland. VT1 이 비활성이어도 **백그라운드에서 계속 실행**됨 | 활성 VT 가 tty2 여도 떠 있음 |
| greeter | 로그인 화면 = **`tuigreet`(텍스트 TUI, Wayland 아님)**. greetd 설정 `vt = 1`. **Hyprland 세션이 끝나면 greetd 가 tty1 에 띄우고 활성 VT 도 tty1 로 옮김** | 화면은 텍스트로 그려짐(커널 VT 콘솔) |
→ "tty2 = kmscon = pts/0"은 같은 것이 아니다. 화면에 보이는 것은 VT2 의 kmscon 이고 pts 는 그 안의 입출력 통로다.

**정정 1 — 이 Claude 의 위치**: 명령을 실행하는 셸은 kmscon 의 `pts/N` 아래가 아니라 **백그라운드 데몬**(`claude bg-pty-host`, 자체 pts, `user@1000` 소속) 아래다. kmscon 쪽 `claude` 는 화면 클라이언트다. 그래서 "이 Claude 는 `login ← kmscon`(session-5.scope) 아래에서 돈다"는 서술(tty2 시험 절)은 틀렸다. 어느 쪽이든 Hyprland 세션을 종료해도 살아남는다는 결론은 같다.
**정정 2 — "그래픽 끔" 시험들의 의미**: `idle_ab.py session` 의 "그래픽 세션 정지"는 Hyprland 를 끄지만, 그러면 **greeter(`tuigreet`, 텍스트 TUI — Wayland 아님)가 tty1 에서 시작되고 활성 VT 가 tty1 로 바뀐다**(시험 직후 `VT tty1`, logind 에 greeter 세션 6·7 확인). 즉 "그래픽 끔"은 "화면 출력 없음"이 아니라 **"tuigreet 텍스트 화면이 tty1 에서 커널 VT 콘솔로 그려지는 상태"**였다(사용자 지적으로 정정: greeter 는 Wayland 프로그램이 아니다). 2026-10-20 08:14~08:26 의 결과(켬 3.76~3.94 W ↔ 끔 5.9~6.1 W, 끔+Netdata 끔 5.5 W)는 이렇게 다시 읽어야 한다:
- "켬" 구간 = 활성 VT **tty2(kmscon)**, Hyprland 는 뒤에서 대기. "끔" 구간 = 활성 VT **tty1(greeter)**.
- 따라서 3.8 W ↔ 6.0 W 의 차이는 "Wayland 켬/끔"이 아니라 **"kmscon 이 화면을 쥔 상태 ↔ tty1 의 텍스트 콘솔(tuigreet)이 화면을 쥔 상태"**일 가능성이 크다(**미증명**). 10-19 20:41 의 같은 시험(켬 6.79 ↔ 끔 6.77 W)과 07:55 의 VT 비교(tty2 ↔ tty1 이 psys 0.2 W 차)는 이 가설로도 모순이 남아, 낮은 상태가 **시간/상태에 따라 켜지고 꺼지는 별도 요인**과 얽혀 있다. 번갈아 재지 않은 순서(켬, 켬, 끔, 끔…)도 한계다.
**앞으로의 시험 원칙**: (1) 시험마다 **활성 VT 와 화면을 쥔 프로세스**(`/sys/class/tty/tty0/active`, DRM master)를 같이 기록한다. (2) "Wayland 를 끈다" 대신 **VT 만 번갈아**(tty1 Hyprland ↔ tty2 kmscon) 바꾸고, 세션을 끄는 시험은 greeter 를 변수로 인정한다. (3) 번갈아(ABAB) 잰다. (4) 세션을 끄는 시험은 끝에서 반드시 복구(재로그인 필요 여부를 사용자에게 먼저 알림).

### 핫스팟에서 Wi-Fi 절전 지연 시험 (2026-10-20 08:44~08:50, 배터리, 출근길, `wifi_latency.py`)
핫스팟 `휴대폰 핫스팟`(2.4GHz, −42 dBm, 휴대폰 회선), 절전 끔-켬-끔-켬 각 구간 게이트웨이 45초 + 1.1.1.1 45초 핑:
| 구간 | 절전 | 게이트웨이 중앙 / 평균 / 95% / 손실 | 1.1.1.1 중앙 / 평균 / 95% / 손실 |
|---|---|---|---|
| 1 | 끔 | 25.8 / 67.0 / 313 ms / 3.1% | 55.0 / 137.5 / 627 ms / 15.6% |
| 2 | 켬 | 14.1 / 46.7 / 147 ms / 6.3% | 65.1 / 122.7 / 421 ms / 0% |
| 3 | 끔 | 10.7 / 33.3 / 125 ms / 0% | 64.7 / 108.4 / 309 ms / 0% |
| 4 | 켬 | 8.8 / 16.6 / 47 ms / 0.4% | 80.5 / 154.5 / 400 ms / 0% |
- **핫스팟 링크 자체가 매우 불안정**(끔 구간에서도 지연 수백 ms, 손실 최대 15%)해서 절전 켬/끔의 차이는 잡음에 묻혔다. 게이트웨이는 켬이 오히려 더 낮았고(14.1, 8.8 ms), 1.1.1.1 은 켬이 약간 높았으나(65, 80 ms vs 55, 65 ms) 구간마다 흔들림이 더 크다. **절전을 켜서 핫스팟이 멈추거나 끊긴다는 증거는 없었다**(손실은 끔 구간에도 있음). 정확한 지연 비용을 재려면 안정된 링크에서 더 길게 필요(집 Wi-Fi 에서는 중앙값 +1.3 ms).
- 시험 뒤 절전은 원래 값(on)으로 복구됨.

### 배터리·핫스팟에서 활성 VT 비교 (2026-10-20 08:51~08:56, 덮개 닫힘, Hyprland 는 끄지 않음)
`idle_ab.py vt`(활성 VT 만 tty2 kmscon ↔ tty1 Hyprland 로 번갈아, 구간 45초 + 안정화 20초):
| 구간 | 활성 VT | 배터리 | psys | 패키지 | 깨어남/s | pc8 |
|---|---|---|---|---|---|---|
| v1 | tty2 | 6.35 W | 5.84 W | 2.72 W | 1222 | 20.0% |
| v2 | tty1 | 6.48 W | 6.35 W | 2.93 W | 1272 | 17.5% |
| v3 | tty2 | 6.03 W | 5.51 W | 2.60 W | 1133 | 24.4% |
| v4 | tty1 | 6.09 W | 5.63 W | 2.61 W | 1193 | 22.1% |
- **활성 VT 의 효과는 약 0.1 W(0.06~0.13)로, 구간 사이 드리프트(6.35 → 6.03 W)보다 작다.** → VT 전환(kmscon ↔ Hyprland)은 전력 차의 원인이 아니다. 07:55 의 AC 시험(0.2 W)과 같은 결론.
- **08:16~08:18 의 3.8~3.9 W("Hyprland 켬, 활성 VT tty2", 집 Wi-Fi 5GHz) 는 이번에는 재현되지 않았다**(같은 배치에서 6.0~6.4 W, 핫스팟 2.4GHz). 08:20 이후의 "Hyprland 끔(tuigreet)" 5.9~6.1 W 와 이번 값이 사실상 같다. 즉 **이상치는 "끔 6.0 W"가 아니라 "켬 3.8 W" 쪽**이고, 이번 시험으로는 두 가지가 섞여 가려지지 않았다: (a) 연결된 네트워크 차이(집 Wi-Fi 5GHz ↔ 핫스팟 2.4GHz 휴대폰 회선), (b) 부팅/세션 이후 경과 시간·덮개를 열고 닫은 이력. 3.8 W 때 같은 조건(08:16)에서 `wifi_ps`, 네트워크, 덮개 이력을 같이 기록하지 않아 지금은 분리할 수 없다.
- **다음 시험**: 집 Wi-Fi 에서 같은 VT 시험을 다시 하고, 시험마다 SSID/주파수·덮개 이력·Hyprland 가동 시간을 함께 기록한다. 3.8 W 가 다시 나오면 그때 구간 시작 직전 상태를 비교한다.

### 낮은 전력(≈4.3 W) 상태 추적 (2026-10-20 09:00~09:50, 배터리·핫스팟·덮개 닫힘·Hyprland 가동)
**1. hyprlock 은 무관**: 잠금 ↔ 해제를 번갈아(`idle_ab.py lock`) 4.39 / 4.34 / 4.27 / 4.29 W — 낮은 상태에서 차이 없음. (`loginctl lock-session` 은 이 hypridle 설정(listener 없음, `lock_cmd` 만)에 반응하지 않아 hyprlock 을 사용자 권한으로 직접 띄워야 한다. 해제 SIGUSR1 은 잠금이 완전히 걸리기 전에 보내면 무시되어 재전송이 필요.)
**2. 낮은 상태는 09:09 에 저절로 나타났다**(09:05 7.09 W, 09:07 6.48 W 잠금, 09:09 이후 4.2~4.4 W, pc10 약 24%). 장치 런타임 PM 스냅샷 비교(`pm_snapshot.py diff`, 07:37 높은 상태 ↔ 낮은 상태): 34개 중 **오디오 컨트롤러 `00:1f.3`(sof-audio-pci-intel-tgl) 하나만** `active/D0` → `suspended/D3hot`.
**3. 그러나 오디오는 원인이 아니다**: `power/control` 을 on(D0 강제) ↔ auto 로 번갈아(`idle_ab.py audio`) 4.24 / 4.26 / 4.33 / 4.24 W — 전력 차이 없음(패키지만 +0.15 W). 낮은 상태의 **결과로 같이 바뀌는 지표**다. PSR 은 낮은 상태에서도 `disabled`(패널은 지원) → PSR 이 낮은 상태를 가르는 것도 아님.
**4. 되돌릴 수 있는 조작을 낮은 상태에서 차례로 가해 봄**(`perturb.py`, 각 90초 관찰; 전력은 `boot_settle.py` 30초 기록):
| 조작 | 직후 배터리 | 판정 |
|---|---|---|
| 기준 | 4.23 W | |
| CPU 4코어 20초 / Netdata 재시작 / Wi-Fi 절전 끔(→복구) | 4.55 / 4.10 / 4.45 W | 변화 없음 |
| **VT tty1 전환** | **6.45 W** | **올라감** |
| tty2 복귀 | 5.98 W | **내려오지 않음**(이후 hyprlock·오디오 조작과 무관하게 6.0~6.8 W 유지, 09:50 에도 6.0~6.4 W) |
→ **tty1 로 한 번 갔다 오면 낮은 상태가 높은 상태로 바뀌고 한동안 되돌아오지 않는다.** 높은 → 낮은 으로 내려오는 조건은 미확인: 두 번(07:58 복귀 → 08:14, 08:56 복귀 → 09:09)은 tty2 복귀 10~16분 뒤였지만 09:33:48 복귀 뒤에는 18분이 지나도 안 내려왔다. `consoleblank=0` 이라 커널 콘솔 블랭크도 아님(kmscon 자체 동작은 미확인). 09:09:19 에 핫스팟 Wi-Fi 채널이 2437 → 2412 MHz 로 바뀐 기록이 있지만 08:14 의 낮은 상태에는 같은 사건이 없어 공통 원인은 아님.
**5. 상시 기록 켜 둠**: `boot_settle.py` 가 30초마다 전력·프로세스별 CPU/깨어남·활성 VT·오디오 PCI 상태·Wi-Fi 채널·hyprlock 여부를 `/tmp/boot-settle.jsonl` 에 남긴다(`power-log.service`, 최대 6시간). 전환 시점이 오면 그 직전 기록을 비교한다.
**6. 현재 가설(미검증)**: 낮은 상태는 "kmscon 이 활성이고 Hyprland 로 한 번도 전환하지 않은(또는 전환 뒤 오래 지난) 디스플레이 구성", 높은 상태는 "VT 전환 이후의 구성"일 가능성. 덮개를 닫은 동안 Hyprland 는 백라이트만 0 으로 하고 패널 출력(DPMS)은 켜 둔 채(`dpmsStatus: 1`)이므로, 덮개 닫힘 시 `hyprctl dispatch dpms off` 를 시험해 볼 가치가 있다(아직 시험 안 함).

### 사무실 Wi-Fi(사무실 Wi-Fi) 배터리 시험과 낮은 상태 전환 포착 (2026-10-20 10:10~10:22, 덮개 닫힘, 2.4GHz 2427 MHz −43 dBm)
`idle_ab.py morning`(어댑터 분리 후 2.5분 안정화 → 절전 끔 2구간 → 끔/켬/끔/켬):
| 구간 | 절전 | 배터리 | psys | 패키지 |
|---|---|---|---|---|
| d1, d2 | 끔 | 6.16, 6.18 W | 6.55, 6.58 | 2.88, 2.91 |
| w1 | 끔 | 6.24 W | 6.31 | 2.85 |
| w2 | 켬 | **4.56 W** | 4.96 | 2.62 |
| w3 | 끔 | **4.69 W** | 4.97 | 2.58 |
| w4 | 켬 | 4.62 W | 5.12 | 2.72 |
- **w1 → w2 에서 −1.7 W 가 떨어졌지만 절전 때문이 아니다**: w3 에서 절전을 다시 꺼도 4.69 W 로 그대로(−0.07 W 차이는 잡음). 상시 기록(`boot_settle.py`)상 **전환은 10:16:46**(6.07 → 4.42 W, psys 6.32 → 5.52 → 4.85)이고 이 시각은 w2 시작(10:16:34) 직후지만, 되돌려도 안 돌아왔으므로 우연 또는 별개 사건. **이 시험으로는 사무실 Wi-Fi 에서의 절전 효과를 깨끗이 못 쟀다**(집 Wi-Fi 기준 −0.62 W 는 유효).
- **낮은 상태는 이번에도 저절로 나타났다**(세 번째 포착). 기록(방전·덮개 닫힘 217행) 중 낮은 상태(<5.2 W)는 23행(약 10%), 평균 4.51 W 대 높음 6.77 W.
- **프로세스와는 강한 상관이 없다**: 전력과의 상관 상위가 rcu_preempt 깨어남 +0.45, netdata CPU −0.36, kmscon CPU +0.35 등으로 모두 약하다(|r| < 0.5). 전환 전후 평균 차이도 containerd 깨어남 7.8 → 0, scripts.d 4.7 → 0, kmscon CPU 0.5 → 0 정도로 작다. → **특정 프로그램이 아니라 디스플레이/펌웨어(하드웨어) 쪽 상태**일 가능성이 높다.
- **DRM 커넥터 `dpms` 는 구분 기준이 아니다**: 높은 상태에서도 `Off`(10:21, 5.5~6.2 W)로 읽혔고 09:43(높은 상태)에는 `On`이었다. 또한 이 기기에서는 `dpms enable` 뒤 화면이 안 돌아오는 문제가 있어(`core.bind.hwctl.nix` 주석) dpms 로 패널을 끄는 방법은 쓰지 않는다. Hyprland 0.55(Lua)에서는 `hyprctl dispatch dpms off` 가 문법 오류이고 `hl.dsp.dpms({ action = ... })` 형식이다.
- **지금까지의 결론**: 낮은 상태(≈4.3 W)는 실재하며 약 10% 의 시간에 저절로 나타났다 사라진다. 알려진 원인(Wi-Fi 절전, Netdata, hyprlock, 오디오, PSR, 활성 VT, 네트워크, 프로세스)으로는 설명되지 않고, tty1 전환은 낮은 → 높은 방향으로만 작동한다. 이후 접근: ① 낮은 상태에서 장치/레지스터를 더 깊이 비교(`pm_snapshot` 외에 `pmc_core`/`slp_s0`, i915 `i915_display_info`, DMC 상태, `/sys/kernel/debug/pmc_core/substate_residencies`), ② 낮은 상태가 어떤 조건에서 유지되는지 장시간 기록 분석, ③ 필요하면 `no-quirks` 부팅으로 같은 기록 비교.

### 핫스팟 프록시 경로와 전력 — 전수조사와 가설 정리 (2026-10-20 10:30, 오후 시험 예정)
**1. 구조(코드 `hosts/msi-summit-me/hotspot-proxy-dispatcher.nix`로 확인; 주석이 낡았을 수 있어 실제 상태도 같이 확인)**
- Wi-Fi 연결(`up`) 때마다 NetworkManager dispatcher 가 **게이트웨이:1080 이 열려 있으면**(= 폰이 SOCKS5 를 연 핫스팟) `redsocks-hotspot` 을 띄우고, nft 로 **uid 1000 과 root(uid 0)의 모든 아웃바운드 TCP 를 REDIRECT**, **UDP 를 TPROXY(`redudp`, ip rule fwmark 1 → table 100 → lo)** 로 사용자 공간 릴레이에 태운다. 사설대역(10/8, 100.64/10, 172.16/12, 192.168/16 등)은 제외. `redsocks_conn_max=1024`. 연결이 끊기면(`down`) nft 테이블·ip rule·서비스·환경변수 모두 원복.
- **`sing-box` 는 이 저장소·이 노트북 어디에도 없다**(저장소 전체 검색 결과 없음, 바이너리/프로세스 없음). 게이트웨이:1080 의 SOCKS5 서버는 폰(또는 핫스팟 공급자) 쪽 프로그램이며 노트북은 클라이언트일 뿐이다. 따라서 "노트북 쪽 sing-box 비용"은 없고, 비용은 **redsocks 릴레이 + 막힌 UDP/직접 경로에 대한 재시도**에서 나온다.
- 확인한 상태: 사무실 Wi-Fi(`사무실 Wi-Fi`)로 옮기자 `redsocks-hotspot` inactive, `/tmp/current_hotspot_proxy`·`/run/redsocks-hotspot.conf` 없음, 프록시 환경변수(셸/사용자 systemd) 없음, `ip rule` 에 fwmark 1 규칙 없음, nft 테이블 `redsocks_hotspot*` 없음 → 정리는 깨끗하다. 프록시 없이 직접 https 정상(0.13 s).
**2. 기록(`boot_settle.py`, 방전·덮개 닫힘)으로 본 핫스팟 ↔ 사무실 차이**(핫스팟 n=88, 사무실 n=29 — 시간대·절전 설정이 다른 **비교 불완전** 자료)
| 프로세스 | 깨어남/s 핫스팟 → 사무실 | CPU% 핫스팟 → 사무실 |
|---|---|---|
| electron(Bitwarden) | 256.8 → 1.2 | 8.9 → 1.6 |
| tailscaled | 87.0 → 41.2 | 3.42 → 0.02 |
| netdata / claude / mongod / meilisearch | 거의 같음 | 거의 같음 |
- 높은 상태 평균 6.76 W(핫스팟) ↔ 6.30 W(사무실), **낮은 상태는 4.46 W 로 둘이 같다.** → 핫스팟 경로의 비용은 높은 상태에서 최대 약 0.45 W 로 보이나 확정은 아님(시간대, PS off/on 혼합, 표본 수 차이).
- **electron 의 257/s·9% CPU 는 핫스팟 전용이 아니다**: 어제 밤 집 Wi-Fi 에서도(재부팅 직후 기록) 같았고(257/s), **10:07 사무실로 옮기며 멈췄다.** 같은 무렵 AC 연결(≈10:05)과 분리(10:10)도 있었으므로 원인(네트워크 전환/AC 사건/재시도 루프 종료)은 미확정. 같은 시각 `tailscaled` 의 3.4% CPU·80~93/s 도 40/s·0% 로 내려왔다(핫스팟에서는 `netcheck: UDP is blocked, trying HTTPS/ICMP` 가 약 12초마다 반복되고 redsocks 로그에 `Socks5 server status: server failure` 가 섞임 — 핫스팟은 UDP 직접 경로가 막혀 tailscale 이 계속 재탐색).
- 반복 작업(전수조사): `touchpad-watchdog` 약 32초마다(시간당 112회), `notif-health` 약 60초마다(56회), 그 외 타이머는 하루 1회 이하 — 초당 1,000회가 넘는 깨어남(netdata 약 340/s, claude 150~200/s, electron 257/s, meilisearch 65/s, mongod 57/s, tailscaled 40~90/s, go.d.plugin 36/s, irq/9-acpi 20~30/s)에 비해 무시할 수준.
**3. 가설(핫스팟/프록시 경로가 전력에 미칠 수 있는 경로) — 모두 미검증**
- H1 electron(Bitwarden, `--autostart`) 재시도 루프: 막힌 UDP/프록시 경로 연결 실패 후 반복. 이전 SIGSTOP ABAB 효과는 −0.20 W(배터리), −0.25 W(psys).
- H2 tailscaled netcheck 루프(핫스팟에서 UDP 차단): CPU 3.4%·깨어남 +45/s.
- H3 redsocks 릴레이 자체의 CPU/깨어남(로그에는 top-N 에 안 잡혀 정량 없음), 유저·root 모든 TCP/UDP 가 사용자 공간 경유(Docker 컨테이너의 아웃바운드도 root 로 걸림).
- H4 링크 차이: 핫스팟은 2.4 GHz 20 MHz(−41~−42 dBm)·폰 AP 의 절전(DTIM/U-APSD) 지원 불확실 → 같은 트래픽에 에어타임·RF 전력이 더 듦. 사무실도 2.4 GHz 라서 이것만으로는 설명이 약함.
- H5 폰 쪽 SOCKS 서버가 UDP ASSOCIATE 를 구현하지 않아 UDP 가 그냥 나감(dispatcher 주석의 '한계') → 재시도.
**4. 오후 시험 계획**(핫스팟 가능해지면; 낮은/높은 상태 구분 위해 `boot_settle` 기록 유지, 시험마다 SSID·상태 기록)
- T1 재현: 사무실 → 핫스팟 전환 후 `thread_top.py electron`, `thread_top.py tailscaled` 를 0·5·10·20분에 찍어 257/s 가 다시 나타나는지, 어느 스레드(`Chrome_IOThread`, ThreadPool 등)인지 본다. 다시 사무실로 돌려 멈추는지 확인.
- T2 효과 크기(핫스팟, ABAB 구간 45초): electron SIGSTOP / Bitwarden 종료(PID) / `tailscale down` / redsocks 우회(서비스 중지 + nft 테이블 삭제; 핫스팟이 비프록시 트래픽을 막으면 연결 끊기므로 짧게, 안전장치 필수).
- T3 같은 시험을 사무실 Wi-Fi 에서 하고 핫스팟 결과와 비교, 낮은/높은 상태를 분리해 해석.
- 개선 후보(시험 후 판단): Bitwarden `--autostart` 제거 또는 필요 시에만 실행, tailscale 의 핫스팟 중 비활성/`--accept-routes` 점검, redsocks UDP 릴레이 조건 완화.
**5. 도구**: `thread_top.py <이름> [초] [상위]`(스레드별 CPU%·자발적 깨어남, 일반 권한). 사무실 조용한 기준값: electron 합계 약 16/s(CPU 2.6%), tailscaled 약 28/s(1.4%).

### 키보드 두 번째 사건: 덮개를 연 뒤 Backspace 와 밝기 조절이 안 먹음 (2026-10-20 10:28~10:32, 재부팅 뒤 정상)
**경과(이전 부팅 `journalctl -b -1` 로 복원)**: 10:28:30 덮개 열림 → 10:28:31 `lid-policy lid=open`(밝기 복원 정상 기록) → 10:28:32 `hypr-input-policy mode=laptop angle=121 lid=open keyboard=true touchpad=true` 적용 → 10:30:14 힌지로 `tent`(282°, 키보드 false) → 10:30:17 `laptop`(140°, 키보드 true) → 10:30:47 Hyprland 세션 종료(fcitx5 언로드)·재로그인(10:30:49~55) → 10:32 재부팅. 사용자 보고: 이 동안 Backspace 와 밝기 조절이 안 먹었고 **Hyprland 를 다시 로그인해도 안 풀렸다**(추정; 재부팅 뒤 모두 정상).
**알게 된 것**
- 이전 부팅 커널 로그에는 `atkbd`/`i8042`/ACPI EC 오류가 한 줄도 없었다(야간 사건 때의 `Unknown key pressed (0xf0)` 같은 흔적도 없음) → 커널이 오류로 인식하지 못하는 조용한 실패.
- 밝기 처리 코드(`lid-screen`/`brt-control`)는 정상 경로로 실행된 기록이 있고 덮개 열림 시 복원은 성공 → 밝기 문제는 **스크립트가 아니라 키 입력 자체가 안 오는 쪽**일 가능성이 크다. Backspace(`AT Translated Set 2 keyboard`, i8042)와 밝기 키(`MSI WMI hotkeys`/`Intel HID 5 button array`/`Video Bus` 중 하나; 어느 장치인지 미확인)는 **서로 다른 입력 장치 경로**인데 같이 죽었다 → Hyprland 아래의 공통 원인(EC/펌웨어 이벤트 경로, 또는 입력 장치가 Hyprland 에서 한꺼번에 비활성)을 의심.
- 지난 밤 사건(Backspace, → 가 커널 이벤트 0)과 합치면: 둘 다 **덮개 닫힘/열림 이력이 있는 긴 가동 뒤**에 나타났고 재부팅/EC 리셋으로 풀렸다. 야간 사건 때는 serio 재연결로 안 풀렸다.
**kmscon `cannot swap display [eDP] -22` 경고(별도 단서)**: 이전 부팅에서 13,662건(08:06 ~ 10:28, 덮개 닫힘·VT2 활성 중 화면을 다시 그릴 때마다). `-22`(EINVAL)는 eDP 에 갱신(page flip)이 안 먹는다는 뜻이다. 낮은 전력 상태(08:14~08:20, 09:09~09:33, 10:16:46~)와 분 단위로 정확히 맞지는 않아(경고는 화면이 갱신을 시도할 때만 나온다) **상관은 미확정**. 가설 H6: 낮은 상태 = VT2 가 DRM master 인데 eDP 파이프가 꺼진(scanout 없음) 상태, 높은 상태 = 파이프가 켜진 상태(10:21 에 DRM `dpms=Off` 를 읽었을 때도 높은 상태였으므로 `dpms` 속성만으로는 구분 안 됨). 검증: 두 상태에서 `/sys/kernel/debug/dri/0000:00:02.0/i915_display_info`(CRTC active/파이프/전원 우물)와 `i915_dmc_info`, `pmc_core` 의 `slp_s0`/substate 를 비교.
**다음에 같은 증상이 나오면(재부팅·재로그인 하기 전에) — 1분이면 된다**
1. `sudo python3 ~/nixos/mods/_data/input-debug/key_probe.py 15` 를 실행하고 15초 동안 **Backspace, →, 밝기 올림, 밝기 내림을 각각 3번씩** 누른다(눌린 글자 내용은 기록 안 함, 키 이름별 눌림 횟수만).
2. 결과 해석: `irq1_delta` = i8042 키보드 인터럽트(PS/2 신호가 하드웨어에서 커널까지 오는지), `gpe6e_delta` = EC 이벤트 인터럽트(밝기/Fn 계열).
   - 키를 눌렀는데 `irq1_delta`=0 → **키보드/EC 가 신호를 안 보냄**(하드웨어·펌웨어, EC 리셋 대상)
   - `irq1_delta` 는 늘었는데 키 이벤트 0 → **커널 입력층에서 버려짐**(atkbd/serio 쪽)
   - 이벤트는 있는데 화면에서 안 먹음 → **Hyprland/입력기 문제**(`hypr-input-policy` 의 키보드 enable 상태, fcitx5 점검)
   - 밝기 키가 어느 장치(`MSI WMI hotkeys`/`Intel HID`/`Video Bus`)에서 오는지도 같이 나온다.
3. 그 다음 순서: 덮개 한 번 더 닫았다 열기 → (소용없으면) 재부팅. 해결 수단이 아니라 **원인 구분이 목적**이므로 위 1~2 를 먼저 한다.
**도구 변경**: `key_probe.py` 가 4개 입력 장치를 동시에 읽고 `irq1_delta`·`gpe6e_delta`·덮개·VT 를 함께 낸다(시험 10개 통과). 기준(키 입력 없는 3초): 모든 키 0, `irq1_delta` 0, `gpe6e_delta` 196(약 65/s, 덮개 닫힘).
**참고(측정 도구의 부작용 가능성)**: `power-log`(30초마다 배터리 sysfs 와 `iw`)는 EC 를 읽는다. 다만 `systemd-logind` 가 이미 6초에 약 44회, waybar 가 15회 읽던 것에 비하면 30초에 한두 번은 무시할 수준이라 원인으로 보기 어렵고, 야간 사건은 도구가 켜져 있기 전부터 있었다고 사용자가 말했다. 그래도 완전히 배제된 것은 아니므로, 재발하면 그 시점에 도구가 돌고 있었는지 같이 기록한다.

### 낮은 상태의 정체 확인과 핫스팟 시험 (2026-10-20 11:08~11:40, 재부팅 뒤, 배터리·덮개 닫힘·kmscon 활성)
**1. 낮은 상태 = 패널 출력(파이프)이 꺼진 상태**(`display_snap.py save/diff`, 낮음 ↔ tty1 다녀온 뒤 높음)
| | 낮음(배터리 3.3 W, 패키지 1.4 W) | 높음(6.6~6.8 W, 패키지 2.6 W) |
|---|---|---|
| eDP 파이프 A | `active=no`(uapi·hw 모두) | `active=yes` |
| 디스플레이 전원 영역(DISPLAY_CORE, PIPE_A, TRANSCODER_A, DDI_LANES/IO_A, AUX_IO_A, PW_A, DDI_IO_A, AUX_A) | 모두 0 | 모두 1 |
| 평면(plane) | 숨김(visible=no) | 보임, 2560×1600 스캔아웃 중 |
| DMC `DC3→DC5` 카운트 | 17 | 26 (카운터라 참고만) |
| 오디오 DSP(`ADSP_D3_STS`), HDA 전원 게이팅 | D3 아님(0)·게이팅 On | D3(1)·Off — 낮은 상태 쪽에서 오디오가 *깨어 있다고* 읽힘(앞선 시험에서 오디오는 원인이 아님으로 확인되어 부수 지표로 해석) |
- 두 상태 모두 `slp_s0` 증가량 0(S0ix 미진입). 즉 낮은 상태의 절전은 S0ix 가 아니라 **디스플레이 파이프/전원 영역이 내려가는 것**(약 2~3 W)이다. 높은 상태에서는 덮개를 닫아 백라이트가 0 이어도 2560×1600 화면이 계속 스캔아웃된다. 앞선 가설 H6 확정.
- **DRM `dpms` 속성은 구분 기준이 아니다**(낮음에서는 Off 였지만 높음에서도 Off 로 읽힌 적이 있다). 구분은 `i915_display_info` 의 `active` 로.
- **관측이 상태를 바꾼다**: 낮은 상태에서 `i915_display_info` 등 debugfs 를 읽는 동안 전력이 3.3 → 7.1 W 로 올랐다(읽기가 디스플레이 파이프/전원 우물을 깨움). 이후 측정은 sysfs `dpms`, 전력 기록처럼 가벼운 값 위주로. 이 때문에 "낮음" 저장본도 읽는 도중 상태가 바뀌었을 수 있으나 첫 파일(display_info)은 읽는 순간 `active=no` 였다.
- 낮은 상태가 **켜지는 조건은 여전히 미확정**: 이번 부팅은 로그인 약 35분 뒤(약 11:08)에 낮은 상태가 나타났고(tty1 전환 없이), tty1 다녀오기(11:17)로 높은 상태로 돌아간 뒤에는 18분이 지나도(11:35) 파이프가 켜진 채였다. 이전 부팅의 "tty2 복귀 10~16분 뒤 낮음"과 맞지 않으므로 시간만의 문제가 아니다. 덮개를 닫을 때 Hyprland 의 `lid-screen`(백라이트 0)과, kmscon 이 DRM master 일 때의 스캔아웃 중단이 어떻게 맞물리는지 추가 조사 필요(kmscon 의 `cannot swap display [eDP] -22` 는 파이프가 꺼진 동안 다시 그릴 때 나는 경고로 보임).
**2. 핫스팟(`휴대폰 핫스팟`, 2462 MHz, −30 dBm, redsocks 자동 기동) — 높은 상태에서 번갈아(ABAB) 2회 반복**
| 후보 | A(그대로) → B(정지) 쌍별 배터리 | 평균 | psys 평균 |
|---|---|---|---|
| electron(Bitwarden) SIGSTOP | −0.16, −0.25 W | **−0.20 W** | −0.1~−0.2 |
| tailscaled SIGSTOP(2회, 4쌍) | −0.74, −0.09, +0.15, −0.11 W | **−0.20 W** (A 5.76 → B 5.56) | **−0.31 W**(4쌍 모두 음수: −0.61, −0.05, −0.41, −0.15), 패키지 4쌍 모두 음수 |
- 기준(두 쌍 모두 −0.3 W 이상)을 **어느 것도 통과하지 못했다**. 효과는 실재하지만 작다(각각 약 −0.2 W; 둘을 합쳐도 사무실 대비 핫스팟의 차이 약 0.45 W 의 절반~전부 수준이며 합산 효과는 직접 안 쟀다). → **코드 변경 안 함.**
- 핫스팟 연결 직후 `thread_top.py`: tailscaled CPU **9.3%**, 깨어남 **148/s**(사무실 1.4%, 28/s). redsocks 0.7/s(무시). electron 15/s(조용; 밤사이 257/s 는 재현 안 됨).
- `conn_log.py`(root, conntrack 직접 읽기; 내용은 안 보고 목적지·개수만): 노트북에서 나가는 새 연결 **초당 1.15개**(60초 69개: TCP 65, UDP 4). 프로세스는 대부분 `?`(너무 짧음), tailscaled 5. 목적지는 서로 다른 여러 IP:443 에 2개씩(tailscale DERP 탐색과 닮았으나 이름으로 확인하지 못함)과 Cloudflare DNS(1.1.1.1/1.0.0.1:53 TCP·UDP). 폰의 sing-box 가 TRACE/DEBUG 로 "connection … finished/closed" 를 많이 찍는다는 사용자 관찰과 일치(이 프록시는 통신사 테더링 한도 우회용이라 노트북 쪽 연결 로그가 곧 프록시 로그).
- 폰 로그 레벨을 `warn`/`error` 로 낮추면 폰 쪽 부하는 줄지만 노트북 전력과는 무관.
**3. 도구**: `display_snap.py save <디렉터리>` / `diff A B`(주의: save 가 디스플레이를 깨워 낮은 상태를 깨뜨릴 수 있음), `conn_log.py [초] [주기]`, `idle_ab.py ab2` 후보 `tailscaled-freeze` 추가, `thread_top.py`.
**4. 다음**: `no-quirks` 임시 부팅 한 번(키보드·전력 비교, 낮은 상태가 나타나는 시점 기록) → 결과에 따라 `pcie_aspm=off`/`acpi_osi=Linux`/`irqpoll` 정리 판단. 낮은 상태를 덮개 닫힘에서 항상 만들려면 "파이프 끄기"를 안전하게 하는 방법(Hyprland 쪽 `monitor` 비활성화 등)이 필요하며, 낮은 상태 진입 조건을 먼저 알아야 한다.

