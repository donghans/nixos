# NixOS 모듈형 설정 프레임워크

TOML 선언 한 파일로 NixOS 호스트를 정의하고, 프리셋 한 줄로 전체 환경을 자동 구성하는 Flake 기반 프레임워크입니다.

---

## 문서 구조

이 문서는 [Diátaxis](https://diataxis.fr/) 분류 체계를 따릅니다.

### 튜토리얼

처음 이 프로젝트를 사용하는 분을 위한 단계별 안내입니다.

- **[첫 번째 NixOS 호스트 설정](./tutorials/first-install.md)** — Fork, Live USB 설치, 첫 변경 적용까지의 전 과정

### 작업 가이드

특정 작업을 수행하기 위한 절차별 문서입니다.

- **[시스템 관리](./how-to/manage-system.md)** — 상황별 nixup 활용 사례
- **[Mod 만들기](./how-to/create-mod.md)** — 7가지 실전 Cookbook, 추가/삭제 절차, Coverage Check 오류 대응

### 레퍼런스

명령어와 API를 조회하는 문서입니다.

- **[nixup 명령어](./reference/nixup-commands.md)** — 서브커맨드, 플래그, 로그 경로
- **[rnixup/rnixstrap 명령어](./reference/rnixup-commands.md)** — 원격 배포·설치 플래그, 비대화형 모드, `.strap.json` 형식
- **[nixsec 명령어](./reference/nixsec-commands.md)** — 시크릿 관리 CLI, 비대화형 업로드·주입
- **[Mod API](./reference/mod-api.md)** — `mkMod`/`mkModOf`/`mkPartOf`/`mkNamedMod` 시그니처 및 파라미터

### 이해하기

프레임워크의 작동 원리를 설명하는 심층 문서입니다.

- **[아키텍처와 설계 결정](./explanation/architecture.md)** — 4개 레이어 구조, 디렉터리 구성, 설계 선택의 이유
- **[내부 원리](./explanation/internals.md)** — Mods 스캐닝, enable 계층, 빌드 격리, 잠금 전략
- **[실행 라이프사이클](./explanation/lifecycle.md)** — nixup / nixstrap 단계별 실행 흐름
