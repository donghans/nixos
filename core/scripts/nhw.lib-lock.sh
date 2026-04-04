#!/usr/bin/env bash

# 락 전략 적용 함수
apply_lock_strategy() {
    local is_rolling=$1
    local stable_lock_path=$2
    local target_lock=$3
    local stable_locks_dir=$4
    local tmp_build_dir=$5

    local final_source_lock="$stable_lock_path"

    # Rolling 여부에 따른 처리
    if [ "$is_rolling" == "true" ]; then
        echo "[nhw:lock] Rolling: Updating unstable only..."
        [ -f "$final_source_lock" ] && cp "$final_source_lock" "$target_lock"
        
        # Git 상태 초기화 (nix flake update를 위해 필요)
        init_tmp_git "$tmp_build_dir"

        # 락 파일이 있으면 unstable만, 없으면 전체 업데이트
        if [ -f "$target_lock" ]; then
            nix flake update --flake "$tmp_build_dir" nixpkgs-unstable
        else
            nix flake update --flake "$tmp_build_dir"
        fi
        
        # 변경 사항 있으면 원본으로 역동기화 예약
        if [ ! -f "$final_source_lock" ] || ! cmp -s "$final_source_lock" "$target_lock"; then
            cp "$target_lock" "$final_source_lock"
            LOCK_CHANGED=true
            echo "[nhw:lock] Lock file updated"
        fi
    else
        # Stable: 기존 락 파일이 반드시 있어야 함
        if [ -f "$final_source_lock" ]; then
            cp "$final_source_lock" "$target_lock"
        else
            echo "[nhw:error] Lock not found ($final_source_lock)."; exit 1
        fi
    fi
}
