# 수정하지 않기로 한 항목

코드 품질 점검 과정에서 "어색해 보이지만 의도적"으로 판단하여 수정하지 않기로 결정한 항목들.

| 항목 | 현재 상태 | 수정하지 않는 이유 |
|---|---|---|
| `gui/core/home.nix` `builtins.fetchTarball` | Hyprland 0.52.1 버그픽스용 별도 nixpkgs 고정 | unstable이 rolling으로 계속 업데이트되므로, 새 버전에 버그가 있을 경우를 대비해 의도적으로 특정 버전에 고정 |
| `gui/core/home/_ux.nix` `float, class:.*` | 모든 창을 기본 플로팅으로 설정 | 타일링 대신 플로팅이 기본인 워크플로 설계. 의도적 선택 |
| `gui/utils/custom-notify-logger-module.nix` dbus 파싱 | `grep`/`sed`로 dbus-monitor 출력 파싱 | 실용적으로 동작함. 완전한 재작성은 별도 프로젝트 수준의 작업 |
| `gui/apps/vivaldi.nix` 복잡한 override | `override` + `overrideAttrs` 중첩, JSON 설정 직접 주입 | Nix에서 브라우저 커스터마이징의 불가피한 복잡도 |
