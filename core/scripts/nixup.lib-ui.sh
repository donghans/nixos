#!/usr/bin/env bash
# nixup.lib-ui.sh — 색상 상수, 로깅 헬퍼, 초기화 배너

# ANSI Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Formatting Helper
log_msg() {
    local category=$1
    local msg=$2
    local cat_color=$NC

    case "$category" in
        Init)    cat_color=$CYAN ;;
        Task)    cat_color=$PURPLE ;;
        Summary) cat_color=$NC ;;
        Done|Success) cat_color=$GREEN ;;
        Error)   cat_color=$RED ;;
        Notice|Warn)  cat_color=$YELLOW ;;
        Prep)    cat_color=$CYAN ;;
        Lock)    cat_color=$YELLOW ;;
        *)       cat_color=$NC ;;
    esac

    # Format: NIXUP [9-char-category] | [msg]
    printf "${CYAN}NIXUP${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# Command Execution Helper (Aligned with | marker)
log_exec() {
    local cmd_name=$1 # e.g., nix, nom
    local state=$2    # > or <
    local msg=$3      # description
    local cat_color=$BLUE

    # Matches NIXUP's aligned format: NIXUP Exec cmd > description
    printf "${CYAN}NIXUP${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# Print Init Banner (실행 시작 시 Action/Target/Mode 출력)
print_init_banner() {
    log_msg "Init" "NixOS update utility"

    if [ "$DO_CLEAN" = true ]; then
        log_msg "Init" "Command:  nix-env --delete-generations (keep: $CLEAN_KEEP)"
    elif [ "$TARGET_PROFILE" = "fix-unstable" ]; then
        log_msg "Init" "Command:  nix flake update <input>"
    elif [ "$TARGET_PROFILE" = "update" ]; then
        log_msg "Init" "Command:  nix flake update"
    elif [ "$TARGET_PROFILE" = "check" ] && [ "$CHECK_DEEP" = true ]; then
        log_msg "Init" "Command:  nix flake check"
    elif [ "$TARGET_PROFILE" = "iso" ]; then
        log_msg "Init" "Command:  nix build .#nixos-iso [${ISO_ARCH}]"
    elif [ "$TARGET_PROFILE" = "check" ]; then
        log_msg "Init" "Command:  nix eval"
    elif [ "$TARGET_PROFILE" = "os" ]; then
        case "$ACTION" in
            switch) log_msg "Init" "Command:  nixos-rebuild switch" ;;
            boot)   log_msg "Init" "Command:  nixos-rebuild boot" ;;
            test)   log_msg "Init" "Command:  nixos-rebuild test" ;;
            build)  log_msg "Init" "Command:  nixos-rebuild build" ;;
        esac
    elif [ "$TARGET_PROFILE" = "home" ]; then
        case "$ACTION" in
            switch) log_msg "Init" "Command:  home-manager switch" ;;
            test)   log_msg "Init" "Command:  home-manager build --dry-run" ;;
            build)  log_msg "Init" "Command:  home-manager build" ;;
        esac
    fi

    if [ -n "$HOST_ID" ] && [ "$TARGET_PROFILE" != "iso" ] && \
       ! { [ "$TARGET_PROFILE" = "check" ] && [ "$CHECK_DEEP" = true ]; }; then
        log_msg "Init" "Target:   $HOST_ID"
        if [ "$IS_ROLLING" == "true" ]; then
            log_msg "Init" "Mode:     rolling"
        else
            log_msg "Init" "Mode:     stable"
        fi
    fi
}
