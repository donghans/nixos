#!/usr/bin/env bash

# Constants
# shellcheck disable=SC2034
TMP_BUILD_DIR="/tmp/nixos-build"
LOCK_FILE="/tmp/nixos-build.lock"
LOG_DIR="/var/log/nhw"

# ANSI Colors
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
        Init)    cat_color=$CYAN ;;
        Task)    cat_color=$PURPLE ;;
        Summary) cat_color=$NC ;;
        Done|Success) cat_color=$GREEN ;;
        Error)   cat_color=$RED ;;
        Notice|Warn)  cat_color=$YELLOW ;;
        Prep)    cat_color=$CYAN ;;
        *)       cat_color=$NC ;;
    esac

    # Format: NHW [9-char-category] | [msg]
    printf "${CYAN}NHW${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# Command Execution Helper (Aligned with | marker)
log_exec() {
    local cmd_name=$1 # e.g., nh, nix, nom
    local state=$2    # > or <
    local msg=$3      # description
    local cat_color=$BLUE
    
    # Matches NHW's aligned format: NHW Exec cmd > description
    printf "${CYAN}NHW${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# 1. Setup Logging (Clean YYYYMMDDTHHMMSS.log format)
setup_logging() {
    local timestamp=$1
    local user_name=$USER
    
    if [ ! -d "$LOG_DIR" ] || [ ! -w "$LOG_DIR" ]; then
        log_msg "Notice" "log directory permission issue detected."
        read -rp "$(printf "${YELLOW}%-13s${NC} | setup log directory with sudo? (Y/n): " "NHW Question")" CONFIRM
        
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

    # Removed 'nhw_' prefix as requested
    LOG_FILE="$LOG_DIR/${timestamp}.log"
    exec > >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")) 2>&1
    return 0
}

# 2. Acquire Lock
acquire_lock() {
    exec 9> "$LOCK_FILE"
    if ! flock -n 9; then
        log_msg "Error" "another build process is already running." "$RED" >&2
        exit 1
    fi
}

# 3. Update .env Utility
update_env_file() {
    local env_path=$1
    local key=$2
    local value=$3
    if [ ! -f "$env_path" ]; then
        echo "$key=$value" > "$env_path"
    elif grep -q "^$key=" "$env_path"; then
        sed -i "s|^$key=.*|$key=$value|" "$env_path"
    else
        echo "$key=$value" >> "$env_path"
    fi
}

# 4. Determine Host Info
determine_host_info() {
    local scope=$1
    local input_host=$2
    local env_file=$3
    local info_json=$4

    if [ "$scope" == "iso" ]; then
        echo "nixos-iso true"
        return
    fi

    local host_id="$input_host"
    [ -z "$host_id" ] && host_id="$HOST"
    if [ -z "$host_id" ]; then
        log_msg "Error" "host id is required."
        exit 1
    fi

    if [[ "$host_id" =~ ^_?default$ ]]; then
        echo "_default false"
    else
        local host_config
        if ! host_config=$(jq -e ".hosts[] | select(.hostname == \"$host_id\")" "$info_json" 2>/dev/null); then
            log_msg "Error" "'$host_id' is not a registered host."
            exit 1
        fi
        update_env_file "$env_file" "HOST" "$host_id"
        local is_rolling
        is_rolling=$(echo "$host_config" | jq -r '.isRolling')
        echo "$host_id $is_rolling"
    fi
}

# 5. Prepare Build Dir
prepare_build_dir() {
    local source_path=$1
    local build_dir=$2
    local env_file=$3

    log_msg "Task" "preparing isolated environment..."
    rm -rf "$build_dir"
    mkdir -p "$build_dir"
    
    cp -a "$source_path/core/"* "$build_dir/"
    cp -a "$source_path/dev" "$build_dir/"
    cp -a "$source_path/lib" "$build_dir/"
    [ -f "$env_file" ] && cp -a "$env_file" "$build_dir/.env"
    
    ln -sfn "$build_dir" "$source_path/.build"
}

# 6. Init Tmp Git
init_tmp_git() {
    local build_dir=$1
    if [ ! -d "$build_dir/.git" ]; then
        git -C "$build_dir" init >/dev/null 2>&1
        git -C "$build_dir" config user.email "nhw@tmp.repo" >/dev/null 2>&1
        git -C "$build_dir" config user.name "nhw-bot" >/dev/null 2>&1
    fi
    git -C "$build_dir" add -A >/dev/null 2>&1
    git -C "$build_dir" commit -m "temp: build environment" >/dev/null 2>&1
}

# 7. Finalize Lock Sync
finalize_lock_sync() {
    local lock_changed=$1
    local target_lock_path=$2
    if [ "$lock_changed" = true ]; then
        log_msg "Notice" "lock file updated: $target_lock_path"
        log_msg "Notice" "please review and commit changes."
    fi
}

# 8. Git Status Check
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

# 9. Log Rotation
rotate_logs() {
    mkdir -p "$LOG_DIR" 2>/dev/null
    # shellcheck disable=SC2012
    ls -t "$LOG_DIR"/*.log 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true
}
