# `nixup` 사용 가이드

`nixup`은 `nix` 커맨드를 베이스로 빌드 격리, 자동 로깅, 패키지 복구 로직 등을 추가한 통합 관리 도구입니다. 이 문서에서는 구체적인 명령어 사용법과 다양한 활용 사례를 설명합니다.

---

## 1. 기본 명령어 구조

```bash
nixup [subcommand] [flags]
```

- **`subcommand`**: 작업 종류 (`os`, `home`, `iso`, `fix`, `check`, `update`, `clean`)
  - 생략 시 `os` (시스템 설정 적용)가 기본값입니다.
- **`flags`**: 동작 제어 옵션 (`--activate`, `--next-boot`, `--dry-run` 등)

> **대상 호스트 결정**: `.env`의 `NIXUP_LAST_HOST` 값을 우선 사용합니다. 없으면 OS 호스트명(`hostname -s`)으로 자동 감지합니다. switch/`--activate`/`--next-boot` 실행 후에는 해당 호스트가 `.env`에 자동으로 저장됩니다.

---

## 2. 주요 명령어 상세

### 무결성 및 품질 관리 (`check`)
프로젝트 전체의 코드를 정돈하고 빌드 가능 여부를 사전에 검증합니다.
- `nixup check`: 아래 단계를 순서대로 수행합니다.
  1. `deadnix` — 미사용 코드 탐지
  2. `statix fix` — 안티패턴 자동 수정
  3. `alejandra` — 코드 포맷팅
  4. `shellcheck` — 셸 스크립트 정적 분석
  5. `nix eval` — 현재 호스트에 대해 빌드 가능 여부를 빠르게 검증
- `nixup check --deep`: 5단계를 `nix flake check`로 교체하여 **전체 호스트**를 완전히 검사합니다. 시간이 오래 걸리지만 CI 수준의 완전한 검증을 제공합니다.
- **참고**: `nixup check`는 `.env`의 `NIXUP_LAST_HOST`를 갱신하지 않습니다. 호스트 기록은 switch/`--activate`/`--next-boot` 시에만 이루어집니다.

### 시스템 설정 관리 (`os`)
기존 `nixos-rebuild`를 대체하며, 빌드 격리 환경에서 안전하게 수행됩니다.
- `nixup [os]`: 설정을 즉시 적용하고 부팅 메뉴에 추가합니다. (가장 많이 사용)
- `nixup os --next-boot` / `-n`: 다음 부팅 시 적용되도록 설정만 합니다.
- `nixup os --activate` / `-t`: 현재 세션에만 임시로 설정을 적용합니다. (재부팅 시 원복)
- `nixup os --dry-run` / `-d`: 빌드만 수행하고 새 세대를 생성하지 않습니다. 빌드 캐시 워밍업 또는 설정 오류 사전 확인에 유용합니다.

### 사용자 설정 관리 (`home`)
Home Manager 설정을 적용합니다.
- `nixup home`: 유저 도구, 테마, 앱 설정 등을 즉시 반영합니다.
- `nixup home --activate` / `-t`: 홈 설정을 dry-run 모드로 미리 확인합니다.
- `nixup home --dry-run` / `-d`: 홈 설정을 빌드만 수행합니다. (`os --dry-run`과 동일한 목적)

### 시스템 업데이트 및 관리
- `nixup update`: `flake.lock`의 모든 입력을 최신 버전으로 업데이트합니다. (Rolling 호스트는 `_rolling.lock` 업데이트)
- `nixup clean [--all] [--keep=N]`: 오래된 세대를 정리하여 디스크 공간을 확보합니다.
  - 기본값: 사용자 홈 영역만, 최근 3세대 보존
  - `--all`: 시스템 프로필(sudo 필요) + 전체 GC 포함
  - `--keep=N`: 보존 세대 수 지정 (기본 3). `--all`과 함께 사용 가능. 예: `nixup clean --all --keep=5`

### 특수 기능
- `nixup iso`: `custom-iso` 타겟(x86_64)을 빌드하여 나만의 설치 미디어를 생성합니다.
- `nixup iso --arm`: `custom-iso-aarch64` 타겟(aarch64)을 빌드합니다.
- `nixup fix [pkg1] [pkg2]`: Unstable 채널에서 빌드 실패하는 특정 패키지를 이전 정상 시점으로 하향 조정(Fallback)합니다.
  - **중요**: 이 기능을 통해 고정된 패키지를 사용하려면 Nix 설정 파일(`*.nix`)에서 해당 패키지를 `unstable.<pkgName>` 대신 **`unstable-fallback.<pkgName>`**으로 참조해야 합니다.
  - 내부 동작 및 `.env` 파일 형식은 [핵심 메커니즘 문서](../hacking/MECHANISMS.md#3-지능형-패키지-복구-fallback-system)를 참고하세요.

---

## 3. 상황별 활용 사례 (Use Cases)

### 상황 A: 새로운 앱 설정을 테스트하고 싶을 때
시스템을 영구적으로 바꾸기 전에 설정이 올바른지 확인하고 싶을 때 사용합니다.
```bash
nixup os --activate
```
- 결과가 만족스러우면 `nixup os`로 영구 적용합니다.

### 상황 B: Unstable 채널에서 패키지 빌드 오류가 날 때
최신 버전의 패키지가 깨져서 전체 시스템 빌드가 실패하는 상황입니다.
```bash
nixup fix python311Packages.tensorflow
# 이후 설정 파일(*.nix) 상단 파라미터에 unstable-fallback을 추가하고 패키지 참조를 변경합니다:
# { pkgs, unstable, unstable-fallback, ... }: {
#   environment.systemPackages = [ unstable-fallback.python311Packages.tensorflow ]; # 시스템 패키지
#   home.packages = [ unstable-fallback.some-package ];                             # 홈 매니저 패키지
# }
nixup os
```
- 내부적으로 TensorFlow의 이전 정상 커밋을 찾아 고정(Pin)하므로, 나머지 시스템은 최신 상태를 유지하면서 문제만 해결할 수 있습니다.

### 상황 C: 디스크 용량이 부족할 때
NixOS는 빌드 시마다 이전 버전을 보관하므로 주기적인 정리가 필요합니다.
```bash
nixup clean --all
```
- 최근 3개 버전을 제외한 모든 오래된 기록을 삭제하여 기가바이트 단위의 용량을 확보합니다.
- 더 많이 남기려면: `nixup clean --all --keep=5`

---

## 4. 로그 확인 (Logging)

모든 `nixup` 실행 결과는 `/var/log/nixup/`에 자동으로 기록됩니다.
- 파일명 형식: `YYYYMMDDTHHMMSS.log` (예: `20260405T120000.log`)
- 빌드 실패 시에만 `YYYYMMDDTHHMMSS.nom-build.log`가 추가로 생성됩니다. 성공 시에는 자동으로 삭제됩니다.
- 터미널에는 nom 색상 출력이 표시되지만, 저장된 로그 파일은 ANSI 색상 코드가 제거된 순수 텍스트로 저장됩니다.
- 로그는 최근 30개까지 자동으로 보관됩니다.

```bash
# 최근 로그 확인
tail -f /var/log/nixup/$(ls -t /var/log/nixup/*.log | head -n 1)

# 빌드 실패 시 빌드 로그 확인
cat /var/log/nixup/*.nom-build.log
```
