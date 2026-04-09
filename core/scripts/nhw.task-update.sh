#!/usr/bin/env bash

run_update_task() {
    log_msg "Task" "attempting to update flake.lock for $HOST_ID..."
    [ -f "$HOST_SPECIFIC_LOCK" ] && cp "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"
    init_tmp_git "$TMP_BUILD_DIR"

    log_exec "nix" ">" "nix flake update"
    (cd "$TMP_BUILD_DIR" && nix flake update --refresh)
    # 스테이징을 해주어야 이후 cmp 비교 등이 정확함
    git -C "$TMP_BUILD_DIR" add -A >/dev/null 2>&1
    log_exec "nix" "<" "nix flake update"

    if [ ! -f "$HOST_SPECIFIC_LOCK" ] || ! cmp -s "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"; then
        cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
        # shellcheck disable=SC2034
        LOCK_CHANGED=true
        log_msg "Done" "update complete. saved to $HOST_SPECIFIC_LOCK"
    else
        log_msg "Info" "no changes detected in flake.lock"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw update..."
    exec nhw update
fi

run_update_task
