# 🏛️ Directory Structure (Final Target)

리팩터링 후의 최종 디렉토리 구조는 다음과 같습니다. 모든 설정은 논리적 역할에 따라 엄격히 분리됩니다.

```text
/home/donghans/nixos/
├── core/               # 프레임워크 엔진 (NixOS 빌더, 스크립트, 핵심 라이브러리)
│   ├── lib/            # 빌더 로직 (builders.nix), 래퍼 유틸리티 (mk-wrapper.nix)
│   ├── scripts/        # 관리 CLI (nhw.sh 및 관련 서브태스크)
│   └── flake.nix       # 메인 엔트리포인트 (inputs & outputs 정의)
├── mods/               # 재사용 가능한 부품 (System, GUI, Devel)
│   ├── sys/            # 시스템 인프라 (base, vfs, fonts, services, utils)
│   ├── gui/            # 사용자 인터페이스 (bundle, apps, utils)
│   ├── devel/          # 개발 도구 (toolchains, jetbrains, data)
│   ├── _preset/        # 완성된 구성 레시피 (workstation, server 등)
│   └── _data/          # 설정용 정적 파일 (devbox.json, fvm.json 등)
├── hosts/              # 호스트별 고유 설정 (기존 dev/ 디렉토리)
│   ├── _info.json      # 전역 호스트 메타데이터 (Single Source of Truth)
│   ├── .template/      # 새 호스트 추가를 위한 템플릿
│   └── <hostname>/     # 각 기기별 configuration.nix, home.nix, _hardware.nix
└── .locks/             # Flake lock 파일 관리 (Rolling/Stable 전략)
```

### 주요 변경 사항
*   **`lib/` → `core/lib/` & `mods/`**: 기존의 루트 `lib/`는 엔진 성격의 코드는 `core/lib/`로, 설정 성격의 코드는 `mods/` 하위의 도메인별 모듈로 해체 및 이동합니다.
*   **`dev/` → `hosts/`**: 호스트 전용 설정임을 명확히 하기 위해 이름을 변경합니다.
*   **`_data/` 신설**: 설정 파일 내부에 하드코딩되거나 흩어져 있던 JSON 데이터들을 한곳으로 모아 관리합니다.
