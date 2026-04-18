#!/usr/bin/env bash
set -euo pipefail

# [nixstrap] NixOS Installation Script
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

    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# Command Execution Helper (Aligned with | marker)
log_exec() {
    local cmd_name=$1 # e.g., disk, git, nix
    local state=$2    # > or <
    local msg=$3
    local cat_color=$BLUE

    # Matches NIXUP's aligned format: NIXSTRAP Exec cmd > description
    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# 2. Initialization
SHORT_CMD="nixstrap"

# Welcome Message
log_msg "Init" "NixOS Installer"

show_usage() {
    log_msg "Usage" "$SHORT_CMD [HOSTNAME]"
    log_msg "Usage" "Example: $SHORT_CMD host"
    echo ""
    log_msg "Notice" "Target repository: ${NIXOS_REPO:-unknown}"
}

# ===========================================================================
# PHASE 1: GATHER ALL INPUT
# Questions are organized into functions so the review loop can re-invoke
# any individual section without re-running the whole script.
# ===========================================================================

# -- Shared State (global variables written by ask_* functions) --
NIXOS_REPO="${NIXOS_REPO:-}"
HOST="${1:-}"
_IS_VM=false
_PART_MODE=""
_NEW_PARTITIONS=false
BOOT_PART=""
ROOT_PART=""
FORMAT_BOOT=""
FORMAT_ROOT=""
_DISK=""
_WIPE=false
_PART_START=""
_PART_END=""
_BOOT_SIZE=""
_BOOT_END=""
_NEW_BOOT_NUM=""
_NEW_ROOT_NUM=""
_PRESET="workstation"

# Detect virtualization (for incus-guest auto-config on new host profiles)
if _VIRT_TYPE=$(systemd-detect-virt 2>/dev/null); then
    _IS_VM=true
    log_msg "Notice" "virtualized environment detected: $_VIRT_TYPE"
fi

# -- Question Functions --

ask_repo() {
    local _prompt _input
    if [ -n "${NIXOS_REPO:-}" ]; then
        _prompt="$(printf "${YELLOW}%-13s${NC} | repository [%s]: " "nixstrap" "$NIXOS_REPO")"
    else
        _prompt="$(printf "${YELLOW}%-13s${NC} | repository (e.g. user/nixos): " "nixstrap")"
    fi
    read -rp "$_prompt" _input
    NIXOS_REPO="${_input:-${NIXOS_REPO:-}}"
}

ask_host() {
    local _prompt _input
    if [ -n "${HOST:-}" ]; then
        _prompt="$(printf "${YELLOW}%-13s${NC} | hostname [%s]: " "nixstrap" "$HOST")"
    else
        _prompt="$(printf "${YELLOW}%-13s${NC} | hostname: " "nixstrap")"
    fi
    read -rp "$_prompt" _input
    HOST="${_input:-${HOST:-}}"
}

ask_partitions() {
    local _USE_WHOLE _CONFIRM_WIPE _FREE_OUTPUT _FREE_SEL _SELECTED
    local _NUM _FS _FE _FSZ _OLD_PART_COUNT

    echo ""
    log_msg "Disk" "current block devices:"
    lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT
    echo ""

    # Reset partition state on every entry (supports re-editing)
    _NEW_PARTITIONS=false
    BOOT_PART=""
    ROOT_PART=""
    FORMAT_BOOT=""
    FORMAT_ROOT=""
    _WIPE=false

    # Mode selection loop (re-asks on invalid input instead of exiting)
    while true; do
        read -rp "$(printf "${YELLOW}%-13s${NC} | partition mode — 1=use existing, 2=create new [2]: " "nixstrap")" _PART_MODE
        _PART_MODE="${_PART_MODE:-2}"
        [[ "$_PART_MODE" == "1" || "$_PART_MODE" == "2" ]] && break
        log_msg "Error" "invalid mode. select 1 or 2."
    done

    if [[ "$_PART_MODE" == "1" ]]; then
        # Use existing partitions
        read -rp "$(printf "${YELLOW}%-13s${NC} | EFI partition path (e.g. /dev/nvme0n1p1): " "nixstrap")" BOOT_PART
        read -rp "$(printf "${YELLOW}%-13s${NC} | root partition path (e.g. /dev/nvme0n1p2): " "nixstrap")" ROOT_PART

        read -rp "$(printf "${YELLOW}%-13s${NC} | format boot partition ($BOOT_PART)? (y/N): " "nixstrap")" FORMAT_BOOT
        read -rp "$(printf "${YELLOW}%-13s${NC} | format root partition ($ROOT_PART)? (y/N): " "nixstrap")" FORMAT_ROOT

    else
        # Create new partitions
        read -rp "$(printf "${YELLOW}%-13s${NC} | target disk (e.g. /dev/nvme0n1): " "nixstrap")" _DISK

        read -rp "$(printf "${YELLOW}%-13s${NC} | use entire disk? (Y/n): " "nixstrap")" _USE_WHOLE
        _USE_WHOLE="${_USE_WHOLE:-Y}"

        if [[ "$_USE_WHOLE" =~ ^[Yy]$ ]]; then
            read -rp "$(printf "${RED}%-13s${NC} | WARNING: ALL data on '%s' will be erased. type 'yes' to confirm: " "nixstrap" "$_DISK")" _CONFIRM_WIPE
            if [[ "$_CONFIRM_WIPE" != "yes" ]]; then
                log_msg "Error" "cancelled."
                exit 1
            fi
            _PART_START="1MiB"
            _PART_END="100%"
            _WIPE=true
        else
            log_msg "Disk" "scanning free space on $_DISK ..."
            _FREE_OUTPUT=$(python3 - "$_DISK" <<'PYEOF'
import subprocess, sys, re

disk = sys.argv[1]
result = subprocess.run(
    ['parted', '-m', disk, 'unit', 'GiB', 'print', 'free'],
    capture_output=True, text=True
)
blocks = []
for line in result.stdout.strip().split('\n')[2:]:
    parts = line.rstrip(';').split(':')
    if len(parts) >= 5 and parts[4] == 'free':
        start, end, size = parts[1], parts[2], parts[3]
        try:
            size_val = float(re.sub(r'[^0-9.]', '', size))
        except ValueError:
            continue
        if size_val >= 2:
            blocks.append((start, end, size))

if not blocks:
    print("NONE")
else:
    for i, (start, end, size) in enumerate(blocks, 1):
        print(f"{i}:{start}:{end}:{size}")
PYEOF
)

            if [[ "$_FREE_OUTPUT" == "NONE" ]]; then
                log_msg "Error" "no usable free space (>=2GiB) found on $_DISK."
                exit 1
            fi

            echo ""
            log_msg "Disk" "available free space:"
            while IFS=: read -r _NUM _FS _FE _FSZ; do
                printf "  %s) %s ~ %s  (%s)\n" "$_NUM" "$_FS" "$_FE" "$_FSZ"
            done <<< "$_FREE_OUTPUT"
            echo ""

            # Free-space selection loop
            while true; do
                read -rp "$(printf "${YELLOW}%-13s${NC} | select number or enter range (e.g. 128GiB-476GiB): " "nixstrap")" _FREE_SEL
                if [[ "$_FREE_SEL" =~ ^[0-9]+$ ]]; then
                    _SELECTED=$(echo "$_FREE_OUTPUT" | grep "^${_FREE_SEL}:" || true)
                    if [ -z "$_SELECTED" ]; then
                        log_msg "Error" "invalid selection."
                        continue
                    fi
                    _PART_START=$(echo "$_SELECTED" | cut -d: -f2)
                    _PART_END=$(echo "$_SELECTED" | cut -d: -f3)
                else
                    _PART_START="${_FREE_SEL%-*}"
                    _PART_END="${_FREE_SEL#*-}"
                fi
                break
            done
            _WIPE=false
        fi

        # Boot partition size
        read -rp "$(printf "${YELLOW}%-13s${NC} | boot partition size (default: 1GiB, enter): " "nixstrap")" _BOOT_SIZE
        _BOOT_SIZE="${_BOOT_SIZE:-1GiB}"

        # Calculate boot end position
        _BOOT_END=$(python3 - "$_PART_START" "$_BOOT_SIZE" <<'PYEOF'
import sys, re

def parse_to_mib(s):
    s = s.strip()
    val = float(re.sub(r'[^0-9.]', '', s))
    unit = re.sub(r'[0-9. ]', '', s).upper()
    if unit in ('GIB', 'G', 'GB'):
        return val * 1024
    elif unit in ('MIB', 'M', 'MB'):
        return val
    return val * 1024  # assume GiB

start_mib = parse_to_mib(sys.argv[1])
size_mib = parse_to_mib(sys.argv[2])
end_mib = start_mib + size_mib

if end_mib >= 1024 and end_mib % 1024 == 0:
    print(f"{int(end_mib // 1024)}GiB")
else:
    print(f"{end_mib:.0f}MiB")
PYEOF
)

        # Count existing partitions to derive new partition numbers
        _OLD_PART_COUNT=$(parted -m "$_DISK" unit MiB print 2>/dev/null | grep -c '^[0-9]' || echo "0")
        _NEW_BOOT_NUM=$((_OLD_PART_COUNT + 1))
        _NEW_ROOT_NUM=$((_OLD_PART_COUNT + 2))

        # Derive device names (nvme/mmcblk style vs sda style)
        if [[ "$_DISK" =~ [0-9]$ ]]; then
            BOOT_PART="${_DISK}p${_NEW_BOOT_NUM}"
            ROOT_PART="${_DISK}p${_NEW_ROOT_NUM}"
        else
            BOOT_PART="${_DISK}${_NEW_BOOT_NUM}"
            ROOT_PART="${_DISK}${_NEW_ROOT_NUM}"
        fi

        _NEW_PARTITIONS=true
        FORMAT_BOOT="y"
        FORMAT_ROOT="y"
    fi
}

ask_preset() {
    # Loops until a valid preset is entered
    local _input _new_preset
    while true; do
        read -rp "$(printf "${YELLOW}%-13s${NC} | select preset (workstation/server) [%s]: " "nixstrap" "$_PRESET")" _input
        _new_preset="${_input:-${_PRESET}}"
        if [[ "$_new_preset" == "workstation" || "$_new_preset" == "server" ]]; then
            _PRESET="$_new_preset"
            return 0
        fi
        log_msg "Error" "unknown preset '$_new_preset'. use workstation or server."
    done
}

show_summary() {
    local _fmt_boot _fmt_root
    echo ""
    printf "${PURPLE}NIXSTRAP${NC} ${CYAN}%-9s${NC} | Installation configuration:\n" "Review"
    printf "  1. %-11s:  %s\n" "Repository" "${NIXOS_REPO:-(not set)}"
    printf "  2. %-11s:  %s\n" "Hostname" "${HOST:-(not set)}"

    if [[ "${_PART_MODE:-}" == "1" ]]; then
        _fmt_boot="no"; [[ "${FORMAT_BOOT:-}" =~ ^[Yy]$ ]] && _fmt_boot="yes"
        _fmt_root="no"; [[ "${FORMAT_ROOT:-}" =~ ^[Yy]$ ]] && _fmt_root="yes"
        printf "  3. %-11s:  existing  boot=%s  root=%s\n" \
            "Partitions" "${BOOT_PART:-(not set)}" "${ROOT_PART:-(not set)}"
        printf "     %-11s   format boot: %s  format root: %s\n" "" "$_fmt_boot" "$_fmt_root"
    elif [[ "${_PART_MODE:-}" == "2" ]]; then
        printf "  3. %-11s:  new  %s -> %s (EFI %s), %s (root)\n" \
            "Partitions" "${_DISK:-(not set)}" \
            "${BOOT_PART:-(not set)}" "${_BOOT_SIZE:-?}" "${ROOT_PART:-(not set)}"
        if [[ "${_WIPE:-false}" == "true" ]]; then
            printf "     %-11s   ${RED}WIPE ENTIRE DISK${NC}\n" ""
        fi
    else
        printf "  3. %-11s:  %s\n" "Partitions" "(not set)"
    fi

    printf "  4. %-11s:  %s  (new host only)\n" "Preset" "${_PRESET:-workstation}"
    printf "  %s\n" "─────────────────────────────────────────────"
}

# -- Initial Collection --
ask_repo
ask_host
ask_partitions
ask_preset

# -- Review Loop --
# User can re-enter any section before confirming.
_review=""
while true; do
    show_summary
    read -rp "$(printf "${YELLOW}%-13s${NC} | Enter=proceed  1-4=edit  q=quit: " "nixstrap")" _review
    case "${_review:-}" in
        "")
            if [ -z "${NIXOS_REPO:-}" ]; then
                log_msg "Error" "repository is required. edit item 1."
                continue
            fi
            if [ -z "${HOST:-}" ]; then
                log_msg "Error" "hostname is required. edit item 2."
                continue
            fi
            if [ -z "${BOOT_PART:-}" ] || [ -z "${ROOT_PART:-}" ]; then
                log_msg "Error" "partition info is incomplete. edit item 3."
                continue
            fi
            break
            ;;
        1) ask_repo ;;
        2) ask_host ;;
        3) ask_partitions ;;
        4) ask_preset ;;
        q|Q) log_msg "Error" "cancelled."; exit 1 ;;
        *) log_msg "Notice" "enter 1-4 to edit an item, or press Enter to proceed." ;;
    esac
done

echo ""

# ===========================================================================
# PHASE 2: EXECUTE
# No more interactive prompts from this point on.
# ===========================================================================

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

# 6. Create Partitions (mode 2 only)
if [[ "$_NEW_PARTITIONS" == "true" ]]; then
    log_msg "Disk" "creating partitions on $_DISK ..."
    log_exec "disk" ">" "parted"
    if [[ "$_WIPE" == "true" ]]; then
        parted "$_DISK" --script mklabel gpt
    fi
    parted "$_DISK" --script mkpart ESP fat32 "$_PART_START" "$_BOOT_END"
    parted "$_DISK" --script set "$_NEW_BOOT_NUM" esp on
    parted "$_DISK" --script mkpart primary "$_BOOT_END" "$_PART_END"
    log_exec "disk" "<" "parted"

    log_msg "Disk" "waiting for udev ..."
    udevadm settle --timeout=10
    log_msg "Disk" "partitions ready: boot=$BOOT_PART, root=$ROOT_PART"
fi

# 7. Boot Partition Format
if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
    log_msg "Disk" "formatting boot partition (fat32, label=$BOOT_LABEL)..."
    log_exec "disk" ">" "mkfs.fat"
    mkfs.fat -F 32 -n "$BOOT_LABEL" "$BOOT_PART"
    log_exec "disk" "<" "mkfs.fat"
else
    log_msg "Disk" "skipping boot partition format."
fi

# 8. Btrfs Format & Subvolume
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

# 9. Mount
export MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
log_msg "Mount" "mounting partitions with optimal options..."
log_exec "disk" ">" "mount"
mount -o subvol=@,"${MOUNT_OPTS}" "$ROOT_PART" /mnt
mkdir -p /mnt/{home,nix,var/log,boot}
mount -o subvol=@home,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/home
mount -o subvol=@nix,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/nix
mount -o subvol=@log,"${MOUNT_OPTS}" "$ROOT_PART" /mnt/var/log
# fmask=0137,dmask=0027: EFI 파티션을 root만 쓰기 가능하게 마운트
# (world-accessible 마운트 시 systemd-boot random seed 보안 경고 발생)
mount -o fmask=0137,dmask=0027 "$BOOT_PART" /mnt/boot
log_exec "disk" "<" "mount"

# 10. Move Cloned Repo to Final Location
log_msg "Git" "moving repository to /mnt/etc/nixos ..."
mkdir -p /mnt/etc
mv "$REPO_TMP" /mnt/etc/nixos

# 11. New Host Profile Creation
# (목적: 레포에 없는 신규 호스트면 host.toml + 최소 nix 파일 자동 생성)
# (주의: resolve.py 실행 전에 생성해야 새 호스트명이 resolved.json에 포함됨)
HOST_DIR="/mnt/etc/nixos/hosts/$HOST"
if [ ! -d "$HOST_DIR" ]; then
    log_msg "Notice" "host profile '$HOST' not found — creating new profile..."

    mkdir -p "$HOST_DIR"

    # host.toml 생성
    # (VM 환경이면 incus-guest 활성화 + incus 비활성화)
    # (이유: incus를 VM 내부에서 켜면 incusbr0가 호스트와 같은 서브넷을 점유해 라우팅 충돌 발생)
    if [[ "$_IS_VM" == "true" ]]; then
        printf 'type = "desktop"\npreset = "%s"\n\n[mods.sys.services]\nincus-guest = true\nincus = false\n' "$_PRESET" > "$HOST_DIR/host.toml"
        log_msg "Config" "incus-guest enabled, incus disabled in host.toml (virtualized environment)"
    else
        printf 'type = "desktop"\npreset = "%s"\n' "$_PRESET" > "$HOST_DIR/host.toml"
    fi

    # 최소 configuration.nix — 하드웨어 임포트만
    printf '{...}: {\n  imports = [./_hardware.nix];\n}\n' > "$HOST_DIR/configuration.nix"

    # 최소 home.nix — 빈 모듈
    printf '_: {}\n' > "$HOST_DIR/home.nix"

    log_msg "Config" "created host profile: $HOST (preset=$_PRESET)"
else
    log_msg "Config" "using existing host profile: $HOST"
fi

# 12. Resolve Metadata (설치 대상 하드웨어 기반 resolved.json 생성)
# (목적: /proc/meminfo에서 실제 RAM을 감지하여 swap/tmpfs 크기를 올바르게 설정)
# (주의: 레포 루트가 아닌 임시 경로에 출력해야 git untracked 파일 오염을 방지함)
RESOLVE_TMP="/tmp/nixos-resolve"
mkdir -p "$RESOLVE_TMP"
log_msg "Config" "generating resolved.json from target hardware..."
log_exec "py" ">" "nixup.resolve.py"
python3 /mnt/etc/nixos/core/scripts/nixup.resolve.py \
    /mnt/etc/nixos "$RESOLVE_TMP"
log_exec "py" "<" "nixup.resolve.py"

# 13. Metadata Extraction
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

# 14. Hardware Config
log_msg "Config" "generating hardware-configuration.nix ..."
nixos-generate-config --root /mnt --no-filesystems
mkdir -p "/mnt/etc/nixos/hosts/$HOST"
mv /mnt/etc/nixos/hardware-configuration.nix "/mnt/etc/nixos/hosts/$HOST/_hardware.nix"
rm -f /mnt/etc/nixos/configuration.nix
printf 'NIXUP_LAST_HOST=%s\n' "$HOST" > /mnt/etc/nixos/.env

# 15. Prepare .build/ Environment
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
cp "$RESOLVE_TMP/resolved.json" "$BUILD_DIR/"
cp "$RESOLVE_TMP/presets.json" "$BUILD_DIR/"
for _lf in "/mnt/etc/nixos/.locks/$HOST.lock" "/mnt/etc/nixos/.locks/_rolling.lock"; do
    [ -f "$_lf" ] && cp "$_lf" "$BUILD_DIR/flake.lock" && break
done

# 16. Install
# --no-root-passwd: root 패스워드 설정 생략 (NixOS 설정에서 잠금 예정)
log_msg "Install" "starting nixos-install for #$HOST ..."
log_exec "nix" ">" "nixos-install"
# HOME=/root: sudo -E로 실행 시 nixos 유저의 $HOME이 넘어오면 "not owned by you" 경고 발생
HOME=/root nixos-install --no-root-passwd --flake "$BUILD_DIR#$HOST"
log_exec "nix" "<" "nixos-install"

# 17. Post-processing
log_msg "Done" "running post-installation tasks for user: $USERNAME ..."
mkdir -p "/mnt/home/$USERNAME/"
mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"

nixos-enter --root /mnt --command "chown -R $USERNAME:users /home/$USERNAME/nixos"
nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"

echo ""
log_msg "Success" "installation complete. please reboot your system."
log_msg "Notice" "first boot: run 'passwd' to set your password."
