# 시스템 관리

`nixup`으로 일상적인 시스템 관리를 수행하는 상황별 가이드입니다.

> 전체 명령어 목록과 플래그 옵션은 [nixup 명령어 레퍼런스](../reference/nixup-commands.md) 참조

---

## 설정 변경 적용하기

### 시스템 패키지 또는 서비스 설정을 변경했을 때

```bash
nixup os
```

### 홈 환경 설정(dotfiles, 사용자 패키지)을 변경했을 때

```bash
nixup home
```

### 두 블록을 동시에 변경했을 때

```bash
nixup os
nixup home
```

두 명령은 독립적으로 동작합니다. 순서는 상관없습니다.

---

## 변경 전 미리 보기

### 설정이 빌드되는지만 확인하고 싶을 때 (적용 없이)

```bash
nixup os --build
nixup home --build
```

### 적용은 하되 부팅 기본값으로 등록하지 않고 싶을 때

```bash
nixup os --try
```

결과가 만족스러우면 `nixup os`로 영구 적용합니다. 재부팅하면 이전 설정으로 돌아갑니다.

### 포맷, 린트, eval을 한 번에 확인하고 싶을 때

```bash
nixup check
```

커밋 전 또는 CI에서 유용합니다.

---

## 패키지 업데이트

### 전체 패키지를 최신으로 업데이트하고 싶을 때

```bash
nixup update
nixup os
```

`nixup update`가 lock 파일을 갱신합니다. 이후 `nixup os`로 실제 빌드합니다.

### 특정 input만 업데이트하고 싶을 때

```bash
nixup update nixpkgs
nixup update home-manager
```

---

## 깨진 패키지 대응 (unstable 채널)

### Unstable 패키지 빌드가 실패할 때

최신 nixpkgs-unstable의 특정 패키지가 깨진 경우:

```bash
nixup fix <패키지 이름>
```

예:

```bash
nixup fix python311Packages.tensorflow
```

:::note
내부적으로 GitHub API를 통해 해당 패키지의 커밋 히스토리를 역추적하여 마지막으로 빌드가 성공했던 커밋을 찾고 `.env`에 기록합니다. 나머지 시스템은 최신 상태를 유지하면서 문제 있는 패키지만 이전 버전으로 내립니다.
:::

이후 해당 패키지를 사용하는 Mod 파일에서 패키지 소스를 `unstable-fallback`으로 바꿉니다:

```nix
{ pkgs, unstable, unstable-fallback, ... }: {
  environment.systemPackages = [
    unstable-fallback.python311Packages.tensorflow  # 고정된 이전 버전
    unstable.some-other-package                     # 최신 유지
  ];
}
```

```bash
nixup os
```

### Fallback이 필요 없어졌을 때

패키지가 upstream에서 수정된 후:

```bash
nixup update nixpkgs-unstable
```

`.env`에서 `NIX_UNSTABLE_FALLBACK_REV`와 `NIX_UNSTABLE_FALLBACK_SHA` 줄을 삭제합니다. Mod 파일의 `unstable-fallback` 참조를 `unstable`로 되돌립니다.

---

## 디스크 관리

### NixOS 이전 세대를 정리하고 싶을 때

```bash
nixup clean
```

기본적으로 최근 3개 세대를 제외하고 삭제합니다.

### 더 적게 남기거나 많이 남기고 싶을 때

```bash
nixup clean --keep=1   # 현재 세대만 남김
nixup clean --keep=5   # 최근 5개 세대 유지
```

### /nix/store 가비지 컬렉션까지 함께 실행하고 싶을 때

:::caution
시스템 프로파일과 전체 nix store를 정리합니다. sudo 권한이 필요합니다.
:::

```bash
nixup clean --all
```

---

## 원격 호스트 배포 (rnixup)

### 원격 서버에 변경 사항을 배포할 때

```bash
rnixup
```

dry-activate 미리보기를 먼저 보여준 뒤 확인을 요청합니다.

### 등록된 원격 호스트 목록을 확인할 때

```bash
rnixup list
```

---

## 새 호스트 추가

### 로컬 기기를 새로 설치할 때

Live USB로 부팅 후:

```bash
./nixstrap.sh
```

자세한 내용은 [시스템 이식 가이드](../tutorials/first-install.md)를 참조하세요.

### 원격 서버를 새로 설치할 때

기존 NixOS 환경에서:

```bash
rnixstrap
```

서버 IP, SSH 키, 서비스 구성을 대화형으로 입력하면 nixos-anywhere로 원격 설치됩니다. 완료 후 일상 배포는 `rnixup`을 사용합니다.

---

--8<-- "_fragments/nixup-log-paths.md"
