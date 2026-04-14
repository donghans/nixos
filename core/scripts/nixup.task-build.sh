#!/usr/bin/env bash

# 성공 후 이전/현재 세대 간 패키지 변경사항을 로그에 기록
# test/build 액션은 새 세대를 만들지 않으므로 제외
_log_nvd_diff() {
    local profile_path=$1
    local label=$2

    # shellcheck disable=SC2153
    [[ "$ACTION" == "test" || "$ACTION" == "build" ]] && return
    [ ! -L "$profile_path" ] && return

    local profile_dir profile_name link_name cur_num prev_num prev_path
    profile_dir=$(dirname "$profile_path")
    profile_name=$(basename "$profile_path")
    link_name=$(readlink "$profile_path")
    cur_num=$(echo "$link_name" | grep -oE '[0-9]+-link' | grep -oE '[0-9]+')
    prev_num=$(( cur_num - 1 ))
    prev_path="$profile_dir/${profile_name}-${prev_num}-link"

    [ ! -e "$prev_path" ] && return

    local diff_out
    diff_out=$(nvd diff "$prev_path" "$(readlink -f "$profile_path")" 2>&1 || true)
    if echo "$diff_out" | grep -qE '^(Added|Removed|Changed) packages:'; then
        log_exec "nvd" ">" "nvd diff ($label)"
        echo "$diff_out"
        log_exec "nvd" "<" "nvd diff ($label)"
    else
        log_msg "Notice" "no package changes ($label)"
    fi
}

# nix build + nom --json 필터 모드 래퍼
# - fd3: nixup.sh에서 setup_logging() 전에 열린 원본 터미널 fd (exec 3>&1)
#         nom 출력을 fd3으로 전달 → tee 파이프라인 완전 우회, 디펜던시 그래프 완전 렌더링
# - nix stderr(2>&1) → tee(→*-build.log + pipe) → nom --json(→fd3=terminal)
# - 빌드 완료 후 *-build.log(@nix JSON)를 세션 로그에 append
# - NIX_BUILD_RESULT: module-level 변수로 store path 반환 (stdout 캡처 오염 방지)
NIX_BUILD_RESULT=""
_nix_build() {
    local attr=$1
    local build_log="$LOG_DIR/${LOG_TIMESTAMP}.nom-build.log"
    local out_link="/tmp/nixup-build-result"

    log_exec "nix" ">" "nix build (nom)"
    set +e
    nix build "$attr" \
        "${NIX_FLAKE_FLAGS[@]}" \
        --log-format internal-json \
        --print-build-logs \
        --out-link "$out_link" \
        2>&1 | tee "$build_log" | nom --json >&3 2>&3
    BUILD_EXIT=${PIPESTATUS[0]}
    set -e
    log_exec "nix" "<" "nix build (nom)"

    if [ "$BUILD_EXIT" -ne 0 ]; then
        # 실패 시 build log 보존 (에러 분석용)
        log_msg "Error" "Build failed. Build log: $build_log"
        exit 1
    fi

    # 성공 시 build log 삭제 (세션 로그와 병합 불가 — 별도 fd 간 race condition)
    rm -f "$build_log"

    NIX_BUILD_RESULT=$(readlink -f "$out_link")
    rm -f "$out_link"
}

# OS 프로파일 활성화
# switch/boot: 새 세대로 nix-env profile 등록 후 switch-to-configuration 실행
# test: 프로파일 등록 없이 즉시 활성화 (부트로더 미기록)
# build: 빌드만, 활성화 없음
_activate_os() {
    local result=$1
    local action=$2

    case "$action" in
        switch|boot)
            log_exec "nix" ">" "nix-env --set + switch-to-configuration $action"
            sudo nix-env -p /nix/var/nix/profiles/system --set "$result"
            sudo "$result/bin/switch-to-configuration" "$action"
            log_exec "nix" "<" "nix-env --set + switch-to-configuration $action"
            ;;
        test)
            log_exec "nix" ">" "switch-to-configuration test"
            sudo "$result/bin/switch-to-configuration" test
            log_exec "nix" "<" "switch-to-configuration test"
            ;;
        build)
            log_msg "Notice" "dry-run: build complete, no activation performed."
            ;;
    esac
}

# Home-manager 프로파일 활성화
# switch: 활성화 스크립트 실행
# test: DRY_RUN=1로 실행 (home-manager activation script가 지원)
# build: 빌드만, 활성화 없음
_activate_home() {
    local result=$1
    local action=$2

    case "$action" in
        switch)
            log_exec "nix" ">" "home-manager activate"
            "$result/activate"
            log_exec "nix" "<" "home-manager activate"
            ;;
        test)
            log_exec "nix" ">" "home-manager activate (dry-run)"
            DRY_RUN=1 "$result/activate"
            log_exec "nix" "<" "home-manager activate (dry-run)"
            ;;
        build)
            log_msg "Notice" "dry-run: build complete, no activation performed."
            ;;
    esac
}

run_build_task() {
    log_msg "Task" "building configuration for #$HOST_ID..."

    if [ "$TARGET_PROFILE" == "os" ]; then
        local attr="path:${BUILD_DIR}#nixosConfigurations.${HOST_ID}.config.system.build.toplevel"
        local pre_store
        pre_store=$(readlink -f "/nix/var/nix/profiles/system" 2>/dev/null || true)
        _nix_build "$attr"
        _activate_os "$NIX_BUILD_RESULT" "$ACTION"
        if [ "$NIX_BUILD_RESULT" = "$pre_store" ]; then
            log_msg "Notice" "no package changes (os)"
        else
            _log_nvd_diff "/nix/var/nix/profiles/system" "os"
        fi
    else
        local attr="path:${BUILD_DIR}#homeConfigurations.\"${USER}@${HOST_ID}\".activationPackage"
        local pre_home_store
        pre_home_store=$(readlink -f "$HOME/.local/state/nix/profiles/home-manager" 2>/dev/null || true)
        _nix_build "$attr"
        _activate_home "$NIX_BUILD_RESULT" "$ACTION"
        if [ "$NIX_BUILD_RESULT" = "$pre_home_store" ]; then
            log_msg "Notice" "no package changes (home)"
        else
            _log_nvd_diff "$HOME/.local/state/nix/profiles/home-manager" "home"
        fi
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nixup dispatcher..."
    exec nixup "$@"
fi

run_build_task
