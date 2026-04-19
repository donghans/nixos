#!/usr/bin/env bash
# nixstrap.lib-ui.sh — 화살표 키 선택 UI

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
                printf "  ${CYAN}>  ${items[$i]}${NC}\n"
            else
                printf "     ${items[$i]}\n"
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
