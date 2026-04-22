#!/usr/bin/env bash
# shellcheck disable=SC1091
# nixup.lib-ui.sh — nixup 도구용 UI 설정 및 초기화 배너

SCRIPT_DIR_UI="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
source "$SCRIPT_DIR_UI/lib-ui.sh"

_LOG_PREFIX="NIXUP"
_LOG_PREFIX_COLOR="$CYAN"
declare -A _LOG_CAT=(
    [Init]="$CYAN"    [Prep]="$CYAN"
    [Task]="$PURPLE"
    [Summary]="$NC"
    [Done]="$GREEN"   [Success]="$GREEN"
    [Error]="$RED"
    [Notice]="$YELLOW" [Warn]="$YELLOW" [Input]="$YELLOW" [Lock]="$YELLOW"
)

# Print Init Banner (실행 시작 시 Action/Target/Mode 출력)
print_init_banner() {
    log_msg "Init" "NixOS 업데이트 도구"

    if [ "$DO_CLEAN" = true ]; then
        log_msg "Init" "명령어:  nix-env --delete-generations (keep: $CLEAN_KEEP)"
    elif [ "$TARGET_PROFILE" = "fix-unstable" ]; then
        log_msg "Init" "명령어:  nix flake update <input>"
    elif [ "$TARGET_PROFILE" = "update" ]; then
        log_msg "Init" "명령어:  nix flake update"
    elif [ "$TARGET_PROFILE" = "check" ] && [ "${CHECK_FAST:-false}" = true ]; then
        log_msg "Init" "명령어:  nix eval"
    elif [ "$TARGET_PROFILE" = "iso" ]; then
        log_msg "Init" "명령어:  nix build .#nixos-iso [${ISO_ARCH}]"
    elif [ "$TARGET_PROFILE" = "check" ]; then
        log_msg "Init" "명령어:  nix flake check"
    elif [ "$TARGET_PROFILE" = "os" ]; then
        case "$ACTION" in
            switch) log_msg "Init" "명령어:  nixos-rebuild switch" ;;
            boot)   log_msg "Init" "명령어:  nixos-rebuild boot" ;;
            test)   log_msg "Init" "명령어:  nixos-rebuild test" ;;
            build)  log_msg "Init" "명령어:  nixos-rebuild build" ;;
        esac
    elif [ "$TARGET_PROFILE" = "home" ]; then
        case "$ACTION" in
            switch) log_msg "Init" "명령어:  home-manager switch" ;;
            test)   log_msg "Init" "명령어:  home-manager build --dry-run" ;;
            build)  log_msg "Init" "명령어:  home-manager build" ;;
        esac
    fi

    if [ -n "$HOST_ID" ] && [ "$TARGET_PROFILE" != "iso" ] && \
       ! { [ "$TARGET_PROFILE" = "check" ] && [ "${CHECK_FAST:-false}" != true ]; }; then
        log_msg "Init" "대상:     $HOST_ID"
        if [ "$IS_ROLLING" == "true" ]; then
            log_msg "Init" "모드:     rolling"
        else
            log_msg "Init" "모드:     stable"
        fi
    fi
}
