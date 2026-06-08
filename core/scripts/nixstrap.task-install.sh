#!/usr/bin/env bash
# nixstrap.task-install.sh — Phase 2 설치 실행 함수
# shellcheck disable=SC1091

source "$SCRIPT_DIR/nixstrap.lib-preauth.sh"

_cleanup_mounts() {
    # 재시도 시 이전 마운트가 남아있으면 mkfs.*가 "contains a mounted filesystem"으로 실패함
    # swapoff → 역순 umount (boot → log → nix → home → /) 후 /mnt 자체 해제
    if mountpoint -q /mnt 2>/dev/null; then
        log_msg "Mount" "/mnt 이전 마운트 정리 중..."
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
    log_msg "Config" "디스크 레이블: boot=$BOOT_LABEL, root=$DISK_LABEL"
}

_create_partitions() {
    [[ "$_NEW_PARTITIONS" != "true" ]] && return

    log_msg "Disk" "$_DISK 에 파티션 생성 중..."
    log_exec "disk" ">" "parted"
    if [[ "$_WIPE" == "true" ]]; then
        parted "$_DISK" --script mklabel gpt
    fi
    parted "$_DISK" --script mkpart ESP fat32 "$_PART_START" "$_BOOT_END"
    parted "$_DISK" --script set "$_NEW_BOOT_NUM" esp on
    parted "$_DISK" --script mkpart primary "$_BOOT_END" "$_PART_END"
    log_exec "disk" "<" "parted"

    log_msg "Disk" "udev 대기 중..."
    udevadm settle --timeout=10
    log_msg "Disk" "파티션 준비 완료: boot=$BOOT_PART, root=$ROOT_PART"
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
    local HOST_TOML="/mnt/etc/nixos/hosts/$HOST.toml"
    local HOST_NIX="/mnt/etc/nixos/hosts/$HOST.nix"
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

    # 대상 머신 RAM 감지 (nixstrap은 대상 머신에서 직접 실행되므로 /proc/meminfo = 정확한 값)
    local _ram_line=""
    local _ram_gb
    _ram_gb=$(awk '/^MemTotal:/ {printf "%d", int(($2 + 1048575) / 1048576)}' /proc/meminfo 2>/dev/null || true)
    [ -n "$_ram_gb" ] && _ram_line=$'\nramGb = '"$_ram_gb"

    if [[ "$_IS_VM" == "true" ]]; then
        printf 'type = "%s"\npreset = "%s"%s%s%s\n\n[mods.sys.services]\nincus-guest = true\nincus = false\n' \
            "$_type" "$_PRESET" "$_sv_line" "$_username_line" "$_ram_line" > "$HOST_TOML"
        log_msg "Config" "$HOST.toml 에서 incus-guest 활성화, incus 비활성화 (가상화 환경)"
    else
        printf 'type = "%s"\npreset = "%s"%s%s%s\n' "$_type" "$_PRESET" "$_sv_line" "$_username_line" "$_ram_line" > "$HOST_TOML"
    fi

    # deploy-rs 설정 — sshKey는 관리 머신 기준 경로 (자동 생성 시 표준 경로 사용)
    if [ "${_DEPLOY_ENABLED:-false}" = true ]; then
        # shellcheck disable=SC2088  # 틸드는 TOML 값용 리터럴 문자열 (런타임 확장 불필요)
        local _key_ref="~/.ssh/${HOST}_ed25519"
        [ -n "${_DEPLOY_SSH_KEY:-}" ] && _key_ref="${_DEPLOY_SSH_KEY/#$HOME/~}"
        printf '\n[deploy]\nip     = ""\nsshKey = "%s"\n' "$_key_ref" >> "$HOST_TOML"
        log_msg "Config" "deploy-rs [deploy] 섹션 추가 (ip는 첫 부팅 후 설정)"
    fi

    # 최소 통합 호스트 파일 — os/hm 블록 분리 (mkHostConfiguration 패턴)
    printf '{mkHostConfiguration, ...}:\nmkHostConfiguration ({...}: { os = {}; hm = {}; })\n' > "$HOST_NIX"

    local _sv_info="${_STATE_VERSION:-rolling}"
    log_msg "Config" "호스트 프로파일 생성: $HOST (preset=$_PRESET, stateVersion=$_sv_info)"
}

_setup_deploy_pubkey() {
    local _mode="${_SSH_ACCESS_MODE:-}"
    # 구버전 세션 호환: _SSH_ACCESS_MODE 없이 _DEPLOY_ENABLED=true이면 deploy-rs로 처리
    [ -z "$_mode" ] && [ "${_DEPLOY_ENABLED:-false}" = true ] && _mode="deploy-rs"
    [[ "$_mode" != "existing-key" && "$_mode" != "deploy-rs" ]] && return

    local deploy_dir="/mnt/etc/nixos/hosts/_deploy"
    mkdir -p "$deploy_dir"

    if [ -n "${_DEPLOY_SSH_KEY:-}" ]; then
        # 기존 키 사용 — pub key 추출
        local pub_key
        pub_key=$(ssh-keygen -y -f "$_DEPLOY_SSH_KEY" 2>/dev/null)
        if [ -z "$pub_key" ]; then
            log_msg "Error" "SSH 공개키 추출 실패: $_DEPLOY_SSH_KEY"
            exit 1
        fi
        printf '%s %s\n' "$pub_key" "$HOST" > "$deploy_dir/${HOST}.pub"
        log_msg "Done" "SSH pub key 등록: hosts/_deploy/${HOST}.pub"
    else
        # 신규 키 생성 (deploy-rs 전용)
        local key_tmp="/tmp/nixstrap-deploy-$$"
        rm -f "$key_tmp" "${key_tmp}.pub"
        ssh-keygen -t ed25519 -f "$key_tmp" -N "" -C "$HOST" >/dev/null 2>&1
        cp "${key_tmp}.pub" "$deploy_dir/${HOST}.pub"
        _DEPLOY_SSH_KEY="$key_tmp"
        _DEPLOY_KEY_WAS_GENERATED=true
        log_msg "Done" "SSH 키 생성 및 pub key 등록: hosts/_deploy/${HOST}.pub"
    fi
}

_save_deploy_pem() {
    [ "${_DEPLOY_KEY_WAS_GENERATED:-false}" != true ] && return

    local ssh_dir="/mnt/home/$USERNAME/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    local pem_name="${HOST}_ed25519"
    cp "$_DEPLOY_SSH_KEY" "$ssh_dir/$pem_name"
    chmod 600 "$ssh_dir/$pem_name"
    nixos-enter --root /mnt --command \
        "chown -R $USERNAME:users /home/$USERNAME/.ssh"

    printf "\n"
    log_msg "Done" "SSH 프라이빗 키 저장: ~/.ssh/$pem_name"
    log_msg "Notice" "▶  첫 부팅 후 관리 머신으로 복사하세요:"
    log_msg "Notice" "   scp ${USERNAME}@<IP>:~/.ssh/${pem_name} ~/.ssh/${pem_name}"
    log_msg "Notice" "   복사 후 TOML [deploy].ip와 sshKey를 관리 머신 기준으로 업데이트하세요."
}

_commit_deploy_files() {
    local _mode="${_SSH_ACCESS_MODE:-}"
    [ -z "$_mode" ] && [ "${_DEPLOY_ENABLED:-false}" = true ] && _mode="deploy-rs"
    [[ "$_mode" != "existing-key" && "$_mode" != "deploy-rs" ]] && return

    local _commit_msg
    if [[ "$_mode" == "deploy-rs" ]]; then
        _commit_msg="feat: ${HOST} deploy-rs 설정 추가"
    else
        _commit_msg="feat: ${HOST} SSH 공개키 등록"
    fi

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
    _format_boot            # 4. 부트 파티션 포맷
    _format_root            # 5. Btrfs 포맷 + 서브볼륨
    _mount_partitions       # 6. 마운트
    _move_repo              # 7. /tmp/nixos-setup-repo → /mnt/etc/nixos
    _create_host_profile    # 8. 신규 호스트 프로파일 생성 ([deploy] 섹션 포함)
    _setup_deploy_pubkey    # 9. deploy-rs pub key 생성/저장 (deploy-rs 시만)
    _resolve_metadata       # 10. nixup.task-resolve.py 실행 → RESOLVE_TMP
    _extract_username       # 11. base.toml → USERNAME
    _prepare_build_dir      # 12. /tmp/nixos-build 구성 (BUILD_DIR 설정됨, pub key 포함)
    _generate_hw_config     # 13. hardware.nix → BUILD_DIR에 직접 생성
    _install_nixos          # 14. nixos-install
    _post_process           # 15. mv, chown, symlink
    check_preauth_keys_local "$HOST"  # 16. preauth key 생성·배포 → /mnt/var/lib/...
    _save_deploy_pem        # 17. PEM → ~/.ssh/ (자동 생성 키만)
    _commit_deploy_files    # 18. pub key + TOML 커밋 + push 시도

    echo ""
    log_msg "Success" "설치 완료. 재부팅 → TTY 로그인 → 'nixup home' → 재로그인."
}
