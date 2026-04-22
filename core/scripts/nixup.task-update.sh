#!/usr/bin/env bash

run_update_task() {
    log_msg "Task" "$HOST_ID flake.lock 업데이트 중..."
    [ -f "$HOST_SPECIFIC_LOCK" ] && cp "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"

    log_exec "nix" ">" "nix flake update"
    nix flake update --refresh --flake "path:$BUILD_DIR"
    log_exec "nix" "<" "nix flake update"

    if [ ! -f "$HOST_SPECIFIC_LOCK" ] || ! cmp -s "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"; then
        cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
        # shellcheck disable=SC2034
        LOCK_CHANGED=true
        log_msg "Done" "업데이트 완료. 저장됨: $HOST_SPECIFIC_LOCK"
    else
        log_msg "Notice" "flake.lock 변경 없음"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "nixup update로 전달 중..."
    exec nixup update
fi

run_update_task
