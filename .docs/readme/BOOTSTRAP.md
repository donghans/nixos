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
username = "your_username"
system   = "x86_64-linux"    # ARM 호스트는 host.toml에서 system = "aarch64-linux"로 오버라이드

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
ramGb  = 16
preset = "workstation"

# 프리셋 기본값에서 변경할 항목만 기재합니다.
[mods.devel]
fvm = true
```

기존 호스트(`hosts/beelink-ser7-co/`, `hosts/msi-summit-me/`)의 `configuration.nix`와 `home.nix`를 참고하여 하드웨어 부팅 파라미터 등을 작성합니다. 하드웨어 프로필(`_hardware.nix`)은 설치 시 자동 생성됩니다.

---

## 4. (선택) 설치 전 설정 검증

기기에 실제로 설치하기 전에 설정이 올바른지 빌드로 확인할 수 있습니다.

```bash
nhw <hostname> os build
```

**VM으로 런타임 동작 확인:**
```bash
nh os build-vm
# 또는
nix build .#nixosConfigurations.<hostname>.config.system.build.vm
./result/bin/run-*-vm
```

> **참고**: VM은 패키지 구성·서비스 동작 등 config 레벨 검증에 활용합니다. Btrfs 서브볼륨 구조(`@`, `@home`)는 VM 디스크(qcow2)와 무관하며, 실제 디스크 설정은 설치 스크립트가 처리합니다.

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

빌드 완료 후 `.build/` 폴더의 ISO 파일을 USB에 구워 부팅하면, kitty 터미널에 설치 안내가 자동으로 표시됩니다:

```bash
nixos-setup /dev/nvme0n1p1 /dev/nvme0n1p2 myhostname
```

---

## 6. 다음으로 해볼 것 (Next Steps)

설치가 완료되고 재부팅하면 `nhw` 명령어를 통해 시스템을 관리할 수 있습니다.

- **시스템 관리 익히기**: [NHW.md](./NHW.md)
- **개발 환경 구성**: `host.toml`의 `[mods.devel]` 섹션에 도구를 활성화하고 `nhw home switch`
- **심화 구조 이해**: [HACKING.md](../hacking/_HACKING.md)
