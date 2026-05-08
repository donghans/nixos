#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p age gh jq
# nixsec — nix-secrets 관리 도구 (완전 대화형)
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIXOS_PATH="$(readlink -f "$SCRIPT_DIR/../..")"
JSON_DIR="${JSON_DIR:-/tmp/nixup-json}"
mkdir -p "$JSON_DIR"

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="NIXSEC"
_START_TIME=$(date +%s)
_START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
trap '_print_summary' EXIT

printf '\n'
log_msg "Init" "nix-secrets 관리 도구"
printf '\n'

command -v gh  &>/dev/null || { log_msg "Error" "gh CLI가 필요합니다.  nix-shell -p gh"; exit 1; }
command -v age &>/dev/null || { log_msg "Error" "age가 필요합니다.  nix-shell -p age";    exit 1; }
command -v jq  &>/dev/null || { log_msg "Error" "jq가 필요합니다.   nix-shell -p jq";     exit 1; }

_pick "작업을 선택하세요:" \
    "새 레포 초기화         — age 키 생성 + GitHub 프라이빗 레포 생성" \
    "시크릿 업로드          — 파일을 age 암호화해서 레포에 추가/갱신" \
    "원격 호스트에 주입     — 워크스테이션에서 복호화 후 SSH 전송" \
    "이 워크스테이션에 적용 — secrets.json 기반으로 로컬에 복호화 배치" \
    "age 키 복구            — 새 워크스테이션에서 키 경로 등록"

printf '\n'
case "$REPLY" in
    0) source "$SCRIPT_DIR/nixsec.task-init.sh";   _run_init ;;
    1) source "$SCRIPT_DIR/nixsec.task-upload.sh"; _run_upload ;;
    2) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_remote_inject ;;
    3) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_local_apply ;;
    4) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_key_restore ;;
esac
