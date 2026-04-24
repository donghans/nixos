#!/usr/bin/env nix-shell
#! nix-shell -i bash -p python3 git jq parted btrfs-progs util-linux
# shellcheck shell=bash
# shellcheck disable=SC2034  # sourced 스크립트들이 공유하는 전역 상태 변수
# shellcheck disable=SC1091  # 동적 경로 source: 정적 분석 불가
set -euo pipefail

# [nixstrap] NixOS 설치 스크립트
# nixos/bootstrap.sh에 의해 래핑됨.
# writeShellApplication이 직접 읽는 파일. lib 파일과 동일하게 한국어 주석 사용 가능.

SCRIPT_DIR="${SCRIPT_DIR:-$(dirname "$(readlink -f "$0")")}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.task-input.sh"
source "$SCRIPT_DIR/nixstrap.task-disk.sh"
source "$SCRIPT_DIR/nixstrap.task-install.sh"

# -- 공유 상태 --
NIXOS_REPO="${NIXOS_REPO:-}"
HOST=""
_HOST_IS_NEW=false
_HOST_TYPE=""
_HOST_PRESET_FROM_REPO=""
_IS_VM=false
_PART_MODE=""
_NEW_PARTITIONS=false
BOOT_PART=""
ROOT_PART=""
FORMAT_BOOT=""
FORMAT_ROOT=""
_DISK=""
_WIPE=false
_PART_START=""
_PART_END=""
_BOOT_SIZE=""
_BOOT_END=""
_NEW_BOOT_NUM=""
_NEW_ROOT_NUM=""
_PRESET="workstation"
_STATE_VERSION=""  # 신규 호스트: 비어있으면 rolling, 값 있으면 host.toml에 기재
_HOST_USERNAME=""  # 신규 호스트: 비어있으면 _base.toml fallback, 값 있으면 host.toml에 기재
_DEPLOY_ENABLED=false         # true: server 신규 호스트에서 deploy-rs 설정
_DEPLOY_SSH_KEY=""            # 관리 머신 SSH 키 경로 (비어있으면 Phase 2에서 자동 생성)
_DEPLOY_KEY_WAS_GENERATED=false  # Phase 2에서 자동 생성했을 때 true → PEM 저장 대상
REPO_TMP="/tmp/nixos-setup-repo"
PARAMS_FILE="${PARAMS_FILE:-/root/nixstrap-params.env}"
_USER_PASSWORD=""  # ask_password에서 설정, _post_process에서 적용 후 즉시 비움 (파일 저장 안 함)
# Phase 2 함수들이 설정:
BOOT_LABEL=""
DISK_LABEL=""
RESOLVE_TMP=""
USERNAME=""
BUILD_DIR=""
# trap 상태:
_TRAP_INT_WARNED_AT=0  # 마지막 Ctrl+C 경고 시각 (epoch seconds, 0=초기)
_NIXOS_INSTALL_PID=""  # setsid로 실행한 nixos-install PID (종료 시 kill 대상)

# -- 인터럽트·종료 처리 --
_trap_cleanup() {
    _USER_PASSWORD=""
    tput cnorm 2>/dev/null || true
    stty sane 2>/dev/null || true
    if [ -n "${_NIXOS_INSTALL_PID:-}" ]; then
        printf "\n" >&2; log_msg "Cleanup" "nixos-install 종료 중..." >&2
        kill "$_NIXOS_INSTALL_PID" 2>/dev/null || true
        wait "$_NIXOS_INSTALL_PID" 2>/dev/null || true
        _NIXOS_INSTALL_PID=""
    fi
    if mountpoint -q /mnt 2>/dev/null; then
        log_msg "Cleanup" "/mnt 마운트 해제 중..." >&2
        swapoff -a 2>/dev/null || true
        umount -R /mnt 2>/dev/null || umount -lR /mnt 2>/dev/null || true
    fi
    if [ -d "${REPO_TMP:-}" ]; then
        rm -rf "$REPO_TMP" 2>/dev/null || true
    fi
}

_trap_int() {
    local _now _timeout
    _now=$(date +%s)
    _timeout=3
    [ -n "${_NIXOS_INSTALL_PID:-}" ] && _timeout=5
    if [ $(( _now - _TRAP_INT_WARNED_AT )) -gt "$_timeout" ]; then
        _TRAP_INT_WARNED_AT=$_now
        printf "\n" >&2
        if [ -n "${_NIXOS_INSTALL_PID:-}" ]; then
            log_msg "Notice" "nixos-install 진행 중 — ${_timeout}초 내 Ctrl+C 한 번 더 누르면 중단합니다." >&2
        else
            log_msg "Notice" "${_timeout}초 내 Ctrl+C 한 번 더 누르면 종료합니다." >&2
        fi
        return
    fi
    _trap_cleanup
    exit 130
}

_trap_exit() {
    local _code=$?
    _print_summary
    _trap_cleanup
    return "$_code"
}

trap '_trap_exit'              EXIT
trap '_trap_int'               INT
trap '_trap_cleanup; exit 143' TERM

# -- 초기화 --
log_msg "Init" "NixOS Installer"
if _VIRT_TYPE=$(systemd-detect-virt 2>/dev/null); then
    _IS_VM=true
    log_msg "Notice" "가상화 환경 감지됨: $_VIRT_TYPE"
fi

# -- Phase 1: 입력 수집 --
if load_params; then
    : # params 로드됨 — review_loop에서 확인/수정
else
    if [ -n "${NIXOS_REPO_PATH:-}" ]; then
        REPO_TMP="$NIXOS_REPO_PATH"
    else
        ask_repo_and_clone
    fi
    select_host
    [ "$_HOST_IS_NEW" = true ] && ask_preset
    [ "$_HOST_IS_NEW" = true ] && ask_state_version
    [ "$_HOST_IS_NEW" = true ] && ask_deploy_config
    ask_partitions
fi
review_loop
ask_password

# -- Phase 2: 실행 --
# 대화형 입력(Phase 1) 완료 후부터 시간 측정
_START_TIME=$(date +%s)
_START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
phase2_execute
