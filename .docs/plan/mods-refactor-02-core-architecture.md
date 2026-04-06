# 🏗️ Core Architecture & Implementation

### 1. Dual-Context Shared Modules (OS & Home Agility)
모든 `mods/` 하위 모듈은 NixOS(`os switch`)와 Home Manager(`home switch`) 양쪽에서 호출 가능한 **"이중 컨텍스트"** 구조를 가집니다.

*   **Detection Logic**: 모듈 내부에서 `options.home-manager` 또는 `config.home-manager` 존재 여부를 체크합니다.
    *   **`home switch` 시**: 시스템 권한이 필요한 `virtualisation`, `services`, `networking.firewall` 등은 무시하고 `home.packages`, `home.file`만 적용합니다.
    *   **`os switch` 시**: 시스템 인프라와 사용자 설정을 동시에 적용합니다.
*   **Explicit Defaults**: 모든 `mods.*.enable`은 `false`에서 시작하며 사용자의 선택을 강제합니다.

### 2. Data Injection: `config.workspace` (SSOT)
`specialArgs`를 통한 파편화된 데이터 전달 대신, 전역 옵션을 통한 중앙 집중식 조회를 사용합니다.
*   **Implementation**: `core/lib/builders.nix`에서 `_info.json` 데이터를 수용할 전역 `options.workspace` 구조를 선언합니다.
*   **Value Injection**: `config.workspace`에 실제 값을 주입하여 어떤 모듈에서든 인자 전달 없이 `config.workspace.username` 등으로 즉시 접근 가능하게 합니다.

### 3. Root User Environment Parity
시스템 관리의 일관성을 위해 `root` 계정은 일반 유저의 **`mods.sys.base`** 환경을 상속받습니다.
*   **Logic**: `home-manager.users.root`가 일반 유저와 동일한 `base` 설정을 import 하되, GUI 관련 설정만 필터링하여 터미널 환경(Zsh, Atuin, Aliases)의 일치성을 유지합니다.

### 4. Presets & Manual Response Enforcement
*   **Strict Governance**: 프리셋(`mods/_preset/`)에 명시되지 않은 Mod가 발견될 경우, `assertions`를 통해 빌드 타임 에러를 발생시켜 사용자의 명시적 수동 대응을 유도합니다.
