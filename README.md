# NixOS 모듈형 설정 프레임워크

TOML 선언 한 파일로 NixOS 호스트를 정의하고, 프리셋 한 줄로 전체 환경을 자동 구성하는 Flake 기반 프레임워크입니다.

---

## 빠른 시작

### 1. 저장소 준비

```bash
# Fork 후 클론
git clone https://github.com/<your-username>/nixos.git
cd nixos
```

### 2. 전역 설정 (자동 초기화)

`./nixstrap.sh` 실행 시 git remote origin에서 설정을 **자동으로 감지·갱신**합니다:

- `git.nixosRepo` · `git.name` · `git.email` — GitHub에서 자동 채우기
- `username` — 대화형 입력

필요하면 `hosts/_base.toml`을 실행 전에 직접 편집할 수도 있습니다.

### 3. 설치

```bash
# 표준 NixOS Live USB에서:
./nixstrap.sh

# 또는 커스텀 ISO(Hyprland GUI 포함)를 빌드하여 설치:
./nixup-iso.sh
```

`nixstrap`이 호스트 선택, 파티셔닝, `nixos-install`까지 대화형으로 안내합니다.

설치 완료 후 재부팅하면 TTY(Ctrl+Alt+F2)에서 아래 명령을 실행하세요:

```bash
nixup home   # 사용자 환경 최초 적용
```

상세 가이드: [시스템 이식 가이드](https://donghans.github.io/nixos/tutorials/first-install/)

---

## 호스트 설정 예시

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
| [시스템 이식 가이드](https://donghans.github.io/nixos/tutorials/first-install/) | 처음 설치 | Fork, 설정, 설치 전 과정 |
| [시스템 관리](https://donghans.github.io/nixos/how-to/manage-system/) | 일상 관리 | 상황별 nixup 활용 사례 |
| [Mod 만들기](https://donghans.github.io/nixos/how-to/create-mod/) | 기능 확장 | Cookbook, 추가/삭제 절차 |
| [nixup 명령어](https://donghans.github.io/nixos/reference/nixup-commands/) | 레퍼런스 | 서브커맨드, 플래그, 로그 경로 |
| [Mod API](https://donghans.github.io/nixos/reference/mod-api/) | 레퍼런스 | mkMod/mkModOf/mkPartOf 시그니처 |
| [아키텍처 · 내부 구조](https://donghans.github.io/nixos/explanation/overview/) | 심층 이해 | 4개 레이어, 메커니즘, 라이프사이클 |

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
