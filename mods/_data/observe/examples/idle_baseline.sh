#!/bin/sh
# 덮개 닫힘·배터리·손대지 않기 상태의 한가한 기준선(T22). 사용: idle_baseline.sh [분=20]
export PATH=/run/wrappers/bin:/run/current-system/sw/bin:$PATH
OBS=observectl; M=${1:-20}
lid=$(cat /proc/acpi/button/lid/*/state | awk '{print $2}'); ac=$(cat /sys/class/power_supply/ADP1/online)
[ "$lid" = closed ] && [ "$ac" = 0 ] || { echo "✗ 덮개 닫힘·AC 분리 상태가 아님(덮개 $lid, AC $ac)"; exit 4; }
T0=$(date +%s); $OBS mark A "idle baseline" >/dev/null; echo "$(date +%T) 기준선 시작 ${M}분"
trap '$OBS mark --clear >/dev/null 2>&1; exit 143' TERM INT HUP
sleep $((M * 60)) & wait $!
$OBS mark --clear >/dev/null
[ "$(cat /proc/acpi/button/lid/*/state | awk '{print $2}')" = closed ] && [ "$(cat /sys/class/power_supply/ADP1/online)" = 0 ] || echo "⚠ 도중에 덮개·AC 상태가 바뀜 — 무효"
echo "== 상태별(깨끗한 표본) =="; $OBS window --since $T0 --clean --by state
echo "== 전체 =="; $OBS window --since $T0 --by none
echo "== 앱 =="; $OBS top --since $((M))m --by app -n 8
