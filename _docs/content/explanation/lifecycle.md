# 실행 라이프사이클

`nixup`, `nixstrap`, `rnixstrap` 각 명령의 실행 흐름을 단계별로 설명합니다.

> 시스템 내부 구조(Mods 스캐닝, enable 계층, 빌드 격리 등)는 [내부 원리](./internals.md) 참조  
> 레이어 구조와 설계 결정 배경은 [아키텍처](./architecture.md) 참조

---

## nixup 라이프사이클

`nixup` 명령어가 입력된 시점부터 시스템에 설정이 반영되기까지의 구체적인 내부 흐름입니다.

```mermaid
--8<-- "_fragments/diagrams/lifecycle-nixup.mermaid"
```

### 1. Orchestration Phase (준비 및 격리)

사용자의 작업 환경을 보호하고 빌드 일관성을 확보하는 단계입니다.

1. **Input Parsing**: 사용자의 명령(예: `nixup os`, `nixup home --build`)을 해석하고 대상 호스트가 롤링 채널을 사용하는지 여부를 확인합니다.
2. **Resolve**: `nixup.task-resolve.py`가 `hosts/_base.toml`, `hosts/<hostname>.toml`, `hosts/_preset.*.toml`을 읽어 `presets.json`(프리셋 mods + explicitOptional)과 `resolved.json`(호스트별 merged 데이터)을 생성합니다.
3. **Build Isolation**: 레포 내 `.build/` 디렉터리에 소스 파일을 물리 복사합니다. nix는 `path:` 모드로 호출되어 git 추적 여부를 확인하지 않고 해당 디렉터리를 store에 직접 복사하여 순수(pure) 평가를 수행합니다.
4. **Lock Injection**: 대상 기기의 특성에 맞는 락 파일(`.locks/_rolling.lock` 또는 `<hostname>.lock`)을 `.build/flake.lock`으로 주입합니다.

### 2. Evaluation Phase (평가 및 선언)

Nix 언어가 코드를 읽어 최종 시스템 명세(Derivation)를 도출하는 단계입니다.

1. **Metadata Parsing**: `flake.nix`가 `resolved.json`과 `presets.json`을 읽어 모든 호스트 설정을 AttrSet으로 생성합니다. `resolved.json`의 `deploy` 섹션 유무로 `isRemote` 여부를 판단하며, `bootLoader`(enum: `systemd-boot` · `grub-bios` · `grub-uefi`)가 부트 방식을 결정합니다.
2. **Package Set Construction**: `nixpkgs`, `unstable`, 그리고 `.env`에 명시된 `unstable-fallback`을 조합하여 기기에 최적화된 패키지 세트를 구성합니다.
3. **Overlay Application**: `mkWrapper`(범용 래핑 헬퍼)와 `mods/` 하위에서 자동 탐색된 `*.overlay.nix` 파일들이 이 단계에서 적용됩니다.

### 3. Expansion Phase (모듈 확장)

호스트 설정을 구성하는 수많은 파일이 하나로 합쳐지는 단계입니다.

1. **Host Specific Loading**: `hosts/<hostname>.nix`가 먼저 로드됩니다. 프리셋 mods는 flake.nix가 `resolved.json`과 `presets.json`을 병합하여 `modsModule`로 주입합니다.
2. **Inheritance**: 기기별 하드웨어 설정(`hardware.nix`)이 `.build/` 환경에서 임포트됩니다. 원격 호스트(`isRemote=true`)는 `hosts/deploy/<hostname>.hardware.nix`를 우선 탐색합니다.
3. **Mix-in**: `core/lib/mods.nix`의 `recursiveImportDir`이 `mods/` 하위를 재귀 탐색하여 sys, gui, devel 세 도메인을 모두 로드합니다.
4. **Coverage Check**: flake.nix가 주입한 `coverageModule`의 `assertions`가 평가됩니다. 누락 옵션 또는 형제 완전성 위반 감지 시 즉시 오류를 발생시킵니다.

### 4. Application Phase (최종 적용)

빌드된 명세를 실제 시스템에 반영하는 마지막 단계입니다.

0. **Sudo Pre-auth**: `nixup os` / `nixup`(기본값) 실행 시 빌드 전 `sudo -v`로 인증을 완료하고 백그라운드 keepalive 프로세스를 유지합니다.
1. **Build Monitor**: **`nom --json`** 필터 모드로 빌드 진행 상황을 시각화합니다.
2. **Switching**: **`nix-env -p /nix/var/nix/profiles/system --set`**으로 새 세대를 등록하고, **`switch-to-configuration`**으로 서비스·심볼릭 링크를 활성화합니다. `test` 액션은 세대 등록 없이 즉시 활성화, `build` 액션은 빌드만 수행합니다.
3. **NVD Diff**: 빌드 전/후 store path를 비교하여 실제로 변경된 경우에만 **`nvd diff`**로 패키지 변경 내역을 출력합니다.
4. **Logging & Sync**: 모든 과정은 `YYYYMMDDTHHMMSS.log`에 기록됩니다.

---

## nixstrap / rnixstrap 라이프사이클

**nixstrap**: 새 로컬 기기에 NixOS를 처음 설치할 때 사용합니다. `./nixstrap.sh`로 진입합니다.

**rnixstrap**: 원격 서버에 nixos-anywhere로 초기 설치하는 도구입니다. `rnixstrap` 명령으로 진입합니다.

```mermaid
--8<-- "_fragments/diagrams/lifecycle-nixstrap.mermaid"
```

### 사전 초기화 · sync-remote

`./nixstrap.sh` 실행 직후, Phase 1 입력 수집에 앞서 `nixstrap.lib-repo.py sync-remote`가 자동으로 실행됩니다.

| 단계 | 동작 |
|------|------|
| 1 | `git remote get-url origin`으로 `owner/repo` 자동 감지 |
| 2 | `_base.toml`의 `git.nixosRepo`와 불일치 시 자동 갱신 |
| 3 | GitHub API로 `git.name` / `git.email` 자동 채우기 (API 실패 시 대화형 입력) |
| 4 | `username` 대화형 입력 |

> remote가 없거나 `_base.toml`이 이미 일치하는 경우 자동으로 건너뜁니다.

### Phase 1 · 입력 수집

이전 세션의 파라미터 파일이 존재하면 불러와 검토 단계(review_loop)로 바로 진입합니다. 없으면 아래 순서로 입력을 수집합니다.

**레포 · 호스트:**

1. **레포 준비**: `NIXOS_REPO_PATH`가 설정된 경우(`./nixstrap.sh` 실행) 현재 레포 경로를 그대로 사용합니다.
2. **호스트 선택**: `select_host`로 기존 호스트를 선택하거나 새 이름을 입력합니다. 신규 호스트라면 `ask_preset`으로 `workstation` / `server` 중 프리셋을 지정하고, `ask_host_username`으로 호스트별 username을 입력합니다.
3. **릴리즈 고정**: `ask_state_version`으로 NixOS 릴리즈를 고정하거나 rolling으로 유지합니다.

**파티셔닝:**

`ask_partitions`에서 두 가지 모드를 선택합니다.

- **mode 1**: 이미 존재하는 EFI · root 파티션을 직접 지정합니다.
- **mode 2**: 대상 디스크와 파티션 범위를 선택하면 nixstrap이 자동으로 생성합니다.

**검토 · 저장:**

`review_loop`에서 수집된 설정을 확인하고 params 파일에 저장합니다. `ask_password`에서 첫 로그인용 비밀번호를 입력합니다. 파일에 저장하지 않고 메모리에만 보관하며, 설치 완료 후 즉시 비웁니다.

### Phase 2 · 설치 실행 (총 14단계)

**디스크 준비 (1–5):**

| # | 함수 | 설명 |
|---|------|------|
| 1 | `cleanup_mounts` | 이전 마운트 잔재 해제 |
| 2 | `read_disk_labels` | TOML → `BOOT_LABEL` / `DISK_LABEL` 결정 |
| 3 | `create_partitions` | mode 2 전용: GPT · ESP · root 파티션 생성 |
| 4 | `format_boot / format_root` | ESP → FAT32 · root → Btrfs 포맷 + 서브볼륨(`@`, `@home`, `@nix`, `@log`) 생성 |
| 5 | `mount_partitions` | `/mnt` 마운트 (btrfs 옵션 적용) |

**설치 환경 구성 (6–11):**

| # | 함수 | 설명 |
|---|------|------|
| 6 | `move_repo` | `REPO_TMP` → `/mnt/etc/nixos` 이동 |
| 7 | `create_host_profile` | 신규 호스트: `<hostname>.toml` · `<hostname>.nix` 생성 |
| 8 | `resolve_metadata` | `nixup.task-resolve.py` 실행 → `resolved.json` / `presets.json` |
| 9 | `extract_username` | `_base.toml` → `USERNAME` 결정 |
| 10 | `prepare_build_dir` | `/tmp/nixos-build` 격리 환경 구성 |
| 11 | `generate_hw_config` | `nixos-generate-config --show-hardware-config` → `hardware.nix` |

**설치 · 후처리 (12–14):**

| # | 함수 | 설명 |
|---|------|------|
| 12 | `nixos-install` | `--no-root-passwd --flake path:#HOST` 로 설치 |
| 13–14 | `_post_process` | `/mnt/etc/nixos` → `/home/USERNAME/nixos` 이동, chown · symlink, `chpasswd`로 비밀번호 자동 적용 후 메모리 즉시 비움 |

### rnixstrap 흐름

원격 서버 초기 설치 전용입니다. 디스크 파티셔닝을 nixos-anywhere에 위임합니다.

**Phase 1 입력:**

| 입력 | 설명 |
|------|------|
| 호스트 선택/신규 | 기존 TOML에서 선택하거나 새 hostname 입력 |
| IP 주소 | 접속 대상 서버 IP |
| SSH 키 경로 | `~/.ssh/rnixup/` 하위 권장. TOML 저장 시 `~` 정규화 |
| system | `x86_64-linux` / `aarch64-linux` (신규 호스트만) |
| 서비스 | headscale 등 선택적 활성화 (신규 호스트만) |

#### 비대화형 모드

`--hostname HOST` 인수를 주면 Phase 1 입력 수집 전체를 건너뛰고 아래 소스에서 자동으로 값을 채웁니다:

| 우선순위 | 소스 |
|---------|------|
| 1 | `~/.ssh/rnixup/<hostname>.strap.json` |
| 2 | `hosts/<hostname>.toml` (기존 호스트, `[deploy]` 섹션 있음) |
| 3 | `~/.ssh/rnixup/<hostname>.bootstrap.env` (standalone 호스트) |

신규 호스트에서 `ip` 또는 `sshKey`가 없으면 에러로 종료합니다.

**run_setup 순서:**

1. `_probe_ram`: SSH로 서버 RAM 사전 측정 (kexec 최소 1000MB 확인)
2. 설정 확인 · 선택: 바로 진행 / 쓰기만 / 취소 — **타이머는 선택 직후부터 시작** (비대화형 시 자동 진행)
3. 파일 작업: `hosts/<hostname>.toml` · `hosts/<hostname>.nix` 생성 또는 업데이트
4. SSH 정보 추출: 서버에서 공개키 추출 → `hosts/deploy/<hostname>.pub` 저장
5. nixos-anywhere: 서버에 원격 파티셔닝 + NixOS 설치. 생성된 `hardware.nix`를 `hosts/deploy/<hostname>.hardware.nix`로 레포에 역복사
6. 시크릿 주입: `hosts/_deploy/<hostname>.secrets/secrets.json` 기반으로 변경된 파일만 자동 전송
7. deploy-rs 배포: 설치 완료 후 rnixup으로 초기 설정 배포
