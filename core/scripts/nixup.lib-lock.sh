#!/usr/bin/env bash

# Lock Strategy Implementation
apply_lock_strategy() {
    local is_rolling=$1
    local stable_lock_path=$2
    local target_lock=$3
    local build_dir=$4

    local final_source_lock="$stable_lock_path"

    # Rolling Strategy
    if [ "$is_rolling" == "true" ]; then
        log_msg "Lock" "rolling: nixpkgs-unstable 업데이트 중..."
        [ -f "$final_source_lock" ] && cp "$final_source_lock" "$target_lock"

        if [ -f "$target_lock" ]; then
            log_exec "nix" ">" "nix flake update nixpkgs-unstable"
            nix flake update nixpkgs-unstable --refresh --flake "path:$build_dir"
            log_exec "nix" "<" "nix flake update nixpkgs-unstable"
        else
            log_exec "nix" ">" "nix flake update"
            nix flake update --refresh --flake "path:$build_dir"
            log_exec "nix" "<" "nix flake update"
        fi

        if [ ! -f "$final_source_lock" ] || ! cmp -s "$final_source_lock" "$target_lock"; then
            cp "$target_lock" "$final_source_lock"
            # shellcheck disable=SC2034
            LOCK_CHANGED=true
            log_msg "Lock" "lock 파일 업데이트됨"
        fi
    else
        # Stable Strategy
        if [ -f "$final_source_lock" ]; then
            cp "$final_source_lock" "$target_lock"
        else
            log_msg "Error" "lock 파일을 찾을 수 없습니다: $final_source_lock"
            log_msg "Error" "  → 초기 lock을 수동으로 생성하세요:"
            log_msg "Error" "    cp $(dirname "$final_source_lock")/_rolling.lock $final_source_lock"
            exit 1
        fi
    fi
}
