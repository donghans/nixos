#!/usr/bin/env bash
# shellcheck disable=SC1091
# nixstrap.lib-ui.sh — nixstrap 도구용 UI 설정

SCRIPT_DIR_UI="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
source "$SCRIPT_DIR_UI/lib-ui.sh"

_LOG_PREFIX="NIXSTRAP"
_LOG_PREFIX_COLOR="$CYAN"
declare -A _LOG_CAT=(
    [Init]="$CYAN"    [Target]="$CYAN"
    [Usage]="$YELLOW"
    [Disk]="$PURPLE"  [Mount]="$PURPLE" [Install]="$PURPLE"
    [Git]="$BLUE"     [Config]="$BLUE"
    [Done]="$GREEN"   [Success]="$GREEN"
    [Error]="$RED"
    [Notice]="$YELLOW" [Question]="$YELLOW" [Input]="$YELLOW" [Cleanup]="$YELLOW"
    [Review]="$CYAN"
)
