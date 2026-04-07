# 🏗️ 프로젝트 아키텍처 (Internal Components)

이 프로젝트는 유지보수성과 확장성을 극대화하기 위해 명확한 **관심사 분리(Separation of Concerns)**를 실천하고 있습니다.

---

## 1. 실행 엔진 레이어 (CLI Engine Layer)
**핵심 경로: `core/scripts/`**

이 레이어는 시스템의 모든 동작을 제어하고 외부 도구들을 오케스트레이션합니다.

- **`nhw.sh` (Dispatcher)**:
  - **역할**: 모든 명령의 통합 입구이자 빌드 오케스트레이터입니다.
  - **특징**: `nix-shell` 쉬뱅을 사용하여 `nh`, `jq`, `nom` 등의 도구가 없어도 시스템을 부트스트랩할 수 있도록 설계되었습니다. 로깅(`YYYYMMDDTHHMMSS.log`)과 세션 락(`flock`)을 독점적으로 관리합니다.
- **Task & Lib**:
  - **`nhw.lib-build.sh`**: `/tmp` 기반 격리 빌드 환경 구축 로직.
  - **`nhw.lib-lock.sh`**: 기기 특성(`isRolling`)에 따른 유연한 락 파일 관리 로직.
  - **`nhw.task-*.sh`**: 실제 비즈니스 로직(빌드, 업데이트, 복구 등)을 수행하는 모듈형 스크립트.

---

## 2. 메타데이터 레이어 (Metadata Layer)
**핵심 경로: `hosts/base.toml`, `hosts/<hostname>/host.toml`, `mods/_preset/*.toml`**

코드와 데이터를 분리하여, 사용자가 `nix` 언어를 깊게 알지 못해도 시스템 구성을 관리할 수 있게 합니다.

- **TOML 소스**: `base.toml`(전역: username, git, system), `host.toml`(호스트: isLaptop, ramGb, preset, mods 오버라이드), `_preset/*.toml`(프리셋 mods 정의 + explicitOptional)을 TOML로 선언합니다.
- **Resolver (`nhw.resolve.py`)**: `nhw` 빌드 시 TOML 소스를 읽어 `presets.json`(프리셋 mods + explicitOptional)과 `resolved.json`(호스트별 merged 데이터)을 생성합니다. flake.nix는 이 JSON 파일을 읽어 빌드합니다.
- **직접 nix 실행 금지**: `flake.nix`는 `resolved.json`이 없으면 명시적 오류를 발생시킵니다. 항상 `nhw`를 통해 빌드하세요.

---

## 3. 로직 코어 레이어 (Logic Core Layer)
**핵심 경로: `core/flake.nix`, `core/lib/`**

시스템 설정의 두뇌에 해당하며, Nix Flake의 강력한 기능을 활용해 복잡한 패키징과 모듈성을 구현합니다.

- **Dynamic Generator (`core/lib/builders.nix`)**: JSON 데이터를 기반으로 `nixosConfigurations`와 `homeConfigurations`를 동적으로 생성해내는 **메타프로그래밍 구조**와 빌더 팩토리입니다.
- **SSOT Options (`core/lib/workspace-options.nix`)**: `config.workspace` 및 `config.mods`를 선언하여 전역 설정과 기능 모듈(Mods)의 통합 옵션을 제공합니다.
- **Advanced Overlay (`core/lib/mk-wrapper.nix`)**: `mkWrapper` 헬퍼를 단독 분리하여, 특정 패키지에 런타임 환경 변수나 라이브러리 경로 등을 주입해 패키지를 래핑하는 로직을 제공합니다.

---

## 4. 모듈 프레임워크 레이어 (Mods Layer)
**핵심 경로: `mods/`**

실제 시스템의 살점이 되는 부분이며, **Mods 프레임워크** 기반으로 설계되었습니다.

- **Domain-Driven Design**: `sys`, `gui`, `devel`로 도메인을 분리하여 응집도를 높였습니다.
  - `mods/sys/`: 시스템 기반 — `base`(부팅/네트워크/Zsh/Git), `fonts`, `vfs`, `services`(bluetooth/tailscale/docker), `utils/nfd`
  - `mods/gui/`: GUI 환경 — `core`(Hyprland 번들), `apps`(vivaldi/slack/bitwarden), `utils/notifications_logger`
  - `mods/devel/`: 개발 도구 — `toolchains`(node/python/fvm/devbox), `apps`(llm-cli/zed), `jetbrains`(android-studio 포함)
- **Opt-in Mods System**: 모든 `mods.<domain>.<feature>.enable`은 `false`에서 시작합니다. `isNixOS` 플래그를 통해 NixOS와 Home Manager 양측의 구성을 단일 파일에서 분기 처리합니다(Dual-Context).
- **워크스테이션 프리셋 (`mods/_preset/`)**: `workstation.toml`에 sys+services+gui+devel 전체 mods를 선언합니다. flake.nix가 이를 읽어 호스트별 mods와 병합하여 적용합니다. `host.toml`에는 프리셋 기본값에서 변경할 항목만 기재합니다.
- **Mods Coverage Check**: flake.nix가 호스트별로 `mk-preset.nix` 기반 coverageModule을 주입합니다. 프리셋 TOML에 누락된 옵션이 있으면 빌드 타임 오류를 발생시킵니다.
- **Shared Data (`mods/_data/`)**: `devbox` 설정 등 정적 템플릿과 메타데이터를 분리 관리하여 로직의 순수성을 유지합니다.
