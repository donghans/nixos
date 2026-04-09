# NixOS 모듈형 설정 프로젝트 (Flake 기반)

이 프로젝트는 **Nix Flakes**와 **Home Manager**를 사용하여 여러 대의 NixOS 호스트 설정을 효율적으로 관리하고, 나만의 커스텀 설치 미디어(ISO)를 생성하기 위한 환경입니다.

---

## 🚀 주요 특징

- **Mods Framework**: 모든 설정을 `sys` / `gui` / `devel` 세 도메인으로 격리하고, 명시적 `enable` 옵션을 통해 기능을 선택합니다.
- **TOML 설정 원본**: `hosts/base.toml`과 `hosts/<hostname>/host.toml`에 메타데이터를 선언합니다. `nhw resolve`가 이를 `resolved.json`으로 변환하여 flake.nix에 주입합니다.
- **프리셋 시스템**: `mods/_preset/`에 workstation, server, iso 등 다양한 프리셋이 정의되어 있습니다. `host.toml`에 `preset = "workstation"` 한 줄로 해당 환경 전체(tailscale, docker, bluetooth, GUI, 개발 도구 등)가 자동 적용되며, 호스트별 변경 항목만 추가로 기재하면 됩니다.
- **Mods Coverage Check**: 빌드 시 프리셋에 선언된 옵션과 workspace-options에 등록된 옵션을 대조하여, 누락된 항목을 빌드 타임 에러로 알립니다.
- **격리된 빌드 환경**: 모든 빌드는 `/tmp/nixos-build` (tmpfs)에서 안전하게 격리되어 수행됩니다.
- **시스템 통합 도구 (`nhw`)**: `nhw`를 통해 시스템 업데이트, 전환, ISO 빌드, 패키지 복구 등 모든 작업을 수행합니다.

---

## 📂 프로젝트 구조

```
nixos/
├── core/               # 프레임워크 엔진
│   ├── flake.nix       # 메인 진입점
│   ├── lib/            # 빌더(builders.nix), 옵션 선언(workspace-options.nix)
│   └── scripts/        # nhw 관리 CLI (nhw.sh, nhw.resolve.py 등)
├── mods/               # 재사용 가능한 기능 모듈
│   ├── sys/            # 시스템 기반 (base, fonts, vfs, services, utils)
│   ├── gui/            # GUI 환경 (Hyprland 번들, apps, utils)
│   ├── devel/          # 개발 도구 (toolchains, jetbrains, android)
│   └── _preset/        # 구성 레시피 (workstation.toml 등)
├── hosts/              # 호스트별 고유 설정
│   ├── base.toml       # 전역 메타데이터 (username, git, system)
│   └── <hostname>/     # host.toml, configuration.nix, home.nix, _hardware.nix
└── .locks/             # Flake lock 파일 (Rolling/Stable 전략)
```

---

## 🛠️ 호스트 설정 방법

```toml
# hosts/<hostname>/host.toml 예시
type   = "desktop"
ramGb  = 32
preset = "workstation"

# 프리셋 기본값에서 변경할 항목만 기재
[mods.devel]
fvm = true
```

```nix
# hosts/<hostname>/configuration.nix 예시
{...}: {
  imports = [./_hardware.nix];

  # 호스트 하드웨어 설정
  boot.kernelParams = [ "..." ];
}
```

---

## 🚀 처음 사용자용 가이드 (Getting Started)

이 프로젝트는 **Btrfs 서브볼륨 구조**에 최적화되어 설계되었습니다. 처음 시스템을 구축하거나 설치하려면 [BOOTSTRAP.md](./.docs/readme/BOOTSTRAP.md) 가이드를 따라 전용 ISO를 빌드하고 설치하는 것을 권장합니다.

---

## 🛠️ 프로젝트 관리 (`nhw`)

시스템이 설치된 후에는 프로젝트 경로와 상관없이 터미널 어디서든 `nhw` 명령어를 사용할 수 있습니다. 구체적인 명령어 사용법과 활용 사례는 [NHW.md](./.docs/readme/NHW.md) 가이드를 참조하세요.

- **OS 설정 적용:** `nhw [host_id] os switch`
- **Home Manager 적용:** `nhw [host_id] home switch`
- **커스텀 ISO 빌드:** `nhw iso` (x86_64) / `nhw iso arm` (aarch64) — 결과물은 `.build/` 폴더에 생성됨
- **시스템 업데이트:** `nhw update`
- **깨진 패키지 복구:** `nhw fix-unstable [pkg1] [pkg2] ...`
- **무결성 및 스타일 점검:** `nhw check` (deadnix, 안티패턴 정리, 포맷팅, shellcheck, 빌드 검증)
- **시스템 정리:** `nhw clean [all]`

---

## 💡 주요 개념 및 고급 가이드

이 프로젝트의 내부 작동 방식(빌드 격리, 락 전략, Mods Framework 아키텍처 등)이 궁금하거나, 시스템을 깊게 커스텀하고 싶은 고급 사용자는 [HACKING.md](./.docs/hacking/_HACKING.md) 파일을 참조하세요.
