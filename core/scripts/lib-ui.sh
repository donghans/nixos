#!/usr/bin/env bash
# shellcheck disable=SC2034  # 색상 상수는 소싱 파일에서 사용됨
# lib-ui.sh — 공통 UI 기반: 색상 상수, 로깅, 프롬프트, 인터랙티브 선택 UI
#
# 사용법: 각 도구의 lib-ui.sh에서 이 파일을 source한 뒤
#         _LOG_PREFIX / _LOG_PREFIX_COLOR / _LOG_CAT 를 도구별로 설정.
#
# 기본값: _LOG_PREFIX=NIXUP, _LOG_PREFIX_COLOR=$CYAN

# ── ANSI 색상 상수 ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 도구별 설정 변수 (각 lib-ui.sh에서 덮어씀) ───────────────────────────────
_LOG_PREFIX="${_LOG_PREFIX:-NIXUP}"
_LOG_PREFIX_COLOR="${_LOG_PREFIX_COLOR:-$CYAN}"
declare -gA _LOG_CAT=()

# ── 로깅 헬퍼 ─────────────────────────────────────────────────────────────────
log_msg() {
    local category=$1 msg=$2
    local cat_color="${_LOG_CAT[$category]:-$NC}"
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${cat_color}%-9s${NC} | %s\n" "$category" "$msg"
}

log_exec() {
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${BLUE}Exec %-4s${NC} %s %s\n" "$1" "$2" "$3"
}

# ── 단일행 입력 프롬프트 ──────────────────────────────────────────────────────
# 사용법: read -rp "$(_log_prompt)질문 텍스트: " VAR
_log_prompt() {
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${YELLOW}%-9s${NC} | " "Input"
}

# readline-safe 버전 (read -e 와 함께 사용 — ANSI 시퀀스를 \001..\002로 감싸 cursor 위치 보정)
_log_prompt_rl() {
    printf "\001${_LOG_PREFIX_COLOR}\002${_LOG_PREFIX}\001${NC}\002 \001${YELLOW}\002%-9s\001${NC}\002 | " "Input"
}

# 위험 동작용 (디스크 삭제 등) — "Input" 텍스트를 RED로 표시
_log_prompt_danger() {
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${RED}%-9s${NC} | " "Input"
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

    log_msg "Input" "$label  (↑↓ 이동, Enter 확인)"
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

# ── _print_summary: 실행 요약 (EXIT trap에서 호출) ─────────────────────────────
# _START_TIME / _START_TIME_STR 가 설정된 경우에만 출력 (미설정 시 no-op)
_print_summary() {
    [ -z "${_START_TIME:-}" ] && return
    local _end _dur
    _end=$(date "+%Y-%m-%d %H:%M:%S")
    _dur=$(( $(date +%s) - _START_TIME ))
    log_msg "Summary" "시작:    $_START_TIME_STR"
    log_msg "Summary" "완료:    $_end"
    log_msg "Summary" "소요:    ${_dur}s"
}
