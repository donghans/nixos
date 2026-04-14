#!/usr/bin/env bash
# bootstrap.sh — NixOS 환경 이식 헬퍼
#
# 사용법:
#   ./bootstrap.sh install [EFI_PART] [ROOT_PART] [HOSTNAME]
#       표준 NixOS live 환경에서 실행. 필요한 도구를 자동으로 확보하고
#       파티션 정보가 없으면 대화형으로 물어봅니다.
#
#   ./bootstrap.sh build-iso [--arm]
#       기존 NixOS 환경에서 커스텀 ISO를 빌드합니다.
#       (from-nixos-mk-iso.sh 대체)
#
#   ./bootstrap.sh
#       현재 환경 정보를 표시합니다.

set -euo pipefail

# ── 색상 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
SETUP_SCRIPT="$SCRIPT_DIR/core/scripts/iso.setup.sh"
NIXUP_SCRIPT="$SCRIPT_DIR/core/scripts/nixup.sh"
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
    printf "${PURPLE}Bootstrap${NC} ${cat_color}%-5s${NC} | %s\n" "$cat" "$*"
}

die() { log Error "$*"; exit 1; }

# ── 도움말 / 환경 정보 ────────────────────────────────────────────────────────
show_help() {
    echo ""
    echo "  bootstrap.sh — NixOS 환경 이식 헬퍼"
    echo ""
    echo "  명령:"
    echo "    install [EFI_PART] [ROOT_PART] [HOSTNAME]"
    echo "        live 환경에서 NixOS를 설치합니다."
    echo "        인자를 생략하면 대화형으로 입력받습니다."
    echo ""
    echo "    build-iso [--arm]"
    echo "        커스텀 NixOS 설치 ISO를 빌드합니다."
    echo "        nixup이 없어도 nix-shell을 통해 자동 실행됩니다."
    echo ""
    echo "  현재 환경:"

    if command -v nixup &>/dev/null; then
        log Ok   "nixup 설치됨 — build-iso 또는 일반 관리 모두 가능"
    elif command -v nix &>/dev/null; then
        log Info "nix 있음, nixup 없음 — build-iso 가능 (nix-shell 자동 사용)"
    else
        log Warn "nix 없음 — install 모드만 권장 (표준 live 환경으로 보임)"
    fi

    if [ ! -f "$BASE_TOML" ]; then
        log Warn "hosts/base.toml 없음 — install 실행 전 저장소를 먼저 클론하세요"
    fi
    echo ""
}

# ── 도구 확보 (install 모드 전용) ─────────────────────────────────────────────
# nix-shell 재진입으로 git/python3/btrfs-progs를 확보합니다.
ensure_tools() {
    if [ "${BOOTSTRAP_IN_NIX_SHELL:-}" = "1" ]; then
        return  # 이미 nix-shell 안에 있음
    fi

    local missing=()
    command -v git     &>/dev/null || missing+=("git")
    command -v python3 &>/dev/null || missing+=("python3")
    command -v btrfs   &>/dev/null || missing+=("btrfs-progs")

    if [ "${#missing[@]}" -gt 0 ]; then
        log Info "누락된 도구: ${missing[*]}"
        log Step "nix-shell로 도구를 확보한 뒤 재실행합니다..."
        export BOOTSTRAP_IN_NIX_SHELL=1
        # $* is intentional — nix-shell --run takes a single string argument
        exec nix-shell -p git python3 btrfs-progs util-linux \
            --run "bash $(readlink -f "$0") install $*"
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

# ── 파티션 정보 수집 ──────────────────────────────────────────────────────────
collect_install_args() {
    local efi=$1 root=$2 host=$3

    if [ -z "$efi" ] || [ -z "$root" ] || [ -z "$host" ]; then
        echo ""
        log Info "현재 디스크 목록:"
        lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>/dev/null || true
        echo ""
    fi

    if [ -z "$efi" ]; then
        read -rp "$(printf '%s' "${CYAN}Bootstrap Input${NC} | EFI 파티션 경로 (예: /dev/nvme0n1p1): ")" efi
    fi
    if [ -z "$root" ]; then
        read -rp "$(printf '%s' "${CYAN}Bootstrap Input${NC} | 루트 파티션 경로 (예: /dev/nvme0n1p2): ")" root
    fi
    if [ -z "$host" ]; then
        read -rp "$(printf '%s' "${CYAN}Bootstrap Input${NC} | 호스트명 (hosts/ 폴더 이름): ")" host
    fi

    [ -n "$efi" ]  || die "EFI 파티션 경로가 입력되지 않았습니다."
    [ -n "$root" ] || die "루트 파티션 경로가 입력되지 않았습니다."
    [ -n "$host" ] || die "호스트명이 입력되지 않았습니다."

    INSTALL_EFI=$efi
    INSTALL_ROOT=$root
    INSTALL_HOST=$host
}

# ── install 모드 ──────────────────────────────────────────────────────────────
cmd_install() {
    ensure_tools "$@"
    resolve_repo

    local efi="${1:-}" root="${2:-}" host="${3:-}"
    collect_install_args "$efi" "$root" "$host"

    [ -f "$SETUP_SCRIPT" ] || die "설치 스크립트를 찾을 수 없습니다: $SETUP_SCRIPT"

    log Step "설치를 시작합니다: EFI=$INSTALL_EFI ROOT=$INSTALL_ROOT HOST=$INSTALL_HOST"
    echo ""
    NIXOS_REPO="$NIXOS_REPO" sudo -E bash "$SETUP_SCRIPT" \
        "$INSTALL_EFI" "$INSTALL_ROOT" "$INSTALL_HOST"
}

# ── build-iso 모드 ────────────────────────────────────────────────────────────
cmd_build_iso() {
    local arm=0
    for arg in "$@"; do
        [ "$arg" = "--arm" ] && arm=1
    done

    [ -f "$NIXUP_SCRIPT" ] || die "nixup 스크립트를 찾을 수 없습니다: $NIXUP_SCRIPT"

    cd "$SCRIPT_DIR"
    if [ "$arm" = "1" ]; then
        log Step "aarch64 커스텀 ISO 빌드를 시작합니다..."
        exec "$NIXUP_SCRIPT" iso --arm
    else
        log Step "x86_64 커스텀 ISO 빌드를 시작합니다..."
        exec "$NIXUP_SCRIPT" iso
    fi
}

# ── 진입점 ────────────────────────────────────────────────────────────────────
case "${1:-}" in
    install)
        shift
        cmd_install "$@"
        ;;
    build-iso)
        shift
        cmd_build_iso "$@"
        ;;
    *)
        show_help
        ;;
esac
