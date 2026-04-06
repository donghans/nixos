# 🛠️ Domain Mapping & Side Effects

### 1. `mods.sys` (System Infrastructure)
*   **`base`**: Btrfs, ZRAM, SSD, Locales, Zsh + Atuin.
*   **`utils.nfd.enable`**: NFD (macOS) 한글 파일명 교정 유틸리티 (`nfd-fix`, `nfd-ls`).
*   **`vfs`**: GVFS, Udisks2 (OS) + Trash-cli, Aliases (Home).
*   **`services`**: `bluetooth` (triggers Blueman if GUI on), `tailscale`, `docker` (OS daemon + user group), `nfd` (Nix Filter Daemon).

### 2. `mods.gui` (User Experience)
*   **`enable` (DE Bundle)**: 
    *   **Core**: Hyprland + Waybar + Fuzzel + Mako + Hyprlock + Hyprpaper.
    *   **Utils**: nm-applet, **Hardware Controls (hwctl)**, Fcitx5-Hangul, Kitty.
    *   **Files**: Nemo + Udiskie.
    *   **Logic**: Automatically enables `mods.sys.fonts.enable` and `mods.sys.vfs.enable`.
*   **`apps`**: `vivaldi`, `slack`, `bitwarden`.
*   **`utils.notifications.logger.enable`**: 커스텀 알림 기록 서비스.

### 3. `mods.devel` (Developer Workshop)
*   **`enable` (Master Switch)**: Sets defaults for all devel sub-mods.
*   **Individual**: `node`, `python`, `fvm`, `devbox`, `llm-cli`.
*   **`_data`**: `devbox`나 `fvm`에서 사용하는 `json` 설정 파일 및 정적 스크립트를 격리.
*   **`jetbrains`**: Master switch + individual IDEs (idea, webstorm, datagrip, pycharm).
    *   `android-studio`: Automatically handles **ADB**, **UDP/Firewall**, and **SDK tools**.
