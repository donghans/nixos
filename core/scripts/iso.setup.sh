#!/usr/bin/env bash
set -euo pipefail

# [iso:setup] NixOS Installation Script
# This script is wrapped by nixos-setup-from-repo.
# Everything is ASCII only to prevent build errors.

# 1. Colors & Formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Formatting Helper
log_msg() {
    local category=$1
    local msg=$2
    local cat_color=$NC

    case "$category" in
        Init|Target)  cat_color=$CYAN ;;
        Usage)        cat_color=$YELLOW ;;
        Disk|Mount)   cat_color=$PURPLE ;;
        Git|Config)   cat_color=$BLUE ;;
        Install)      cat_color=$PURPLE ;;
        Done|Success) cat_color=$GREEN ;;
        Error)        cat_color=$RED ;;
        Notice|Question) cat_color=$YELLOW ;;
        *)            cat_color=$NC ;;
    esac

    printf "${PURPLE}ISO${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# Command Execution Helper (Aligned with | marker)
log_exec() {
    local cmd_name=$1 # e.g., disk, git, nix
    local state=$2    # > or <
    local msg=$3
    local cat_color=$BLUE

    # Matches NIXUP's aligned format: ISO Exec cmd > description
    printf "${PURPLE}ISO${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# 2. Initialization
SHORT_CMD="nixos-setup"

BOOT_PART=$1
ROOT_PART=$2
HOST=$3

# Welcome Message
log_msg "Init" "ISO: NixOS Installation Helper"

show_usage() {
    log_msg "Usage" "$SHORT_CMD <EFI_PART> <ROOT_PART> <HOSTNAME>"
    log_msg "Usage" "Example: $SHORT_CMD /dev/nvme0n1p1 /dev/nvme0n1p2 host"
    echo ""
    log_msg "Notice" "Target repository: ${NIXOS_REPO:-unknown}"
}

if [ -z "$BOOT_PART" ] || [ -z "$ROOT_PART" ] || [ -z "$HOST" ]; then
    show_usage
    exit 1
fi

# Print Configuration Info
log_msg "Init" "Action:   installation"
log_msg "Init" "Target:   Boot($BOOT_PART), Root($ROOT_PART)"
log_msg "Init" "Hostname: $HOST"
echo ""

# 3. Ensure NIXOS_REPO is known before clone
# (목적: clone 전에 레포 주소 확보 — 레이블 추출을 위해 먼저 clone 필요)
if [ -z "${NIXOS_REPO:-}" ]; then
    log_msg "Notice" "nixos_repo environment variable is not defined."
    read -rp "$(printf "${YELLOW}%-13s${NC} | enter repository (e.g. user/nixos): " "ISO Input")" NIXOS_REPO
fi

# 4. Cleanup Previous Attempt
# 재시도 시 이전 마운트가 남아있으면 mkfs.*가 "contains a mounted filesystem"으로 실패함
# swapoff → 역순 umount (boot → log → nix → home → /) 후 /mnt 자체 해제
if mountpoint -q /mnt 2>/dev/null; then
    log_msg "Mount" "cleaning up previous mounts under /mnt ..."
    swapoff -a 2>/dev/null || true
    umount -R /mnt 2>/dev/null || umount -lR /mnt 2>/dev/null || true
fi

# Git Clone (임시 경로 — 레이블 추출 후 최종 위치로 이동)
REPO_TMP="/tmp/nixos-setup-repo"
rm -rf "$REPO_TMP"
log_msg "Git" "cloning repository from github.com/$NIXOS_REPO ..."
log_exec "git" ">" "git clone"
git clone "https://github.com/$NIXOS_REPO.git" "$REPO_TMP"
log_exec "git" "<" "git clone"

# 5. Read Disk Labels from TOML
# (목적: base.toml + host.toml에서 diskDevice/bootDevice를 읽어 레이블 추출)
# (by-label 경로에서만 레이블 추출. UUID 등 다른 형식이면 기본값 사용)
read -r BOOT_LABEL DISK_LABEL <<< "$(HOST="$HOST" REPO_TMP="$REPO_TMP" python3 - <<'PYEOF'
import tomllib, os

repo = os.environ['REPO_TMP']
host = os.environ['HOST']

with open(f'{repo}/hosts/base.toml', 'rb') as f:
    base = tomllib.load(f)

host_path = f'{repo}/hosts/{host}/host.toml'
host_data = {}
if os.path.exists(host_path):
    with open(host_path, 'rb') as f:
        host_data = tomllib.load(f)

boot_dev = host_data.get('bootDevice', base['bootDevice'])
disk_dev = host_data.get('diskDevice', base['diskDevice'])

def extract_label(path):
    prefix = '/dev/disk/by-label/'
    return path[len(prefix):] if path.startswith(prefix) else ''

print(extract_label(boot_dev), extract_label(disk_dev))
PYEOF
)"
BOOT_LABEL="${BOOT_LABEL:-boot}"
DISK_LABEL="${DISK_LABEL:-nixos}"
log_msg "Config" "disk labels: boot=$BOOT_LABEL, root=$DISK_LABEL"

# 6. Boot Partition Format
read -rp "$(printf "${YELLOW}%-13s${NC} | format boot partition($BOOT_PART)? (y/N): " "ISO Question")" FORMAT_BOOT
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    log_msg "Disk" "formatting boot partition (fat32, label=$BOOT_LABEL)..."
    log_exec "disk" ">" "mkfs.fat"
    mkfs.fat -F 32 -n "$BOOT_LABEL" "$BOOT_PART"
    log_exec "disk" "<" "mkfs.fat"
else
    log_msg "Disk" "skipping boot partition format."
fi

# 7. Btrfs Format & Subvolume
read -rp "$(printf "${YELLOW}%-13s${NC} | format root partition($ROOT_PART)? (y/N): " "ISO Question")" FORMAT_ROOT
if [[ "$FORMAT_ROOT" =~ ^[Yy]$ ]]; then
    log_msg "Disk" "formatting root (label=$DISK_LABEL) and creating subvolumes..."
    log_exec "disk" ">" "mkfs.btrfs"
    mkfs.btrfs -L "$DISK_LABEL" -f "$ROOT_PART"
    mount "$ROOT_PART" /mnt
    btrfs subvolume create /mnt/@
    btrfs subvolume create /mnt/@home
    btrfs subvolume create /mnt/@nix
    btrfs subvolume create /mnt/@log
    umount /mnt
    log_exec "disk" "<" "mkfs.btrfs"
else
    log_msg "Disk" "skipping root format — using existing btrfs and subvolumes."
fi

# 8. Mount
export MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
log_msg "Mount" "mounting partitions with optimal options..."
log_exec "disk" ">" "mount"
mount -o subvol=@,"${MOUNT_OPTS}" "$ROOT_PART" /mnt
mkdir -p /mnt/{home,nix,var/log,boot}
mount -o subvol=@home,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/home
mount -o subvol=@nix,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/nix
mount -o subvol=@log,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/var/log
mount "$BOOT_PART" /mnt/boot
log_exec "disk" "<" "mount"

# 9. Move Cloned Repo to Final Location
log_msg "Git" "moving repository to /mnt/etc/nixos ..."
mkdir -p /mnt/etc
mv "$REPO_TMP" /mnt/etc/nixos

# 10. Resolve Metadata (설치 대상 하드웨어 기반 resolved.json 생성)
# (목적: /proc/meminfo에서 실제 RAM을 감지하여 swap/tmpfs 크기를 올바르게 설정)
log_msg "Config" "generating resolved.json from target hardware..."
log_exec "py" ">" "nixup.resolve.py"
python3 /mnt/etc/nixos/core/scripts/nixup.resolve.py \
    /mnt/etc/nixos /mnt/etc/nixos
log_exec "py" "<" "nixup.resolve.py"

# 11. Metadata Extraction
BASE_TOML="/mnt/etc/nixos/hosts/base.toml"
if [ ! -f "$BASE_TOML" ]; then
    log_msg "Error" "could not find $BASE_TOML in the cloned repository."
    exit 1
fi
USERNAME=$(BASE_TOML="$BASE_TOML" python3 -c "import tomllib, os; print(tomllib.load(open(os.environ['BASE_TOML'],'rb'))['username'])")
if [ -z "$USERNAME" ]; then
    log_msg "Error" "failed to extract username from $BASE_TOML"
    exit 1
fi

# 12. Hardware Config
log_msg "Config" "generating hardware-configuration.nix ..."
nixos-generate-config --root /mnt --no-filesystems
mkdir -p "/mnt/etc/nixos/hosts/$HOST"
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/hosts/$HOST/_hardware.nix"
rm -f /mnt/etc/nixos/configuration.nix
echo "$HOST" > /mnt/etc/nixos/.current_host

# 13. Prepare .build/ Environment
# (목적: nixup과 동일한 격리 환경 구성 — core/flake.nix의 import 경로가 .build/ 루트 기준이므로
#         /mnt/etc/nixos/core를 직접 flake로 지정하면 core/core/flake.outputs.nix를 찾아 실패)
# (주의: /mnt/etc/nixos 안에 두면 해당 git repo의 미추적 파일로 인식되어 nixos-install 실패.
#         /tmp/nixos-build 처럼 git repo 바깥에 두면 Nix가 git을 전혀 참조하지 않음)
log_msg "Config" "preparing .build/ environment for nixos-install..."
BUILD_DIR="/tmp/nixos-build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp -a /mnt/etc/nixos/core "$BUILD_DIR/"
cp -a /mnt/etc/nixos/hosts "$BUILD_DIR/"
cp -a /mnt/etc/nixos/mods "$BUILD_DIR/"
cp /mnt/etc/nixos/core/flake.nix "$BUILD_DIR/flake.nix"
cp /mnt/etc/nixos/resolved.json "$BUILD_DIR/"
cp /mnt/etc/nixos/presets.json "$BUILD_DIR/"
for _lf in "/mnt/etc/nixos/.locks/$HOST.lock" "/mnt/etc/nixos/.locks/_rolling.lock"; do
    [ -f "$_lf" ] && cp "$_lf" "$BUILD_DIR/flake.lock" && break
done

# 14. Install
log_msg "Install" "starting nixos-install for #$HOST ..."
log_exec "nix" ">" "nixos-install"
nixos-install --flake "$BUILD_DIR#$HOST"
log_exec "nix" "<" "nixos-install"

# 15. Post-processing
log_msg "Done" "running post-installation tasks for user: $USERNAME ..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

nixos-enter --root /mnt --command "chown -R $USERNAME:users /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo ""
log_msg "Success" "installation complete. please reboot your system."
