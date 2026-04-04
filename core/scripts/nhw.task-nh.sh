#!/usr/bin/env bash

run_nh_task() {
    init_tmp_git "$TMP_BUILD_DIR"

    log_msg "Task" "building configuration for #$HOST_ID..."
    
    log_exec "nh" ">" "nh $TARGET_PROFILE $ACTION"
    if [ "$TARGET_PROFILE" == "os" ]; then
        nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID"
    else
        nh home "$ACTION" "$TMP_BUILD_DIR"
    fi
    log_exec "nh" "<" "nh $TARGET_PROFILE $ACTION"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw "$@"
fi

run_nh_task
