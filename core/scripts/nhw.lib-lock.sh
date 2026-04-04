#!/usr/bin/env bash

# Lock Strategy Implementation
apply_lock_strategy() {
    local is_rolling=$1
    local stable_lock_path=$2
    local target_lock=$3
    local stable_locks_dir=$4
    local tmp_build_dir=$5

    local final_source_lock="$stable_lock_path"

    # Rolling Strategy
    if [ "$is_rolling" == "true" ]; then
        log_msg "Lock" "rolling: updating nixpkgs-unstable..."
        [ -f "$final_source_lock" ] && cp "$final_source_lock" "$target_lock"
        
        init_tmp_git "$tmp_build_dir"

        if [ -f "$target_lock" ]; then
            nix flake update --flake "$tmp_build_dir" nixpkgs-unstable
        else
            nix flake update --flake "$tmp_build_dir"
        fi
        
        if [ ! -f "$final_source_lock" ] || ! cmp -s "$final_source_lock" "$target_lock"; then
            cp "$target_lock" "$final_source_lock"
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
