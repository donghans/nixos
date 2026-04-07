#!/usr/bin/env bash

# 성공 후 이전/현재 세대 간 패키지 변경사항을 로그에 기록
# test 액션은 새 세대를 만들지 않으므로 제외
_log_nvd_diff() {
    local profile_path=$1
    local label=$2

    [[ "$ACTION" == "test" || "$ACTION" == "build" ]] && return
    [ ! -L "$profile_path" ] && return

    local profile_dir profile_name link_name cur_num prev_num prev_path
    profile_dir=$(dirname "$profile_path")
    profile_name=$(basename "$profile_path")
    link_name=$(readlink "$profile_path")
    cur_num=$(echo "$link_name" | grep -oP '\d+(?=-link)')
    prev_num=$(( cur_num - 1 ))
    prev_path="$profile_dir/${profile_name}-${prev_num}-link"

    [ ! -e "$prev_path" ] && return

    log_exec "nvd" ">" "nvd diff ($label)"
    nvd diff "$prev_path" "$(readlink -f "$profile_path")" || true
    log_exec "nvd" "<" "nvd diff ($label)"
}

run_nh_task() {
    init_tmp_git "$TMP_BUILD_DIR"

    log_msg "Task" "building configuration for #$HOST_ID..."

    # build: result 심볼릭 링크 불필요 (빌드 테스트/캐시 히트 목적)
    # -d never: nh 내장 diff 비활성화 (nvd diff로 로그에 별도 기록)
    # nh 출력은 fd 3(원본 터미널)으로만 보냄 → 로그에 기록 안 됨
    # 실패 시 nix build --print-build-logs로 상세 오류만 로그에 기록
    NH_EXTRA=()
    [ "$ACTION" == "build" ] && NH_EXTRA=("--" "--no-link")

    log_exec "nh" ">" "nh $TARGET_PROFILE $ACTION"
    if [ "$TARGET_PROFILE" == "os" ]; then
        if ! nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID" -d never "${NH_EXTRA[@]}" >&3 2>&3; then
            log_exec "nh" "<" "nh $TARGET_PROFILE $ACTION"
            log_msg "Error" "Build failed. Re-running with full build logs..."
            nix build --print-build-logs \
                "${TMP_BUILD_DIR}#nixosConfigurations.${HOST_ID}.config.system.build.toplevel" \
                --extra-experimental-features 'nix-command flakes' || true
            exit 1
        fi
        log_exec "nh" "<" "nh $TARGET_PROFILE $ACTION"
        _log_nvd_diff "/nix/var/nix/profiles/system" "os"
    else
        if ! nh home "$ACTION" "$TMP_BUILD_DIR" -d never "${NH_EXTRA[@]}" >&3 2>&3; then
            log_exec "nh" "<" "nh $TARGET_PROFILE $ACTION"
            log_msg "Error" "Build failed. Re-running with full build logs..."
            nix build --print-build-logs \
                "${TMP_BUILD_DIR}#homeConfigurations.\"${USER}@${HOST_ID}\".activationPackage" \
                --extra-experimental-features 'nix-command flakes' || true
            exit 1
        fi
        log_exec "nh" "<" "nh $TARGET_PROFILE $ACTION"
        _log_nvd_diff "$HOME/.local/state/nix/profiles/home-manager" "home"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw "$@"
fi

run_nh_task
