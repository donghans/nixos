# 🛠️ Domain Mapping & Side Effects

### 1. `mods.sys` (System Infrastructure)
*   **`base`**: 
    *   **OS**: Btrfs 최적화, ZRAM, SSD trim, Locales, Nix 엔진 설정 (GC, Optimise).
    *   **Home**: Zsh (Theme, Keybinds), Atuin (History sync), Git (Global config), `gh` (GitHub CLI).
    *   **Root Parity**: `root` 계정에도 Zsh/Atuin 등 터미널 환경을 동일하게 적용하여 관리 일관성 유지.
*   **`utils`**:
    *   **`nfd`**: NFD (macOS) 한글 파일명 교정 유틸리티 (`nfd-fix`, `nfd-ls`).
*   **`vfs`**: 
    *   **OS**: GVFS, Udisks2 (스마트폰 및 외부 장치 마운트 기반).
    *   **Home**: `trash-cli` (CLI 휴지통) 및 관련 에일리어스.
*   **`fonts`**: CJK (나눔, Noto) 및 Nerd Fonts. (`kmscon`이나 `gui` 활성화 시 자동 트리거)
*   **`services`**:
    *   **`bluetooth`**: 블루투스 서비스 및 `bluetoothctl`. (`gui` 활성화 시 `blueman` 자동 포함)
    *   **`tailscale`**: 메시 VPN 서비스 (Tray 아이콘 포함).
    *   **`docker`**: 도커 데몬 및 사용자 그룹(`docker`) 자동 추가.

### 2. `mods.gui` (User Experience)
*   **`enable` (DE Bundle)**: 
    *   **Core**: Hyprland (UWSM 기반), Waybar, Fuzzel, Mako, Hyprlock, Hyprpaper.
    *   **Security/Session**: `greetd` (tuigreet), Polkit, Gnome Keyring.
    *   **Input**: Fcitx5-Hangul (환경 변수 및 자동 실행 세팅 포함).
    *   **Term/Utility**: Kitty, nm-applet, **Hardware Controls (hwctl)**, `cliphist`, `wl-clip-persist`.
    *   **Files**: Nemo + Udiskie (GUI 기반 마운트 도구).
    *   **Logic**: 활성화 시 자동으로 `mods.sys.fonts`와 `mods.sys.vfs`를 활성화합니다.
*   **`apps`**: `vivaldi`, `slack`, `bitwarden`.
*   **`utils`**:
    *   **`notifications.logger`**: 커스텀 알림 기록 서비스 (`custom-notify-logger`).

### 3. `mods.devel` (Developer Workshop)
*   **`enable` (Master Switch)**: 활성화 시 하위 개발 도구의 기본값을 `true`로 설정.
*   **Individual**: `node`, `python`, `fvm`, `devbox`, `llm-cli`, `zed`.
*   **`jetbrains`**: 
    *   **`enable`**: 마스터 스위치 (Custom UI scaling, Cursor fix 래퍼 등 공통 인프라).
    *   **`android-studio` 부수 효과**: ADB 활성화, **UDP 5353(mDNS)** 방화벽 오픈, SDK 커맨드라인 툴 설치, 사용자 그룹(**`adbusers`**) 자동 추가.
