# NixOS 모듈형 설정 프레임워크

TOML 선언 한 파일로 NixOS 호스트를 정의하고, 프리셋 한 줄로 전체 환경을 자동 구성하는 Flake 기반 프레임워크입니다.

---

## 문서 구조

이 문서는 세 계층으로 구성되어 있습니다.

### 시작하기

처음 이 프로젝트를 사용하는 분을 위한 일회성 가이드입니다.

- **[시스템 이식 가이드](./readme/BOOTSTRAP.md)** — Fork, 전역 설정, `nixstrap` 설치까지의 전 과정

### 사용 가이드

설치 이후 반복적으로 참조하는 레퍼런스입니다.

- **[nixup 명령어](./manual/NIXUP.md)** — 시스템 관리 CLI의 서브커맨드, 플래그, 활용 사례
- **[Mods 확장 가이드](./manual/MODS.md)** — `mkMod`/`mkModOf`/`mkPartOf` API 레퍼런스, 7가지 실전 예시, 추가/삭제 절차

### 내부 구조

프레임워크의 작동 원리를 이해하고 싶은 고급 사용자를 위한 심층 문서입니다.

- **[개요](./hacking/_HACKING.md)** — 4개 핵심 레이어 요약 및 문서 인덱스
- **[프로젝트 아키텍처](./hacking/ARCHITECTURE.md)** — CLI Engine, Metadata, Logic Core, Mods Layer
  - **[Mods 프레임워크](./hacking/ARCHITECTURE-MODS.md)** — 모듈 스캐닝, enable 계층, autoWrap, Dual-Context
- **[핵심 메커니즘](./hacking/MECHANISMS.md)** — 빌드 격리, 락 전략, 패키지 복구
- **[nixup 라이프사이클](./hacking/LIFECYCLE_NIXUP.md)** — 명령어 입력부터 시스템 적용까지의 4단계 흐름
- **[nixstrap 라이프사이클](./hacking/LIFECYCLE_NIXSTRAP.md)** — 신규 기기 부트스트랩 설치 흐름
