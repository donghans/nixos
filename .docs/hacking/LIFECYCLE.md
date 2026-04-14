# 🔄 실행 라이프사이클 (Execution Lifecycle)

`nixup` 명령어가 입력된 시점부터 시스템에 설정이 반영되기까지의 구체적인 내부 흐름입니다.

---

## 1. Orchestration Phase (준비 및 격리)
사용자의 작업 환경을 보호하고 빌드 일관성을 확보하는 단계입니다.

1.  **Input Parsing**: 사용자의 명령(예: `os switch`)을 해석하고 대상 호스트의 `isRolling` 여부를 확인합니다.
2.  **Resolve**: `nixup.resolve.py`가 `hosts/base.toml`, `hosts/<hostname>/host.toml`, `mods/_preset/*.toml`을 읽어 `presets.json`(프리셋 mods + explicitOptional)과 `resolved.json`(호스트별 merged 데이터)을 생성합니다.
3.  **Build Isolation**: 레포 내 `.build/` 디렉터리에 소스 파일을 물리 복사합니다. `.build/`는 메인 레포의 `.gitignore`에 등록되어 있고 자체 `.git`이 없습니다. nix는 `path:` 모드로 호출되어 git 추적 여부를 확인하지 않고 해당 디렉터리를 store에 직접 복사하여 순수(pure) 평가를 수행합니다. 커밋하지 않은 실험적인 코드도 즉시 테스트할 수 있습니다.
4.  **Lock Injection**: 대상 기기의 특성에 맞는 락 파일(`.locks/_rolling.lock` 또는 `<hostname>.lock`)을 `.build/flake.lock`으로 주입합니다. `flake.lock`은 `.build/` 안에만 존재하며 메인 레포에 커밋되지 않습니다.

---

## 2. Evaluation Phase (평가 및 선언)
Nix 언어가 코드를 읽어 최종 시스템 명세(Derivation)를 도출하는 단계입니다.

1.  **Metadata Parsing**: `flake.nix`가 `resolved.json`과 `presets.json`을 읽어 모든 호스트 설정을 AttrSet으로 생성합니다.
2.  **Package Set Construction**: `nixpkgs`, `unstable`, 그리고 `.env`에 명시된 `unstable-fallback`을 조합하여 기기에 최적화된 패키지 세트를 구성합니다.
3.  **Overlay Application**: `mkWrapper`(범용 래핑 헬퍼)와 `mods/` 하위에서 자동 탐색된 `*.overlay.nix` 파일들이 이 단계에서 적용됩니다.

---

## 3. Expansion Phase (모듈 확장)
호스트 설정을 구성하는 수많은 파일이 하나로 합쳐지는 단계입니다.

1.  **Host Specific Loading**: `hosts/<hostname>/configuration.nix`가 먼저 로드됩니다. 프리셋 mods는 flake.nix가 `resolved.json`과 `presets.json`을 병합하여 `modsModule`로 주입합니다.
2.  **Inheritance**: 기기별 하드웨어 설정(`hosts/<hostname>/_hardware.nix`)이 임포트됩니다. Btrfs/ZRAM 스토리지 공통 설정은 `mods/sys/base/default.nix`를 통해 sys 도메인에서 포함됩니다.
3.  **Mix-in**: `mods/default.nix`를 통해 sys, gui, devel 세 도메인이 모두 로드됩니다. 각 모듈은 `mkIf cfg.enable`로 enable된 항목만 실제 설정에 기여합니다.
4.  **Coverage Check**: flake.nix가 주입한 `coverageModule`(`mk-preset.nix` 기반)의 `assertions`가 평가됩니다. ① 선언됐지만 preset에 없는 누락 옵션, ② 같은 그룹 내 일부만 명시된 형제 완전성 위반 중 하나라도 감지되면 즉시 오류를 발생시킵니다.

---

## 4. Application Phase (최종 적용)
빌드된 명세를 실제 시스템에 반영하는 마지막 단계입니다.

1.  **Build Monitor**: **`nom` (nix-output-monitor)**을 통해 빌드 진행 상황을 시각화합니다.
2.  **Switching**: **`nh` (nix-helper)**가 최종 결과물을 현재 구동 중인 시스템의 `/nix/store`에 올리고, 필요한 심볼릭 링크를 교체하여 설정을 활성화합니다.
3.  **Logging & Sync**: 모든 과정은 로그 파일로 기록되며, 성공 시 락 파일 변경 사항 등을 사용자에게 보고합니다.
