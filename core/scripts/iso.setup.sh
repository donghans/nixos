#!/usr/bin/env bash

# [iso:setup] NixOS Installation Script
# This logic is wrapped into the 'nixos-setup-from-repo' command.

REAL_CMD="nixos-setup-from-repo"
SHORT_CMD="nixos-setup" # defined as alias in iso.nix

BOOT_PART=$1
ROOT_PART=$2
HOST=$3

# Usage Guide (nhw style)
show_usage() {
    echo "--------------------------------------------------"
    echo "[iso:setup] NixOS Installation Helper"
    echo "--------------------------------------------------"
    echo "Usage: $SHORT_CMD <EFI_PART> <ROOT_PART> <HOSTNAME>"
    echo "Example:"
    echo "  $SHORT_CMD /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co"
    echo ""
    echo "TIP: You can specify the repository path via NIXOS_REPO env var."
    echo "     Current Default: ${NIXOS_REPO:-Guessing...}"
    echo "--------------------------------------------------"
}

if [ -z "$BOOT_PART" ] || [ -z "$ROOT_PART" ] || [ -z "$HOST" ]; then
    show_usage
    exit 1
fi

echo "[iso:setup] Target: Boot($BOOT_PART), Root($ROOT_PART) | Host: $HOST"

# 1. Boot Partition Format
read -rp "[iso:setup] Format Boot Partition($BOOT_PART)? (y/N): " FORMAT_BOOT
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    echo "[iso:setup] Formatting Boot Partition (FAT32)..."
    mkfs.fat -F 32 -n boot "$BOOT_PART"
else
    echo "[iso:setup] Skipping Boot Partition format."
fi

# 2. Btrfs Format & Subvolume
echo "[iso:setup] Formatting Root Partition and creating Subvolumes..."
mkfs.btrfs -L nixos -f "$ROOT_PART"

mount "$ROOT_PART" /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@nix
btrfs subvolume create /mnt/@log
umount /mnt

# 3. Mount with Options
export MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
mount -o subvol=@,"${MOUNT_OPTS}" "$ROOT_PART" /mnt
mkdir -p /mnt/{home,nix,var/log,boot}
mount -o subvol=@home,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/home
mount -o subvol=@nix,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/nix
mount -o subvol=@log,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/var/log
mount "$BOOT_PART" /mnt/boot

# 4. Git Clone (NIXOS_REPO check)
if [ -z "${NIXOS_REPO:-}" ]; then
    echo "[iso:setup] NixOS Repository information is not set."
    read -rp "[iso:setup] Enter Repository (e.g., user/nixos): " NIXOS_REPO
else
    echo "[iso:setup] Target Repository: $NIXOS_REPO"
fi

echo "[iso:setup] Cloning repository (github.com/$NIXOS_REPO)..."
git clone "https://github.com/$NIXOS_REPO.git" /mnt/etc/nixos

# 5. Metadata Extraction
INFO_JSON="/mnt/etc/nixos/dev/_info.json"
if [ ! -f "$INFO_JSON" ]; then
    echo "[iso:setup:error] Could not find $INFO_JSON."
    exit 1
fi
USERNAME=$(jq -r '.username' "$INFO_JSON")

# 6. Hardware Configuration
echo "[iso:setup] Generating hardware-configuration..."
nixos-generate-config --root /mnt --no-filesystems
mkdir -p /mnt/etc/nixos/dev/hardware
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/dev/hardware/$HOST.nix"
rm -f /mnt/etc/nixos/configuration.nix
echo "$HOST" > /mnt/etc/nixos/.current_host

# 7. NixOS Install
echo "[iso:setup] Starting NixOS Installation (#$HOST)..."
nixos-install --flake "/mnt/etc/nixos/core#$HOST"

# 8. Post-processing
echo "[iso:setup] Post-processing (User: $USERNAME)..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

# Permissions
nixos-enter --root /mnt --command "chown -R 1000:100 /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo "--------------------------------------------------"
echo "[iso:setup] Installation complete! Please reboot."
echo "--------------------------------------------------"
