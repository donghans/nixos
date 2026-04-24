## 명령어 상세

### 무결성 및 품질 관리 (`check`)

프로젝트 전체의 코드를 정돈하고 빌드 가능 여부를 사전에 검증합니다.

- `nixup check`: 아래 단계를 순서대로 수행합니다.
  1. `deadnix` — 미사용 코드 탐지
  2. `statix fix` — 안티패턴 자동 수정
  3. `alejandra` — 코드 포맷팅
  4. `shellcheck` — 셸 스크립트 정적 분석
  5. `nix flake check` — **전체 호스트**를 완전히 검사합니다. CI 수준의 완전한 검증을 제공합니다.
- `nixup check --fast`: 5단계를 `nix eval`로 교체하여 현재 호스트만 빠르게 검증합니다. 전체 검사 전 빠른 확인이 필요할 때 사용합니다.

### 전체 설정 적용 (기본값)

서브커맨드 없이 실행하면 NixOS 시스템과 Home Manager를 순서대로 적용합니다.

- `nixup`: os → home 순서로 모두 적용합니다. (가장 많이 사용)
- `nixup --try` / `-t`: 둘 다 임시 활성화합니다. (재부팅 시 원복)
- `nixup --build` / `-b`: 둘 다 빌드만 수행합니다.

### 시스템 설정 관리 (`os`)

NixOS 시스템 설정만 적용합니다. `os` 블록 변경사항만 있을 때 사용합니다.

:::note
`nixup os` 및 `nixup`(기본값)은 빌드 시작 전 `sudo -v`로 인증을 완료하고 백그라운드 keepalive 프로세스를 유지합니다. 빌드가 오래 걸려도 활성화 단계에서 sudo 타임아웃이 발생하지 않습니다.
:::

- `nixup os`: 시스템 설정을 즉시 적용하고 부팅 메뉴에 추가합니다.
- `nixup os --stage` / `-s`: 다음 부팅 시 적용되도록 설정만 합니다.
- `nixup os --try` / `-t`: 현재 세션에만 임시로 설정을 적용합니다. (재부팅 시 원복)
- `nixup os --build` / `-b`: 빌드만 수행하고 새 세대를 생성하지 않습니다.

### 사용자 설정 관리 (`home`)

Home Manager 설정만 적용합니다. `hm` 블록 변경사항만 있을 때 사용합니다.

- `nixup home`: 유저 도구, 테마, 앱 설정 등을 즉시 반영합니다.
- `nixup home --try` / `-t`: 홈 설정을 즉시 활성화합니다. (세대 등록 없음, 재부팅 시 원복)
- `nixup home --build` / `-b`: 홈 설정을 빌드만 수행합니다.

### 시스템 업데이트 및 관리

- `nixup update`: `flake.lock`의 모든 입력을 최신 버전으로 업데이트합니다. (Rolling 호스트는 `_rolling.lock` 업데이트)
- `nixup update <input>`: 특정 flake input만 업데이트합니다. (예: `nixup update nixpkgs`)
- `nixup clean [--all] [--keep=N]`: 오래된 세대를 정리하여 디스크 공간을 확보합니다.
  - 기본값: 사용자 홈 영역만, 최근 3세대 보존
  - `--all`: 시스템 프로필(sudo 필요) + 전체 GC 포함
  - `--keep=N`: 보존 세대 수 지정 (기본 3). `--all`과 함께 사용 가능. 예: `nixup clean --all --keep=5`

### 특수 기능

- `nixup iso`: `custom-iso` 타겟(x86_64)을 빌드하여 나만의 설치 미디어를 생성합니다.
- `nixup iso --arm`: `custom-iso-aarch64` 타겟(aarch64)을 빌드합니다.
- `nixup fix [pkg1] [pkg2]`: Unstable 채널에서 빌드 실패하는 특정 패키지를 이전 정상 시점으로 하향 조정(Fallback)합니다.
  - **중요**: 이 기능을 통해 고정된 패키지를 사용하려면 Nix 설정 파일(`*.nix`)에서 해당 패키지를 `unstable.<pkgName>` 대신 **`unstable-fallback.<pkgName>`**으로 참조해야 합니다.
  - 내부 동작 및 `.env` 파일 형식은 [내부 원리](../explanation/internals.md#지능형-패키지-복구-fallback-system) 참고
