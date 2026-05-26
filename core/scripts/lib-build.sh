#!/usr/bin/env bash
# shellcheck disable=SC2153

# Constants
# shellcheck disable=SC2034
BUILD_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/nixos/build"
JSON_DIR="/tmp/nixup-json"
SESSION_LOCK="/tmp/nixup-build.lock"
LOG_DIR="/var/log/nixup"
NIX_FLAKE_FLAGS=(--extra-experimental-features 'nix-command flakes')

# 1. Setup Logging (Clean YYYYMMDDTHHMMSS.log format)
setup_logging() {
    local timestamp=$1
    local user_name=$USER

    if [ ! -d "$LOG_DIR" ] || [ ! -w "$LOG_DIR" ]; then
        log_msg "Notice" "로그 디렉토리 권한 문제가 감지되었습니다."
        read -rp "$(_log_prompt)sudo로 로그 디렉토리를 설정하시겠습니까? (Y/n): " CONFIRM

        if [[ "$CONFIRM" =~ ^[Yy]$ ]] || [ -z "$CONFIRM" ]; then
            sudo mkdir -p "$LOG_DIR"
            sudo chown -R "$user_name:users" "$LOG_DIR"
            sudo chmod -R 775 "$LOG_DIR"
            log_msg "Init" "로그 디렉토리 준비 완료."
        else
            log_msg "Init" "이번 세션에서 로깅이 비활성화됩니다."
            return 1
        fi
    fi

    LOG_FILE="$LOG_DIR/${timestamp}.log"
    exec > >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")) 2>&1
    return 0
}

# 2. Acquire Lock (PID 기반 스테일 감지 포함)
acquire_lock() {
    exec 9> "$SESSION_LOCK"
    if ! flock -n 9; then
        local held_pid
        held_pid=$(cat "$SESSION_LOCK" 2>/dev/null || echo "")
        if [ -n "$held_pid" ] && ! kill -0 "$held_pid" 2>/dev/null; then
            # PID가 죽어있으나 락이 유지 중 (자식 프로세스 fd 상속 케이스)
            log_msg "Warn" "이전 프로세스(PID $held_pid)의 잔여 락을 정리합니다."
            rm -f "$SESSION_LOCK"
            exec 9> "$SESSION_LOCK"
            flock -n 9 || {
                log_msg "Error" "락 해제 실패. 수동 확인: lsof $SESSION_LOCK" >&2
                exit 1
            }
        else
            log_msg "Error" "이미 실행 중인 nixup이 있습니다 (PID: ${held_pid:-unknown})." >&2
            log_msg "Error" "종료 후 재시도하거나, 프로세스가 없으면: rm $SESSION_LOCK" >&2
            exit 1
        fi
    fi
    echo "$$" >&9
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
            log_msg "Error" "NIXUP_LAST_HOST가 설정되지 않았으며 OS 호스트명이 라이브 ISO로 보입니다 ($os_host)."
            exit 1
        fi
        host_id="$os_host"
        log_msg "Notice" "NIXUP_LAST_HOST 미설정 — OS 호스트명 사용: $host_id"
    fi

    local resolved_path="$JSON_DIR/resolved.json"
    if [ ! -f "$resolved_path" ]; then
        log_msg "Error" "resolved.json을 찾을 수 없습니다. resolver 실패 가능성이 있습니다."
        exit 1
    fi
    if ! jq -e ".\"$host_id\"" "$resolved_path" > /dev/null 2>&1; then
        log_msg "Error" "'$host_id'은(는) 등록된 호스트가 아닙니다."
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

    log_msg "Task" "격리된 빌드 환경 준비 중..."

    if [ -z "$build_dir" ]; then
        log_msg "Error" "build_dir가 비어 있습니다. 중단합니다."
        exit 1
    fi

    if [ -L "$build_dir" ]; then
        rm -f "$build_dir"
    fi

    if [ -d "$build_dir" ]; then
        # 댕글링 *.iso 심볼릭링크 제거 (재부팅 후 /tmp 초기화로 대상 파일이 사라진 경우)
        # (-xtype l: 심볼릭링크를 역참조했을 때도 l 타입 → 대상이 존재하지 않는 댕글링 링크)
        find "$build_dir" -mindepth 1 -maxdepth 1 -name '*.iso' -xtype l -exec rm -f {} +
        find "$build_dir" -mindepth 1 -maxdepth 1 ! -name '*.iso' ! -name 'flake.lock' ! -name 'hardware.nix' -exec rm -rf {} +
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

    # hardware.nix: 없을 때만 생성 (flake.lock처럼 .build/에 캐시)
    # 하드웨어가 바뀌면 .build/hardware.nix를 삭제해서 강제 재생성
    # (sudo 필요: nixos-generate-config가 Btrfs 서브볼륨 쿼리 등에 root 권한을 요구함)
    if [ ! -s "$build_dir/hardware.nix" ]; then
        log_msg "Prep" "hardware.nix 생성 중..."
        sudo nixos-generate-config --no-filesystems --show-hardware-config | sudo tee "$build_dir/hardware.nix" > /dev/null
    fi
    # nix는 path: 모드로 호출 — git 추적 없이 BUILD_DIR을 store에 직접 복사하여 순수 평가
}

# 6. Finalize Lock Sync
finalize_lock_sync() {
    local lock_changed=$1
    local target_lock_path=$2
    if [ "$lock_changed" = true ]; then
        log_msg "Notice" "lock 파일 업데이트됨: $target_lock_path"
        log_msg "Notice" "변경사항을 확인하고 커밋하세요."
    fi
}

# 7. Git Status Check
check_origin_git_status() {
    local origin_path=$1
    if [ -d "$origin_path/.git" ]; then
        local status_out
        status_out=$(git -C "$origin_path" status --porcelain 2>/dev/null)
        if [ -n "$status_out" ]; then
            log_msg "Notice" "커밋되지 않은 변경사항이 있습니다."
            log_msg "Notice" "히스토리 보존을 위해 커밋하는 것을 권장합니다."
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
    log_msg "Error" "사용자에 의해 중단되었습니다. ($sig)"
    exit 130
}

# 10. Cleanup (EXIT trap 핸들러 — 실행 요약 및 후처리)
cleanup() {
    [ -n "${SUDO_KEEPALIVE_PID:-}" ] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
    preauth_cleanup_tmp_key 2>/dev/null || true

    if [ "$IS_SUCCESS" != true ]; then
        log_msg "Error" "비정상 종료."
    fi

    _print_summary
    log_msg "Summary" "로그:    ${LOG_FILE:-disabled}"

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
