# 💡 핵심 메커니즘 (Key Mechanisms)

이 프로젝트가 단순한 설정 파일 모음을 넘어 강력한 관리 프레임워크로 동작할 수 있게 하는 핵심 기술적 장치들입니다.

---

## 1. 빌드 격리 (Build Isolation)
사용자의 작업 환경(Working Tree)을 완벽하게 보호합니다.

- **문제**: Nix Flake 빌드 도중 Git 인덱스가 꼬이거나, 실수로 빌드 중인 파일이 커밋되는 등의 오염 발생 위험.
- **해결**: `/tmp` (**tmpfs**)에서 임시 Git 저장소를 생성하여 빌드합니다. 덕분에 사용자는 **커밋하지 않은 실험적인 코드**를 메인 리포지토리의 기록 손상 없이 즉시 테스트할 수 있습니다.

---

## 2. 하이브리드 잠금 전략 (Hybrid Lock Strategy)
하나의 리포지토리로 최신 성능과 안정성을 동시에 추구합니다.

- **Rolling 기기**: 항상 최신 패키지를 테스트하는 기기들(`isRolling=true`)은 공용 **`_rolling.lock`**을 사용하여 활발한 업데이트를 유도합니다.
- **Stable 기기**: 서버나 안정적인 작업용 기기들은 개별 **`<hostname>.lock`**으로 고정된 패키지 버전을 유지합니다.
- **전환**: 기기의 기동 시점에 엔진이 어떤 잠금 파일을 사용할지 지능적으로 결정합니다.

---

## 3. 지능형 패키지 복구 (Fallback System)
Unstable 채널 사용자의 최대 고민인 '빌드 실패'를 자동화로 해결합니다.

- **메커니즘 (`fix-unstable`)**:
  1. 깨진 패키지의 히스토리를 GitHub API로 추적합니다.
  2. 가장 최근에 빌드가 성공했던 시점의 커밋 해시를 찾아냅니다.
  3. 해당 해시와 SHA256을 프로젝트 루트 **`.env`**에 기록합니다.
- **`.env` 파일 형식** (git 추적 제외):
  ```bash
  NHW_LAST_HOST=<마지막으로 빌드한 호스트명>         # switch/test/boot 시 nhw가 기록 (check/build는 기록 안 함)
  NIX_UNSTABLE_FALLBACK_REV=<nixpkgs 커밋 해시>    # nhw fix-unstable이 관리
  NIX_UNSTABLE_FALLBACK_SHA=<sha256 해시>          # nhw fix-unstable이 관리
  ```
- **적용**: `flake.nix`의 빌더가 `.env`를 감지하여 `unstable-fallback` 패키지 세트를 해당 커밋 기준으로 구성합니다. 전체 시스템은 최신 상태로 유지하면서 **문제 있는 특정 패키지만 안전한 구버전**으로 내려서 빌드합니다.

---

## 4. Mods Coverage Check (프리셋 커버리지 검증)
`workspace-options.nix`에 새 옵션이 추가될 때 프리셋 선언에서 누락되는 것을 빌드 타임에 감지합니다.

- **문제**: `workspace-options.nix`에 새 `enable` 옵션을 추가하면서 프리셋 TOML에 해당 항목을 기재하지 않으면, 신규 기능이 의도치 않게 모든 호스트에서 비활성화 상태로 방치됩니다.
- **해결**: `core/lib/mk-preset.nix`가 호스트별로 주입되어 두 목록을 대조합니다. 일반 호스트뿐 아니라 ISO 빌드(`custom-iso`, `custom-iso-aarch64`)도 coverageModule 대상에 포함됩니다.
  1. **presetCovered**: `presets.json`에서 읽은 preset mods의 `.enable` 경로 목록
  2. **declaredOptions**: `options.mods`를 재귀 탐색하여 찾은 선언된 `.enable` 옵션 목록
- **효과**: 두 가지 검사를 수행하며, 하나라도 실패하면 빌드 타임 오류를 발생시킵니다.
  1. **누락 검사**: `declaredOptions`에 있지만 `presetCovered`에 없는 옵션(`uncovered`)이 존재하면 오류.
  2. **형제 완전성 검사**: 같은 그룹(공통 부모, 예: `mods.gui.apps`) 내 옵션 중 하나라도 preset에 명시했다면 같은 그룹의 나머지 옵션도 전부 명시해야 합니다. 의도적으로 관리하는 그룹임을 선언하는 일관성 정책입니다.
- 의도적으로 프리셋 외부에서 관리되는 옵션(예: `gui/default.nix`가 내부적으로 활성화하는 `sys.fonts`, `sys.vfs`)은 프리셋 TOML의 `[explicitOptional]`에 등록하면 체크에서 제외됩니다.

---

## 5. 오버레이 시스템 (Overlay System)
복잡한 패키지 의존성 문제를 선언적으로 해결합니다.

- **`mkWrapper` (`core/lib/mk-wrapper.nix`)**: 패키지의 소스 코드를 수정하지 않고도, 실행 파일에 필요한 환경 변수(`PATH`, `LD_LIBRARY_PATH` 등)를 주입하거나 래핑(Wrapping)할 수 있는 범용 헬퍼 함수입니다.
- **`*.overlay.nix` 자동 탐색**: `mods/` 하위 어디든 `<name>.overlay.nix` 파일을 두면 `flake.outputs.nix`가 `lib.filesystem.listFilesRecursive`로 자동 탐색하여 `customOverlays`에 추가합니다. 특정 패키지를 nixpkgs overlay로 패치할 때 사용합니다. `mods/_lib.nix`의 `importDir`은 이 파일을 home-manager 모듈로 로드하지 않도록 자동 제외합니다.
  - **사례**: 특정 패키지가 런타임에 필요한 외부 바이너리를 PATH에 포함하지 않을 경우, `postFixup`에서 `wrapProgram`으로 주입.
