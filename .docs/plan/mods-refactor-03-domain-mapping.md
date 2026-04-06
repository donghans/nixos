# 🛠️ Domain Mapping & Side Effects

모든 설정은 아래의 `mods.*` 네임스페이스로 매핑되며, 각 모듈은 관련된 모든 부수 효과(Side Effects)를 책임지고 처리합니다.

### 1. `mods.sys` (System Infrastructure)
*   **`base`**: 
    *   **OS**: Btrfs 최적화, ZRAM, SSD trim, Locales, Nix 엔진 설정 (GC, Optimise).
    *   **Home**: Zsh (Theme, Keybinds), Atuin (History sync), Git (Global config), `gh` (GitHub CLI).
    *   **Consistency**: `mods.sys.base` 활성화 시, 시스템 관리의 일관성을 위해 `root` 계정에도 최소한의 사용자 환경(Zsh, Atuin)이 자동으로 적용됩니다.
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
    *   **`nfd`**: Nix Filter Daemon (선택사항).

### 2. `mods.gui` (User Experience)
*   **`enable` (DE Bundle)**: 
    *   **Core**: Hyprland (UWSM 기반), Waybar, Fuzzel, Mako, Hyprlock, Hyprpaper.
    *   **Security/Session**: `greetd` (tuigreet), Polkit (hyprpolkitagent), Gnome Keyring.
    *   **Input**: Fcitx5-Hangul (환경 변수 및 자동 실행 세팅 포함).
    *   **Term**: Kitty (기본 터미널 에뮬레이터).
    *   **Utility**: nm-applet, Hardware Controls (`hwctl`), `cliphist` (클립보드 매니저), `wl-clip-persist`, XDG Portal (Hyprland/GTK).
    *   **Logic**: 활성화 시 자동으로 `mods.sys.fonts`와 `mods.sys.vfs`를 활성화합니다.
*   **`apps`**:
    *   **`vivaldi`**: 브라우저 (코덱 및 한글 패치 포함).
    *   **`slack`**: 커뮤니케이션 툴.
    *   **`bitwarden`**: 패스워드 매니저.
*   **`utils`**:
    *   **`notifications.logger`**: 커스텀 알림 기록 서비스 (`custom-notify-logger`).

### 3. `mods.devel` (Developer Workshop)
*   **`enable` (Master Switch)**: 활성화 시 모든 하위 개발 도구의 기본값을 `true`로 설정합니다.
*   **Toolchains**:
    *   **`node`**: Node.js, pnpm, Prisma engine wrappers.
    *   **`python`**: Python 환경 및 관련 유틸리티.
    *   **`fvm`**: Flutter 버전 관리자 (전용 데이터 경로 포함).
    *   **`devbox`**: 글로벌 Devbox (전용 JSON 데이터 로드).
    *   **`llm-cli`**: 터미널 기반 AI 비서 (Gemini, Claude-code).
    *   **`zed`**: Zed 에디터.
*   **`jetbrains`**: 
    *   **`enable`**: 마스터 스위치 (Custom UI scaling, Cursor fix 래퍼 등 **공통 인프라** 활성화).
    *   **Individual**: `idea`, `webstorm`, `datagrip`, `pycharm`, `android-studio`.
    *   **`android-studio` 부수 효과**: ADB 활성화, 방화벽(UDP) 오픈, SDK 커맨드라인 툴 설치, 사용자 그룹(`adbusers`) 자동 추가.
