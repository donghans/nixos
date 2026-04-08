# 🚀 처음 사용자용 부트스트랩 (ISO 기반)

이 프로젝트는 **Btrfs 서브볼륨 구조(`@`, `@home`, `@nix`, `@log`)**에 최적화되어 설계되었습니다. 따라서 기존 시스템에서 단순히 설정을 전환하는 것보다, **전용 설치 ISO**를 통해 정해진 구조대로 시스템을 구축하는 것이 가장 안전하고 권장되는 방법입니다.

---

## 1. 저장소 준비 (Fork & Clone)

이 프로젝트는 본인의 GitHub 계정으로 **Fork**하여 관리하는 것을 전제로 합니다.

```bash
# 본인의 저장소로 클론 (유저명을 본인 것으로 수정하세요)
git clone https://github.com/<your-username>/nixos.git
cd nixos
```

---

## 2. 전역 메타데이터 수정 (`hosts/base.toml`)

저장소 전체에 공통으로 적용되는 사용자 정보를 선언합니다.

```toml
# hosts/base.toml
username = "your_username"   # 생성할 유저명
system   = "x86_64-linux"    # 현재 x86_64 시스템만 테스트됨

[git]
name      = "Your Name"
email     = "your@email.com"
nixosRepo = "<your-username>/nixos"  # 설치 시 클론할 저장소 경로
```

---

## 3. 새로운 호스트 정의

설치할 기기에 맞는 설정 폴더를 준비합니다.

### 3-1. 호스트 메타데이터 (`hosts/<hostname>/host.toml`)

```toml
# hosts/<hostname>/host.toml
isLaptop = false   # 랩탑이면 true (배터리 표시, 터치패드 등 자동 적용)
ramGb    = 16      # 물리 메모리 크기(GB) — 스왑·tmpfs 크기 자동 계산에 사용
preset   = "workstation"

# 프리셋 기본값에서 변경할 mods만 기재합니다.
[mods.devel]
fvm = true
```

### 3-2. 호스트별 설정 파일

```bash
mkdir -p hosts/<hostname>
```

기존 호스트(`hosts/beelink-ser7-co/`, `hosts/msi-summit-me/`)의 `configuration.nix`와 `home.nix`를 참고하여 하드웨어 부팅 파라미터, 서비스 등 호스트 고유 설정을 작성합니다. 하드웨어 프로필(`_hardware.nix`)은 설치 시 자동으로 생성됩니다.

---

## 4. 나만의 설치 ISO 빌드 및 설치

`nhw` CLI로 커스텀 ISO를 빌드합니다.

```bash
nhw iso
```

빌드가 완료되면 `.build/` 심볼릭 링크가 가리키는 디렉터리에 ISO 파일이 생성됩니다. 이 ISO로 부팅하면 터미널에 안내 메시지가 나타납니다.

안내에 따라 아래 명령어를 실행하면 설치가 자동으로 진행됩니다:

```bash
# 기본 설치 (EFI 파티션, 루트 파티션, 호스트명 지정)
nixos-setup <EFI_PART> <ROOT_PART> <HOSTNAME>

# 예시 (nvme0n1 기기)
nixos-setup /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co

# 다른 저장소로 설치할 경우
NIXOS_REPO=user/nixos sudo -E nixos-setup-from-repo <EFI_PART> <ROOT_PART> <HOSTNAME>
```

설치 스크립트가 순서대로 수행하는 작업:
1. **EFI 파티션 포맷**: FAT32 포맷 여부를 확인 후 진행합니다.
2. **Btrfs 파티셔닝**: `@`, `@home`, `@nix`, `@log` 서브볼륨 자동 생성 및 최적 옵션 마운트.
3. **저장소 클론**: `hosts/base.toml`의 `nixosRepo`에 설정된 GitHub 저장소를 `/mnt/etc/nixos`에 클론합니다.
4. **하드웨어 감지**: `nixos-generate-config`를 실행하여 해당 기기의 하드웨어 설정을 `hosts/<hostname>/_hardware.nix` 경로에 자동으로 저장합니다.
5. **시스템 빌드**: `nixos-install --flake "/mnt/etc/nixos/core#<hostname>"`으로 시스템을 빌드하고 설치합니다.
6. **후처리**: 저장소를 `~/nixos`로 이동하고 `/etc/nixos`에서 심볼릭 링크를 생성합니다.

설치가 완료되고 재부팅하면, 전역 명령어 `nhw`를 통해 시스템을 관리할 수 있습니다.

---

## 5. 다음으로 해볼 것 (Next Steps)

시스템 설치를 성공적으로 마치셨나요? 이제 본인만의 환경으로 커스터마이징할 차례입니다.

- **시스템 관리 익히기**: `nhw` 도구의 상세한 사용법과 업데이트, 청소 방법 등은 [NHW.md](./NHW.md) 가이드를 참조하세요.
- **개발 환경 구성**: `mods/devel/` 하위 파일을 수정하여 본인에게 필요한 개발 도구를 추가할 수 있습니다.
  - `host.toml`의 `[mods.devel]` 섹션에 `toolchain = true` 형식으로 활성화합니다.
  - 수정 후에는 `nhw home switch` 명령으로 즉시 반영할 수 있습니다.
- **심화 구조 이해**: 이 프로젝트의 빌드 격리, 락 전략 등 기술적 내부 구조가 궁금하다면 [HACKING.md](../hacking/_HACKING.md) 문서를 탐독해 보세요.
