#!/usr/bin/env bash

run_nh_task() {
    init_tmp_git "$TMP_BUILD_DIR"

    log_msg "Task" "building configuration for #$HOST_ID..."
    echo "" # nh 빌드 로그 시작 전 여백 추가
    
    if [ "$SCOPE" == "os" ]; then
        nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID"
    else
        nh home "$ACTION" "$TMP_BUILD_DIR"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw "$@"
fi

run_nh_task
