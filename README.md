# NixOS 모듈형 설정 프로젝트 (Flake 기반)

이 프로젝트는 **Nix Flakes**와 **Home Manager**를 사용하여 여러 대의 NixOS 호스트 설정을 효율적으로 관리하고, 나만의 커스텀 설치 미디어(ISO)를 생성하기 위한 환경입니다.

---

## 🚀 주요 특징

- **Mods Framework**: 모든 설정을 `sys` / `gui` / `devel` 세 도메인으로 격리하고, 명시적 `enable` 옵션을 통해 기능을 선택합니다.
- **TOML 설정 원본**: `hosts/_base.toml`과 `hosts/<hostname>.toml`에 메타데이터를 선언합니다. `nixup` 실행 시 내부적으로 이를 `resolved.json`으로 변환하여 flake.nix에 주입합니다.
- **프리셋 시스템**: `hosts/_preset.*.toml`에 workstation, server, iso 등 다양한 프리셋이 정의되어 있습니다. `<hostname>.toml`에 `preset = "workstation"` 한 줄로 해당 환경 전체(tailscale, docker, bluetooth, GUI, 개발 도구 등)가 자동 적용되며, 호스트별 변경 항목만 추가로 기재하면 됩니다.
- **Mods Coverage Check**: 빌드 시 프리셋에 선언된 옵션과 workspace-options에 등록된 옵션을 대조하여, 누락된 항목을 빌드 타임 에러로 알립니다.
- **격리된 빌드 환경**: 모든 빌드는 소스를 `.build/` 디렉터리에 물리 복사하고 `path:` 모드로 호출하여 git 추적 없이 안전하게 수행됩니다.
- **시스템 통합 도구 (`nixup`)**: `nixup`을 통해 시스템 업데이트, 전환, ISO 빌드, 패키지 복구 등 모든 작업을 수행합니다.

---

## 📂 프로젝트 구조

```
nixos/
├── core/               # 프레임워크 엔진
│   ├── flake.nix       # 메인 진입점
│   ├── lib/            # 호스트 빌더(host.nix), Mods 헬퍼(mods.nix), 옵션 선언(workspace-options.nix)
│   └── scripts/        # nixup 관리 CLI + nixstrap 설치 스크립트
├── mods/               # 재사용 가능한 기능 모듈
│   ├── sys/            # 시스템 기반 (base, fonts, vfs, services, utils)
│   ├── gui/            # GUI 환경 (Hyprland 번들, apps, utils)
│   ├── devel/          # 개발 도구 (base, toolchains, apps)
│   └── _data/          # 비-Nix 데이터 파일 (zsh 스크립트, CSS, XML 등)
├── hosts/              # 호스트별 고유 설정 (평탄 구조)
│   ├── _base.toml      # 전역 메타데이터 (username, git, system)
│   ├── _preset.*.toml  # 프리셋 정의 (workstation/server/iso)
│   ├── <hostname>.toml # 호스트 메타데이터 (type, preset, mods 오버라이드)
│   └── <hostname>.nix  # 호스트 전용 NixOS + Home Manager 설정
└── .locks/             # Flake lock 파일 (Rolling/Stable 전략)
```

---

## 🛠️ 호스트 설정 방법

```toml
# hosts/<hostname>.toml 예시
type   = "desktop"
preset = "workstation"

# 프리셋 기본값에서 변경할 항목만 기재
[mods.devel]
fvm = true
```

상세한 설정 옵션(파티션 경로, 메모리, 프리셋 등)은 [BOOTSTRAP.md](./.docs/readme/BOOTSTRAP.md) 섹션 4를 참고하세요.

---

## 🚀 처음 사용자용 가이드 (Getting Started)

이 프로젝트는 **Btrfs 서브볼륨 구조**에 최적화되어 설계되었습니다. `hosts/_base.toml`에서 사용자 정보만 수정한 뒤 바로 설치를 시작할 수 있습니다. 호스트 프로필은 설치 도중 `nixstrap`이 대화형으로 생성합니다. 자세한 내용은 [BOOTSTRAP.md](./.docs/readme/BOOTSTRAP.md) 가이드를 참고하세요.

---

## 🛠️ 프로젝트 관리 (`nixup`)

시스템이 설치된 후에는 프로젝트 경로와 상관없이 터미널 어디서든 `nixup` 명령어를 사용할 수 있습니다. 구체적인 명령어 사용법과 활용 사례는 [NIXUP.md](./.docs/manual/NIXUP.md) 가이드를 참조하세요.

- **OS 설정 적용:** `nixup [os]`
- **Home Manager 적용:** `nixup home`
- **커스텀 ISO 빌드:** `nixup iso` (x86_64) / `nixup iso --arm` (aarch64) — 결과물은 `.build/` 폴더에 생성됨
- **시스템 업데이트:** `nixup update`
- **깨진 패키지 복구:** `nixup fix [pkg1] [pkg2] ...`
- **무결성 및 스타일 점검:** `nixup check` (deadnix, 안티패턴 정리, 포맷팅, shellcheck, 빌드 검증)
- **시스템 정리:** `nixup clean [--all] [--keep=N]`

---

## 📦 Mods 확장 (커스텀 기능 추가)

이 프로젝트의 모든 기능은 `mods/` 디렉터리의 모듈(Mod)로 구성되어 있습니다. 새 기능을 추가하거나 기존 기능을 수정하려면 Mods 가이드를 참고하세요.

- **API 레퍼런스**: `mkMod`, `mkModOf`, `mkPartOf` 헬퍼 사용법
- **Cookbook**: 패키지 설치, NixOS+HM 동시 설정, 부모 도메인 cascade 등 7가지 실전 예시
- **추가/삭제 절차**: 파일 생성 → 프리셋 등록 → `nixup check` 검증

👉 [MODS.md](./.docs/manual/MODS.md)

내부 작동 원리(모듈 스캐닝, enable 계층, Dual-Context 등)가 궁금하다면 [ARCHITECTURE-MODS.md](./.docs/hacking/ARCHITECTURE-MODS.md)를 참고하세요.

---

## 💡 주요 개념 및 고급 가이드

이 프로젝트의 내부 작동 방식(빌드 격리, 락 전략, Mods Framework 아키텍처 등)이 궁금하거나, 시스템을 깊게 커스텀하고 싶은 고급 사용자는 [HACKING.md](./.docs/hacking/_HACKING.md) 파일을 참조하세요.
