#!/usr/bin/env bash

# 태스크 로직 함수
run_nh_task() {
    init_tmp_git "$TMP_BUILD_DIR"

    echo "[nhw:task] Building #$HOST_ID ($SCOPE $ACTION)..."
    if [ "$SCOPE" == "os" ]; then
        nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID"
    else
        nh home "$ACTION" "$TMP_BUILD_DIR"
    fi
}

# 직접 실행 시 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "[nhw:notice] Redirecting to nhw dispatcher..."
    exec nhw "$@"
fi

# nhw.sh에 의해 source된 경우 실행
run_nh_task
