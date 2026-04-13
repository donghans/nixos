# 🚀 시스템 이식 가이드 (Bootstrap)

이 프로젝트는 **Btrfs 서브볼륨 구조(`@`, `@home`, `@nix`, `@log`)**에 최적화되어 설계되었습니다. `bootstrap.sh` 하나로 설치 전 과정이 자동화됩니다.

---

## 1. 저장소 준비 (Fork & Clone)

이 프로젝트는 본인의 GitHub 계정으로 **Fork**하여 관리하는 것을 전제로 합니다.

```bash
git clone https://github.com/<your-username>/nixos.git
cd nixos
```

---

## 2. 전역 메타데이터 수정 (`hosts/base.toml`)

```toml
# hosts/base.toml
username            = "your_username"
system              = "x86_64-linux"    # ARM 호스트는 host.toml에서 system = "aarch64-linux"로 오버라이드
rollingStateVersion = "25.11"           # stateVersion 미지정 호스트의 폴백 버전 (채널 업그레이드 시 여기만 수정)
diskDevice          = "/dev/disk/by-label/nixos"  # Btrfs 루트 파티션 장치 경로
bootDevice          = "/dev/disk/by-label/boot"   # EFI 파티션 장치 경로 (host.toml에서 오버라이드 가능)

[git]
name      = "Your Name"
email     = "your@email.com"
nixosRepo = "<your-username>/nixos"  # 설치 스크립트가 클론할 저장소 경로
```

---

## 3. 새로운 호스트 정의

### 호스트 메타데이터 (`hosts/<hostname>/host.toml`)

```toml
type   = "desktop"    # desktop, laptop, server, rpi
preset = "workstation"

# 프리셋 기본값에서 변경할 항목만 기재합니다.
[mods.devel]
fvm = true

# ramGb는 /proc/meminfo에서 자동 감지됩니다 (host.toml 입력 불가).
# swap/tmpfs/zram은 ramGb를 기반으로 자동 계산되며, 필요 시 아래에서 오버라이드 가능합니다.
# swapGb      = 24    # swap 파일 크기 (GB). 기본: ceil(ramGb × 0.75)
# tmpfsSize   = "100%" # /tmp tmpfs 상한. 기본: "100%"
# zramPercent = 50    # ZRAM 풀 크기 (물리 RAM의 %). 기본: 50

# 파티션 경로 (기본값은 base.toml 참조, 기기마다 다를 경우에만 기재)
# bootDevice = "/dev/disk/by-label/ESP"          # 레이블이 다른 경우
# bootDevice = "/dev/disk/by-uuid/XXXX-XXXX"     # 기존 파티션을 UUID로 참조하는 경우
# diskDevice = "/dev/disk/by-label/custom-label" # Btrfs 레이블이 다른 경우
```

기존 호스트(`hosts/beelink-ser7-co/`, `hosts/msi-summit-me/`)의 `configuration.nix`와 `home.nix`를 참고하여 하드웨어 부팅 파라미터 등을 작성합니다. 하드웨어 프로필(`_hardware.nix`)은 설치 시 자동 생성됩니다.

---

## 4. (선택) 설치 전 설정 검증

기기에 실제로 설치하기 전에 설정이 올바른지 빌드로 확인할 수 있습니다. nhw가 설치된 기존 NixOS 환경에서 실행하세요.

```bash
nhw <hostname> os build    # NixOS 시스템 설정 빌드 검증
nhw <hostname> home build  # Home Manager 설정 빌드 검증
nhw check                  # 포맷팅 + 린트 + eval 통합 검증
```

> **참고**: 이 명령들은 `nhw`가 설치된 환경(기존 NixOS 호스트)에서만 실행 가능합니다. 첫 설치 시에는 이 단계를 건너뛰어도 됩니다.

---

## 5. 설치

### 경로 A: 표준 NixOS Live USB (범용)

NixOS 공식 ISO를 USB에 구워 부팅한 뒤:

```bash
# git 하나만 임시로 가져와서 저장소 클론
nix-shell -p git --run "git clone https://github.com/<your-username>/nixos"

cd nixos
./bootstrap.sh install                                          # 대화형 (파티션 입력 안내)
./bootstrap.sh install /dev/nvme0n1p1 /dev/nvme0n1p2 myhostname  # 또는 직접 지정
```

`bootstrap.sh install`이 자동으로 처리하는 것:
- 누락된 도구(`python3`, `btrfs-progs` 등)를 `nix-shell`로 확보
- `hosts/base.toml`에서 `nixosRepo` 값을 읽어 `NIXOS_REPO` 자동 설정
- 파티션 정보 누락 시 `lsblk` 출력 후 대화형 입력
- Btrfs 서브볼륨 구조 생성 → 저장소 클론 → 하드웨어 감지 → `nixos-install`

---

### 경로 B: 커스텀 ISO 빌드 (기존 NixOS 환경)

이미 NixOS가 설치된 기기에서 커스텀 ISO를 빌드하면, 부팅 직후 친숙한 Hyprland 환경과 설치 명령이 자동으로 안내됩니다.

```bash
./bootstrap.sh build-iso        # x86_64
./bootstrap.sh build-iso --arm  # aarch64
```

> nhw가 아직 설치되지 않아도 `nix-shell` 쉬뱅을 통해 필요한 도구를 자동으로 가져옵니다.

빌드 완료 후 `.build/` 폴더의 ISO 파일을 USB에 구워 부팅하면, kitty 터미널에 설치 안내가 자동으로 표시됩니다.
(터미널을 닫았거나 추가로 열어야 할 경우: `Super + P` → kitty 검색)

```bash
nixos-setup /dev/nvme0n1p1 /dev/nvme0n1p2 myhostname
```

> **기본 단축키 (Hyprland)**
>
> | 단축키 | 동작 |
> |--------|------|
> | `Super + P` | 앱 런처 (fuzzel) — kitty 등 앱 실행 |
> | `Super + Q` | 현재 창 닫기 |
> | `Super + F` | 플로팅 모드 토글 |
> | `Super + L` | 화면 잠금 (hyprlock) |
> | `Super + 1~0` | 워크스페이스 1~10 이동 |
> | `Super + Shift + Q` | Hyprland 종료 (로그인 화면으로 이동) |
> | `Super + 마우스 좌클릭 드래그` | 창 이동 |
> | `Super + 마우스 우클릭 드래그` | 창 크기 조절 |
>
> `Super`는 키보드의 Windows/Command 키입니다. 전체 단축키는 `mods/gui/core/home/_bind.nix`를 참고하세요.

---

## 6. 다음으로 해볼 것 (Next Steps)

설치가 완료되고 재부팅하면 `nhw` 명령어를 통해 시스템을 관리할 수 있습니다.

- **시스템 관리 익히기**: [NHW.md](./NHW.md)
- **개발 환경 구성**: `host.toml`의 `[mods.devel]` 섹션에 도구를 활성화하고 `nhw home switch`
- **심화 구조 이해**: [HACKING.md](../hacking/_HACKING.md)
