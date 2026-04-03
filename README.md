# NixOS 모듈형 설정 프로젝트 (Flake 기반)

이 프로젝트는 **Nix Flakes**와 **Home Manager**를 사용하여 여러 대의 NixOS 호스트 설정을 효율적으로 관리하고, 나만의 커스텀 설치 미디어(ISO)를 생성하기 위한 환경입니다.

## 🚀 주요 특징

- **모듈형 설계**: 하드웨어 설정, 시스템 공통 설정, 사용자별 설정을 분리하여 코드 재사용성을 높였습니다.
- **메타데이터 기반 관리**: `dev/_info.json` 파일 하나로 사용자 정보와 호스트 목록을 중앙 집중식으로 관리합니다.
- **강력한 헬퍼 스크립트**: `nh`(nix-helper)를 래핑한 `nhw.sh`를 통해 복잡한 Nix 명령어를 외울 필요 없이 간편하게 시스템을 업데이트하고 전환할 수 있습니다.
- **커스텀 ISO 생성**: 현재 설정의 핵심을 담은 나만의 NixOS 설치 이미지를 빌드하는 워크플로우를 제공합니다.
- **최신성 유지**: Stable(25.11) 채널을 기본으로 하되, 필요한 경우 Unstable 채널의 패키지를 혼합하여 사용할 수 있도록 구성되었습니다.

## 📂 프로젝트 구조

- `_flakes/`: 시스템 빌드의 핵심인 `flake.nix`가 위치합니다. (빌드 시 필요한 파일들이 이곳으로 링크됩니다.)
- `dev/`: 호스트별 개별 설정과 사용자 정보(`_info.json`)가 담겨 있습니다.
- `lib/`: 모든 호스트가 공유하는 공통 모듈(Hyprland, 시스템 기본값 등)이 정의되어 있습니다.
- `_iso/`: 커스텀 설치용 ISO 빌드를 위한 설정 파일들입니다.
- `.locks/`: 시스템의 안정성을 보장하는 `flake.lock` 파일들을 호스트별/상태별로 관리합니다.
- `nhw.sh`: 시스템 및 Home Manager 설정을 관리하는 메인 스크립트입니다.
- `iso.sh`: 커스텀 ISO 빌드용 스크립트입니다.

## 🛠️ 시작하기

### 사전 요구 사항

- NixOS가 설치되어 있어야 하며, `flakes`와 `nix-command` 기능이 활성화되어 있어야 합니다.
- `nh`, `jq`, `nix-output-monitor` 패키지가 설치되어 있어야 합니다.

### 호스트 및 사용자 설정

`dev/_info.json` 파일을 수정하여 본인의 환경에 맞게 변경하세요.
```json
{
  "username": "사용자명",
  "git": { "name": "이름", "email": "이메일" },
  "hosts": [
    { "hostname": "호스트명", "system": "x86_64-linux", "isLaptop": true, "isRolling": true }
  ]
}
```

### 기본 사용법 (`nhw.sh`)

스크립트를 실행할 때 호스트 ID를 지정하지 않으면 현재 시스템의 호스트명을 자동으로 감지합니다.

- **OS 설정 적용 (Switch):**
  ```bash
  ./nhw.sh [host_id] os switch
  ```
- **Home Manager 설정 적용 (사용자 환경):**
  ```bash
  ./nhw.sh [host_id] home switch
  ```
- **시스템 업데이트 (Flake Update):**
  ```bash
  ./nhw.sh update
  ```
- **불필요한 세대 삭제 (Garbage Collection):**
  ```bash
  ./nhw.sh clean [all]
  ```

### 커스텀 ISO 빌드

현재 프로젝트의 설정을 기반으로 부팅 가능한 ISO 파일을 생성합니다.
```bash
./iso.sh
```
빌드가 완료되면 `result/iso/` 디렉토리에 `.iso` 파일이 생성됩니다.

## 💡 주요 개념

### metaConfig
`flake.nix`는 `_info.json`의 내용을 읽어 `metaConfig`라는 이름으로 모든 모듈에 전달합니다. 이를 통해 호스트명, 사용자명, 노트북 여부 등을 코드 내에서 변수로 활용할 수 있습니다.

### 빌드 환경 구성
`nhw.sh`는 실행 시 `dev/`, `lib/`, `.env` 파일을 `_flakes/` 디렉토리 내부로 심볼릭 링크하거나 복사하여 Nix 빌드 환경을 동적으로 구성합니다. 이는 설정을 깔끔하게 유지하면서도 Flake의 엄격한 경로 규칙을 준수하기 위함입니다.
