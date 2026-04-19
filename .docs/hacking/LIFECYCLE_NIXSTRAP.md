# 🔧 nixstrap 부트스트랩 라이프사이클

새 기기에 NixOS를 처음 설치할 때 `nixstrap`이 실행하는 단계별 흐름입니다. 커스텀 ISO 부팅 또는 기존 환경에서 `./nixstrap.sh`로 진입합니다.

> **다이어그램**: [NIXSTRAP.mermaid](./NIXSTRAP.mermaid)

---

## Phase 1 · 입력 수집

이전 세션의 파라미터 파일이 존재하면 불러와 검토 단계(review_loop)로 바로 진입합니다. 없으면 아래 순서로 입력을 수집합니다.

1.  **레포 준비**: `NIXOS_REPO_PATH`가 설정된 경우(`./nixstrap.sh` 실행) 현재 레포 경로를 그대로 사용합니다. 커스텀 ISO 환경에서는 `ask_repo_and_clone`으로 GitHub에서 클론합니다.
2.  **호스트 선택**: `select_host`로 기존 호스트를 선택하거나 새 이름을 입력합니다. 신규 호스트라면 `ask_preset`으로 `workstation` / `server` 중 프리셋을 지정합니다.
3.  **파티션 설정**: `ask_partitions`에서 두 가지 모드를 선택합니다.
    - **mode 1**: 이미 존재하는 파티션 레이블을 직접 지정합니다.
    - **mode 2**: 대상 디스크와 파티션 범위를 선택하면 nixstrap이 자동으로 생성합니다.
4.  **검토 및 저장**: `review_loop`에서 수집된 설정을 확인하고 params 파일에 저장합니다.
5.  **비밀번호 입력**: `ask_password`에서 첫 로그인용 비밀번호를 입력합니다. 파일에 저장하지 않고 메모리에만 보관합니다.

---

## Phase 2 · 설치 실행

총 14단계로 구성됩니다.

| # | 함수 | 설명 |
|---|------|------|
| 1 | `cleanup_mounts` | 이전 마운트 잔재 해제 |
| 2 | `read_disk_labels` | TOML → `BOOT_LABEL` / `DISK_LABEL` 결정 |
| 3 | `create_partitions` | mode 2 전용: GPT · ESP · root 파티션 생성 |
| 4 | `format_boot` | ESP → FAT32 포맷 |
| 5 | `format_root` | root → Btrfs 포맷 + 서브볼륨(`@`, `@home`, `@nix`, `@log`) 생성 |
| 6 | `mount_partitions` | `/mnt` 마운트 (btrfs 옵션 적용) |
| 7 | `move_repo` | 레포 → `/mnt/etc/nixos` 이동 |
| 8 | `create_host_profile` | 신규 호스트: `host.toml` · nix 파일 생성 |
| 9 | `resolve_metadata` | `nixup.resolve.py` 실행 → `resolved.json` / `presets.json` |
| 10 | `extract_username` | `base.toml` → `USERNAME` 결정 |
| 11 | `generate_hw_config` | `nixos-generate-config` → `_hardware.nix` 생성 |
| 12 | `prepare_build_dir` | `/tmp/nixos-build` 격리 환경 구성 |
| 13 | `nixos-install` | `--no-root-passwd --flake path:#HOST` 로 설치 |
| 14 | `_post_process` | `/mnt/etc/nixos` → `/home/USERNAME/nixos` 이동, chown · symlink, `chpasswd`로 비밀번호 자동 적용 후 메모리 즉시 비움 |
