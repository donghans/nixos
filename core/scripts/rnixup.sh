#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p jq python3
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="RNIXUP"

# 상수 (nixup.lib-build.sh와 동일한 경로)
BUILD_DIR="$NIXOS_PATH/.build"
JSON_DIR="/tmp/nixup-json"
ENV_FILE="$NIXOS_PATH/.env"

# ── 도움말 ────────────────────────────────────────────────────────────────────
_print_help() {
    printf "\n"
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${CYAN}%-9s${NC} | Remote NixOS deploy tool\n" "Help"
    printf "\n"
    printf "  Usage:\n"
    printf "    rnixup        — dry-activate preview, then confirm → deploy all hosts\n"
    printf "    rnixup list   — list configured remote hosts\n"
    printf "\n"
    printf "  Tip: run 'rnixstrap' to add a new remote host.\n"
    printf "\n"
}

# ── 인자 파싱 ─────────────────────────────────────────────────────────────────
SUBCOMMAND="${1:-}"

case "$SUBCOMMAND" in
    --help|-h)
        _print_help
        exit 0
        ;;
    list)
        # resolve 후 목록 출력 (아래에서 처리)
        ;;
    "")
        # 전체 배포
        ;;
    *)
        log_msg "Error" "unknown: '$SUBCOMMAND'. use: rnixup / rnixup list / rnixup --help"
        exit 1
        ;;
esac

# ── resolved.json 생성 ────────────────────────────────────────────────────────
mkdir -p "$JSON_DIR"
python3 -B "$SCRIPT_DIR/nixup.task-resolve.py" "$NIXOS_PATH" "$JSON_DIR" >/dev/null

# ── list 처리 ─────────────────────────────────────────────────────────────────
if [ "$SUBCOMMAND" = "list" ]; then
    local_count=$(jq '[to_entries[] | select(.value.deploy != null)] | length' "$JSON_DIR/resolved.json")
    if [ "$local_count" -eq 0 ]; then
        log_msg "Notice" "no remote hosts configured (add [deploy] section to a host TOML)"
        exit 0
    fi
    log_msg "Hosts" "$local_count remote host(s) found"
    jq -r '
        to_entries[]
        | select(.value.deploy != null)
        | [.key, (.value.deploy.ip // "?"), (.value.bootLoader // "?"), (.value.type // "?")]
        | @tsv
    ' "$JSON_DIR/resolved.json" | while IFS=$'\t' read -r name ip dest type; do
        printf "  %-28s %-18s %-14s %s\n" "$name" "$ip" "$dest" "$type"
    done
    exit 0
fi

# ── 빌드 환경 준비 ────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/nixup.lib-build.sh"

IS_SUCCESS=false
trap 'handle_signal SIGINT' INT
trap 'handle_signal SIGTERM' TERM

prepare_build_dir "$NIXOS_PATH" "$BUILD_DIR" "$ENV_FILE"

# ── 배포 실행 ─────────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/rnixup.task-deploy.sh"

IS_SUCCESS=true
