# 🔄 실행 라이프사이클 (Execution Lifecycle)

`nhw` 명령어가 입력된 시점부터 시스템에 설정이 반영되기까지의 구체적인 내부 흐름입니다.

---

## 1. Orchestration Phase (준비 및 격리)
사용자의 작업 환경을 보호하고 빌드 일관성을 확보하는 단계입니다.

1.  **Input Parsing**: 사용자의 명령(예: `os switch`)을 해석하고 대상 호스트의 `isRolling` 여부를 확인합니다.
2.  **Tmpfs Isolation**: `/tmp/nixos-build` 디렉터리를 생성하고 소스 파일을 복사합니다. 하드디스크가 아닌 **RAM 디스크**를 사용하므로 I/O 속도가 빠르고 메인 저장소를 오염시키지 않습니다.
3.  **Lock Injection**: 대상 기기의 특성에 맞는 락 파일(`.locks/_rolling.lock` 또는 `<hostname>.lock`)을 격리 디렉터리의 `flake.lock`으로 주입합니다.
4.  **Ephemeral Git Commit**: Nix Flake은 Git에 추적되는 파일만 빌드에 포함합니다. `nhw`는 격리된 공간에서 즉석으로 `git init`과 `commit`을 수행하여, **저장되지 않은(Dirty) 파일들도 즉시 빌드**될 수 있게 처리합니다.

---

## 2. Evaluation Phase (평가 및 선언)
Nix 언어가 코드를 읽어 최종 시스템 명세(Derivation)를 도출하는 단계입니다.

1.  **Metadata Parsing**: `flake.nix`가 `hosts/_info.json`을 읽어 모든 호스트 설정을 AttrSet으로 생성합니다.
2.  **Package Set Construction**: `nixpkgs`, `unstable`, 그리고 `.env`에 명시된 `unstable-fallback`을 조합하여 기기에 최적화된 패키지 세트를 구성합니다.
3.  **Overlay Application**: `mkWrapper` 등 프로젝트 고유의 패키지 수정 로직이 이 단계에서 적용됩니다.

---

## 3. Expansion Phase (모듈 확장)
호스트 설정을 구성하는 수많은 파일이 하나로 합쳐지는 단계입니다.

1.  **Host Specific Loading**: `hosts/<hostname>/configuration.nix`가 먼저 로드됩니다.
2.  **Inheritance**: 베이스 설정(`hosts/base.dev.nix`)과 기기별 자동 감지된 하드웨어 설정(`hosts/<hostname>/_hardware.nix`)이 순차적으로 임포트됩니다.
3.  **Mix-in**: 모듈 프레임워크 폴더(`mods/`)의 기능별 설정들이 활성화됩니다.

---

## 4. Application Phase (최종 적용)
빌드된 명세를 실제 시스템에 반영하는 마지막 단계입니다.

1.  **Build Monitor**: **`nom` (nix-output-monitor)**을 통해 빌드 진행 상황을 시각화합니다.
2.  **Switching**: **`nh` (nix-helper)**가 최종 결과물을 현재 구동 중인 시스템의 `/nix/store`에 올리고, 필요한 심볼릭 링크를 교체하여 설정을 활성화합니다.
3.  **Logging & Sync**: 모든 과정은 로그 파일로 기록되며, 성공 시 락 파일 변경 사항 등을 사용자에게 보고합니다.
