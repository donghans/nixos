#!/usr/bin/env bash

# Usage: [GH_USER=id] ./setup.sh /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co
BOOT_PART=$1
ROOT_PART=$2
HOST=$3

if [ -z "$BOOT_PART" ] || [ -z "$ROOT_PART" ] || [ -z "$HOST" ]; then
    echo "[ERROR] Usage: $0 <EFI_PART> <ROOT_PART> <HOSTNAME>"
    echo "Example: $0 /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co"
    exit 1
fi

echo "[TARGET] Partition: Boot($BOOT_PART), Root($ROOT_PART) (Host: $HOST)"

# 1. Boot Partition Format
read -rp "[?] Format Boot Partition($BOOT_PART)? (y/N): " FORMAT_BOOT
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    echo "[CLEAN] Formatting Boot Partition (FAT32)..."
    mkfs.fat -F 32 -n boot "$BOOT_PART"
else
    echo "[SKIP] Skipping Boot Partition format."
fi

# 2. Btrfs Format & Subvolume
echo "[DISK] Formatting Root Partition and creating Subvolumes..."
mkfs.btrfs -L nixos -f "$ROOT_PART"

mount "$ROOT_PART" /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@nix
btrfs subvolume create /mnt/@log
umount /mnt

# 3. Mount with Options
export MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
mount -o subvol=@,"$MOUNT_OPTS" "$ROOT_PART" /mnt
mkdir -p /mnt/{home,nix,var/log,boot}
mount -o subvol=@home,"$MOUNT_OPTS" "$ROOT_PART" /mnt/home
mount -o subvol=@nix,"$MOUNT_OPTS" "$ROOT_PART" /mnt/nix
mount -o subvol=@log,"$MOUNT_OPTS" "$ROOT_PART" /mnt/var/log
mount "$BOOT_PART" /mnt/boot

# 4. Git Clone (GH_USER check)
if [ -z "${GH_USER:-}" ]; then
    echo "[INFO] Environment variable GH_USER is not defined."
    read -rp "[INPUT] GitHub Username: " GH_USER
else
    echo "[OK] GH_USER($GH_USER) detected."
fi

echo "[GIT] Cloning repository (github.com/$GH_USER/nixos)..."
git clone "https://github.com/$GH_USER/nixos.git" /mnt/etc/nixos

# 5. Metadata Extraction
INFO_JSON="/mnt/etc/nixos/dev/_info.json"
if [ ! -f "$INFO_JSON" ]; then
    echo "[ERROR] $INFO_JSON not found. Check your repository."
    exit 1
fi
USERNAME=$(jq -r '.username' "$INFO_JSON")

# 6. Hardware Configuration
echo "[SCAN] Generating hardware-configuration..."
nixos-generate-config --root /mnt --no-filesystems
mkdir -p /mnt/etc/nixos/dev/hardware
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/dev/hardware/$HOST.nix"
rm -f /mnt/etc/nixos/configuration.nix
echo "$HOST" > /mnt/etc/nixos/.current_host

# 7. NixOS Install
echo "[INSTALL] Starting NixOS Installation (#$HOST)..."
nixos-install --flake "/mnt/etc/nixos/_flakes/stable#$HOST"

# 8. Post-processing
echo "[DONE] Post-processing (User: $USERNAME)..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

# Permissions
nixos-enter --root /mnt --command "chown -R 1000:100 /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo "[SUCCESS] Installation complete! Please reboot your system."
