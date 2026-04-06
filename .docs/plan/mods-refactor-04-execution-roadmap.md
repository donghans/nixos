# 🚀 Execution Roadmap

1.  **Phase 1: Engine Preparation**: `lib/` → `core/lib/` 통합 및 `builders.nix` 옵션 주입 로직 개발.
2.  **Phase 2: Asset Migration**: `devbox/*.json` 등 데이터 파일을 `mods/_data/`로 이동.
3.  **Phase 3: Mods Migration**: 기존 설정을 `mods/` 하위로 해체 및 컨텍스트 인식 로직(mkIf) 적용.
4.  **Phase 4: Host Renaming**: `dev/` → `hosts/` 변경 및 `nhw.sh` 경로 전수 수정.
5.  **Phase 5: Preset Implementation**: 각 호스트 성격에 맞는 `_preset/` 파일 생성 및 `hosts/` 설정 간소화.
