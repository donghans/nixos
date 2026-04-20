# 🛠️ 고급 사용자용 기술 가이드 (HACKING)

이 프로젝트는 단순히 설정을 모아놓은 것이 아니라, 자동화된 빌드 및 배포 워크플로우를 갖춘 하나의 **프레임워크**입니다. 내부 구조를 깊게 탐색하고 싶은 분석가들을 위한 가이드입니다.

---

## 🏗️ 1. 프로젝트 아키텍처 (Architecture)
프로젝트를 구성하는 4개의 핵심 레이어에 대한 상세 분석입니다.
👉 [**ARCHITECTURE.md 자세히 보기**](./ARCHITECTURE.md) · [📊 다이어그램](./ARCHITECTURE.mermaid)

- **CLI Engine**: `nixup.sh`와 태스크 스크립트 구조 (Update, Fix, Check 등).
- **Metadata**: JSON 기반의 데이터 중심 설계.
- **Logic Core**: Flake 기반 동적 호스트 생성.
- **Modules**: 공통 라이브러리 및 베이스 설정.

---

## 🔄 2. 실행 라이프사이클 (Lifecycle)

### nixup
명령어 입력부터 시스템 적용까지의 단계별 프로세스입니다.
👉 [**LIFECYCLE_NIXUP.md 자세히 보기**](./LIFECYCLE_NIXUP.md) · [📊 다이어그램](./LIFECYCLE_NIXUP.mermaid)

- **Orchestration**: 입력 분석, TOML resolve, 소스 물리 복사 및 `path:` 모드 격리 환경 구축.
- **Evaluation**: Flake 평가, 패키지 세트 구성, overlay 적용.
- **Expansion**: 호스트 구성 로드·상속, 모듈 믹스인 및 커버리지 검증.
- **Application**: 빌드·액션 분기, NVD diff, 로그 기록.

### nixstrap
신규 기기 부트스트랩 설치 흐름입니다.
👉 [**LIFECYCLE_NIXSTRAP.md 자세히 보기**](./LIFECYCLE_NIXSTRAP.md) · [📊 다이어그램](./LIFECYCLE_NIXSTRAP.mermaid)

- **Phase 1 — 레포 · 호스트**: 레포 클론 또는 로컬 경로 사용, 호스트 선택·프리셋·릴리즈 고정.
- **Phase 1 — 파티셔닝**: 기존 파티션 지정(mode 1) 또는 디스크·범위 선택 후 자동 생성(mode 2).
- **Phase 1 — 검토 · 저장**: 설정 검토, params 저장, 비밀번호 입력(메모리에만 보관).
- **Phase 2 — 디스크 준비**: cleanup → labels → 파티션 생성 → 포맷 → 마운트.
- **Phase 2 — 설치 환경 구성**: 레포 이동, 호스트 프로파일, resolve, build-dir, hw-config.
- **Phase 2 — 설치 · 후처리**: nixos-install, post_process (chown · symlink · chpasswd).

---

## 📦 3. Mods 등록 · 삭제 가이드
새 기능 추가/삭제 절차와 Coverage Check 오류 대응입니다.
👉 [**MODS.md 자세히 보기**](./MODS.md)

- **추가**: `.nix` 파일 생성 → `mkMod`/`mkModOf`/`mkPartOf` 패턴 선택 → 프리셋 TOML 등록 → `nixup check`
- **삭제**: `.nix` 파일 삭제 → 프리셋 TOML에서 항목 제거 → `nixup check`
- **Coverage Check 오류**: 오류 메시지가 누락 경로와 해결 방법을 안내합니다.

---

## 💡 4. 핵심 메커니즘 (Mechanisms)
이 프로젝트만의 독창적인 기술적 강점과 구현 원리입니다.
👉 [**MECHANISMS.md 자세히 보기**](./MECHANISMS.md)

- **Build Isolation**: 작업 환경 오염 방지 전략.
- **Lock Strategy**: Rolling vs Stable 하이브리드 관리.
- **Fallback System**: Unstable 채널의 깨진 패키지 자동 복구 로직.

---

## 📂 5. 디렉토리 구조 요약

```text
/
├── core/                    # Flake 진입점(flake.nix), 빌더(lib/), 엔진 스크립트(scripts/)
│   ├── lib/                 # builders.nix, mods-lib.nix, workspace-options.nix, mk-wrapper.nix, mk-preset.nix
│   ├── scripts/             # nixup 관리 CLI, nixstrap 설치 스크립트
│   ├── iso.nix              # ISO 전용 NixOS 설정 (Firefox 네트워크 패치, 진단 도구 등)
│   ├── iso.home.nix         # ISO 전용 Home Manager 설정 (spice-vdagent, 클립보드 브릿지 등)
│   └── iso.nixstrap.nix     # ISO에 nixstrap 인스톨러 주입 로직
├── hosts/                   # 호스트별 설정 (평탄 구조)
│   ├── _base.toml           # 전역 설정 원본 (username, git, system)
│   ├── _preset.workstation.toml  # 워크스테이션 프리셋 mods 정의
│   ├── _preset.server.toml  # 서버 프리셋 mods 정의
│   ├── _preset.iso.toml     # ISO 프리셋 mods 정의
│   ├── <hostname>.toml      # 호스트 메타데이터 (type, preset, mods 오버라이드)
│   └── <hostname>.nix       # 호스트 전용 NixOS + Home Manager 설정 (mkHostConfiguration 패턴)
├── mods/                    # Mods 프레임워크 (3개 도메인)
│   ├── sys/                 # 시스템 기반 (base, fonts, vfs, services, utils)
│   ├── gui/                 # GUI 환경 (base 번들, apps, utils)
│   ├── devel/               # 개발 도구 (toolchains, jetbrains, apps)
│   └── _data/               # 비-Nix 데이터 파일 (zsh 스크립트, waybar CSS, incus XML/PS1, devbox 설정 등)
├── .docs/                   # 문서 저장소 (readme, plan, hacking)
└── .locks/                  # 시스템 안정성을 위한 락 파일 관리
```

이 설계를 바탕으로 본인만의 강력한 NixOS 환경을 구축해 보세요!
