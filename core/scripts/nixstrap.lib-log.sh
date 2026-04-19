#!/usr/bin/env bash
# nixstrap.lib-log.sh — 색상 상수 및 로깅 헬퍼

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log_msg() {
    local category=$1
    local msg=$2
    local cat_color=$NC

    case "$category" in
        Init|Target)     cat_color=$CYAN ;;
        Usage)           cat_color=$YELLOW ;;
        Disk|Mount)      cat_color=$PURPLE ;;
        Git|Config)      cat_color=$BLUE ;;
        Install)         cat_color=$PURPLE ;;
        Done|Success)    cat_color=$GREEN ;;
        Error)           cat_color=$RED ;;
        Notice|Question) cat_color=$YELLOW ;;
        *)               cat_color=$NC ;;
    esac

    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# nixup과 동일한 정렬 포맷: NIXSTRAP Exec cmd > description
log_exec() {
    local cmd_name=$1
    local state=$2
    local msg=$3
    local cat_color=$BLUE

    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}
