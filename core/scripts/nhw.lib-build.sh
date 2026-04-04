#!/usr/bin/env bash

# 공통 상수 정의
TMP_BUILD_DIR="/tmp/nixos-build"
LOCK_FILE="/tmp/nixos-build.lock"

# 1. 중복 실행 방지 락
acquire_lock() {
    exec 9> "$LOCK_FILE"
    if ! flock -n 9; then
        echo "[nhw:error] 다른 빌드 작업이 이미 진행 중입니다." >&2
        exit 1
    fi
}

# 2. .env 업데이트 유틸리티
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

# 3. 호스트 정보 결정 함수
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
        echo "[nhw:error] Host ID가 필요합니다. (nhw <host_id> ...)" >&2
        exit 1
    fi

    if [[ "$host_id" =~ ^_?default$ ]]; then
        echo "_default false"
    else
        local host_config=$(jq -e ".hosts[] | select(.hostname == \"$host_id\")" "$info_json" 2>/dev/null)
        if [ $? -ne 0 ]; then
            echo "[nhw:error] '$host_id'는 등록되지 않은 호스트입니다." >&2
            exit 1
        fi
        update_env_file "$env_file" "HOST" "$host_id"
        local is_rolling=$(echo "$host_config" | jq -r '.isRolling')
        echo "$host_id $is_rolling"
    fi
}

# 4. 격리된 빌드 디렉토리 준비
prepare_build_dir() {
    local source_path=$1
    local build_dir=$2
    local env_file=$3

    echo "[nhw] Preparing isolated build environment in $build_dir..."
    rm -rf "$build_dir"
    mkdir -p "$build_dir"
    
    cp -a "$source_path/core/"* "$build_dir/"
    cp -a "$source_path/dev" "$build_dir/"
    cp -a "$source_path/lib" "$build_dir/"
    [ -f "$env_file" ] && cp -a "$env_file" "$build_dir/.env"
    
    ln -sfn "$build_dir" "$source_path/.build"
}

# 5. 임시 Git 초기화 (Nix Dirty 경고 차단을 위해 커밋까지 수행)
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

# 6. Lock 파일 역동기화 알림/처리
finalize_lock_sync() {
    local lock_changed=$1
    local target_lock_path=$2
    if [ "$lock_changed" = true ]; then
        echo -e "\n[nhw:notice] Lock file updated: $target_lock_path"
        echo "   Please review and commit the changes."
    fi
}

# 7. 원본 레포지토리 Git 상태 체크 (정밀 수정)
check_origin_git_status() {
    local origin_path=$1
    if [ -d "$origin_path/.git" ]; then
        # --porcelain 옵션은 변경 사항이 없으면 아예 아무것도 출력하지 않음
        local status_out
        status_out=$(git -C "$origin_path" status --porcelain 2>/dev/null)
        if [ -n "$status_out" ]; then
            echo -e "\n[nhw:notice] 원본 레포지토리에 커밋되지 않은 변경 사항이 있습니다."
            echo "   기록을 남기려면 'git add' 및 'commit'을 진행해 주세요."
        fi
    fi
}
