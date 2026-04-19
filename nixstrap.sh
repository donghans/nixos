#!/usr/bin/env bash
# nixstrap.sh — NixOS 설치 진입점
#
# 사용법:
#   ./nixstrap.sh
#       NixOS/표준 live ISO 환경에서 실행. 필요한 도구를 자동으로 확보하고
#       nixstrap을 실행합니다. 호스트·파티션 선택은 nixstrap이 대화형으로 안내합니다.

set -euo pipefail

# ── 색상 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
SETUP_SCRIPT="$SCRIPT_DIR/core/scripts/nixstrap.sh"
BASE_TOML="$SCRIPT_DIR/hosts/base.toml"

log() {
    local cat=$1; shift
    local cat_color=$NC
    case "$cat" in
        Info)    cat_color=$CYAN ;;
        Ok)      cat_color=$GREEN ;;
        Warn)    cat_color=$YELLOW ;;
        Error)   cat_color=$RED ;;
        Step)    cat_color=$PURPLE ;;
    esac
    printf "${PURPLE}nixstrap${NC} ${cat_color}%-5s${NC} | %s\n" "$cat" "$*"
}

die() { log Error "$*"; exit 1; }

# ── 도구 확보 ─────────────────────────────────────────────────────────────────
# nix-shell 재진입으로 nixstrap 의존 도구를 확보합니다.
ensure_tools() {
    if [ "${BOOTSTRAP_IN_NIX_SHELL:-}" = "1" ]; then
        return  # 이미 nix-shell 안에 있음
    fi

    local missing=()
    command -v git     &>/dev/null || missing+=("git")
    command -v python3 &>/dev/null || missing+=("python3")
    command -v btrfs   &>/dev/null || missing+=("btrfs-progs")
    command -v parted  &>/dev/null || missing+=("parted")

    if [ "${#missing[@]}" -gt 0 ]; then
        log Info "누락된 도구: ${missing[*]}"
        log Step "nix-shell로 도구를 확보한 뒤 재실행합니다..."
        export BOOTSTRAP_IN_NIX_SHELL=1
        # $* is intentional — nix-shell --run takes a single string argument
        exec nix-shell -p git python3 btrfs-progs util-linux parted \
            --run "bash $(readlink -f "$0") $*"
    fi
}

# ── NIXOS_REPO 자동 설정 ──────────────────────────────────────────────────────
resolve_repo() {
    if [ -n "${NIXOS_REPO:-}" ]; then
        return
    fi
    if [ ! -f "$BASE_TOML" ]; then
        die "hosts/base.toml을 찾을 수 없습니다. 저장소 루트에서 실행하거나 NIXOS_REPO 환경변수를 설정하세요."
    fi
    NIXOS_REPO=$(BASE_TOML="$BASE_TOML" python3 -c "
import tomllib, os
with open(os.environ['BASE_TOML'], 'rb') as f:
    d = tomllib.load(f)
print(d.get('git', {}).get('nixosRepo', ''))
")
    if [ -z "$NIXOS_REPO" ]; then
        die "hosts/base.toml에서 [git] nixosRepo 값을 읽을 수 없습니다."
    fi
    log Info "저장소: $NIXOS_REPO (base.toml에서 읽음)"
}

# ── 진입점 ────────────────────────────────────────────────────────────────────
case "${1:-}" in
    --help|-h)
        echo ""
        echo "  nixstrap.sh — NixOS 설치 진입점"
        echo ""
        echo "  사용법: ./nixstrap.sh"
        echo ""
        echo "  NixOS/표준 live ISO 환경에서 nixstrap을 실행합니다."
        echo "  필요한 도구(git, python3, btrfs-progs, parted)가 없으면"
        echo "  nix-shell로 자동 확보 후 재실행합니다."
        echo ""
        exit 0
        ;;
esac

ensure_tools "$@"
resolve_repo

[ -f "$SETUP_SCRIPT" ] || die "설치 스크립트를 찾을 수 없습니다: $SETUP_SCRIPT"

log Step "nixstrap을 시작합니다..."
echo ""
NIXOS_REPO="$NIXOS_REPO" sudo -E bash "$SETUP_SCRIPT"
