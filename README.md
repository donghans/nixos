# ❄️ NixOS Configuration (Flake-based)

이 저장소는 **Nix Flakes**와 **Home Manager**를 사용하여 여러 기기의 NixOS 환경과 사용자 설정을 코드 하나로 관리하는 프로젝트입니다. 모듈화된 설정을 통해 데스크탑, 노트북, 서버 등 다양한 환경을 일관되게 유지할 수 있습니다.

## 🚀 주요 특징

- **Modular Design:** 하드웨어(`hardware/`), 공통 라이브러리(`lib/`), 호스트별 설정(`dev/`)을 분리하여 재사용성이 높습니다.
- **Metadata-Driven:** `dev/_info.json` 파일 하나로 사용자 정보와 호스트 목록을 중앙 관리하며, 이를 `metaConfig`로 모든 모듈에 전달합니다.
- **NH (Nix Helper) 통합:** `nh` 도구를 활용하여 직관적인 시스템 업데이트 및 빌드 출력을 제공합니다.
- **Custom ISO 지원:** 나만의 NixOS 설치 이미지를 생성할 수 있는 전용 설정이 포함되어 있습니다.
- **Branch Strategy:** `stable`과 `rolling` 브랜치 전략을 통해 안정적인 배포와 실험적인 업데이트를 구분합니다.

---

## 📂 프로젝트 구조

```text
.
├── _flakes/          # Nix Flake 정의 (stable/rolling)
├── _iso/             # 커스텀 설치 ISO 빌드 설정
├── dev/              # 호스트 및 사용자별 구체적 설정
│   ├── _info.json    # 사용자/호스트 메타데이터 (가장 먼저 확인!)
│   ├── base/         # 기본 파일시스템 및 쉘 환경
│   └── hardware/     # CPU/GPU 등 기기별 하드웨어 최적화
├── lib/              # 공유 가능한 Nix 모듈 (Hyprland, UI 등)
├── scripts/          # 자동 업데이트 및 유지보수 스크립트
├── nhw.sh            # 시스템 관리를 위한 메인 래퍼 스크립트
└── iso.sh            # ISO 이미지 생성 스크립트
```

---

## 🛠️ 시작하기

### 1. 메타데이터 설정
`dev/_info.json` 파일을 열어 사용자 이름, Git 정보, 호스트 목록을 본인의 환경에 맞게 수정하세요. 이 정보는 시스템 전체의 사용자 계정과 설정에 반영됩니다.

```json
{
  "username": "사용자명",
  "git": { "name": "이름", "email": "이메일" },
  "hosts": [
    { "hostname": "my-host", "system": "x86_64-linux", "isLaptop": false }
  ]
}
```

### 2. 시스템 관리 (`nhw.sh`)
이 프로젝트는 `nhw.sh`라는 통합 관리 도구를 제공합니다.

#### **Home Manager 설정 반영 (기본값)**
```bash
# 현재 호스트의 Home Manager 설정을 switch 합니다.
./nhw.sh home switch
```

#### **NixOS 시스템 업데이트**
```bash
# 시스템 전체 설정을 업데이트하고 적용합니다.
./nhw.sh os switch [hostname]
```

#### **유용한 옵션**
- **호스트 지정:** `./nhw.sh [host_id] ...` (생략 시 `.current_host` 파일 참조)
- **작업 범위:** `os` (시스템) 또는 `home` (사용자 설정)
- **동작 방식:** `switch` (즉시 적용), `boot` (다음 부팅 시 적용), `test` (임시 적용)
- **가비지 컬렉션:** `./nhw.sh clean` 또는 `./nhw.sh clean all` (오래된 세대 삭제)

### 3. ISO 이미지 빌드
커스텀 NixOS 설치 미디어가 필요한 경우 다음 명령어를 실행하세요.
```bash
./iso.sh
```
결과물은 `result/iso/` 디렉토리에 생성됩니다.

---

## 📋 호스트 목록
현재 등록된 기기 목록 (`dev/_info.json` 기준):
- `beelink-ser7-co`: 메인 데스크탑 환경
- `msi-summit-me`: 비즈니스용 노트북 환경 (Laptop 특화 설정 포함)

---

## 💡 참고 사항
- **State Version:** 현재 시스템의 상태 버전은 `25.11`입니다.
- **Hyprland:** `lib/hyprland`를 통해 고도로 개인화된 Wayland 타일형 윈도우 매니저 환경을 제공합니다.
- **필수 도구:** 이 스크립트를 원활히 사용하려면 `nh`, `nix-output-monitor`, `jq`가 설치되어 있어야 합니다.
