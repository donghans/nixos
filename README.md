# NixOS 모듈형 설정 프로젝트 (Flake 기반)

이 프로젝트는 **Nix Flakes**와 **Home Manager**를 사용하여 여러 대의 NixOS 호스트 설정을 효율적으로 관리하고, 나만의 커스텀 설치 미디어(ISO)를 생성하기 위한 환경입니다.

## 🚀 주요 특징

- **모듈형 설계**: 하드웨어 설정, 시스템 공통 설정, 사용자별 설정을 분리하여 코드 재사용성을 높였습니다.
- **격리된 빌드 환경**: 모든 빌드는 `/tmp/nixos-build` (tmpfs)에서 안전하게 격리되어 수행되므로, 작업 도중 오류가 발생하더라도 사용자의 Git 트리를 더럽히지 않습니다.
- **시스템 통합 도구 (`nhw`)**: `nh`(nix-helper)를 기반으로 한 전역 명령어 `nhw`를 통해 시스템 업데이트, 전환, ISO 빌드, 패키지 복구 등 모든 작업을 어디서든 수행할 수 있습니다.
- **전문적인 인터페이스**: 정렬된 로그 포맷과 실행 마커(`Exec > / <`)를 통해 작업 단계를 직관적으로 추적하며, 모든 실행 결과는 `/var/log/nhw/`에 자동으로 기록됩니다.
- **유연한 락(Lock) 관리**: `isRolling=true` 기기들은 `_rolling.lock`을 공유하며, Stable 기기들은 개별 `<hostname>.lock`으로 안정성을 유지합니다.

## 📂 프로젝트 구조

- `core/`: 시스템 빌드의 핵심 진입점(`flake.nix`) 및 관련 스크립트들이 통합된 디렉터리입니다.
  - `scripts/`: 시스템 관리 도구 `nhw`의 핵심 로직과 ISO 설치 스크립트(`iso.setup.sh`)가 위치합니다.
- `dev/`: 호스트별 개별 설정과 사용자 정보 및 리포지토리 메타데이터(`_info.json`)가 담겨 있습니다.
- `lib/`: 모든 호스트가 공유하는 공통 모듈(Hyprland, 시스템 기본값 등)이 정의되어 있습니다.
- `.locks/`: 시스템 안정성을 보장하는 락 파일들(`_rolling.lock`, `<hostname>.lock`)을 관리합니다.
- `.build/`: 빌드 시 생성되는 임시 심볼릭 링크로, 완료된 ISO 파일 등을 쉽게 확인할 수 있습니다.

## 🛠️ 시작하기

### 사전 요구 사항

- NixOS가 설치되어 있어야 하며, `flakes`와 `nix-command` 기능이 활성화되어 있어야 합니다.
- `nh`, `jq`, `nix-output-monitor` 패키지가 필요합니다. (첫 빌드 성공 시 `nhw` 명령어가 자동 등록됩니다.)

### 호스트 및 사용자 설정 (`dev/_info.json`)

리포지토리 정보와 호스트 목록을 본인의 환경에 맞게 수정하세요.
```json
{
  "username": "사용자명",
  "git": {
    "name": "이름",
    "email": "이메일",
    "nixosRepo": "유저명/리포지토리"
  },
  "hosts": [
    { "hostname": "호스트명", "system": "x86_64-linux", "isLaptop": true, "isRolling": true }
  ]
}
```

### 기본 사용법 (`nhw`)

이제 프로젝트 경로와 상관없이 터미널 어디서든 `nhw` 명령어를 사용할 수 있습니다.

- **OS 설정 적용:** `nhw [host_id] os switch`
- **Home Manager 적용:** `nhw [host_id] home switch`
- **커스텀 ISO 빌드:** `nhw iso` (결과물은 `.build/` 폴더에 생성됨)
- **시스템 업데이트:** `nhw update`
- **깨진 패키지 복구:** `nhw fix-unstable [pkg1] [pkg2] ...`
- **시스템 정리:** `nhw clean [all]`

## 💡 주요 개념

### 전역 명령어 nhw 및 로깅
`nhw`는 실행 시마다 `/var/log/nhw/YYYYMMDDTHHMMSS.log` 형식으로 로그를 남깁니다. 로그 디렉터리 권한이 없는 경우 자동으로 복구 프롬프트를 띄워 설정을 도와줍니다. 최근 30개의 로그만 유지되도록 자동으로 정리됩니다.

### 실행 마커 (Execution Markers)
외부 명령어 실행 시 `Exec nh >` (시작) 및 `Exec nh <` (종료) 마커가 표시되어 로그 상에서 실행 구간을 명확히 구분할 수 있습니다.

### 커스텀 인스톨러 (ISO)
빌드된 ISO는 부팅 시 한글 환영 메시지와 `nixos-setup` 가이드를 제공합니다. `_info.json`에 정의된 `nixosRepo` 정보를 자동으로 참조하여 사용자만의 환경을 즉시 구축할 수 있습니다.
