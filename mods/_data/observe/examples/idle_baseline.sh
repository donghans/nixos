#!/bin/sh
# 덮개 닫힘·배터리·손대지 않기 상태의 한가한 기준선(T22). 사용: idle_baseline.sh [분=20]
export PATH=/run/wrappers/bin:/run/current-system/sw/bin:$PATH
OBS=observectl; M=${1:-20}
lid=$(cat /proc/acpi/button/lid/*/state | awk '{print $2}'); ac=$(cat /sys/class/power_supply/ADP1/online)
# ABAB_AC_MODE=1 이면 AC 를 꽂은 채(tlp bat 으로 배터리 정책 적용) 잰다. 아니면 AC 분리 상태여야 한다.
WANT_AC=0; [ "${ABAB_AC_MODE:-0}" = 1 ] && WANT_AC=1
[ "$lid" = closed ] && [ "$ac" = "$WANT_AC" ] || { echo "✗ 덮개 닫힘·AC 상태가 맞지 않음(덮개 $lid, AC $ac, 기대 AC=$WANT_AC)"; exit 4; }
[ "$WANT_AC" = 1 ] && { sudo -n tlp bat >/dev/null || exit 3; trap 'sudo -n tlp start >/dev/null 2>&1' EXIT; }
T0=$(date +%s); $OBS mark A "idle baseline" >/dev/null; echo "$(date +%T) 기준선 시작 ${M}분"
trap '$OBS mark --clear >/dev/null 2>&1; [ "$WANT_AC" = 1 ] && sudo -n tlp start >/dev/null 2>&1; exit 143' TERM INT HUP
sleep $((M * 60)) & wait $!
$OBS mark --clear >/dev/null
[ "$(cat /proc/acpi/button/lid/*/state | awk '{print $2}')" = closed ] && [ "$(cat /sys/class/power_supply/ADP1/online)" = "$WANT_AC" ] || echo "⚠ 도중에 덮개·AC 상태가 바뀜 — 무효"
echo "== 상태별(깨끗한 표본) =="; $OBS window --since $T0 --clean --by state
echo "== 전체 =="; $OBS window --since $T0 --by none
echo "== 앱 =="; $OBS top --since $((M))m --by app -n 8
