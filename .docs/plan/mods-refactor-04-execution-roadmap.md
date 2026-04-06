# 🚀 Execution Roadmap

가동 중인 시스템의 빌드 실패 시간을 최소화하기 위해 **"원자적 경로 이관(Atomic Transition)"** 전략을 사용합니다.

1.  **Phase 1: Engine Preparation (Atomic)**
    *   `lib/` → `core/lib/` 통합.
    *   `builders.nix` 내 `config.workspace` 옵션 선언 및 데이터 주입 로직 개발.
    *   `flake.nix`에서 호스트 생성 시 `config.workspace`를 사용하도록 수정.

2.  **Phase 2: Global Renaming & Path Normalization**
    *   `dev/` → `hosts/` 디렉토리 변경.
    *   `nhw.sh` 내부의 모든 경로 참조를 `hosts/`로 전수 수정.
    *   **Note**: `dev/` 심볼릭 링크를 잠시 유지하여 예기치 못한 빌드 중단 방지.

3.  **Phase 3: Asset & Logic Migration**
    *   `devbox/*.json` 등 설정 데이터를 `mods/_data/`로 이관.
    *   기존 설정을 `mods/` 하위 도메인으로 해체하여 재배치.
    *   각 모듈에 **Dual-Context Awareness** (`mkIf`) 로직 적용.

4.  **Phase 4: Preset Implementation & Host Cleanup**
    *   `mods/_preset/` 파일 생성 및 `hosts/<hostname>/`의 설정 파일을 프리셋 기반으로 대폭 간소화.
    *   **Verification**: `nhw check`를 통해 모든 호스트의 무결성 검증.
    *   `dev/` 심볼릭 링크 제거.
