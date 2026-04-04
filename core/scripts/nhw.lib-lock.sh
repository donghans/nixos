#!/usr/bin/env bash

# Lock Strategy Implementation
apply_lock_strategy() {
    local is_rolling=$1
    local stable_lock_path=$2
    local target_lock=$3
    # shellcheck disable=SC2034
    local LOCK_STORE_DIR=$4
    local tmp_build_dir=$5

    local final_source_lock="$stable_lock_path"

    # Rolling Strategy
    if [ "$is_rolling" == "true" ]; then
        log_msg "Lock" "rolling: updating nixpkgs-unstable..."
        [ -f "$final_source_lock" ] && cp "$final_source_lock" "$target_lock"
        
        init_tmp_git "$tmp_build_dir"

        if [ -f "$target_lock" ]; then
            log_exec "nix" ">" "nix flake update nixpkgs-unstable"
            (cd "$tmp_build_dir" && nix flake update nixpkgs-unstable --refresh)
            # 스테이징을 다시 해주어야 이후 nh os switch 과정에서 Nix가 변경된 락 파일을 인식함
            git -C "$tmp_build_dir" add -A >/dev/null 2>&1
            log_exec "nix" "<" "nix flake update nixpkgs-unstable"
        else
            log_exec "nix" ">" "nix flake update"
            (cd "$tmp_build_dir" && nix flake update --refresh)
            git -C "$tmp_build_dir" add -A >/dev/null 2>&1
            log_exec "nix" "<" "nix flake update"
        fi
        
        if [ ! -f "$final_source_lock" ] || ! cmp -s "$final_source_lock" "$target_lock"; then
            cp "$target_lock" "$final_source_lock"
            # shellcheck disable=SC2034
            LOCK_CHANGED=true
            log_msg "Lock" "lock file updated"
        fi
    else
        # Stable Strategy
        if [ -f "$final_source_lock" ]; then
            cp "$final_source_lock" "$target_lock"
        else
            log_msg "Error" "lock not found: $final_source_lock"
            exit 1
        fi
    fi
}
