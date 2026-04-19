#!/usr/bin/env bash
# shellcheck disable=SC2153

# Constants
# shellcheck disable=SC2034
BUILD_DIR="$NIXOS_PATH/.build"
JSON_DIR="/tmp/nixup-json"
SESSION_LOCK="/tmp/nixup-build.lock"
LOG_DIR="/var/log/nixup"
NIX_FLAKE_FLAGS=(--extra-experimental-features 'nix-command flakes')

# 1. Setup Logging (Clean YYYYMMDDTHHMMSS.log format)
setup_logging() {
    local timestamp=$1
    local user_name=$USER

    if [ ! -d "$LOG_DIR" ] || [ ! -w "$LOG_DIR" ]; then
        log_msg "Notice" "log directory permission issue detected."
        read -rp "$(printf "${YELLOW}%-15s${NC} | setup log directory with sudo? (Y/n): " "NIXUP Question")" CONFIRM

        if [[ "$CONFIRM" =~ ^[Yy]$ ]] || [ -z "$CONFIRM" ]; then
            sudo mkdir -p "$LOG_DIR"
            sudo chown -R "$user_name:users" "$LOG_DIR"
            sudo chmod -R 775 "$LOG_DIR"
            log_msg "Init" "log directory prepared."
        else
            log_msg "Init" "logging disabled for this session."
            return 1
        fi
    fi

    LOG_FILE="$LOG_DIR/${timestamp}.log"
    exec > >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")) 2>&1
    return 0
}

# 2. Acquire Lock
acquire_lock() {
    exec 9> "$SESSION_LOCK"
    if ! flock -n 9; then
        log_msg "Error" "another build process is already running." >&2
        exit 1
    fi
}

# 3. Update .env Utility (순수 bash — sed 구분자/정규식 문제 회피)
update_env_file() {
    local env_path=$1 key=$2 value=$3
    if [ ! -f "$env_path" ]; then
        echo "$key=$value" > "$env_path"
        return
    fi
    local updated=false
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" == "${key}="* ]]; then
            echo "$key=$value"
            updated=true
        else
            echo "$line"
        fi
    done < "$env_path" > "${env_path}.tmp"
    if [ "$updated" = false ]; then
        echo "$key=$value" >> "${env_path}.tmp"
    fi
    mv "${env_path}.tmp" "$env_path"
}

# 4. Resolve Host Info
resolve_host_info() {
    local target_profile=$1
    local env_file=$2

    if [ "$target_profile" == "iso" ]; then
        echo "nixos-iso true"
        return
    fi

    # NIXUP_LAST_HOST 우선 (.env에서 로드된 값).
    # 없으면 OS hostname으로 fallback (nixos-iso 계열이면 거부).
    local host_id="${NIXUP_LAST_HOST:-}"
    if [ -z "$host_id" ]; then
        local os_host
        os_host=$(hostname -s 2>/dev/null || true)
        if [[ "$os_host" == nixos* ]]; then
            log_msg "Error" "NIXUP_LAST_HOST is not set and OS hostname looks like a live ISO ($os_host)."
            exit 1
        fi
        host_id="$os_host"
        log_msg "Notice" "NIXUP_LAST_HOST not set — using OS hostname: $host_id"
    fi

    local resolved_path="$JSON_DIR/resolved.json"
    if [ ! -f "$resolved_path" ]; then
        log_msg "Error" "resolved.json not found. resolver may have failed."
        exit 1
    fi
    if ! jq -e ".\"$host_id\"" "$resolved_path" > /dev/null 2>&1; then
        log_msg "Error" "'$host_id' is not a registered host."
        exit 1
    fi
    [ -n "$env_file" ] && update_env_file "$env_file" "NIXUP_LAST_HOST" "$host_id"
    local is_rolling
    is_rolling=$(jq -r ".\"$host_id\".isRolling" "$resolved_path")
    echo "$host_id $is_rolling"
}

# 5. Prepare Build Dir
prepare_build_dir() {
    local source_path=$1
    local build_dir=$2
    local env_file=$3
    local lock_file="${4:-}"

    log_msg "Task" "preparing isolated environment..."

    if [ -z "$build_dir" ]; then
        log_msg "Error" "build_dir is empty. aborting."
        exit 1
    fi

    if [ -L "$build_dir" ]; then
        rm -f "$build_dir"
    fi

    if [ -d "$build_dir" ]; then
        # 댕글링 *.iso 심볼릭링크 제거 (재부팅 후 /tmp 초기화로 대상 파일이 사라진 경우)
        # (-xtype l: 심볼릭링크를 역참조했을 때도 l 타입 → 대상이 존재하지 않는 댕글링 링크)
        find "$build_dir" -mindepth 1 -maxdepth 1 -name '*.iso' -xtype l -exec rm -f {} +
        find "$build_dir" -mindepth 1 -maxdepth 1 ! -name '*.iso' ! -name 'flake.lock' -exec rm -rf {} +
    else
        mkdir -p "$build_dir"
    fi

    # core/는 디렉터리 그대로 복사, flake.nix만 루트에 단독 배치
    cp -a "$source_path/core" "$build_dir/"
    cp -a "$source_path/hosts" "$build_dir/"
    cp -a "$source_path/mods" "$build_dir/"
    cp "$source_path/core/flake.nix" "$build_dir/flake.nix"

    [ -f "$env_file" ] && cp -a "$env_file" "$build_dir/.env"

    # resolved.json + presets.json (JSON_DIR → build_dir 루트)
    cp "$JSON_DIR/resolved.json" "$build_dir/"
    cp "$JSON_DIR/presets.json" "$build_dir/"

    if [ -n "$lock_file" ] && [ -f "$lock_file" ]; then
        cp "$lock_file" "$build_dir/flake.lock"
    fi
    # nix는 path: 모드로 호출 — git 추적 없이 BUILD_DIR을 store에 직접 복사하여 순수 평가
}

# 6. Finalize Lock Sync
finalize_lock_sync() {
    local lock_changed=$1
    local target_lock_path=$2
    if [ "$lock_changed" = true ]; then
        log_msg "Notice" "lock file updated: $target_lock_path"
        log_msg "Notice" "please review and commit changes."
    fi
}

# 7. Git Status Check
check_origin_git_status() {
    local origin_path=$1
    if [ -d "$origin_path/.git" ]; then
        local status_out
        status_out=$(git -C "$origin_path" status --porcelain 2>/dev/null)
        if [ -n "$status_out" ]; then
            log_msg "Notice" "uncommitted changes found in repository."
            log_msg "Notice" "consider committing to save history."
        fi
    fi
}

# 8. Resolve Log Name
# 메인 로그: 타임스탬프만 (20260414T210920.log)
# 서브 로그: 타임스탬프.타입.log (예: 20260414T210920.nom-build.log)
resolve_log_name() {
    echo "$LOG_TIMESTAMP"
}

# 9. Signal Handler
handle_signal() {
    local sig="${1:-UNKNOWN}"
    log_msg "Error" "Process interrupted by user. ($sig)"
    exit 130
}

# 10. Cleanup (EXIT trap 핸들러 — 실행 요약 및 후처리)
cleanup() {
    END_TIME_RAW=$(date +%s)
    END_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
    DURATION=$((END_TIME_RAW - START_TIME_RAW))

    if [ "$IS_SUCCESS" != true ]; then
        log_msg "Error" "Process terminated abnormally."
    fi

    log_msg "Summary" "Started:  $START_TIME_STR"
    log_msg "Summary" "Finished: $END_TIME_STR"
    log_msg "Summary" "Duration: ${DURATION}s"
    log_msg "Summary" "Log File: ${LOG_FILE:-disabled}"

    rm -f "$NIXOS_PATH"/result "$NIXOS_PATH"/result-*
    check_origin_git_status "$NIXOS_PATH"
    if [ -n "${HOST_SPECIFIC_LOCK:-}" ]; then
        finalize_lock_sync "$LOCK_CHANGED" "$HOST_SPECIFIC_LOCK"
    fi

    rotate_logs
}

# 11. Log Rotation
rotate_logs() {
    mkdir -p "$LOG_DIR" 2>/dev/null
    find "$LOG_DIR" -maxdepth 1 -name '*.log' -type f -printf '%T@\t%p\0' 2>/dev/null \
        | sort -rzn | tail -z -n +31 | cut -z -f2- | xargs -0 rm -f 2>/dev/null || true
}
