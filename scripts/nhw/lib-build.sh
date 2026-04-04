#!/usr/bin/env bash

# 공통 상수 정의
TMP_BUILD_DIR="/tmp/nixos-build"
LOCK_FILE="/tmp/nixos-build.lock"

# 1. 중복 실행 방지 락
acquire_lock() {
    exec 9> "$LOCK_FILE"
    if ! flock -n 9; then
        echo "❌ Error: 다른 빌드 스크립트가 이미 실행 중입니다." >&2
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
        echo "❌ Error: Host ID가 필요합니다. (또는 .env의 HOST 변수 확인)" >&2
        exit 1
    fi

    if [[ "$host_id" =~ ^_?default$ ]]; then
        echo "_default false"
    else
        local host_config=$(jq -e ".hosts[] | select(.hostname == \"$host_id\")" "$info_json" 2>/dev/null)
        if [ $? -ne 0 ]; then
            echo "❌ Error: '$host_id'는 등록되지 않은 호스트입니다." >&2
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

    echo "🔗 Preparing isolated build environment in $build_dir..."
    rm -rf "$build_dir"
    mkdir -p "$build_dir"
    
    cp -a "$source_path/core/"* "$build_dir/"
    cp -a "$source_path/dev" "$build_dir/"
    cp -a "$source_path/lib" "$build_dir/"
    [ -f "$env_file" ] && cp -a "$env_file" "$build_dir/.env"
    
    ln -sfn "$build_dir" "$source_path/.build"
}

# 5. 임시 Git 초기화
init_tmp_git() {
    local build_dir=$1
    git -C "$build_dir" init >/dev/null 2>&1
    git -C "$build_dir" add -A >/dev/null 2>&1
}

# 6. Lock 파일 역동기화 알림/처리
finalize_lock_sync() {
    local lock_changed=$1
    local target_lock_path=$2
    if [ "$lock_changed" = true ]; then
        echo -e "\n📝 [Notice] Lock file has been updated: $target_lock_path"
        echo "   Please review and commit the changes."
    fi
}
