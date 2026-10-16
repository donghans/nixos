# 화면 관리 (displayctl / displayui)

Hyprland 의 모니터 구성을 CLI(`displayctl`)와 TUI(`displayui`)로 관리한다. 본체는 `mods/_data/display/`, 패키징은 `mods/gui/base/display-manager.nix`.

## 사용

| 열기 | 동작 |
|---|---|
| `SUPER+P` / `Fn+F11`(XF86Display) | 화면 모드 목록에서 시작하는 TUI. 다시 누르면 닫힘. 모드를 고르면 적용하고 닫힘(`--quick`) |
| 앱 런처 "Display Settings" | 주사율에서 시작하는 TUI. 해상도·주사율·배율·상대 위치를 만지는 용도 |

TUI 안: `m` 모드, `s` 해상도, `r` 주사율, `c` 배율, `p` 위치, `a` 적용, `S` 프리셋 저장, `d` 프리셋 삭제, `F5` 새로고침, `q` 종료.
해상도/주사율/배율/위치를 적용하면 10초 안에 "유지"를 누르지 않으면 자동으로 되돌린다.

```
displayctl status                     # 모니터 현황
displayctl modes DP-4                 # 모니터가 지원하는 해상도/주사율 + 사용자 지정 후보
displayctl layout extend|mirror|internal|external
displayctl set DP-4 --res 1920x1080 --hz 60 --scale 1 --pos right:eDP-1:center [--confirm 10]
displayctl present 1920x1080          # 프리젠테이션(미러 + 외부 해상도 고정). present off / back 으로 복귀
displayctl preset list|load|save|delete <이름>
displayctl reset                      # 저장된 구성을 지우고 설정 파일의 기본 구성으로
```

## 동작 원리

- 변경은 `hyprctl eval 'hl.monitor({...})'`. **`hyprctl reload` 없이** 명시 규칙으로 전환한다.
  꺼졌던 모니터를 켜려면 `disabled = false`, 미러를 풀려면 `mirror = ""` 를 반드시 같이 줘야 한다(없으면 상태가 그대로 남음. 실측).
- 구성은 `~/.local/state/displayctl/state.json`, 사용자 프리셋은 `~/.config/displayctl/presets.json`.
  Hyprland 는 reload 때 런타임 모니터 설정을 지우므로 시작 / `config.reloaded` / `monitor.added` / `monitor.removed` 에서 `displayctl restore` 로 다시 적용한다.
- 안전장치: 연결된 모니터로 불가능한 레이아웃(외장이 없는데 "외부만")은 확장으로 바꿔 모든 화면이 꺼지지 않게 한다.

## 실측 (msi-summit-me, 내장 AU Optronics + 외장 MNT 2728UDP4K)

- 내장 패널: EDID 모드는 2560x1600 @165/@60 뿐. 목록 밖의 해상도(1920x1200, 1920x1080, 1600x900)와 **48Hz 는 됨**, **45/30Hz 는 거부**되고 60Hz 로 돌아감.
- 외장: 목록 밖의 값(1920x1200, 3840x2560 @48/@45/@30 등)도 Hyprland 가 모두 받아들임. 실제로 화면이 나오는지는 모니터에 달림.
- 적용 뒤 실제 모드를 읽어 요청과 다르면 경고한다.

## 알려진 문제 / 미확인

- **kitty 크래시(대응 확인됨)**: `displayctl layout external` 로 노트북 화면을 끄는 순간, 그 화면에 있던 kitty(0.47.0)가 `libwayland-client` 에서
  SIGSEGV 로 죽었다(코어 덤프 `coredumpctl`, 2026-10-16 22:02). 대응으로 모니터를 끄거나 미러로 만들기 전에 그 화면의 창을
  남는 화면으로 먼저 옮긴다. **시험(2026-10-16)**: 노트북 화면에 시험용 kitty 를 두고 `external` → `extend` 를 하자 창이 외장으로
  옮겨진 뒤 화면이 꺼졌고 크래시가 없었으며, 복귀 뒤 `wl_output` 에 두 모니터가 모두 있고 `grim`/waybar 도 정상이었다.
  다만 **창 이동 없이 끄면 실제로 크래시가 재현되는지(대조 실험)는 하지 않았다** — 재현되면 노트북 화면의 `wl_output` 이 사라져
  재로그인이 필요할 수 있어서.
- **노트북 화면이 `wl_output` 에서 사라지는 현상**: 위 상황 뒤 `hyprctl`/`wlr-randr` 는 노트북 화면(eDP-1)을 켜짐으로 보이는데
  `wayland-info` 에는 외장(DP-4) 하나뿐이고 `grim` 이 노트북 화면 영역을 못 찾았다. 화면 자체는 정상으로 보였다.
  waybar 에 문제가 있었음. **로그아웃 후 다시 로그인하면 정상으로 돌아왔다**(wl_output 에 두 모니터 모두 나타나고 waybar 도 양쪽에 뜸).
  원인(껐다 켠 노트북 화면의 wl_output 이 다시 만들어지지 않음)은 모른다.
- 터치스크린/펜 매핑(`hosts/msi-summit-me.nix` 의 `hl.device`)은 모니터가 꺼졌다 켜질 때 유지되는지 확인하지 못했다.
- 시험: 실제 Hyprland 를 건드리지 않도록 가짜 `hyprctl` 로 코어와 TUI(Textual Pilot)를 시험한다. 실제 환경의 관찰된 동작(미러/disabled 지속,
  내장 패널의 48Hz 미만 거부)을 흉내 내고, 창 이동과 모니터 끄기의 순서도 검증한다.
  `PYTHON=<textual 이 있는 python> mods/_data/display/tests/run.sh`
