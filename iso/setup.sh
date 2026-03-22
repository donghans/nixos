#!/usr/bin/env nix-shell
#!nix-shell -i bash -p jq git btrfs-progs

# 사용법: [GH_USER=id] ./setup.sh /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co
BOOT_PART=$1
ROOT_PART=$2
HOST=$3

if [ -z "$BOOT_PART" ] || [ -z "$ROOT_PART" ] || [ -z "$HOST" ]; then
    echo "❌ 사용법: $0 <EFI 파티션> <루트 파티션> <호스트명>"
    echo "예시: $0 /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co"
    exit 1
fi

echo "🎯 대상 파티션: Boot($BOOT_PART), Root($ROOT_PART) (호스트: $HOST)"

# 1. Boot 파티션 포맷 여부 확인
read -p "❓ Boot 파티션($BOOT_PART)을 포맷하시겠습니까? (y/N): " FORMAT_BOOT
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    echo "🧹 Boot 파티션 포맷 중 (FAT32)..."
    mkfs.fat -F 32 -n boot "$BOOT_PART"
else
    echo "⏭️ Boot 파티션 포맷을 건너뜁니다."
fi

# 2. Btrfs 포맷 및 Subvolume 생성
echo "💾 Root 파티션 포맷 및 Subvolume 생성 중..."
mkfs.btrfs -L nixos -f "$ROOT_PART"

# 임시 마운트 및 Subvolume 생성
mount "$ROOT_PART" /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@nix
btrfs subvolume create /mnt/@log
umount /mnt

# 3. 최적화 옵션으로 재마운트
export MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
mount -o subvol=@,$MOUNT_OPTS "$ROOT_PART" /mnt
mkdir -p /mnt/{home,nix,var/log,boot}
mount -o subvol=@home,$MOUNT_OPTS "$ROOT_PART" /mnt/home
mount -o subvol=@nix,$MOUNT_OPTS "$ROOT_PART" /mnt/nix
mount -o subvol=@log,$MOUNT_OPTS "$ROOT_PART" /mnt/var/log
mount "$BOOT_PART" /mnt/boot

# 4. 설정 저장소 클론 (GH_USER 분기 처리)
if [ -z "$GH_USER" ]; then
    echo "🔍 환경 변수 GH_USER가 정의되지 않았습니다."
    read -p "👤 GitHub Username (for repository clone): " GH_USER
else
    echo "✅ 환경 변수 GH_USER($GH_USER)를 감지했습니다."
fi

echo "📂 설정 저장소 클론 중 (github.com/$GH_USER/nixos)..."
git clone "https://github.com/$GH_USER/nixos.git" /mnt/etc/nixos

# 5. 유저 정보 추출 (dev/_info.json 사용)
INFO_JSON="/mnt/etc/nixos/dev/_info.json"
if [ ! -f "$INFO_JSON" ]; then
    echo "❌ 에러: $INFO_JSON 파일을 찾을 수 없습니다. 클론이 정상적으로 되었는지 확인하세요."
    exit 1
fi
USERNAME=$(jq -r '.username' "$INFO_JSON")

# 6. 하드웨어 설정 생성
echo "🔍 하드웨어 정보 추출 중..."
nixos-generate-config --root /mnt --no-filesystems
# 기존 설정 정리 및 .hardware.nix 이동
mkdir -p /mnt/etc/nixos/dev/base
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/dev/hardware/$HOST.nix"
rm -f /mnt/etc/nixos/configuration.nix # 기본 생성 파일 제거
echo "$HOST" > /mnt/etc/nixos/.current_host

echo "🚀 NixOS 설치 시작 (#$HOST)..."
nixos-install --flake "/mnt/etc/nixos/_flakes/stable#$HOST"

# 7. 사후 처리 (유저 홈 이동 및 권한 부여)
echo "🧹 후처리 작업 중 (User: $USERNAME)..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

# 유저 생성 전이므로 UID:GID(1000:100)로 직접 할당
nixos-enter --root /mnt --command "chown -R 1000:100 /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo "✨ 모든 작업이 완료되었습니다! 시스템을 재부팅하세요."
