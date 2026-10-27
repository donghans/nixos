#!/bin/sh
# PSR(패널 셀프 리프레시) 끔(A) / 켬(B) 번갈아 — 덮개 열림·화면 켜짐에서 PSR 의 전력 효과(장부 #56 의 3분 2쌍을 긴 구간으로 재확인).
# 사용: ABAB_AC_MODE=1 SEG=300 PAIRS=4 SETTLE=60 psr_abab.sh   (덮개 열림, 어댑터 AC·독 없음, 시험 중 무입력)
# 전환은 debugfs i915_edp_psr_debug(0=끔, 2=켬)에 쓰고 링크 재훈련(i915_dp_force_link_retrain)으로 모드셋을 일으켜 반영한다(DPMS·VT 전환은 반영 안 함 — 장부 #54).
# 재훈련 때 화면이 잠깐 깜빡이는 것은 정상. 끝나면(중단 포함) 시작 때의 값으로 복구한다.
SETTLE=${SETTLE:-60}   # abab_lib.sh 가 SETTLE 기본값(40)을 먼저 채우므로 불러오기 전에 정한다
. "$(dirname "$0")/abab_lib.sh"
DRI=${PSR_DRI:-/sys/kernel/debug/dri/1}
PSR_DBG=$DRI/i915_edp_psr_debug              # eDP-1/ 아래에는 없다(2026-10-22 확인)
PSR_STATUS=$DRI/eDP-1/i915_psr_status
PSR_RETRAIN=$DRI/eDP-1/i915_dp_force_link_retrain
_psr_rd() { sudo -n cat "$1" 2>/dev/null; }
_psr_wr() { printf '%s\n' "$1" | sudo -n tee "$2" >/dev/null; }
_psr_set() {   # $1=값(0|2)
    _psr_wr "$1" "$PSR_DBG" || return 1
    _psr_wr 1 "$PSR_RETRAIN" || return 1
    sleep 5   # 재훈련·모드셋이 끝나 상태가 갱신될 시간
}
PSR_ORIG=$(_psr_rd "$PSR_DBG" | awk 'NR==1{print $1}')
[ -n "$PSR_ORIG" ] || { echo "✗ $PSR_DBG 를 읽지 못함(sudo·debugfs 확인)"; exit 3; }
_psr_mode() { _psr_rd "$PSR_STATUS" | sed -n 's/^PSR mode: //p' | head -1; }
abab_set_a()    { _psr_set 0; }
abab_set_b()    { _psr_set 2; }
abab_verify_a() { case "$(_psr_mode)" in *enabled*) return 1 ;; *) return 0 ;; esac; }   # PSR 이 켜졌다는 말이 없으면 꺼진 것
abab_verify_b() { case "$(_psr_mode)" in *PSR*enabled*) return 0 ;; *) return 1 ;; esac; }
abab_restore()  { _psr_set "$PSR_ORIG"; echo "PSR 복구: debug=$PSR_ORIG · $(_psr_mode)"; }
echo "시작 값: debug=$PSR_ORIG · PSR mode: $(_psr_mode)"
abab_run
