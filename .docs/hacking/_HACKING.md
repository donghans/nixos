# 🛠️ 고급 사용자용 기술 가이드 (HACKING)

이 프로젝트는 단순히 설정을 모아놓은 것이 아니라, 자동화된 빌드 및 배포 워크플로우를 갖춘 하나의 **프레임워크**입니다. 내부 구조를 깊게 탐색하고 싶은 분석가들을 위한 가이드입니다.

---

## 🏗️ 1. 프로젝트 아키텍처 (Architecture)
프로젝트를 구성하는 4개의 핵심 레이어에 대한 상세 분석입니다.
👉 [**ARCHITECTURE.md 자세히 보기**](./ARCHITECTURE.md)

- **CLI Engine**: `nixup.sh`와 태스크 스크립트 구조 (Update, Fix, Check 등).
- **Metadata**: JSON 기반의 데이터 중심 설계.
- **Logic Core**: Flake 기반 동적 호스트 생성.
- **Modules**: 공통 라이브러리 및 베이스 설정.

---

## 🔄 2. 실행 라이프사이클 (Lifecycle)
명령어 입력부터 시스템 적용까지의 단계별 프로세스입니다.
👉 [**LIFECYCLE.md 자세히 보기**](./LIFECYCLE.md)

- **Orchestration**: 소스 물리 복사 및 `path:` 모드 격리 환경 구축.
- **Evaluation**: Flake 평가 및 패키지 구성.
- **Expansion**: 모듈 상속 및 믹스인 과정.
- **Application**: 최종 빌드 및 시스템 전환.

---

## 💡 3. 핵심 메커니즘 (Mechanisms)
이 프로젝트만의 독창적인 기술적 강점과 구현 원리입니다.
👉 [**MECHANISMS.md 자세히 보기**](./MECHANISMS.md)

- **Build Isolation**: 작업 환경 오염 방지 전략.
- **Lock Strategy**: Rolling vs Stable 하이브리드 관리.
- **Fallback System**: Unstable 채널의 깨진 패키지 자동 복구 로직.

---

## 📂 4. 디렉토리 구조 요약

```text
/
├── core/             # Flake 진입점(flake.nix), 빌더(lib/), 엔진 스크립트(scripts/)
│   └── lib/          # builders.nix, workspace-options.nix, mk-wrapper.nix, mk-preset.nix
├── hosts/            # 호스트별 설정(폴더 단위), 하드웨어 프로필, 전역 메타데이터
│   ├── base.toml     # 전역 설정 원본 (username, git, system)
│   └── <hostname>/   # host.toml, configuration.nix, home.nix, _hardware.nix
├── mods/             # Mods 프레임워크 (4개 레이어)
│   ├── sys/          # 시스템 기반 (base, fonts, vfs, services, utils)
│   ├── gui/          # GUI 환경 (core 번들, apps, utils)
│   ├── devel/        # 개발 도구 (toolchains, jetbrains, apps)
│   ├── _preset/      # 구성 레시피 (workstation.toml 등)
│   └── _data/        # 정적 데이터 (devbox 템플릿 등)
├── .docs/            # 문서 저장소 (readme, plan, hacking)
└── .locks/           # 시스템 안정성을 위한 락 파일 관리
```

이 설계를 바탕으로 본인만의 강력한 NixOS 환경을 구축해 보세요!
