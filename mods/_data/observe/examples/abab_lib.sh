#!/bin/sh
# abab_lib.sh — 번갈아(ABAB) 측정 틀. 이 파일을 `.` 로 불러오고 아래 함수를 정의한 뒤 `abab_run` 을 부른다.
#
#   abab_set_a     A 조건을 적용(실패하면 비-0 으로 끝남)         abab_verify_a  A 가 실제로 적용됐는지 확인(0=맞음)
#   abab_set_b     B 조건을 적용                                   abab_verify_b  B 가 실제로 적용됐는지 확인
#   abab_restore   원래 상태로 복구 — 끝나거나 중단되거나 실패하든 **반드시 한 번** 실행된다
#
# 환경변수: SEG=구간 초(기본 300, 5분 이상 권장 — 짧으면 순간 V×I·누적 계량이 신뢰 낮음), PAIRS=쌍 수(기본 3), SETTLE=안정화 초(기본 40),
#           AB_ARGS=`observectl ab` 에 더 넘길 인자(예: "--expect-a dev.wifi.ps=off --expect-b dev.wifi.ps=on")
#
# 이 틀이 막아 주는 것(2026-10-21 시험에서 실제로 겪은 문제):
#   - 신호(Ctrl-C/TERM)를 받으면 복구하고 **끝낸다**(복구만 하고 다음 단계로 가지 않음). 기다리는 sleep 도 바로 깨어난다.
#   - 시작 때의 덮개·AC 상태를 기억해 두고, 구간 사이마다 달라졌으면 즉시 중단(예: 중간에 덮개를 엶) — 무효 구간을 15분 더 재지 않는다.
#   - 조건을 바꾼 직후 실제 값을 읽어 확인(verify)하고, 다르면 중단.
#   - 마지막 `observectl ab` 에 `--require dev.lid=… --require pw.ac=…` 를 자동으로 붙여 교란을 한 번 더 검증.
#
# 주의: root 명령은 setuid 래퍼(/run/wrappers/bin/sudo)여야 한다(PATH 앞에 /run/current-system/sw/bin 을 두면 안 됨).
export PATH=/run/wrappers/bin:/run/current-system/sw/bin:$PATH
SEG=${SEG:-300}; PAIRS=${PAIRS:-3}; SETTLE=${SETTLE:-40}; OBS=${OBS:-observectl}
_ABAB_DONE=0; _ABAB_SLP=""; _ABAB_RC=0

abab_lid() { cat ${ABAB_LID_FILE:-/proc/acpi/button/lid/*/state} 2>/dev/null | awk '{print $2}' | head -1; }
abab_ac()  { cat ${ABAB_AC_FILE:-/sys/class/power_supply/ADP1/online} 2>/dev/null | head -1; }

_abab_cleanup() {
    [ "$_ABAB_DONE" = 1 ] && return 0
    _ABAB_DONE=1
    [ -n "$_ABAB_SLP" ] && kill "$_ABAB_SLP" 2>/dev/null
    abab_restore
    $OBS mark --clear >/dev/null 2>&1
    echo "$(date +%T) 복구 완료"
}
trap '_abab_cleanup' EXIT
trap '_abab_cleanup; exit 130' INT
trap '_abab_cleanup; exit 143' TERM HUP

_abab_sleep() { sleep "$1" & _ABAB_SLP=$!; wait "$_ABAB_SLP"; _ABAB_SLP=""; }       # 신호가 오면 wait 가 바로 끝나 trap 이 실행된다

_abab_guard() {   # 덮개·AC 가 시작 때와 같은지
    [ "$(abab_lid)" = "$_LID0" ] && [ "$(abab_ac)" = "$_AC0" ] && return 0
    echo "$(date +%T) ✗ 시험 도중 조건이 바뀜(덮개 $_LID0→$(abab_lid), AC $_AC0→$(abab_ac)) — 중단합니다(이후 구간은 무효)"
    exit 4
}

_abab_step() {   # $1=A|B  $2=표지 설명
    "abab_set_$(echo "$1" | tr 'AB' 'ab')" || { echo "FAIL: $1 조건 적용 실패"; exit 3; }
    _abab_sleep 3
    "abab_verify_$(echo "$1" | tr 'AB' 'ab')" || { echo "FAIL: $1 조건이 실제로 적용되지 않음"; exit 3; }
    $OBS mark "$1" "$2" >/dev/null
    echo "$(date +%T) $1 시작 ($2) · 덮개 $(abab_lid) · AC $(abab_ac)"
    _abab_sleep "$SEG"
    _abab_guard
}

abab_run() {
    _LID0=$(abab_lid); _AC0=$(abab_ac); T0=$(date +%s)
    echo "T0=$T0 · 구간 ${SEG}초 × $((PAIRS * 2)) · 덮개 $_LID0 · AC $_AC0"
    i=1
    while [ "$i" -le "$PAIRS" ]; do
        _abab_step A "A #$i"
        _abab_step B "B #$i"
        i=$((i + 1))
    done
    $OBS mark --clear >/dev/null
    # shellcheck disable=SC2086
    $OBS ab --since "$T0" --settle "$SETTLE" --min-samples 3 --require "dev.lid=$_LID0" --require "pw.ac=$_AC0" $AB_ARGS
}
