# 🛠️ `nhw` (NixOS Helper Wrapper) 사용 가이드

`nhw`는 [nh](https://github.com/viperML/nh)를 기반으로 빌드 격리, 자동 로깅, 패키지 복구 로직 등을 추가한 통합 관리 도구입니다. 이 문서에서는 구체적인 명령어 사용법과 다양한 활용 사례를 설명합니다.

---

## 📋 1. 기본 명령어 구조

```bash
nhw [scope] [action] [hostname]
```

- **`scope`**: 작업 범위 (`os`, `home`, `iso`, `fix-unstable`)
- **`action`**: 수행할 동작 (`switch`, `boot`, `test`, `update`)
- **`hostname`**: 대상 기기 이름 (생략 시 현재 기기 혹은 기본값 사용)

---

## ⚙️ 2. 주요 명령어 상세

### 시스템 설정 관리 (`os`)
기존 `nixos-rebuild`를 대체하며, 빌드 격리 환경에서 안전하게 수행됩니다.
- `nhw os switch`: 설정을 즉시 적용하고 부팅 메뉴에 추가합니다. (가장 많이 사용)
- `nhw os boot`: 다음 부팅 시 적용되도록 설정만 합니다.
- `nhw os test`: 현재 세션에만 임시로 설정을 적용합니다. (테스트용)

### 사용자 설정 관리 (`home`)
Home Manager 설정을 적용합니다.
- `nhw home switch`: 유저 도구, 테마, 앱 설정 등을 즉시 반영합니다.

### 시스템 업데이트 및 관리
- `nhw update`: `flake.lock`의 모든 입력을 최신 버전으로 업데이트합니다. (Rolling 호스트는 `_rolling.lock` 업데이트)
- `nhw clean`: 오래된 세대를 정리하여 디스크 공간을 확보합니다. (`--keep 3` 설정 적용)
- `nhw clean all`: 시스템 전체(Sudo 권한 포함)의 오래된 세대를 정리합니다.

### 특수 기능
- `nhw iso`: `custom-iso` 타겟을 빌드하여 나만의 설치 미디어를 생성합니다.
- `nhw fix-unstable [pkg1] [pkg2]`: Unstable 채널에서 빌드 실패하는 특정 패키지를 이전 정상 시점으로 하향 조정(Fallback)합니다.

---

## 💡 3. 상황별 활용 사례 (Use Cases)

### 상황 A: 새로운 앱 설정을 테스트하고 싶을 때
시스템을 영구적으로 바꾸기 전에 설정이 올바른지 확인하고 싶을 때 사용합니다.
```bash
nhw os test
```
- 결과가 만족스러우면 `nhw os switch`로 영구 적용합니다.

### 상황 B: Unstable 채널에서 패키지 빌드 오류가 날 때
최신 버전의 패키지가 깨져서 전체 시스템 빌드가 실패하는 상황입니다.
```bash
nhw fix-unstable python311Packages.tensorflow
nhw os switch
```
- 내부적으로 TensorFlow의 이전 정상 커밋을 찾아 고정(Pin)하므로, 나머지 시스템은 최신 상태를 유지하면서 문제만 해결할 수 있습니다.

### 상황 C: 여러 대의 기기를 관리할 때
현재 사용 중인 기기가 아닌 다른 기기의 설정을 미리 빌드해보고 싶을 때 사용합니다.
```bash
nhw beelink-ser7-co os switch
```
- `_info.json`에 등록된 호스트명을 지정하여 원격으로 관리하거나 설정을 검증할 수 있습니다.

### 상황 D: 디스크 용량이 부족할 때
NixOS는 빌드 시마다 이전 버전을 보관하므로 주기적인 정리가 필요합니다.
```bash
nhw clean all
```
- 최근 3개 버전을 제외한 모든 오래된 기록을 삭제하여 기가바이트 단위의 용량을 확보합니다.

---

## 📂 4. 로그 확인 (Logging)

모든 `nhw` 실행 결과는 `/var/log/nhw/`에 자동으로 기록됩니다.
- 파일명 형식: `YYYYMMDDTHHMMSS.log`
- 터미널에는 색상이 표시되지만, 저장된 로그 파일은 텍스트 검색이 용이하도록 ANSI 색상 코드가 제거된 순수 텍스트로 저장됩니다.

문제가 발생했을 때 로그 파일의 마지막 부분을 확인하세요.
```bash
tail -f /var/log/nhw/$(ls -t /var/log/nhw/ | head -n 1)
```
