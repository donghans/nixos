# 🏗️ Core Architecture & Implementation

### 1. Context-Aware Shared Modules
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
