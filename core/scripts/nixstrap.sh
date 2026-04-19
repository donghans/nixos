#!/usr/bin/env nix-shell
#! nix-shell -i bash -p python3 git jq parted btrfs-progs util-linux
# shellcheck shell=bash
# shellcheck disable=SC1091,SC2034
set -euo pipefail

# [nixstrap] NixOS 설치 스크립트
# nixos/bootstrap.sh에 의해 래핑됨.
# writeShellApplication이 직접 읽는 파일. lib 파일과 동일하게 한국어 주석 사용 가능.

SCRIPT_DIR="${SCRIPT_DIR:-$(dirname "$(readlink -f "$0")")}"
source "$SCRIPT_DIR/nixstrap.lib-log.sh"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-input.sh"
source "$SCRIPT_DIR/nixstrap.lib-install.sh"

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
REPO_TMP="/tmp/nixos-setup-repo"
PARAMS_FILE="${PARAMS_FILE:-/root/nixstrap-params.env}"
# Phase 2 함수들이 설정:
BOOT_LABEL=""
DISK_LABEL=""
RESOLVE_TMP=""
USERNAME=""
BUILD_DIR=""

# -- 초기화 --
log_msg "Init" "NixOS Installer"
if _VIRT_TYPE=$(systemd-detect-virt 2>/dev/null); then
    _IS_VM=true
    log_msg "Notice" "virtualized environment detected: $_VIRT_TYPE"
fi

# -- Phase 1: 입력 수집 --
if load_params; then
    : # params 로드됨 — review_loop에서 확인/수정
else
    ask_repo_and_clone
    select_host
    ask_partitions
    [ "$_HOST_IS_NEW" = true ] && ask_preset
fi
review_loop

# -- Phase 2: 실행 --
phase2_execute
