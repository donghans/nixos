#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p jq python3 age gh
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="RNIXUP"

# lib-build.sh: BUILD_DIR / JSON_DIR / SESSION_LOCK 정의 및 빌드 헬퍼 제공
source "$SCRIPT_DIR/lib-build.sh"
ENV_FILE="$NIXOS_PATH/.env"

# ── 도움말 ────────────────────────────────────────────────────────────────────
_print_help() {
    printf "\n"
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${CYAN}%-9s${NC} | 원격 NixOS 배포 도구\n" "Help"
    printf "\n"
    printf "  사용법:\n"
    printf "    rnixup                — dry-activate 미리보기 후 확인 → 전체 호스트 배포\n"
    printf "    rnixup <hostname>     — 특정 호스트만 배포\n"
    printf "    rnixup list           — 설정된 원격 호스트 목록 출력\n"
    printf "\n"
    printf "  팁: 새 원격 호스트 추가는 'rnixstrap'을 사용하세요.\n"
    printf "\n"
}

# ── 인자 파싱 ─────────────────────────────────────────────────────────────────
SUBCOMMAND="${1:-}"
export DEPLOY_NODE=""

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
        # 호스트명 지정 단일 배포
        DEPLOY_NODE="$SUBCOMMAND"
        ;;
esac

# ── 세션 락 획득 ──────────────────────────────────────────────────────────────
acquire_lock

# ── resolved.json 생성 ────────────────────────────────────────────────────────
mkdir -p "$JSON_DIR"
python3 -B "$SCRIPT_DIR/nixup.task-resolve.py" "$NIXOS_PATH" "$JSON_DIR" >/dev/null

# ── list 처리 ─────────────────────────────────────────────────────────────────
if [ "$SUBCOMMAND" = "list" ]; then
    local_count=$(jq '[to_entries[] | select(.value.deploy != null)] | length' "$JSON_DIR/resolved.json")
    if [ "$local_count" -eq 0 ]; then
        log_msg "Notice" "원격 호스트 없음 (호스트 TOML에 [deploy] 섹션을 추가하거나 rnixstrap을 실행하세요)"
        exit 0
    fi
    log_msg "Hosts" "$local_count 개의 원격 호스트"
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

# ── 배너 ──────────────────────────────────────────────────────────────────────
log_msg "Init" "원격 NixOS 배포 도구"
log_msg "Init" "명령어:  deploy-rs (dry-activate → deploy)"
if [ -n "$DEPLOY_NODE" ]; then
    log_msg "Init" "호스트:   ${DEPLOY_NODE} (단일)"
else
    _deploy_count=$(jq '[to_entries[] | select(.value.deploy != null)] | length' "$JSON_DIR/resolved.json")
    log_msg "Init" "호스트:   ${_deploy_count}개"
fi

# ── 트랩 ──────────────────────────────────────────────────────────────────────
trap 'handle_signal SIGINT'  INT
trap 'handle_signal SIGTERM' TERM
trap '_print_summary'        EXIT

# ── 빌드 환경 준비 ────────────────────────────────────────────────────────────
prepare_build_dir "$NIXOS_PATH" "$BUILD_DIR" "$ENV_FILE"

# ── 배포 실행 ─────────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/rnixup.task-deploy.sh"
