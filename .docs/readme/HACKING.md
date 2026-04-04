# 🛠️ 고급 사용자용 기술 가이드 (HACKING)

이 프로젝트는 단순히 NixOS 설정을 모아놓은 것이 아니라, 자동화된 빌드/배포 워크플로우를 갖춘 하나의 프레임워크입니다. 내부 구조를 깊게 탐색하고 싶은 분들을 위한 기술 가이드입니다.

## 1. 핵심 철학: 빌드 격리 (Build Isolation)

이 프로젝트의 모든 빌드는 현재 디렉터리(`nixos/`)에서 직접 실행되지 않습니다. `nhw.sh`는 실행될 때마다 다음과 같은 작업을 수행합니다.

- **격리 디렉토리**: `/tmp/nixos-build` (tmpfs)를 생성하고 소스 코드를 복사합니다.
- **임시 Git 커밋**: Nix Flake은 파일이 Git에 추적되어야만 빌드에 포함됩니다. `nhw`는 `/tmp` 내에서 즉석으로 Git 저장소를 초기화하고 임시 커밋을 생성하여, **사용자가 작업 중인 미커밋(Dirty) 파일을 즉시 빌드**할 수 있게 합니다.
- **결과**: 작업 도중 빌드가 실패해도 실제 프로젝트 저장소의 Git 상태(Index/Worktree)는 완벽하게 깨끗하게 유지됩니다.

## 2. 관리 도구: `nhw` 디스패처 (Dispatcher)

`core/scripts/nhw.sh`는 모든 작업의 중앙 입구입니다. `nix-shell` 쉬뱅을 사용하여 `nh`, `jq`, `nom` 등의 필수 도구를 즉석에서 내려받아 실행하므로, 시스템에 해당 도구가 깔려 있지 않아도 독립적으로 동작합니다.

- **Smart Redirect**: 각 개별 태스크 스크립트(`nhw.task-*.sh`)는 단독 실행 시 자동으로 `nhw.sh`로 위임되도록 설계되었습니다. 이는 로깅, 락(Lock), 빌드 디렉토리 초기화가 항상 보장되도록 합니다.
- **Execution Markers**: 외부 명령어를 실행할 때 `Exec nh >` 와 같이 표시하여 로그에서 각 구간을 명확히 구분합니다.

## 3. 잠금 전략 (Lock Strategy)

`.locks/` 디렉터리에는 호스트별 `flake.lock` 상태를 관리합니다.

- **Rolling 호스트**: `_rolling.lock`을 공유합니다. 최신 패키지를 선호하는 기기들을 위해 설계되었습니다.
- **Stable 호스트**: 개별 `<hostname>.lock`을 사용하여 고유한 패키지 버전을 유지합니다.
- **빌드 시 결합**: 빌드 직전, 선택된 락 파일을 `/tmp/nixos-build/flake.lock`으로 복사하여 빌드 일관성을 유지합니다.

## 4. Unstable 패키지 복구 (Fallback Mechanism)

`nhw.task-fix.sh`는 NixOS Unstable 사용자들을 위한 고유한 기능입니다.

- **문제**: Unstable 채널에서는 특정 패키지가 깨지는 일이 잦습니다.
- **해결**: 깨진 패키지의 이름을 인자로 주면, GitHub API를 통해 해당 패키지의 커밋 히스토리를 추적하고 **작동하는 이전 시점의 커밋 해시**를 자동으로 찾아 `.env`에 기록합니다.
- **적용**: `flake.nix`는 빌드 시 `.env`의 `UNSTABLE_FALLBACK_REV`를 확인하여, 해당 패키지만 안전한 구버전으로 하향 조정(Downgrade)합니다.

## 5. 메타데이터 기반 구성 (`dev/_info.json`)

`flake.nix`는 이 JSON 파일을 읽어 `nixosConfigurations`를 동적으로 생성합니다.

- **유동적인 호스트 추가**: `flake.nix` 코드를 건드리지 않고 JSON에 객체 하나를 추가하는 것만으로 새로운 호스트를 등록할 수 있습니다.
- **동적 오버레이**: `ramGb` 값을 보고 `/tmp` 크기를 조절하거나 물리 스왑 파일 생성을 결정하는 등, 하드웨어 특성에 따른 동적 설정이 가능합니다.

---

## 🏗️ 프로젝트 디렉터리 맵 (Directory Map)

프로젝트의 전체적인 구조와 각 폴더의 역할을 3단계 깊이로 설명합니다.

- **`core/`**: 시스템의 두뇌와 근육이 담긴 핵심부입니다.
  - `flake.nix`: 모든 설정의 **Entry Point**. `dev/_info.json`을 읽어 호스트를 동적으로 생성합니다.
  - `scripts/`: 시스템 관리 프레임워크인 `nhw`의 구현체들입니다.
    - `nhw.sh`: 메인 디스패처. 로깅, 락, 격리 환경 구축을 담당합니다.
    - `nhw.lib-*.sh`: 공통 함수 모음 (빌드 준비, 락 전략 등).
    - `nhw.task-*.sh`: 실제 수행되는 개별 작업 단위.
- **`dev/`**: "무엇을 빌드할 것인가"를 결정하는 데이터 계층입니다.
  - `_info.json`: 유저 정보, 호스트 목록, GitHub 저장소 경로 등 핵심 메타데이터.
  - `<hostname>.nix`: 특정 기기의 시스템 레벨 설정 (서비스, 부트로더 등).
  - `<hostname>.home.nix`: 특정 기기의 사용자 레벨 설정 (Home Manager).
  - `hardware/`: `nixos-setup`이 자동 생성한 기기별 하드웨어 드라이버 설정.
  - `base/`: `developer.nix` 등 여러 호스트가 공유하는 기본 프로필.
- **`lib/`**: 재사용 가능한 기능 중심의 추상화 계층입니다.
  - `default.nix`: 시스템 공통 패키지 및 기본 설정 모음.
  - `hyprland.nix`: 창 관리자 설정. 복잡한 로직은 `hyprland.home/` 하위로 분산되어 있습니다.

## 🔄 설정 로드 라이프사이클 (Configuration Lifecycle)

`nhw` 명령어를 실행했을 때부터 시스템에 설정이 적용되기까지의 흐름입니다.

1.  **Orchestration Phase (`nhw.sh`)**:
    - 인자 분석 및 대상 호스트 결정.
    - `/tmp/nixos-build` 격리 환경 생성 및 소스 복사.
    - 대상 호스트에 맞는 `flake.lock` 주입.
    - 임시 Git 커밋 생성 (Flake 인식용).
2.  **Flake Evaluation Phase (`flake.nix`)**:
    - `dev/_info.json` 파싱 -> `nixosConfigurations` 및 `homeConfigurations` AttrSet 자동 생성.
    - `getHM` 헬퍼 함수 호출: `unstable`, `unstable-fallback` 패키지 세트 준비 및 전역 오버레이(`mkWrapper` 등) 적용.
3.  **Module Import Phase**:
    - `dev/<hostname>.nix` 임포트.
    - 내부에서 `dev/base/developer.nix` -> `dev/base/_filesystem.nix` 순으로 확장.
    - 하드웨어별 전용 모듈(`dev/hardware/<hostname>.nix`) 로드.
4.  **Application Phase**:
    - `nh` (nix-helper)가 최종 결과물을 시스템에 스위칭.

## 🔍 핵심 파일 딥다이브 (Deep-dive)

분석 시 가장 먼저 살펴봐야 할 핵심 파일 3선입니다.

### 1. `core/flake.nix` (Logic Entry)
이 프로젝트의 "메타 프로그래밍"이 일어나는 곳입니다.
- **Dynamic Hosts**: `builtins.fromJSON`을 통해 외부 파일을 읽어 호스트 설정을 실시간으로 생성합니다.
- **Custom Overlays**: `mkWrapper`와 같은 독자적인 오버레이를 통해 패키지에 환경 변수나 라이브러리를 주입하는 로직을 확인할 수 있습니다.

### 2. `core/scripts/nhw.sh` (Workflow Engine)
NixOS의 복잡한 빌드 명령어를 추상화한 래퍼입니다.
- **Isolation Logic**: 왜 빌드가 `/tmp`에서 일어나는지, 어떻게 Git 인덱스를 보호하는지 이해하려면 이 파일을 분석하세요.
- **Smart Redirect**: `if [[ "${BASH_SOURCE[0]}" == "${0}" ]]` 패턴을 통해 개별 태스크가 어떻게 메인 엔진과 통신하는지 볼 수 있습니다.

### 3. `dev/base/_filesystem.nix` (Storage Standard)
이 프로젝트의 물리적 기반입니다.
- **Btrfs Subvolumes**: `@`, `@home`, `@nix`, `@log` 서브볼륨 마운트 옵션과 압축 설정(`zstd:3`)이 정의되어 있습니다.
- **Dynamic Swap**: 호스트 메타데이터의 `ramGb` 값을 읽어 물리 스왑 파일 크기를 동적으로 결정하는 로직이 포함되어 있습니다.

---

이 설계를 바탕으로 본인만의 강력한 NixOS 환경을 구축해 보세요!
