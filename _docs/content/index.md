# NixOS 모듈형 설정 프레임워크

TOML 선언 한 파일로 NixOS 호스트를 정의하고, 프리셋 한 줄로 전체 환경을 자동 구성하는 Flake 기반 프레임워크입니다.

---

## 문서 구조

이 문서는 [Diátaxis](https://diataxis.fr/) 분류 체계를 따릅니다.

### 튜토리얼

처음 이 프로젝트를 사용하는 분을 위한 단계별 안내입니다.

- **[시스템 이식 가이드](./tutorials/first-install.md)** — Fork, 전역 설정, `nixstrap` 설치까지의 전 과정

### 작업 가이드

특정 작업을 수행하기 위한 절차별 문서입니다.

- **[시스템 관리](./how-to/manage-system.md)** — 상황별 nixup 활용 사례
- **[Mod 만들기](./how-to/create-mod.md)** — 7가지 실전 Cookbook, 추가/삭제 절차, Coverage Check 오류 대응

### 레퍼런스

명령어와 API를 조회하는 문서입니다.

- **[nixup 명령어](./reference/nixup-commands.md)** — 서브커맨드, 플래그, 로그 경로
- **[Mod API](./reference/mod-api.md)** — `mkMod`/`mkModOf`/`mkPartOf`/`mkNamedMod` 시그니처 및 파라미터

### 이해하기

프레임워크의 작동 원리를 설명하는 심층 문서입니다.

- **[개요](./explanation/overview.md)** — 4개 핵심 레이어 요약 및 문서 인덱스
- **[아키텍처](./explanation/architecture.md)** — CLI Engine, Metadata, Logic Core, Mods Layer
  - **[Mods 내부 원리](./explanation/mods-internals.md)** — 모듈 스캐닝, enable 계층, autoWrap, Dual-Context
- **[핵심 메커니즘](./explanation/mechanisms.md)** — 빌드 격리, 락 전략, 패키지 복구
- **[nixup 라이프사이클](./explanation/lifecycle-nixup.md)** — 명령어 입력부터 시스템 적용까지의 4단계 흐름
- **[nixstrap 라이프사이클](./explanation/lifecycle-nixstrap.md)** — 신규 기기 부트스트랩 설치 흐름
