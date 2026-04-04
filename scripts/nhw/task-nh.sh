#!/usr/bin/env bash

# 태스크 로직 함수
run_nh_task() {
    init_tmp_git "$TMP_BUILD_DIR"

    echo "🚀 [nh] Building #$HOST_ID ($SCOPE $ACTION)"
    if [ "$SCOPE" == "os" ]; then
        nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID"
    else
        nh home "$ACTION" "$TMP_BUILD_DIR"
    fi
}

# 직접 실행 시 nhw.sh로 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "⚠️  직접 실행 감지: nhw.sh 환경으로 전환합니다..."
    # 인자가 없으므로 nhw.sh를 기본값으로 실행하게 함
    exec "$(dirname "$0")/../../nhw.sh" "$@"
fi

# nhw.sh에 의해 source된 경우 실행
run_nh_task
