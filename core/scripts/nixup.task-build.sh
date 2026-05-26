#!/usr/bin/env bash

source "$SCRIPT_DIR/nixstrap.lib-preauth.sh"

# 빌드 전/후 store path를 직접 비교하여 패키지 변경사항 출력
# pre_store와 new_store를 직접 받아 비교 → 모든 액션(switch/test/build)에서 동작
_show_nvd_diff() {
    local old_store=$1 new_store=$2 label=$3

    if [ -z "$old_store" ] || [ -z "$new_store" ] || [ "$old_store" = "$new_store" ]; then
        log_msg "Notice" "패키지 변경 없음 ($label)"
        return
    fi

    local diff_out
    diff_out=$(nvd diff "$old_store" "$new_store" 2>&1 || true)
    if echo "$diff_out" | grep -qE '^(Added|Removed|Changed) packages:'; then
        log_exec "nvd" ">" "nvd diff ($label)"
        echo "$diff_out"
        log_exec "nvd" "<" "nvd diff ($label)"
    else
        log_msg "Notice" "패키지 변경 없음 ($label)"
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
        log_msg "Error" "빌드 실패. 빌드 로그: $build_log"
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
            log_msg "Notice" "dry-run: 빌드 완료, 활성화 없음."
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
            log_msg "Notice" "dry-run: 빌드 완료, 활성화 없음."
            ;;
    esac
}

run_build_task() {
    log_msg "Task" "#$HOST_ID 설정 빌드 중..."

    if [ "$TARGET_PROFILE" == "os" ] || [ "$TARGET_PROFILE" == "all" ]; then
        local attr="path:${BUILD_DIR}#nixosConfigurations.${HOST_ID}.config.system.build.toplevel"
        local pre_store
        pre_store=$(readlink -f "/nix/var/nix/profiles/system" 2>/dev/null || true)
        _nix_build "$attr"
        # shellcheck disable=SC2153  # ACTION은 nixup.sh에서 전역으로 설정됨
        _activate_os "$NIX_BUILD_RESULT" "$ACTION"
        _show_nvd_diff "$pre_store" "$NIX_BUILD_RESULT" "os"
        # switch 완료 후 누락된 preauth key 로컬 배포 (headscale SSH 키 필요 시 프롬프트)
        # 새 key가 실제로 배포됐을 때만 tailscale-autoauth 재시작 (이미 인증된 경우 불필요)
        if [ "$ACTION" == "switch" ]; then
            check_preauth_keys_local "$HOST_ID" ""
            if [ "${PREAUTH_KEYS_DEPLOYED:-false}" = true ]; then
                sudo systemctl restart tailscale-autoauth 2>/dev/null || true
            fi
        fi
    fi

    if [ "$TARGET_PROFILE" == "home" ] || [ "$TARGET_PROFILE" == "all" ]; then
        local attr="path:${BUILD_DIR}#homeConfigurations.\"${USER}@${HOST_ID}\".activationPackage"
        local pre_home_store
        pre_home_store=$(readlink -f "$HOME/.local/state/nix/profiles/home-manager" 2>/dev/null || true)
        _nix_build "$attr"
        _activate_home "$NIX_BUILD_RESULT" "$ACTION"
        # nixstrap 첫 부팅 마커 제거 (switch 시에만)
        [[ "$ACTION" == "switch" ]] && rm -f "$HOME/.nixstrap-first-run" 2>/dev/null || true
        _show_nvd_diff "$pre_home_store" "$NIX_BUILD_RESULT" "home"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "nixup으로 전달 중..."
    exec nixup "$@"
fi

run_build_task
