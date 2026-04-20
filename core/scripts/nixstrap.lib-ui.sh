#!/usr/bin/env bash
# nixstrap.lib-ui.sh — 색상 상수, 로깅 헬퍼, 화살표 키 선택 UI

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
        Notice|Question|Input) cat_color=$YELLOW ;;
        *)               cat_color=$NC ;;
    esac

    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

# read -rp용 프롬프트 접두사 (log_msg와 동일한 정렬)
log_prompt() {
    printf "${PURPLE}NIXSTRAP${NC} ${YELLOW}%-9s${NC} | " "Input"
}

# 위험 동작 프롬프트 (빨간색)
log_prompt_danger() {
    printf "${PURPLE}NIXSTRAP${NC} ${RED}%-9s${NC} | " "Input"
}

# nixup과 동일한 정렬 포맷: NIXSTRAP Exec cmd > description
log_exec() {
    local cmd_name=$1
    local state=$2
    local msg=$3
    local cat_color=$BLUE

    printf "${PURPLE}NIXSTRAP${NC} ${cat_color}Exec %-4s${NC} %s %s\n" "$cmd_name" "$state" "$msg"
}

# 사용법: _pick "레이블" "항목1" "항목2" ...
# 선택된 인덱스(0-based)를 REPLY에 설정.
_pick() {
    local label="$1"; shift
    local items=("$@")
    local count=${#items[@]}
    local sel=0

    _redraw_pick() {
        local i
        for i in "${!items[@]}"; do
            tput el || true
            if [ "$i" -eq "$sel" ]; then
                printf "  %s>  %s%s\n" "${CYAN}" "${items[$i]}" "${NC}"
            else
                printf "     %s\n" "${items[$i]}"
            fi
        done
    }

    log_msg "Input" "$label"
    _redraw_pick

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
            $'\x1b[A') if ((sel > 0)); then sel=$((sel - 1)); fi ;;
            $'\x1b[B') if ((sel < count - 1)); then sel=$((sel + 1)); fi ;;
            '') break ;;
        esac
        _redraw_pick
    done

    # Enter 시 커서가 목록 상단에 있으므로 최종 상태를 다시 그려 커서를 아래로 이동
    _redraw_pick
    REPLY=$sel
}
