#!/usr/bin/env bash

# 태스크 로직 함수
run_update_task() {
    echo "🔄 Updating lock for $HOST_ID..."
    [ -f "$HOST_SPECIFIC_LOCK" ] && cp "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"
    init_tmp_git "$TMP_BUILD_DIR"

    nix flake update --flake "$TMP_BUILD_DIR"

    if [ ! -f "$HOST_SPECIFIC_LOCK" ] || ! cmp -s "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK"; then
        cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
        LOCK_CHANGED=true
        echo "✅ Update complete. Saved to $HOST_SPECIFIC_LOCK"
    else
        echo "ℹ️ No changes in flake.lock"
    fi
}

# 직접 실행 시 nhw.sh로 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "⚠️  직접 실행 감지: nhw.sh update 환경으로 전환합니다..."
    exec "$(dirname "$0")/../../nhw.sh" update
fi

# nhw.sh에 의해 source된 경우 실행
run_update_task
exit 0
