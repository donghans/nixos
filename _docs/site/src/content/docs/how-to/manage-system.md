---
title: "nixup 활용 가이드"
---

`nixup`으로 일상적인 시스템 관리를 수행하는 상황별 가이드입니다.

> 전체 명령어 목록과 플래그 옵션은 [nixup 명령어 레퍼런스](../reference/nixup-commands) 참조

---

## 상황별 활용 사례

### 상황 A: 새로운 앱 설정을 테스트하고 싶을 때
시스템을 영구적으로 바꾸기 전에 설정이 올바른지 확인하고 싶을 때 사용합니다.
```bash
nixup os --try
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
