# 🌌 Gemini Context: NixOS Modular Framework (nixup)

이 프로젝트는 NixOS 설정을 데이터 중심으로 관리하기 위한 커스텀 프레임워크입니다. TOML 기반의 설정을 Nix 모듈로 변환하여 시스템과 사용자 환경(Home Manager)을 통합 제어합니다.

## 🏗️ 프로젝트 아키텍처 및 핵심 기술

- **Nix Flakes & Home Manager**: 시스템 구성의 기본 엔진.
- **nixup CLI**: 프로젝트 관리의 핵심 도구 (`core/scripts/nixup.sh`). 빌드 격리, 로깅, 패키지 복구 등을 수행합니다.
- **Mods Framework**: 기능을 `sys`(시스템), `gui`(데스크탑 환경), `devel`(개발 도구) 도메인으로 격리.
- **TOML Configuration**: `hosts/_base.toml`, `hosts/<hostname>.toml`, `hosts/_preset.*.toml`을 소스로 사용하며, `nixup.task-resolve.py`가 이를 `resolved.json`으로 변환하여 Nix에 주입합니다.
- **Build Isolation**: 모든 빌드는 소스를 `.build/`로 복사한 뒤 수행되어, Git 추적되지 않은 파일로 인한 오동작을 방지합니다.

## 🛠️ 주요 명령어 (`nixup`)

프로젝트 루트에서 다음 명령어를 사용합니다. (모든 작업은 빌드 격리 환경에서 수행됩니다.)

- **전체 설정 적용**: `nixup [hostname]` — NixOS 시스템 + Home Manager 동시 적용 (기본값)
- **시스템만 적용**: `nixup os [hostname]` — `os` 블록 변경만 있을 때
- **사용자만 적용**: `nixup home [hostname]` — `hm` 블록 변경만 있을 때
- **무결성 점검**: `nixup check` (포맷팅, 린팅, 빌드 가능 여부 확인)
- **전체 호스트 검사**: `nixup check --deep`
- **커스텀 ISO 빌드**: `nixup iso` (x86_64), `nixup iso --arm` (aarch64)
- **패키지 복구**: `nixup fix [packageName]` (빌드 실패하는 Unstable 패키지를 고정)
- **시스템 정리**: `nixup clean --all --keep=5`

## 📂 주요 디렉토리 구조

- `core/`: 프레임워크의 엔진. `flake.nix`, 빌더 로직, `nixup` 스크립트 포함.
- `mods/`: 재사용 가능한 기능 모듈. `sys/`, `gui/`, `devel/`로 구성.
- `hosts/`: 호스트별 설정 (평탄 구조). `_base.toml`, `<hostname>.toml`, `<hostname>.nix`, `_preset.*.toml`.
- `.docs/`: 프로젝트 상세 문서 (Hacking, Lifecycle, Mechanisms 등).
- `.locks/`: 호스트별 또는 Rolling 전략을 위한 Flake lock 파일 저장소.

## 📝 개발 컨벤션 및 주의사항

1. **직접적인 Nix 명령 금지**: `nixos-rebuild`나 `nix build`를 직접 실행하지 마세요. 반드시 `nixup`을 통해야 `resolved.json`이 생성되고 빌드 격리가 보장됩니다.
2. **모듈 추가**: 새로운 기능을 추가할 때는 `mods/` 하위의 적절한 도메인에 `.nix` 파일을 배치하면 자동으로 로드됩니다. `mkMod`/`mkModOf`/`mkPartOf` 헬퍼를 사용하고, `hosts/_preset.*.toml`에 enable 항목을 등록하세요.
3. **코드 스타일**: `nixup check`가 내부적으로 `alejandra`(포맷터), `statix`(린터), `deadnix`(미사용 코드 제거)를 실행하므로, 커밋 전 반드시 수행하세요.
4. **패키지 참조**: Unstable 패키지를 사용할 때는 `unstable.<name>`을 기본으로 하되, `nixup fix`로 고정된 패키지는 `unstable-fallback.<name>`으로 참조해야 합니다.

## 💡 유용한 팁

- **로그 확인**: 모든 `nixup` 결과는 `/var/log/nixup/`에 저장됩니다. 빌드 실패 시 `.nom-build.log`를 확인하세요.
- **새 호스트 추가**: `hosts/<hostname>.toml`과 `hosts/<hostname>.nix`를 작성한 뒤 `nixup os [newhost]`를 실행하면 됩니다. (또는 `nixstrap`이 대화형으로 자동 생성)
