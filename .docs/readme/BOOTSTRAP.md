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

## 4. 프리셋 (`mods/_preset/`)

`preset` 필드에 지정한 이름에 따라 기본 mods 활성화 여부가 결정됩니다.

| 프리셋 | 설명 | GUI | 개발 환경 | 서버 서비스 |
|--------|------|-----|-----------|------------|
| `workstation` | 데스크탑/랩탑 기본 (Hyprland + 개발 도구) | ✅ | ✅ | ❌ |
| `server` | 헤드리스 서버 (GUI 없음, 서버 서비스 중심) | ❌ | ❌ | ✅ |

### workstation 프리셋

GUI(Hyprland), 개발 도구(`mods.devel`), Bluetooth, Docker, Tailscale, NetworkManager가 기본 활성화됩니다. `stateVersion` 미지정 시 rolling 채널을 사용합니다.

### server 프리셋

GUI와 개발 도구는 비활성화됩니다. 다음 서비스가 기본 활성화됩니다:

| 서비스 | 설명 |
|--------|------|
| `networkmanager` | 네트워크 관리 |
| `tailscale` | VPN 메시 네트워크 |
| `incus` | LXC/VM 컨테이너 |
| `headscale` | Tailscale 컨트롤 서버 |
| `caddy` | 리버스 프록시 |
| `cockpit` | 웹 기반 서버 관리 UI |
| `frp` | Fast Reverse Proxy (내부망 노출) |

host.toml의 `[mods.sys.services]` 섹션에서 개별 서비스를 `false`로 비활성화하거나 추가 서비스를 켤 수 있습니다.

---

## 5. (선택) 설치 전 설정 검증


기기에 실제로 설치하기 전에 설정이 올바른지 빌드로 확인할 수 있습니다. nixup이 설치된 기존 NixOS 환경에서 실행하세요.

```bash
nixup os <hostname> --dry-run    # NixOS 시스템 설정 빌드 검증
nixup home <hostname> --dry-run  # Home Manager 설정 빌드 검증
nixup check                      # 포맷팅 + 린트 + eval 통합 검증
```

> **참고**: 이 명령들은 `nixup`이 설치된 환경(기존 NixOS 호스트)에서만 실행 가능합니다. 첫 설치 시에는 이 단계를 건너뛰어도 됩니다.

---

## 6. 설치

### 경로 A: 표준 NixOS Live USB (범용)

NixOS 공식 ISO를 USB에 구워 부팅한 뒤:

```bash
# git 하나만 임시로 가져와서 저장소 클론
nix-shell -p git --run "git clone https://github.com/<your-username>/nixos"

cd nixos
./bootstrap.sh install              # 완전 대화형 (nixstrap이 파티션 포함 안내)
./bootstrap.sh install myhostname   # 호스트명만 지정, 파티션은 nixstrap이 대화형으로 안내
```

`bootstrap.sh install`이 자동으로 처리하는 것:
- 누락된 도구(`python3`, `btrfs-progs`, `parted` 등)를 `nix-shell`로 확보
- `hosts/base.toml`에서 `nixosRepo` 값을 읽어 `NIXOS_REPO` 자동 설정
- 이후 `nixstrap`을 호출 — 파티션 선택, 저장소 클론, 하드웨어 감지, `nixos-install`까지 안내

`nixstrap` 주요 동작:
- **파티션 모드**: 기존 파티션 직접 지정(mode 1) 또는 전체 디스크·빈 공간 범위로 신규 생성(mode 2) 중 선택
- **params 저장/복원**: review 확인 후 설치 파라미터를 `/root/nixstrap-params.env`에 저장. 네트워크 오류 등으로 실패 후 재시도 시 이전 설정을 불러와 확인/수정 후 재개 가능

---

### 경로 B: 커스텀 ISO 빌드 (기존 NixOS 환경)

이미 NixOS가 설치된 기기에서 커스텀 ISO를 빌드하면, 부팅 직후 친숙한 Hyprland 환경과 설치 명령이 자동으로 안내됩니다.

```bash
./bootstrap.sh build-iso        # x86_64
./bootstrap.sh build-iso --arm  # aarch64
```

> nixup이 아직 설치되지 않아도 `nix-shell` 쉬뱅을 통해 필요한 도구를 자동으로 가져옵니다.

빌드 완료 후 `.build/` 폴더의 ISO 파일을 USB에 구워 부팅하면, kitty 터미널에 설치 안내가 자동으로 표시됩니다.
(터미널을 닫았거나 추가로 열어야 할 경우: `Super + P` → kitty 검색)

```bash
nixstrap myhostname   # 호스트명 지정
nixstrap              # 완전 대화형 (호스트명도 nixstrap이 물어봄)
```

`<hostname>`에 레포에 없는 새 이름을 지정하면, 설치 도중 프리셋(workstation/server)을 물어보고 `host.toml` · `configuration.nix` · `home.nix`를 자동 생성합니다. 하드웨어 프로필(`_hardware.nix`)은 기존과 동일하게 자동 감지됩니다.

다른 리포지토리에서 설치하거나 `NIXOS_REPO`를 직접 지정하려면:

```bash
NIXOS_REPO=user/repo sudo -E nixstrap myhostname
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

## 7. 다음으로 해볼 것 (Next Steps)

설치가 완료되고 재부팅하면 `nixup` 명령어를 통해 시스템을 관리할 수 있습니다.

- **시스템 관리 익히기**: [NIXUP.md](./NIXUP.md)
- **개발 환경 구성**: `host.toml`의 `[mods.devel]` 섹션에 도구를 활성화하고 `nixup home`
- **심화 구조 이해**: [HACKING.md](../hacking/_HACKING.md)
