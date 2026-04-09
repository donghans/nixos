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
    
    # Matches NHW's aligned format: ISO Exec cmd > description
    printf "${PURPLE}ISO${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# 2. Initialization
# shellcheck disable=SC2034
REAL_CMD="nixos-setup-from-repo"
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

# 1. Boot Partition Format
read -rp "$(printf "${YELLOW}%-13s${NC} | format boot partition($BOOT_PART)? (y/N): " "ISO Question")" FORMAT_BOOT
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    log_msg "Disk" "formatting boot partition (fat32)..."
    log_exec "disk" ">" "mkfs.fat"
    mkfs.fat -F 32 -n boot "$BOOT_PART"
    log_exec "disk" "<" "mkfs.fat"
else
    log_msg "Disk" "skipping boot partition format."
fi

# 2. Btrfs Format & Subvolume
log_msg "Disk" "formatting root and creating subvolumes..."
log_exec "disk" ">" "mkfs.btrfs"
mkfs.btrfs -L nixos -f "$ROOT_PART"

mount "$ROOT_PART" /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@nix
btrfs subvolume create /mnt/@log
umount /mnt
log_exec "disk" "<" "mkfs.btrfs"

# 3. Mount
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

# 4. Git Clone
if [ -z "${NIXOS_REPO:-}" ]; then
    log_msg "Notice" "nixos_repo environment variable is not defined."
    read -rp "$(printf "${YELLOW}%-13s${NC} | enter repository (e.g. user/nixos): " "ISO Input")" NIXOS_REPO
fi

log_msg "Git" "cloning repository from github.com/$NIXOS_REPO ..."
log_exec "git" ">" "git clone"
git clone "https://github.com/$NIXOS_REPO.git" /mnt/etc/nixos
log_exec "git" "<" "git clone"

# 5. Resolve Metadata (설치 대상 하드웨어 기반 resolved.json 생성)
# (목적: /proc/meminfo에서 실제 RAM을 감지하여 swap/tmpfs 크기를 올바르게 설정)
log_msg "Config" "generating resolved.json from target hardware..."
log_exec "py" ">" "nhw.resolve.py"
python3 /mnt/etc/nixos/core/scripts/nhw.resolve.py \
    /mnt/etc/nixos /mnt/etc/nixos
log_exec "py" "<" "nhw.resolve.py"

# 6. Metadata Extraction
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

# 7. Hardware Config
log_msg "Config" "generating hardware-configuration.nix ..."
nixos-generate-config --root /mnt --no-filesystems
mkdir -p "/mnt/etc/nixos/hosts/$HOST"
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/hosts/$HOST/_hardware.nix"
rm -f /mnt/etc/nixos/configuration.nix
echo "$HOST" > /mnt/etc/nixos/.current_host

# 8. Install
log_msg "Install" "starting nixos-install for #$HOST ..."
log_exec "nix" ">" "nixos-install"
nixos-install --flake "/mnt/etc/nixos/core#$HOST"
log_exec "nix" "<" "nixos-install"

# 9. Post-processing
log_msg "Done" "running post-installation tasks for user: $USERNAME ..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

nixos-enter --root /mnt --command "chown -R $USERNAME:users /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo ""
log_msg "Success" "installation complete. please reboot your system."
