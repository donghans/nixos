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
    elif [ "$TARGET_PROFILE" = "check" ] && [ "${CHECK_FAST:-false}" = true ]; then
        log_msg "Init" "Command:  nix eval"
    elif [ "$TARGET_PROFILE" = "iso" ]; then
        log_msg "Init" "Command:  nix build .#nixos-iso [${ISO_ARCH}]"
    elif [ "$TARGET_PROFILE" = "check" ]; then
        log_msg "Init" "Command:  nix flake check"
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
       ! { [ "$TARGET_PROFILE" = "check" ] && [ "${CHECK_FAST:-false}" != true ]; }; then
        log_msg "Init" "Target:   $HOST_ID"
        if [ "$IS_ROLLING" == "true" ]; then
            log_msg "Init" "Mode:     rolling"
        else
            log_msg "Init" "Mode:     stable"
        fi
    fi
}

# ── _pick: 화살표 키 단일 선택 ────────────────────────────────────────────────
# 사용법: _pick "레이블" "항목1" "항목2" ...
# 선택된 인덱스(0-based)를 REPLY에 설정.
#
# _PICK_FIXED_FOOTER (선택적 전역 배열): 설정 시 선택 목록 하단에
# 구분선과 함께 비선택 항목으로 표시됨. 커서가 이 영역에 진입하지 않음.
_pick() {
    local label="$1"; shift
    local items=("$@")
    local count=${#items[@]}
    local sel=0
    local footer=("${_PICK_FIXED_FOOTER[@]+"${_PICK_FIXED_FOOTER[@]}"}")
    local footer_count=${#footer[@]}
    local draw_lines=$count
    [ "$footer_count" -gt 0 ] && draw_lines=$((draw_lines + 1 + footer_count))

    _redraw_pick() {
        local i
        for i in "${!items[@]}"; do
            tput el || true
            if [ "$i" -eq "$sel" ]; then
                printf "  ${CYAN}>  %s${NC}\n" "${items[$i]}"
            else
                printf "     %s\n" "${items[$i]}"
            fi
        done
        if [ "$footer_count" -gt 0 ]; then
            tput el || true
            printf "  \033[2m─────────────────────────────────────────\033[0m\n"
            for item in "${footer[@]}"; do
                tput el || true
                printf "  \033[2m     %s\033[0m\n" "$item"
            done
        fi
    }

    log_msg "Input" "$label"
    _redraw_pick

    local key seq
    while true; do
        local i
        for ((i=0; i<draw_lines; i++)); do tput cuu1 || true; done
        IFS= read -rsn1 key
        if [[ "$key" == $'\x1b' ]]; then
            IFS= read -rsn2 seq || true
            key+="$seq"
        fi
        case "$key" in
            $'\x1b[A') ((sel > 0)) && sel=$((sel - 1)) ;;
            $'\x1b[B') ((sel < count - 1)) && sel=$((sel + 1)) ;;
            '') break ;;
        esac
        _redraw_pick
    done

    _redraw_pick
    REPLY=$sel
}

# ── _check: 스페이스 토글 다중 선택 ──────────────────────────────────────────
# 사용법: _check "레이블" KEY1 "표시1" KEY2 "표시2" ...
# (키와 표시가 쌍으로 입력. KEY 목록 → REPLY_CHECKED 배열에 설정)
_check() {
    local label="$1"; shift
    local -a keys=() labels=()
    while [ $# -ge 2 ]; do
        keys+=("$1")
        labels+=("$2")
        shift 2
    done
    local count=${#keys[@]}
    local -a selected=()
    local cur=0

    for ((i=0; i<count; i++)); do selected+=("false"); done

    _redraw_check() {
        local i mark
        for i in "${!keys[@]}"; do
            tput el || true
            if [ "${selected[$i]}" = "true" ]; then mark="[x]"; else mark="[ ]"; fi
            if [ "$i" -eq "$cur" ]; then
                printf "  ${CYAN}> %s  %s${NC}\n" "$mark" "${labels[$i]}"
            else
                printf "    %s  %s\n" "$mark" "${labels[$i]}"
            fi
        done
    }

    log_msg "Input" "$label  (↑↓ 이동, Space 토글, Enter 확인)"
    _redraw_check

    local key seq
    while true; do
        local i
        for ((i=0; i<count; i++)); do tput cuu1 || true; done
        IFS= read -rsn1 key
        if [[ "$key" == $'\x1b' ]]; then
            IFS= read -rsn2 seq || true
            key+="$seq"
        fi
        case "$key" in
            $'\x1b[A') ((cur > 0)) && cur=$((cur - 1)) ;;
            $'\x1b[B') ((cur < count - 1)) && cur=$((cur + 1)) ;;
            ' ')
                if [ "${selected[$cur]}" = "true" ]; then
                    selected[cur]="false"
                else
                    selected[cur]="true"
                fi
                ;;
            '') break ;;
        esac
        _redraw_check
    done

    _redraw_check
    REPLY_CHECKED=()
    for i in "${!keys[@]}"; do
        [ "${selected[$i]}" = "true" ] && REPLY_CHECKED+=("${keys[$i]}")
    done
}
