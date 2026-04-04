# 🏗️ 프로젝트 아키텍처 (Internal Components)

이 프로젝트는 유지보수성과 확장성을 극대화하기 위해 명확한 관심사 분리(Separation of Concerns)를 실천하고 있습니다.

## 1. 실행 엔진 레이어 (CLI Engine Layer)
**핵심 경로: `core/scripts/`**

이 레이어는 시스템의 모든 동작을 제어하고 외부 도구들을 오케스트레이션합니다.

- **`nhw.sh` (Dispatcher)**:
  - **역할**: 모든 명령의 통합 입구이자 빌드 오케스트레이터입니다.
  - **특징**: `nix-shell` 쉬뱅을 사용하여 `nh`, `jq`, `nom` 등의 도구가 없어도 시스템을 부트스트랩할 수 있도록 설계되었습니다. 로깅(YYYYMMDDTHHMMSS.log)과 세션 락(`flock`)을 독점적으로 관리합니다.
- **Task & Lib**:
  - `nhw.lib-build.sh`: `/tmp` 기반 격리 빌드 환경 구축 로직.
  - `nhw.lib-lock.sh`: 기기 특성(`isRolling`)에 따른 유연한 락 파일 관리 로직.
  - `nhw.task-*.sh`: 실제 비즈니스 로직(빌드, 업데이트, 복구 등)을 수행하는 모듈형 스크립트.

## 2. 메타데이터 레이어 (Metadata Layer)
**핵심 경로: `dev/_info.json`**

코드와 데이터를 분리하여, 사용자가 `nix` 언어를 깊게 알지 못해도 시스템 구성을 관리할 수 있게 합니다.

- **중앙 설정**: 사용자 계정명, Git 저장소 주소, 호스트별 하드웨어 특성을 JSON으로 선언합니다.
- **동적 활용**: `flake.nix`는 빌드 타임에 이 파일을 읽어 호스트 설정을 실시간으로 생성하고, `nhw.sh`는 런타임에 이를 읽어 빌드 대상 기기를 결정합니다.

## 3. 로직 코어 레이어 (Logic Core Layer)
**핵심 경로: `core/flake.nix`**

시스템 설정의 두뇌에 해당하며, Nix Flake의 강력한 기능을 활용해 복잡한 패키징과 모듈성을 구현합니다.

- **Dynamic Generator**: JSON에 호스트를 추가하는 것만으로 `nixosConfigurations`와 `homeConfigurations`가 자동 생성되는 메타프로그래밍 구조입니다.
- **Advanced Overlay**: `mkWrapper` 오버레이를 통해 특정 패키지에 런타임 환경 변수, 라이브러리 경로 등을 주입하여 패키지를 래핑하는 로직이 핵심입니다.

## 4. 구성 모듈 레이어 (Library & Config Layer)
**핵심 경로: `lib/`, `dev/base/`**

실제 시스템의 살점이 되는 부분입니다.

- **Base Components (`dev/base/`)**: 파일시스템 마운트 규칙, 개발자 기본 환경, 유틸리티 등 모든 기기가 예외 없이 상속받는 핵심 모듈입니다.
- **Functional Modules (`lib/`)**: Hyprland, Waybar 등 기능 단위로 조각난 설정들입니다. 개별 호스트 설정(`dev/<hostname>.nix`)에서 필요한 것만 골라 담는(Mix-in) 방식으로 구성됩니다.
