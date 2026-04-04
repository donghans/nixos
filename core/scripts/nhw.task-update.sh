#!/usr/bin/env bash

# 태스크 로직 함수
run_update_task() {
    echo "[nhw:task] Updating lock for $HOST_ID..."
    [ -f "$HOST_SPECIFIC_LOCK" ] && cp "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"
    init_tmp_git "$TMP_BUILD_DIR"

    nix flake update --flake "$TMP_BUILD_DIR"

    if [ ! -f "$HOST_SPECIFIC_LOCK" ] || ! cmp -s "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"; then
        cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
        LOCK_CHANGED=true
        echo "[nhw] Update complete. Saved to $HOST_SPECIFIC_LOCK"
    else
        echo "[nhw] No changes in flake.lock"
    fi
}

# 직접 실행 시 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "[nhw:notice] Redirecting to nhw update..."
    exec nhw update
fi

# nhw.sh에 의해 source된 경우 실행
run_update_task
exit 0
