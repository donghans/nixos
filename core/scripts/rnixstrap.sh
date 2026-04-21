#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p jq python3 git openssh
# shellcheck disable=SC1008,SC1091,SC2034,SC2154
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="RNIXSTRAP"
_LOG_CAT[Review]="$CYAN"

# ── 도움말 ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    printf "\n"
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${CYAN}%-9s${NC} | 원격 NixOS 호스트 초기 설치 도구\n" "Help"
    printf "\n"
    printf "  Usage:\n"
    printf "    rnixstrap     — 대화형으로 새 호스트 추가 또는 기존 호스트 재설치\n"
    printf "\n"
    printf "  흐름:\n"
    printf "    새 호스트:    공급자/IP/키/서비스 입력 → 설정 확인 → 선택\n"
    printf "    기존 호스트:  목록에서 선택 → IP/키 확인 → 설정 확인 → 선택\n"
    printf "\n"
    printf "  선택지:\n"
    printf "    바로 진행  nixos-anywhere 설치 + deploy-rs 배포\n"
    printf "    쓰기만     파일만 생성/갱신하고 종료 (.nix 편집 후 재실행)\n"
    printf "    취소       아무것도 하지 않고 종료\n"
    printf "\n"
    printf "  설정 변경 배포(재설치 아님)는 'rnixup'을 사용하세요.\n"
    printf "\n"
    exit 0
fi

# 파라미터 없이 실행 — 불필요한 인자 거부
if [ $# -gt 0 ]; then
    log_msg "Error" "rnixstrap은 파라미터를 받지 않습니다. 도움말: rnixstrap --help"
    exit 1
fi

# ── 상수 ──────────────────────────────────────────────────────────────────────
BUILD_DIR="$NIXOS_PATH/.build"
JSON_DIR="/tmp/nixup-json"
ENV_FILE="$NIXOS_PATH/.env"
mkdir -p "$JSON_DIR"

# ── 공유 상태 (Phase 1 → Phase 2 전달) ───────────────────────────────────────
_HOST_IS_NEW=true       # false = 기존 호스트 재설치
_HOSTNAME=""
_IP=""
_SSH_KEY=""
_SYSTEM="x86_64-linux"
_BOOT_LOADER=""
_DISK_DEVICE=""
_REMOTE_RAM_MB=-1   # 원격 RAM(MB), -1=감지 전/실패
_SERVICES=()
_SSH_USER="root"        # nixos-anywhere bootstrap 접속 유저
_TOML_IP=""             # 기존 호스트 TOML에서 로드
_TOML_SSH_KEY=""        # 기존 호스트 TOML에서 로드
_TOML_BOOT_LOADER=""    # 기존 호스트 TOML에서 로드
_TOML_DISK_DEVICE=""    # 기존 호스트 TOML에서 로드

# ── lib 로드 ──────────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/lib-build.sh"
source "$SCRIPT_DIR/rnixstrap.lib-input.sh"
source "$SCRIPT_DIR/rnixstrap.task-setup.sh"

# ── Cleanup trap ──────────────────────────────────────────────────────────────
_cleanup() {
    _print_summary
    tput cnorm 2>/dev/null || true
    stty sane 2>/dev/null || true
}
trap '_cleanup' EXIT
trap '_cleanup; exit 130' INT TERM

# ── 시작 배너 ─────────────────────────────────────────────────────────────────
printf "\n"
log_msg "Init" "원격 NixOS 호스트 초기 설치 도구"
log_msg "Init" "새 호스트 추가 또는 기존 호스트 재설치를 진행합니다."
printf "\n"

# ── Phase 1: 입력 수집 ────────────────────────────────────────────────────────
select_or_create_hostname

if [ "$_HOST_IS_NEW" = true ]; then
    ask_ssh_user
    ask_ip
    ask_ssh_key
    ask_system
    ask_services
else
    ask_ip        # 기존 IP를 기본값으로, 변경 가능
    ask_ssh_key   # 기존 키를 기본값으로, 변경 가능
fi

run_setup
