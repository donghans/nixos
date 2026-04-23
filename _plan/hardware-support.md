# MSI Summit Flip 16 Evo — 하드웨어 지원 현황 및 설정 계획

> 기준 날짜: 2026-04-20
> 기준 호스트: `hosts/msi-summit-me.nix`

---

## 1. 카메라 / 마이크 (Google Meet 등 화상회의)

### 현재 상태

| 항목 | 상태 | 비고 |
|------|------|------|
| `xdg-desktop-portal` | ✅ 활성화 | `mods/gui/base/xdg.nix` |
| `xdg-desktop-portal-hyprland` | ❌ 미설치 | 화면 공유 시 검은 화면 원인 |
| `xdg-desktop-portal-gtk` | ✅ 설치됨 | 폴백으로만 사용 |
| PipeWire | ❌ 미설정 | 오디오 기본값 의존 중 |
| `video` 그룹 | ❌ 미추가 | 카메라 접근 막힐 수 있음 |
| `audio` 그룹 | ❌ 미추가 | — |

### 필요한 변경사항

#### `mods/gui/base/xdg.nix` — portal-hyprland 추가

```nix
xdg.portal.extraPortals = with pkgs; [
  xdg-desktop-portal-hyprland   # ← 추가 (Wayland 화면 공유 필수)
  xdg-desktop-portal-gtk
];
xdg.portal.config.common.default = ["hyprland" "gtk"];  # 이미 설정됨
```

#### `mods/sys/base/core.nix` 또는 오디오 모듈 — PipeWire 설정

```nix
# os 설정에 추가
services.pipewire = {
  enable = true;
  alsa.enable = true;
  alsa.support32Bit = true;
  pulse.enable = true;   # PulseAudio 호환
};
hardware.pulseaudio.enable = false;   # PipeWire와 충돌 방지
security.rtkit.enable = true;
```

#### `mods/sys/base/core.nix` — video/audio 그룹 추가

```nix
users.users.${config.workspace.username} = {
  extraGroups = ["wheel" "video" "audio"];   # video, audio 추가
};
```

### 브라우저별 화면 공유 참고

- **Chrome**: `--enable-features=WebRTCPipeWireCapturer` 플래그 또는 최신 버전(자동 지원)
- **Firefox**: `media.webrtc.hw.h264.enabled` 설정 불필요, PipeWire + portal-hyprland 이면 자동

---

## 2. 지문 인식 (Goodix)

### 현재 상태

`hosts/msi-summit-me.nix:52` 에 이미 명시적으로 비활성화:

```nix
services.fprintd.enable = false; # (이유: 지문 인식 초기화 시 프리징 방지)
```

### Goodix Linux 지원 현황 (2025 기준)

**결론: 실사용 불가 수준, 현재 상태 유지 권장**

- 공식 드라이버 없음. libfprint에 일부 모델(27c6:633C, 27c6:6512)만 실험적 추가
- 커뮤니티 드라이버(`goodix-fp-linux-dev`) 존재하나 심각한 문제 있음:
  - 센서에 펌웨어를 직접 플래싱 해야 함
  - 과도한 플래싱 시 센서 **영구 손상** 가능
  - **보안 버그**: 매칭 알고리즘 오작동으로 엉뚱한 손가락도 인증될 수 있음
  - 듀얼부팅 환경에서 Windows가 펌웨어를 덮어쓸 수 있음

### 대응 방침

- `services.fprintd.enable = false` 유지
- libfprint 공식 지원 추가 여부를 주기적으로 확인
  - 참고: [goodix-fp-linux-dev](https://github.com/goodix-fp-linux-dev)
  - 참고: [fwupd Goodix 논의](https://github.com/fwupd/fwupd/discussions/3637)

---

## 3. 외부 모니터 확장 / 복제 키바인딩

### MSI Summit Flip 16 Evo 출력 포트

| 포트 | 규격 | 비고 |
|------|------|------|
| USB-C × 2 | Thunderbolt 4 (DisplayPort 1.2) | 4K 지원, 데이지체인 가능 |
| HDMI × 1 | HDMI | — |

### 현재 모니터 설정 (`hosts/msi-summit-me.nix`)

```nix
monitor = lib.mkForce [
  "eDP-1,2560x1600@60,auto,1"        # 노트북 내장
  "HDMI-A-1,preferred,auto-up,1"     # 외부 모니터 (HDMI) — Hexium 32UL3C
];
```

### 기존 스크립트 — `hypr-swap-monitors`

`mods/gui/base/core.bind.nix` 에 이미 구현됨.
두 모니터 간 워크스페이스를 서로 교환하는 기능.
키바인딩: `$mainMod + SHIFT + 마우스 휠 클릭(274)`

### 추가할 스크립트 — 확장 / 복제 / 노트북 단독 토글

아래 스크립트를 `core.bind.hwctl.nix` 또는 별도 모듈에 추가 가능:

```nix
# 확장 ↔ 복제 ↔ 노트북 단독 순환 토글
monitorToggle = pkgs.writeShellScriptBin "hypr-monitor-toggle" ''
  EXTERNAL="DP-2"
  INTERNAL="eDP-1"
  MIRROR_OF=$(hyprctl monitors -j | ${pkgs.jq}/bin/jq -r \
    --arg ext "$EXTERNAL" '.[] | select(.name==$ext) | .mirrorOf // ""')
  EXT_ACTIVE=$(hyprctl monitors -j | ${pkgs.jq}/bin/jq -r \
    --arg ext "$EXTERNAL" '[.[] | select(.name==$ext)] | length')

  if [ "$EXT_ACTIVE" = "0" ]; then
    # 외부 모니터 없음 → 아무것도 안 함
    notify-send "모니터" "외부 모니터가 연결되지 않았습니다"
  elif [ -n "$MIRROR_OF" ]; then
    # 현재 복제 모드 → 확장 모드로 전환
    hyprctl keyword monitor "$EXTERNAL,preferred,auto-up,1"
    notify-send "모니터" "확장 모드로 전환"
  else
    # 현재 확장 모드 → 복제 모드로 전환
    hyprctl keyword monitor "$EXTERNAL,preferred,auto,1,mirror,$INTERNAL"
    notify-send "모니터" "복제 모드로 전환"
  fi
'';

# 내장 화면만 사용 (프레젠테이션 후 복귀 등)
monitorLaptopOnly = pkgs.writeShellScriptBin "hypr-laptop-only" ''
  hyprctl keyword monitor "DP-2,disabled"
  notify-send "모니터" "노트북 화면만 사용"
'';

# 외부 모니터만 사용 (클램쉘 모드)
monitorExternalOnly = pkgs.writeShellScriptBin "hypr-external-only" ''
  hyprctl keyword monitor "eDP-1,disabled"
  notify-send "모니터" "외부 모니터만 사용"
'';
```

키바인딩 예시:

```nix
bind = [
  # 확장/복제 토글 — 랩탑 키보드의 Fn+F 계열 또는 Super+M 등으로 설정
  "$mainMod, M, exec, hypr-monitor-toggle"
];
```

> **참고**: `DP-2`는 USB-C 연결 시 이름이 `HDMI-A-1` 또는 `DP-3` 등으로 바뀔 수 있음.
> 실제 연결 후 `hyprctl monitors` 로 이름 확인 필요.

---

## 요약 — 우선순위 작업

| 우선순위 | 항목 | 예상 효과 |
|----------|------|-----------|
| 높음 | PipeWire 설정 | 마이크/스피커 안정화 |
| 높음 | `xdg-desktop-portal-hyprland` 추가 | 화면 공유 정상화 |
| 높음 | `video`, `audio` 그룹 추가 | 카메라 권한 해결 |
| 낮음 | 모니터 토글 스크립트 추가 | 편의성 향상 |
| 유지 | 지문 인식 비활성화 유지 | 프리징 방지 |
