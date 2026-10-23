#!/bin/sh
# abab_lib.sh — 번갈아(ABAB) 측정 틀. 이 파일을 `.` 로 불러오고 아래 함수를 정의한 뒤 `abab_run` 을 부른다.
#
#   abab_set_a     A 조건을 적용(실패하면 비-0 으로 끝남)         abab_verify_a  A 가 실제로 적용됐는지 확인(0=맞음)
#   abab_set_b     B 조건을 적용                                   abab_verify_b  B 가 실제로 적용됐는지 확인
#   abab_restore   원래 상태로 복구 — 끝나거나 중단되거나 실패하든 **반드시 한 번** 실행된다
#
# AC 모드(ABAB_AC_MODE=1): 어댑터를 뽑지 않고 잰다 — AC 가 연결된 채로 `tlp bat`(배터리 전원 정책을 수동 적용)로 바꿔 두고, 끝나면 `tlp start`(자동)로 되돌린다.
#   배터리가 충전 중이 아니어야 깨끗하다(만충·"Not charging"). 이 모드에서는 배터리 쪽 지표(순간 V×I·누적 계량)가 없고 RAPL(psys·패키지)·Netdata 1초 값으로 판정한다.
#   psys 는 배터리 쪽 지표보다 효과가 크게 나올 수 있어(예: Netdata 끔 psys −1.07 W 대 배터리 −0.5~−0.6 W) 최종 결정 전에는 배터리 모드로 한 번 확인한다.
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
_ABAB_DONE=0; _ABAB_SLP=""; _ABAB_RC=0; _ABAB_TLP=0
_ABAB_FINISHED=0; _NPAIR_OK=0; _T_PAIR_END=""; _ABAB_REC=""
RAPL_CMD=${RAPL_CMD:-timeout 5 sudo -n cat /sys/class/powercap/intel-rapl:1/energy_uj /sys/class/powercap/intel-rapl:0/energy_uj}   # 누적 에너지(μJ) 두 줄: psys, 패키지
ABAB_OUT_DIR=${ABAB_OUT_DIR:-$HOME/.local/state/observe/ab-runs}   # 구간마다 한 줄씩 남기는 기록과 분석 결과(중간에 중단돼도 남는다)

abab_lid() { cat ${ABAB_LID_FILE:-/proc/acpi/button/lid/*/state} 2>/dev/null | awk '{print $2}' | head -1; }
abab_ac()  { cat ${ABAB_AC_FILE:-/sys/class/power_supply/ADP1/online} 2>/dev/null | head -1; }

_abab_cleanup() {
    [ "$_ABAB_DONE" = 1 ] && return 0
    _ABAB_DONE=1
    [ -n "$_ABAB_SLP" ] && kill "$_ABAB_SLP" 2>/dev/null
    abab_restore
    [ "$_ABAB_TLP" = 1 ] && ${TLP_CMD:-sudo -n tlp} start >/dev/null 2>&1
    $OBS mark --clear >/dev/null 2>&1
    echo "$(date +%T) 복구 완료"
    if [ "$_ABAB_FINISHED" = 0 ]; then _abab_partial; _abab_rapl_report; fi
    return 0
}

_abab_rapl_report() { [ -n "$_ABAB_REC" ] && [ -s "$_ABAB_REC.rapl" ] || return 0; python3 "$(dirname "${ABAB_LIB_PATH:-$0}")/abab_rapl.py" "$_ABAB_REC.rapl" 2>&1 | tee -a "$_ABAB_REC.result"; }

_abab_partial() {   # 도중에 끝났을 때: 조건이 유지된 채 끝낸 쌍(A+B)까지만 분석한다. `observectl ab` 는 구간이 4개(2쌍) 이상이어야 하므로 그보다 적으면 기록만 남는다(표본은 수집기에 저장돼 있음).
    [ "$_NPAIR_OK" -ge 2 ] || { echo "중단됨 — 끝낸 쌍이 ${_NPAIR_OK}개라 분석하지 않습니다(2쌍 이상 필요). 표본은 저장돼 있고 구간 기록: $_ABAB_REC"; return 0; }
    echo "중단됨 — 조건이 유지된 채 끝낸 ${_NPAIR_OK}쌍까지만 분석합니다(구간 기록: $_ABAB_REC)"
    # shellcheck disable=SC2086
    $OBS ab --since "$T0" --until "$_T_PAIR_END" --settle "$SETTLE" --min-samples 3 --require "dev.lid=$_LID0" --require "pw.ac=$_AC0" $AB_ARGS 2>&1 | tee "$_ABAB_REC.result"
}
trap '_abab_cleanup' EXIT
trap '_abab_cleanup; exit 130' INT
trap '_abab_cleanup; exit 143' TERM HUP

_abab_rapl() { printf '%s %s\n' "$(date +%s%N)" "$($RAPL_CMD 2>/dev/null | tr '\n' ' ')"; }   # "시각(ns) psys_uJ pkg_uJ" — 구간 경계에서 누적 카운터를 직접 읽어 수집기 30초 격자 오차를 없앤다

_abab_sleep() { sleep "$1" & _ABAB_SLP=$!; wait "$_ABAB_SLP"; _ABAB_SLP=""; }       # 신호가 오면 wait 가 바로 끝나 trap 이 실행된다

_abab_guard() {   # 덮개·AC 가 시작 때와 같은지. $1=A|B $2=표지 $3=구간 시작(초). 구간마다 기록 파일에 한 줄(조건·시작·끝·덮개·AC·유효 여부)을 남긴다.
    _ok=1; { [ "$(abab_lid)" = "$_LID0" ] && [ "$(abab_ac)" = "$_AC0" ]; } || _ok=0
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$(date +%s)" "$(abab_lid)" "$(abab_ac)" "$([ "$_ok" = 1 ] && echo valid || echo INVALID)" >> "$_ABAB_REC"
    [ "$_ok" = 1 ] && return 0
    echo "$(date +%T) ✗ 시험 도중 조건이 바뀜(덮개 $_LID0→$(abab_lid), AC $_AC0→$(abab_ac)) — 이 구간부터 무효, 중단합니다(앞서 끝낸 쌍은 분석)"
    exit 4
}

_abab_step() {   # $1=A|B  $2=표지 설명
    "abab_set_$(echo "$1" | tr 'AB' 'ab')" || { echo "FAIL: $1 조건 적용 실패"; exit 3; }
    _abab_sleep 3
    "abab_verify_$(echo "$1" | tr 'AB' 'ab')" || { echo "FAIL: $1 조건이 실제로 적용되지 않음"; exit 3; }
    _seg0=$(date +%s)
    $OBS mark "$1" "$2" >/dev/null
    echo "$(date +%T) $1 시작 ($2) · 덮개 $(abab_lid) · AC $(abab_ac)"
    _r0=$(_abab_rapl); _ss=$SETTLE; [ "$_ss" -gt "$SEG" ] && _ss=$SEG
    _abab_sleep "$_ss"; _r1=$(_abab_rapl)
    _abab_sleep $((SEG - _ss)); _r2=$(_abab_rapl)
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$_r0" "$_r1" "$_r2" >> "$_ABAB_REC.rapl"
    _abab_guard "$1" "$2" "$_seg0"
    if [ "$1" = B ]; then _NPAIR_OK=$((_NPAIR_OK + 1)); _T_PAIR_END=$(date +%s); fi
}

abab_run() {
    _LID0=$(abab_lid); _AC0=$(abab_ac); T0=$(date +%s)
    if [ "${ABAB_AC_MODE:-0}" = 1 ]; then
        [ "$_AC0" = 1 ] || { echo "✗ ABAB_AC_MODE=1 은 AC 를 꽂은 상태에서 쓰는 모드입니다(현재 AC=$_AC0)"; exit 4; }
        ${TLP_CMD:-sudo -n tlp} bat >/dev/null || { echo "FAIL: tlp bat 적용 실패"; exit 3; }
        _ABAB_TLP=1
        echo "AC 모드: AC 를 꽂은 채 TLP 배터리 정책으로 측정합니다(배터리 지표 없음 — psys·패키지로 판정)"
    fi
    mkdir -p "$ABAB_OUT_DIR" && _ABAB_REC="$ABAB_OUT_DIR/$T0-$(basename "$0" .sh).tsv" || _ABAB_REC=/dev/null
    { echo "# 환경 지문(재현용): 시각 $(date -Is) · 커널 $(uname -r)"
      for _f in /sys/class/power_supply/BAT1/status /sys/class/power_supply/BAT1/capacity /sys/class/power_supply/BAT1/current_now /sys/devices/system/cpu/intel_pstate/max_perf_pct /sys/devices/system/cpu/intel_pstate/no_turbo /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference; do echo "$_f=$(cat "$_f" 2>/dev/null)"; done
      echo "wifi=$(iwgetid -r 2>/dev/null)"; echo "loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"; echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
      echo "상위 CPU: $(ps -eo comm,%cpu --sort=-%cpu 2>/dev/null | sed -n 2,6p | tr '\n' ';')"; } > "$_ABAB_REC.env" 2>/dev/null
    : > "$_ABAB_REC.rapl"   # 구간 경계 RAPL 읽기: 조건·표지·(시각ns psys pkg)×3(시작·안정화 끝·구간 끝)
    printf '# 조건\t표지\t시작(초)\t끝(초)\t덮개\tAC\t유효\n' > "$_ABAB_REC"
    echo "T0=$T0 · 구간 ${SEG}초 × $((PAIRS * 2)) · 덮개 $_LID0 · AC $_AC0 · 구간 기록 $_ABAB_REC"
    _pair=1       # 훅 함수(abab_set_* 등)가 같은 이름을 쓰지 못하게 앞에 밑줄(POSIX sh 는 변수가 전역 — 2026-10-21 T20 에서 훅의 i 가 쌍 카운터를 덮어 무한 반복했음)
    while [ "$_pair" -le "$PAIRS" ]; do
        _abab_step A "A #$_pair"
        _abab_step B "B #$_pair"
        _pair=$((_pair + 1))
    done
    _ABAB_FINISHED=1
    $OBS mark --clear >/dev/null
    # shellcheck disable=SC2086
    $OBS ab --since "$T0" --settle "$SETTLE" --min-samples 3 --require "dev.lid=$_LID0" --require "pw.ac=$_AC0" $AB_ARGS 2>&1 | tee "$_ABAB_REC.result"
    _abab_rapl_report
}
