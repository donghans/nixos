#!/usr/bin/env bash
# nixstrap.task-install.sh — Phase 2 설치 실행 함수

_cleanup_mounts() {
    # 재시도 시 이전 마운트가 남아있으면 mkfs.*가 "contains a mounted filesystem"으로 실패함
    # swapoff → 역순 umount (boot → log → nix → home → /) 후 /mnt 자체 해제
    if mountpoint -q /mnt 2>/dev/null; then
        log_msg "Mount" "cleaning up previous mounts under /mnt ..."
        swapoff -a 2>/dev/null || true
        umount -R /mnt 2>/dev/null || umount -lR /mnt 2>/dev/null || true
    fi
}

_read_disk_labels() {
    # base.toml + host.toml에서 diskDevice/bootDevice를 읽어 레이블 추출
    # by-label 경로에서만 레이블 추출. UUID 등 다른 형식이면 기본값 사용
    read -r BOOT_LABEL DISK_LABEL <<< "$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" disk-labels "$REPO_TMP" "$HOST")"
    BOOT_LABEL="${BOOT_LABEL:-boot}"
    DISK_LABEL="${DISK_LABEL:-nixos}"
    log_msg "Config" "disk labels: boot=$BOOT_LABEL, root=$DISK_LABEL"
}

_create_partitions() {
    if [[ "$_NEW_PARTITIONS" != "true" ]]; then return; fi

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
}

_format_boot() {
    if [[ "$FORMAT_BOOT" =~ ^[Yy]$ ]]; then
        log_msg "Disk" "formatting boot partition (fat32, label=$BOOT_LABEL)..."
        log_exec "disk" ">" "mkfs.fat"
        mkfs.fat -F 32 -n "$BOOT_LABEL" "$BOOT_PART"
        log_exec "disk" "<" "mkfs.fat"
    else
        log_msg "Disk" "skipping boot partition format."
    fi
}

_format_root() {
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
}

_mount_partitions() {
    local MOUNT_OPTS="noatime,compress=zstd,space_cache=v2"
    log_msg "Mount" "mounting partitions with optimal options..."
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
    log_msg "Git" "moving repository to /mnt/etc/nixos ..."
    mkdir -p /mnt/etc
    mv "$REPO_TMP" /mnt/etc/nixos
}

_create_host_profile() {
    # 레포에 없는 신규 호스트면 <hostname>.toml + <hostname>.nix 자동 생성
    # resolve.py 실행 전에 생성해야 새 호스트명이 resolved.json에 포함됨
    local HOST_TOML="/mnt/etc/nixos/hosts/$HOST.toml"
    local HOST_NIX="/mnt/etc/nixos/hosts/$HOST.nix"
    if [ -f "$HOST_TOML" ]; then
        log_msg "Config" "using existing host profile: $HOST"
        return
    fi

    log_msg "Notice" "host profile '$HOST' not found — creating new profile..."

    # VM 환경이면 incus-guest 활성화 + incus 비활성화
    # (incus를 VM 내부에서 켜면 incusbr0가 호스트와 같은 서브넷을 점유해 라우팅 충돌 발생)
    local _sv_line=""
    [ -n "${_STATE_VERSION:-}" ] && _sv_line=$'\nstateVersion = "'"$_STATE_VERSION"'"'
    local _username_line=""
    [ -n "${_HOST_USERNAME:-}" ] && _username_line=$'\nusername = "'"$_HOST_USERNAME"'"'

    if [[ "$_IS_VM" == "true" ]]; then
        printf 'type = "desktop"\npreset = "%s"%s%s\n\n[mods.sys.services]\nincus-guest = true\nincus = false\n' \
            "$_PRESET" "$_sv_line" "$_username_line" > "$HOST_TOML"
        log_msg "Config" "incus-guest enabled, incus disabled in $HOST.toml (virtualized environment)"
    else
        printf 'type = "desktop"\npreset = "%s"%s%s\n' "$_PRESET" "$_sv_line" "$_username_line" > "$HOST_TOML"
    fi

    # 최소 통합 호스트 파일 — os/hm 블록 분리 (mkHostConfiguration 패턴)
    printf '{mkHostConfiguration, ...}:\nmkHostConfiguration ({...}: { os = {}; hm = {}; })\n' > "$HOST_NIX"

    local _sv_info="${_STATE_VERSION:-rolling}"
    log_msg "Config" "created host profile: $HOST (preset=$_PRESET, stateVersion=$_sv_info)"
}

_resolve_metadata() {
    # /proc/meminfo에서 실제 RAM을 감지하여 swap/tmpfs 크기를 올바르게 설정
    # 레포 루트가 아닌 임시 경로에 출력하여 git untracked 파일 오염 방지
    RESOLVE_TMP="/tmp/nixos-resolve"
    mkdir -p "$RESOLVE_TMP"
    log_msg "Config" "generating resolved.json from target hardware..."
    log_exec "py" ">" "nixup.task-resolve.py"
    python3 /mnt/etc/nixos/core/scripts/nixup.task-resolve.py \
        /mnt/etc/nixos "$RESOLVE_TMP"
    log_exec "py" "<" "nixup.task-resolve.py"
}

_extract_username() {
    local BASE_TOML="/mnt/etc/nixos/hosts/_base.toml"
    if [ ! -f "$BASE_TOML" ]; then
        log_msg "Error" "could not find $BASE_TOML in the cloned repository."
        exit 1
    fi
    USERNAME=$(BASE_TOML="$BASE_TOML" python3 -c \
        "import tomllib, os; print(tomllib.load(open(os.environ['BASE_TOML'],'rb'))['username'])")
    if [ -z "$USERNAME" ]; then
        log_msg "Error" "failed to extract username from $BASE_TOML"
        exit 1
    fi
}

_generate_hw_config() {
    log_msg "Config" "generating hardware.nix for $HOST..."
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
}

_install_nixos() {
    log_msg "Install" "starting nixos-install for #$HOST ..."
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
    log_msg "Done" "running post-installation tasks for user: $USERNAME ..."
    mkdir -p "/mnt/home/$USERNAME/"
    mv /mnt/etc/nixos "/mnt/home/$USERNAME/nixos"
    nixos-enter --root /mnt --command "chown -R $USERNAME:users /home/$USERNAME/nixos"
    nixos-enter --root /mnt --command "ln -sfn /home/$USERNAME/nixos /etc/nixos"
    if [ -n "${_USER_PASSWORD:-}" ]; then
        log_msg "Notice" "setting password for '$USERNAME'..."
        printf "%s:%s\n" "$USERNAME" "$_USER_PASSWORD" | nixos-enter --root /mnt -- chpasswd
        _USER_PASSWORD=""
    fi
    # home-manager 첫 실행 마커 — 첫 로그인 시 경고 표시용
    touch "/mnt/home/$USERNAME/.nixstrap-first-run"
    nixos-enter --root /mnt --command "chown $USERNAME:users /home/$USERNAME/.nixstrap-first-run"
}

phase2_execute() {
    _cleanup_mounts       # 1. 이전 마운트 정리
    _read_disk_labels     # 2. TOML → nixstrap.lib-repo.py disk-labels → BOOT_LABEL, DISK_LABEL
    _create_partitions    # 3. 파티션 생성 (mode 2만)
    _format_boot          # 4. 부트 파티션 포맷
    _format_root          # 5. Btrfs 포맷 + 서브볼륨
    _mount_partitions     # 6. 마운트
    _move_repo            # 7. /tmp/nixos-setup-repo → /mnt/etc/nixos
    _create_host_profile  # 8. 신규 호스트 프로파일 생성
    _resolve_metadata     # 9. nixup.task-resolve.py 실행 → RESOLVE_TMP
    _extract_username     # 10. base.toml → USERNAME
    _prepare_build_dir    # 11. /tmp/nixos-build 구성 (BUILD_DIR 설정됨)
    _generate_hw_config   # 12. _hardware.nix → BUILD_DIR에 직접 생성
    _install_nixos        # 13. nixos-install
    _post_process         # 14. mv, chown, symlink

    echo ""
    log_msg "Success" "installation complete. reboot → TTY login → 'nixup home' → re-login."
}
