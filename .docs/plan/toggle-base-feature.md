# Mods Framework Specification: The Grand Refactoring

## 🎯 Vision & Purpose (의도와 방향성)
본 리팩터링은 "내가 무엇을 사용하고 있는지 100% 장악한다"는 철학 아래, 무질서한 설정을 **논리적 도메인(Mods)**으로 격리하고 **명시적 선언(Explicit Opt-in)** 체계를 구축하는 것을 목적으로 합니다. 

1.  **Dual-Context Agility**: `nhw home switch`를 통한 가벼운 사용자 환경 갱신과 `nhw os switch`를 통한 견고한 시스템 기반 갱신을 완벽히 분리하고 공존시킵니다.
2.  **Absolute SSOT**: `_info.json`의 데이터를 `config.workspace` 전역 옵션으로 승격시켜 시스템 전반의 투명성을 확보합니다.
3.  **Strict Governance**: 프리셋에 정의되지 않은 기능은 스스로 판단하지 않으며, 사용자의 명시적 결정을 강제합니다.
4.  **Zero-Leak Security**: 어떤 형태의 비밀값(Secrets)도 레포지토리에 포함하지 않으며, 철저히 외부 관리자에게 위임합니다.

---

## 🏛️ Directory Structure (Final Target)
```text
/home/donghans/nixos/
├── core/           # Engine: Flake, Builders, Scripts (nhw), Libs (mkWrapper)
├── mods/           # Parts: The Mods (sys, gui, devel)
│   └── _preset/    # Recipes: Pre-assembled sets (workstation, server, etc.)
└── hosts/          # Specs: _info.json, Host-specific configs (_hardware.nix)
```

---

## 🏗️ Core Architecture & Implementation

### 1. The `mods.*` Namespace (Shared Logic)
모든 `mods/` 하위 파일은 NixOS와 Home Manager에서 동시에 해석될 수 있는 **"공통 모듈"** 구조를 가집니다.
*   **Context Awareness**: 모듈 내부에서 `config.home-manager` 존재 여부를 체크하여, `home switch` 시에는 시스템 설정(Services, Firewall)을 건너뛰고 사용자 환경만 즉시 적용합니다.
*   **Explicit Defaults**: 모든 `mods.*.enable`은 `false`에서 시작합니다.

### 2. Data Injection: `config.workspace`
`specialArgs` 대신 전역 옵션을 사용합니다.
*   **Implementation**: `core/lib/builders.nix`에서 `_info.json` 데이터를 `options.workspace`로 정의하고 주입합니다.
*   **Usage**: 어떤 모듈에서든 `config.workspace.username` 등으로 데이터에 즉시 접근합니다.

### 3. Presets & Strictness (`mods/_preset/`)
*   **Preset Role**: `lib.mkDefault true`를 통해 권장 환경을 제안합니다.
*   **Manual Response Enforcement**: 프리셋에 명시되지 않은 Mod가 존재할 경우 빌드 타임에 에러를 발생시키거나 경고를 띄워 사용자의 수동 대응을 유도합니다.

---

## 🛠️ Domain Mapping & Side Effects

### 1. `mods.sys` (Infrastructure)
*   **`base`**: Btrfs, ZRAM, SSD, Locales, Zsh + Atuin, NFD Utils.
*   **`vfs`**: GVFS, Udisks2 (OS) + Trash-cli, Aliases (Home).
*   **`services`**: `bluetooth` (triggers Blueman if GUI on), `tailscale`, `docker` (OS daemon + user group).

### 2. `mods.gui` (Interface)
*   **`enable` (DE Bundle)**: Hyprland + Waybar + Fuzzel + Mako + Hyprlock + Nemo + Udiskie + Fcitx5 + Kitty + nm-applet.
    *   **Auto-wiring**: Triggers `mods.sys.fonts.enable` and `mods.sys.vfs.enable`.
*   **`apps`**: `vivaldi`, `slack`, `bitwarden`.

### 3. `mods.devel` (Workshop)
*   **`enable` (Master Switch)**: Sets defaults for all devel sub-mods.
*   **Individual**: `node`, `python`, `fvm`, `devbox`, `llm-cli`.
*   **`jetbrains`**: Master switch + individual IDEs.
    *   `android-studio`: Automatically handles **ADB**, **UDP/Firewall**, and **SDK tools**.

---

## 🚀 Execution Roadmap (Roadmap)
1.  **Phase 1: Engine Preparation**: `lib/` → `core/lib/` 통합 및 `builders.nix` 옵션 주입 로직 개발.
2.  **Phase 2: Mods Migration**: 기존 설정을 `mods/` 하위로 해체 및 컨텍스트 인식 로직(mkIf) 적용.
3.  **Phase 3: Host Renaming**: `dev/` → `hosts/` 변경 및 `nhw.sh` 경로 전수 수정.
4.  **Phase 4: Preset Implementation**: 각 호스트 성격에 맞는 `_preset/` 파일 생성 및 `hosts/` 설정 간소화.
