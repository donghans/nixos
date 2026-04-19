#!/usr/bin/env bash
# nixup-iso.sh — nixstrap 내장 커스텀 live GUI ISO 빌드
#
# 사용법:
#   ./nixup-iso.sh          x86_64 ISO 빌드
#   ./nixup-iso.sh --arm    aarch64 ISO 빌드
#
# NixOS/표준 live ISO 환경에서 실행 가능합니다.
# nixup이 없어도 nix-shell 쉬뱅을 통해 필요한 도구를 자동으로 확보합니다.

set -euo pipefail

# ── 색상 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXUP_SCRIPT="$SCRIPT_DIR/core/scripts/nixup.sh"

log() {
    local cat=$1; shift
    local cat_color=$NC
    case "$cat" in
        Error) cat_color=$RED ;;
        Step)  cat_color=$PURPLE ;;
    esac
    printf "${PURPLE}nixup-iso${NC} ${cat_color}%-5s${NC} | %s\n" "$cat" "$*"
}

die() { log Error "$*"; exit 1; }

# ── 진입점 ────────────────────────────────────────────────────────────────────
case "${1:-}" in
    --help|-h)
        echo ""
        echo "  nixup-iso.sh — nixstrap 내장 커스텀 live GUI ISO 빌드"
        echo ""
        echo "  사용법:"
        echo "    ./nixup-iso.sh          x86_64 ISO 빌드"
        echo "    ./nixup-iso.sh --arm    aarch64 ISO 빌드"
        echo ""
        echo "  빌드 결과물은 .build/ 디렉터리에 심볼릭 링크로 생성됩니다."
        echo ""
        exit 0
        ;;
esac

[ -f "$NIXUP_SCRIPT" ] || die "nixup 스크립트를 찾을 수 없습니다: $NIXUP_SCRIPT"

cd "$SCRIPT_DIR"
if [ "${1:-}" = "--arm" ]; then
    log Step "aarch64 커스텀 ISO 빌드를 시작합니다..."
    exec "$NIXUP_SCRIPT" iso --arm
else
    log Step "x86_64 커스텀 ISO 빌드를 시작합니다..."
    exec "$NIXUP_SCRIPT" iso
fi
