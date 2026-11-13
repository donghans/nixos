#!/usr/bin/env bash
# nixstrap.task-install.sh — Phase 2 설치 실행 함수
# shellcheck disable=SC1091


_cleanup_mounts() {
    # 재시도 시 이전 마운트가 남아있으면 mkfs.*가 "contains a mounted filesystem"으로 실패함
    # swapoff → 역순 umount (boot → log → nix → home → /) 후 /mnt 자체 해제
    if mountpoint -q /mnt 2>/dev/null; then
        log_msg "Mount" "/mnt 이전 마운트 정리 중..."
        swapoff -a 2>/dev/null || true
        umount -R /mnt 2>/dev/null || umount -lR /mnt 2>/dev/null || true
    fi
    # LUKS: 이전 시도가 남긴 열린 매퍼를 mklabel 전에 닫는다(마운트 없이 매퍼만 열린 경우도 포함)
    luks_close
}

_read_disk_labels() {
    # base.toml + host.toml에서 diskDevice/bootDevice를 읽어 레이블 추출
    # by-label 경로에서만 레이블 추출. UUID 등 다른 형식이면 기본값 사용
    read -r BOOT_LABEL DISK_LABEL <<< "$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" disk-labels "$REPO_TMP" "$HOST")"
    BOOT_LABEL="${BOOT_LABEL:-boot}"
    DISK_LABEL="${DISK_LABEL:-nixos}"
    log_msg "Config" "디스크 레이블: boot=$BOOT_LABEL, root=$DISK_LABEL"
}

_create_partitions() {
    [[ "$_NEW_PARTITIONS" != "true" ]] && return

    log_msg "Disk" "$_DISK 에 파티션 생성 중..."
    log_exec "disk" ">" "parted"
    if [[ "$_WIPE" == "true" ]]; then
        if [ "${_LUKS:-false}" = true ]; then
            # 옛 평문 데이터가 LUKS 영역 밑에 raw 로 남지 않게 전체 TRIM(SSD/NVMe). 보장은 아니다 — 미지원이면 경고만 한다.
            log_msg "Disk" "기존 데이터 폐기(TRIM): $_DISK"
            blkdiscard -f "$_DISK" || log_msg "Notice" "TRIM 미지원/실패 — 옛 데이터가 디스크에 남아 있을 수 있습니다(암호화 영역 밖을 raw 로 읽으면 복원될 수 있음)."
        fi
        parted "$_DISK" --script mklabel gpt
    fi
    parted "$_DISK" --script mkpart ESP fat32 "$_PART_START" "$_BOOT_END"
    parted "$_DISK" --script set "$_NEW_BOOT_NUM" esp on
    # LUKS: 루트 파티션 이름을 cryptroot 로 짓는다 → mods/sys/services/luks.nix 기본 device(by-partlabel/cryptroot)와 맞음
    local _root_pname="primary"
    [ "${_LUKS:-false}" = true ] && _root_pname="$_LUKS_NAME"
    parted "$_DISK" --script mkpart "$_root_pname" "$_BOOT_END" "$_PART_END"
    log_exec "disk" "<" "parted"

    log_msg "Disk" "udev 대기 중..."
    udevadm settle --timeout=10
    # BOOT_PART·ROOT_PART 는 nixstrap.sh/task-disk.sh 에서 대입되는 전역이다(다른 파일이라 shellcheck 가 오탐)
    # shellcheck disable=SC2153
    log_msg "Disk" "파티션 준비 완료: boot=$BOOT_PART, root=$ROOT_PART"
}

# LUKS: 루트 파티션을 luksFormat+open 하고 이후 단계(mkfs·mount)가 매퍼 장치를 루트로 쓰게 한다.
# Phase 1 에서 확인된 복구 암호(_LUKS_PW)를 쓴다. 포맷 직후 종이를 보고 다시 입력해 열림을 검증한 뒤에만 계속한다.
_luks_setup() {
    [ "${_LUKS:-false}" = true ] || return 0
    if [[ "$_NEW_PARTITIONS" != "true" || "$_WIPE" != "true" || "$FORMAT_ROOT" != "y" ]]; then
        log_msg "Error" "LUKS 는 신규 파티션 + 전체 디스크 초기화에서만 지원됩니다(내부 정합성 오류)."
        exit 1
    fi
    luks_format_open "$ROOT_PART" || { log_msg "Error" "LUKS 포맷/열기 실패"; exit 1; }
    luks_verify_typed "$_LUKS_PART" || { log_msg "Error" "복구 암호로 열림을 확인하지 못했습니다 — 중단합니다."; exit 1; }
    ROOT_PART="/dev/mapper/$_LUKS_NAME"
}

_format_boot() {
    if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
        log_msg "Disk" "부트 파티션 포맷 중 (fat32, label=$BOOT_LABEL)..."
        log_exec "disk" ">" "mkfs.fat"
        mkfs.fat -F 32 -n "$BOOT_LABEL" "$BOOT_PART"
        log_exec "disk" "<" "mkfs.fat"
    else
        log_msg "Disk" "부트 파티션 포맷 건너뜀."
    fi
}

_format_root() {
    if [[ "$FORMAT_ROOT" =~ ^[Yy]$ ]]; then
        log_msg "Disk" "루트 포맷 중 (label=$DISK_LABEL) 및 서브볼륨 생성..."
        log_exec "disk" ">" "mkfs.btrfs"
        mkfs.btrfs -L "$DISK_LABEL" -f "$ROOT_PART"
        mount "$ROOT_PART" /mnt
        btrfs subvolume create /mnt/@
        btrfs subvolume create /mnt/@home
        btrfs subvolume create /mnt/@nix
        btrfs subvolume create /mnt/@log
        # (목적: 워크스테이션은 docker(btrfs storage-driver)+incus 컨테이너/이미지가 같은
        #        볼륨에서 빈번히 생성/삭제되는데, full qgroup 모드는 이때마다 무거운 backref
        #        역추적을 해서 btrfs-cleaner가 상시 부하에 걸림(2026-08-04 msi-summit-me
        #        실측 — 이미지 197개/79GB 누적 후 qgroup 삭제 backlog 수천 개, CPU만 태우고
        #        디스크 I/O 없이 며칠도 안 끝날 수준). squota(simple quota)는 extent를
        #        "처음 만든 subvolume 소유"로만 단순 기록해 이 오버헤드를 회피하면서도
        #        subvolume/프로젝트별 용량 제한(btrfs qgroup limit)은 그대로 지원 — 서버는
        #        정밀한 공유/전용 추적(snapshot 위주 워크플로우)이 더 맞을 수 있어 제외)
        if [[ "${_PRESET:-}" == "workstation" ]]; then
            log_msg "Disk" "워크스테이션 프리셋 — btrfs squota(simple quota) 활성화 중..."
            btrfs quota enable -s /mnt
        fi
        umount /mnt
        log_exec "disk" "<" "mkfs.btrfs"
    else
        log_msg "Disk" "루트 포맷 건너뜀 — 기존 btrfs 및 서브볼륨 사용."
    fi
}

_mount_partitions() {
    local MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
    log_msg "Mount" "파티션을 최적 옵션으로 마운트 중..."
    log_exec "disk" ">" "mount"
    mount -o "subvol=@,${MOUNT_OPTS}" "$ROOT_PART" /mnt
    mkdir -p /mnt/{home,nix,var/log,boot}
    mount -o "subvol=@home,${MOUNT_OPTS}" "$ROOT_PART" /mnt/home
    mount -o "subvol=@nix,${MOUNT_OPTS}" "$ROOT_PART" /mnt/nix
    mount -o "subvol=@log,${MOUNT_OPTS}" "$ROOT_PART" /mnt/var/log
    # fmask=0137,dmask=0027: EFI 파티션을 root만 쓰기 가능하게 마운트
    # (world-accessible 마운트 시 systemd-boot random seed 보안 경고 발생)
    mount -o fmask=0137,dmask=0027 "$BOOT_PART" /mnt/boot
    log_exec "disk" "<" "mount"
}

_move_repo() {
    log_msg "Git" "레포지터리를 /mnt/etc/nixos 로 이동 중..."
    mkdir -p /mnt/etc
    # REPO_TMP가 CWD 안에 있을 경우(./nixstrap.sh 직접 실행 시) mv 후 getcwd 실패 방지
    cd /
    mv "$REPO_TMP" /mnt/etc/nixos
}

_create_host_profile() {
    # 레포에 없는 신규 호스트면 <hostname>.toml + <hostname>.nix 자동 생성
    # resolve.py 실행 전에 생성해야 새 호스트명이 resolved.json에 포함됨
    local HOST_TOML="${_INSTALL_REPO_DIR:-/mnt/etc/nixos}/hosts/$HOST.toml"
    local HOST_NIX="${_INSTALL_REPO_DIR:-/mnt/etc/nixos}/hosts/$HOST.nix"
    if [ -f "$HOST_TOML" ]; then
        log_msg "Config" "기존 호스트 프로파일 사용: $HOST"
        return
    fi

    log_msg "Notice" "호스트 프로파일 '$HOST' 없음 — 새 프로파일 생성 중..."

    # VM 환경이면 incus-guest 활성화 + incus 비활성화
    # (incus를 VM 내부에서 켜면 incusbr0가 호스트와 같은 서브넷을 점유해 라우팅 충돌 발생)
    local _sv_line=""
    [ -n "${_STATE_VERSION:-}" ] && _sv_line=$'\nstateVersion = "'"$_STATE_VERSION"'"'
    local _username_line=""
    [ -n "${_HOST_USERNAME:-}" ] && _username_line=$'\nusername = "'"$_HOST_USERNAME"'"'

    # type: server 프리셋은 "server", 그 외는 "desktop"
    local _type="desktop"
    [ "${_PRESET:-}" = "server" ] && _type="server"
    [ "${_IS_LAPTOP:-false}" = true ] && _type="laptop"

    # 대상 머신 RAM 감지 (nixstrap은 대상 머신에서 직접 실행되므로 /proc/meminfo = 정확한 값)
    local _ram_line=""
    local _ram_gb
    _ram_gb=$(awk '/^MemTotal:/ {printf "%d", int(($2 + 1048575) / 1048576)}' /proc/meminfo 2>/dev/null || true)
    [ -n "$_ram_gb" ] && _ram_line=$'\nramGb = '"$_ram_gb"

    # [mods.sys.services] 표는 하나로 합쳐 쓴다(헤더가 두 번 나오면 resolve 파싱 오류)
    local _svc_lines=""
    [[ "$_IS_VM" == "true" ]] && _svc_lines+=$'incus-guest = true\nincus = false\n'
    # incus 를 끄면 그것을 요구하는 항목도 꺼야 한다(안 그러면 평가 어서션 실패 — P4 리허설에서 발생).
    # incus-win11 은 services, incus-vm 은 gui.apps 에 있다. gui 는 워크스테이션 계열에만 있다.
    local _gui_lines=""
    if [[ "$_IS_VM" == "true" ]]; then
        _svc_lines+=$'incus-win11 = false\n'
        [ "${_PRESET:-}" != "server" ] && _gui_lines=$'\n[mods.gui.apps]\nincus-vm = false\n'
    fi
    [ "${_REFIND:-false}" = true ] && _svc_lines+=$'refind = true\n'
    if [ -n "$_svc_lines" ]; then
        printf 'type = "%s"\npreset = "%s"%s%s%s\n\n[mods.sys.services]\n%s' \
            "$_type" "$_PRESET" "$_sv_line" "$_username_line" "$_ram_line" "$_svc_lines" > "$HOST_TOML"
        printf '%s' "$_gui_lines" >> "$HOST_TOML"
        [[ "$_IS_VM" == "true" ]] && log_msg "Config" "$HOST.toml 에서 incus-guest 활성화, incus·incus-win11·incus-vm 비활성화 (가상화 환경)"
        [ "${_REFIND:-false}" = true ] && log_msg "Config" "$HOST.toml 에서 refind 활성화 (노트북)"
    else
        printf 'type = "%s"\npreset = "%s"%s%s%s\n' "$_type" "$_PRESET" "$_sv_line" "$_username_line" "$_ram_line" > "$HOST_TOML"
    fi

    # 최소 통합 호스트 파일 — os/hm 블록 분리 (mkHostConfiguration 패턴)
    printf '{mkHostConfiguration, ...}:\nmkHostConfiguration ({...}: { os = {}; hm = {}; })\n' > "$HOST_NIX"

    local _sv_info="${_STATE_VERSION:-rolling}"
    log_msg "Config" "호스트 프로파일 생성: $HOST (preset=$_PRESET, stateVersion=$_sv_info)"
}

# SSH 공개키를 hosts/_deploy/<host>.pub 에 등록 (host.nix가 primary user의 authorized_keys로 주입)
# - existing-key: _SSH_KEY_FILE에서 공개키 추출 / generate-key: 새 키 생성
# - [deploy] 섹션은 만들지 않음 (스탠드얼론 서버: root 로그인 비활성, nixup으로 서버에서 직접 관리)
# LUKS 를 골랐으면 설치 사본의 호스트 toml 에 luks = true 를 [mods.sys.services] 표 안에 넣는다.
# 원격 저장소에는 올라가지 않는다 — 설치 끝에 안내(_luks_final_notice). 현재 쓰는 시스템에서 먼저 켜면 부팅 불가(cryptroot 없음).
_apply_luks_host_config() {
    [ "${_LUKS:-false}" = true ] || return 0
    python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" set-mod-bool "${_INSTALL_REPO_DIR:-/mnt/etc/nixos}/hosts/$HOST.toml" sys services luks true \
        || { log_msg "Error" "호스트 toml 에 luks = true 설정 실패"; exit 1; }
    log_msg "Config" "$HOST.toml: [mods.sys.services] luks = true (설치 사본에만 적용)"
}

# 새 시스템의 initrd 에 LUKS 해제 구성이 들어갔는지 확인한다(없으면 재부팅해도 루트를 못 연다). 경고만 한다(형식 해석 실패가 설치 실패는 아님).
_luks_check_initrd() {
    [ "${_LUKS:-false}" = true ] || return 0
    local _f _list
    local _dir="${_INITRD_DIR:-/mnt/boot/EFI/nixos}"   # 환경변수는 시험용
    # 가장 최근 initrd. 없거나 find 가 실패해도 set -e/pipefail 로 중단되지 않게 || true
    _f=$(find "$_dir" -maxdepth 1 -name '*initrd*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2- || true)
    if [ -z "$_f" ]; then
        log_msg "Notice" "$_dir 에서 initrd 를 찾지 못해 LUKS 구성 확인을 건너뜁니다 — 재부팅 전 직접 확인하세요."
        return 0
    fi
    _list=$(zstdcat "$_f" 2>/dev/null | cpio -it 2>/dev/null || true)
    if [ -z "$_list" ]; then
        log_msg "Notice" "initrd 형식을 해석하지 못했습니다(확인 불가): ${_f##*/}"
    # 파이프(printf | grep -q)는 pipefail 에서 목록이 크면 SIGPIPE 로 실패해 오탐한다(리허설에서 실제로 발생) — here-string 사용
    elif grep -q -E 'cryptsetup|crypttab' <<<"$_list"; then
        log_msg "Success" "initrd 에 LUKS 해제 구성 확인됨: ${_f##*/}"
    else
        log_msg "Error" "initrd 에 cryptsetup/crypttab 이 없습니다 — 이대로 재부팅하면 루트를 열지 못할 수 있습니다: ${_f##*/}"
    fi
}

_luks_header_backup() {
    [ "${_LUKS:-false}" = true ] || return 0
    luks_offer_header_backup "$_LUKS_PART"
}

_luks_final_notice() {
    [ "${_LUKS:-false}" = true ] || return 0
    printf "\n"
    log_msg "Notice" "디스크가 LUKS2 로 암호화되었습니다. 첫 부팅에서 복구 암호(영어 단어)를 입력해야 합니다."
    log_msg "Notice" "설치 사본의 hosts/$HOST.toml 에만 luks = true 가 있고 원격 저장소에는 없습니다 — 새 시스템에서 커밋·push 하세요."
}

_setup_ssh_pubkey() {
    local _mode="${_SSH_ACCESS_MODE:-}"
    [[ "$_mode" != "existing-key" && "$_mode" != "generate-key" ]] && return

    local pub_dir="/mnt/etc/nixos/hosts/_deploy"
    mkdir -p "$pub_dir"

    if [ "$_mode" = "existing-key" ]; then
        local pub_key
        pub_key=$(ssh-keygen -y -f "$_SSH_KEY_FILE" 2>/dev/null)
        if [ -z "$pub_key" ]; then
            log_msg "Error" "SSH 공개키 추출 실패: $_SSH_KEY_FILE"
            exit 1
        fi
        printf '%s %s\n' "$pub_key" "$HOST" > "$pub_dir/${HOST}.pub"
        log_msg "Done" "SSH pub key 등록: hosts/_deploy/${HOST}.pub"
    else
        local key_tmp="/tmp/nixstrap-ssh-$$"
        rm -f "$key_tmp" "${key_tmp}.pub"
        ssh-keygen -t ed25519 -f "$key_tmp" -N "" -C "$HOST" >/dev/null 2>&1
        cp "${key_tmp}.pub" "$pub_dir/${HOST}.pub"
        _SSH_KEY_FILE="$key_tmp"
        _SSH_KEY_GENERATED=true
        log_msg "Done" "SSH 키 생성 및 pub key 등록: hosts/_deploy/${HOST}.pub"
    fi
}

# rEFInd 를 쓰는 호스트: 펌웨어 NVRAM 에 rEFInd 부팅 항목을 등록한다(refind mod 는 ESP 파일만 채우고 NVRAM 은 안 건드림).
# 디스크·파티션 번호는 BOOT_PART 에서 유도한다. 실패해도 설치는 계속(NVRAM 이 비어도 EFI/BOOT/BOOTX64.EFI 폴백으로 NixOS 가 부팅됨).
_register_refind() {
    [ "${_REFIND:-false}" = true ] || return 0
    local _loader="/mnt/boot/EFI/refind/refind_x64.efi" _pk _num
    if [ ! -f "$_loader" ]; then
        log_msg "Notice" "ESP 에 rEFInd 파일이 없어 NVRAM 등록을 건너뜁니다 — 첫 부팅 후 nixup 으로 채운 뒤 efibootmgr 로 등록하세요."
        return 0
    fi
    if [ ! -d /sys/firmware/efi/efivars ]; then
        log_msg "Notice" "UEFI 변수 접근 불가(레거시 부팅?) — rEFInd NVRAM 등록 건너뜀."
        return 0
    fi
    _pk=$(lsblk -no PKNAME "$BOOT_PART" 2>/dev/null | head -1)
    _num=$(cat "/sys/class/block/$(basename "$BOOT_PART")/partition" 2>/dev/null || true)
    if [ -z "$_pk" ] || [ -z "$_num" ]; then
        log_msg "Notice" "ESP 의 디스크/번호를 알 수 없어 rEFInd NVRAM 등록을 건너뜁니다: $BOOT_PART"
        return 0
    fi
    if efibootmgr --create --disk "/dev/$_pk" --part "$_num" --label "rEFInd" --loader '\EFI\refind\refind_x64.efi' >/dev/null; then
        log_msg "Done" "rEFInd NVRAM 부팅 항목 등록: /dev/$_pk 파티션 $_num"
        efibootmgr | sed 's/^/        /'
    else
        log_msg "Notice" "efibootmgr 등록 실패 — 첫 부팅 후 수동 등록 필요"
    fi
}

_save_ssh_pem() {
    [ "${_SSH_KEY_GENERATED:-false}" != true ] && return

    local ssh_dir="/mnt/home/$USERNAME/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    local pem_name="${HOST}_ed25519"
    cp "$_SSH_KEY_FILE" "$ssh_dir/$pem_name"
    chmod 600 "$ssh_dir/$pem_name"
    nixos-enter --root /mnt --command \
        "chown -R $USERNAME:users /home/$USERNAME/.ssh"

    printf "\n"
    log_msg "Done" "SSH 프라이빗 키 저장: ~/.ssh/$pem_name"
    log_msg "Notice" "▶  첫 부팅 후 관리 머신으로 복사하세요:"
    log_msg "Notice" "   scp ${USERNAME}@<IP>:~/.ssh/${pem_name} ~/.ssh/${pem_name}"
    log_msg "Notice" "   복사 후 서버의 사본은 삭제하세요: ssh ${USERNAME}@<IP> rm ~/.ssh/${pem_name}"
    log_msg "Notice" "   (rnixup 배포 대상으로 쓰려면 host.toml에 [deploy] 섹션을 직접 추가하세요)"
}

_commit_ssh_files() {
    local _mode="${_SSH_ACCESS_MODE:-}"
    [[ "$_mode" != "existing-key" && "$_mode" != "generate-key" ]] && return

    local _commit_msg="feat: ${HOST} SSH 공개키 등록"

    local repo_dir="/mnt/home/$USERNAME/nixos"
    log_msg "Git" "SSH 설정 파일 커밋 중..."

    git -C "$repo_dir" \
        -c user.name="nixstrap" -c user.email="nixstrap@localhost" \
        add "hosts/_deploy/${HOST}.pub" "hosts/${HOST}.toml" 2>/dev/null || true

    if git -C "$repo_dir" diff --cached --quiet 2>/dev/null; then
        log_msg "Notice" "커밋할 변경사항 없음"
        return
    fi

    if git -C "$repo_dir" \
        -c user.name="nixstrap" -c user.email="nixstrap@localhost" \
        commit -m "$_commit_msg" 2>/dev/null; then
        log_msg "Done" "커밋 완료"
        if git -C "$repo_dir" push 2>/dev/null; then
            log_msg "Done" "push 완료"
        else
            log_msg "Notice" "push 실패 — 첫 부팅 후 'git push' 필요"
        fi
    else
        log_msg "Notice" "커밋 실패 — 첫 부팅 후 수동 커밋 필요:"
        log_msg "Notice" "  git add hosts/_deploy/${HOST}.pub hosts/${HOST}.toml"
        log_msg "Notice" "  git commit -m '${_commit_msg}'"
    fi
}

_resolve_metadata() {
    # /proc/meminfo에서 실제 RAM을 감지하여 swap/tmpfs 크기를 올바르게 설정
    # 레포 루트가 아닌 임시 경로에 출력하여 git untracked 파일 오염 방지
    RESOLVE_TMP="/tmp/nixos-resolve"
    mkdir -p "$RESOLVE_TMP"
    log_msg "Config" "대상 하드웨어에서 resolved.json 생성 중..."
    log_exec "py" ">" "nixup.task-resolve.py"
    python3 /mnt/etc/nixos/core/scripts/nixup.task-resolve.py \
        /mnt/etc/nixos "$RESOLVE_TMP"
    log_exec "py" "<" "nixup.task-resolve.py"
}

_extract_username() {
    local resolved="$RESOLVE_TMP/resolved.json"
    if [ ! -f "$resolved" ]; then
        log_msg "Error" "resolved.json 미발견: $resolved"
        exit 1
    fi
    USERNAME=$(jq -r --arg h "$HOST" '.[$h].username' "$resolved")
    if [ -z "$USERNAME" ] || [ "$USERNAME" = "null" ]; then
        log_msg "Error" "resolved.json에서 username 추출 실패 (host=$HOST)"
        exit 1
    fi
}

_generate_hw_config() {
    log_msg "Config" "$HOST 의 hardware.nix 생성 중..."
    # --show-hardware-config: stdout 출력만 하고 /mnt/etc/nixos/에 파일을 쓰지 않음
    # → 레포에 hardware.nix가 남지 않음; 빌드 디렉터리에만 존재
    nixos-generate-config --root /mnt --no-filesystems --show-hardware-config \
        > "$BUILD_DIR/hardware.nix"
    printf 'NIXUP_LAST_HOST=%s\n' "$HOST" > /mnt/etc/nixos/.env
}

_prepare_build_dir() {
    # nixup과 동일한 격리 환경 구성 — core/flake.nix의 import 경로가 .build/ 루트 기준이므로
    # /mnt/etc/nixos/core를 직접 flake로 지정하면 core/core/flake.outputs.nix를 찾아 실패
    # /tmp/nixos-build처럼 git repo 바깥에 두면 Nix가 git을 전혀 참조하지 않음
    log_msg "Config" "nixos-install 을 위한 .build/ 환경 준비 중..."
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
}

_install_nixos() {
    log_msg "Install" "$HOST NixOS 설치 시작..."
    log_exec "nix" ">" "nixos-install"
    # setsid: 새 세션에서 실행 → 터미널 Ctrl+C(SIGINT)를 받지 않음
    # HOME=/root: sudo -E로 실행 시 nixos 유저의 $HOME이 넘어오면 "not owned by you" 경고 발생
    setsid env HOME=/root nixos-install --no-root-passwd --flake "$BUILD_DIR#$HOST" &
    _NIXOS_INSTALL_PID=$!
    local _rc
    while true; do
        if wait "$_NIXOS_INSTALL_PID"; then
            _rc=0; break
        else
            _rc=$?
            # rc > 128: wait가 시그널로 중단됨. 프로세스가 아직 살아있으면 계속 대기.
            if [ "$_rc" -gt 128 ] && kill -0 "$_NIXOS_INSTALL_PID" 2>/dev/null; then
                continue
            fi
            break
        fi
    done
    _NIXOS_INSTALL_PID=""
    log_exec "nix" "<" "nixos-install"
    return "$_rc"
}

_post_process() {
    log_msg "Done" "사용자 '$USERNAME' 의 설치 후 작업 실행 중..."
    mkdir -p "/mnt/home/$USERNAME/"
    mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"
    nixos-enter --root /mnt --command "chown -R $USERNAME:users /home/$USERNAME/nixos"
    nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"
    if [ -n "${_USER_PASSWORD:-}" ]; then
        log_msg "Notice" "'$USERNAME' 의 비밀번호 설정 중..."
        printf "%s:%s\n" "$USERNAME" "$_USER_PASSWORD" | nixos-enter --root /mnt -- chpasswd
        _USER_PASSWORD=""
    fi
    # home-manager 첫 실행 마커 — 첫 로그인 시 경고 표시용
    touch "/mnt/home/$USERNAME/.nixstrap-first-run"
    nixos-enter --root /mnt --command "chown $USERNAME:users /home/$USERNAME/.nixstrap-first-run"

    # git@github.com:user/repo.git → https://github.com/user/repo.git 변환
    # (nixstrap 설치 서버에는 GitHub SSH 키가 없으므로 nixup os 시 git pull 가능하도록)
    local _repo_dir="/mnt/home/$USERNAME/nixos"
    local _ssh_url
    _ssh_url=$(git -C "$_repo_dir" remote get-url origin 2>/dev/null || true)
    if [[ "$_ssh_url" == git@github.com:* ]]; then
        local _https_url="https://github.com/${_ssh_url#git@github.com:}"
        git -C "$_repo_dir" remote set-url origin "$_https_url"
        log_msg "Git" "remote URL → HTTPS: $_https_url"
    fi
}

phase2_execute() {
    _cleanup_mounts         # 1. 이전 마운트 정리
    _read_disk_labels       # 2. TOML → nixstrap.lib-repo.py disk-labels → BOOT_LABEL, DISK_LABEL
    _create_partitions      # 3. 파티션 생성 (mode 2만)
    _luks_setup             # 3b. LUKS 포맷·열기 (LUKS 선택 시만; ROOT_PART → /dev/mapper/cryptroot)
    _format_boot            # 4. 부트 파티션 포맷
    _format_root            # 5. Btrfs 포맷 + 서브볼륨
    _mount_partitions       # 6. 마운트
    _move_repo              # 7. /tmp/nixos-setup-repo → /mnt/etc/nixos
    _create_host_profile    # 8. 신규 호스트 프로파일 생성
    _apply_luks_host_config # 8b. 설치 사본 toml 에 luks=true (LUKS 선택 시만)
    _setup_ssh_pubkey       # 9. SSH pub key 등록 (existing-key/generate-key 시만)
    _resolve_metadata       # 10. nixup.task-resolve.py 실행 → RESOLVE_TMP
    _extract_username       # 11. base.toml → USERNAME
    _prepare_build_dir      # 12. /tmp/nixos-build 구성 (BUILD_DIR 설정됨, pub key 포함)
    _generate_hw_config     # 13. hardware.nix → BUILD_DIR에 직접 생성
    _install_nixos          # 14. nixos-install
    _post_process           # 15. mv, chown, symlink
    _register_refind        # 16. rEFInd NVRAM 항목 등록 (_REFIND 호스트만)
    _save_ssh_pem           # 17. PEM → ~/.ssh/ (generate-key 모드만)
    _commit_ssh_files       # 18. pub key + TOML 커밋 + push 시도

    _luks_check_initrd
    _luks_header_backup
    _luks_final_notice
    echo ""
    log_msg "Success" "설치 완료. 재부팅 → TTY 로그인 → 'nixup home' → 재로그인."
}
