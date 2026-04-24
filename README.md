# NixOS 모듈형 설정 프레임워크

TOML 선언 한 파일로 NixOS 호스트를 정의하고, 프리셋 한 줄로 전체 환경을 자동 구성하는 Flake 기반 프레임워크입니다.

---

## 빠른 시작

### 1. 저장소 Fork하기

GitHub에서 이 저장소를 본인 계정으로 **Fork**합니다.

> 이 프레임워크 코드와 여러분의 기기 설정이 같은 저장소에 공존합니다. Fork해야 upstream 업데이트와 내 설정을 분리해서 관리할 수 있습니다.

```bash
git clone https://github.com/<your-username>/nixos.git
cd nixos
```

### 2. 설치

NixOS 공식 Live USB로 부팅한 뒤:

```bash
./nixstrap.sh
```

`nixstrap`이 호스트 이름, 프리셋, 파티셔닝, `nixos-install`까지 대화형으로 안내합니다. `hosts/_base.toml`의 username · git 정보는 GitHub API로 자동 채워집니다.

설치 완료 후 재부팅하면 TTY(Ctrl+Alt+F2)에서:

```bash
nixup home   # 사용자 환경 최초 적용 (dotfiles, 앱 등)
```

> 설치 중에는 시스템 환경(`os`)만 구성됩니다. 사용자 환경(`hm`)은 재부팅 후 이 명령으로 적용합니다.

---

## 이렇게 씁니다

```toml
# hosts/<hostname>.toml
type   = "desktop"
preset = "workstation"     # GUI + 개발도구 + 서비스 자동 구성

# 프리셋 기본값에서 변경할 항목만 기재
[mods.devel]
fvm = true                 # Flutter 추가 활성화
```

프리셋이 Hyprland, Docker, Tailscale, Bluetooth, 개발 도구 등을 한꺼번에 설정합니다.
호스트별로 다른 부분만 몇 줄 추가하면 됩니다.

---

## 문서

> 전체 문서는 사이드바와 검색을 지원하는 [**문서 사이트**](https://donghans.github.io/nixos/)에서 볼 수 있습니다.

| 문서 | 대상 | 내용 |
|------|------|------|
| [첫 번째 NixOS 호스트 설정](https://donghans.github.io/nixos/tutorials/first-install/) | 처음 설치 | Fork, Live USB 설치, 첫 변경 적용 |
| [시스템 관리](https://donghans.github.io/nixos/how-to/manage-system/) | 일상 관리 | 상황별 nixup 활용 사례 |
| [Mod 만들기](https://donghans.github.io/nixos/how-to/create-mod/) | 기능 확장 | Cookbook, 추가/삭제 절차 |
| [nixup 명령어](https://donghans.github.io/nixos/reference/nixup-commands/) | 레퍼런스 | 서브커맨드, 플래그, 로그 경로 |
| [Mod API](https://donghans.github.io/nixos/reference/mod-api/) | 레퍼런스 | mkMod/mkModOf/mkPartOf 시그니처 |
| [아키텍처 · 내부 원리](https://donghans.github.io/nixos/explanation/architecture/) | 심층 이해 | 레이어 구조, 설계 결정, 메커니즘, 라이프사이클 |

---

<details>
<summary><strong>프로젝트 구조</strong></summary>

```
nixos/
├── core/               # 프레임워크 엔진
│   ├── flake.nix       # 메인 진입점
│   ├── lib/            # 호스트 빌더(host.nix), Mods 헬퍼(mods.nix), 옵션 선언(workspace-options.nix)
│   ├── overlays/       # 커스텀 오버레이 (mkWrapper 헬퍼)
│   └── scripts/        # nixup · nixstrap · rnixup · rnixstrap CLI
├── mods/               # 재사용 가능한 기능 모듈
│   ├── sys/            # 시스템 기반 (base, fonts, vfs, services, utils)
│   ├── gui/            # GUI 환경 (Hyprland 번들, apps, utils)
│   ├── devel/          # 개발 도구 (base, toolchains, apps)
│   └── _data/          # 비-Nix 데이터 파일 (zsh 스크립트, CSS, XML 등)
├── hosts/              # 호스트별 고유 설정 (평탄 구조)
│   ├── _base.toml      # 전역 메타데이터 (username, git, system)
│   ├── _preset.*.toml  # 프리셋 정의 (workstation/server/iso)
│   ├── <hostname>.toml # 호스트 메타데이터 (type, preset, mods 오버라이드)
│   ├── <hostname>.nix  # 호스트 전용 NixOS + Home Manager 설정
│   └── deploy/         # 원격 호스트 전용 (pub 키, hardware.nix)
├── .locks/             # Flake lock 파일 (Rolling/Stable 전략)
├── _docs/              # 문서 인프라
│   ├── content/        # Markdown 소스 (Diátaxis 구조)
│   └── site/           # Starlight 사이트 생성기
└── _plan/              # 개발 계획 문서 (빌드 비포함)
```

</details>
