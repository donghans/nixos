#!/bin/sh
# 검증형 Wi-Fi 절전 A/B 예제(observectl 사용). A=절전 끔(기준), B=절전 켬. 120초 × 4구간, 바꾼 직후 실제 값을 읽어 확인하고 다르면 중단.
# 전제: observectl on L0 이 켜져 있고 어댑터를 뺀 상태, 덮개 닫힘. 사용: wifi_abab.sh [안정화 초=100]
# 주의: root 명령은 setuid 래퍼 /run/wrappers/bin/sudo 여야 한다(PATH 앞에 /run/current-system/sw/bin 을 두면 안 됨).
export PATH=/run/wrappers/bin:/run/current-system/sw/bin:$PATH
IW=${IW:-$(ls -d /nix/store/*-iw-*/bin 2>/dev/null | head -1)/iw}
OBS=observectl
setps() {
  sudo -n "$IW" dev wlan0 set power_save "$1" || { echo "FAIL: sudo/iw 실행 실패"; $OBS mark --clear; exit 3; }
  sleep 2
  got=$("$IW" dev wlan0 get power_save | awk '{print $3}')
  [ "$got" = "$1" ] || { echo "FAIL: 절전 $1 로 바꿨는데 실제 $got"; $OBS mark --clear; exit 3; }
  echo "$(date +%T) 절전 $got 확인"
}
T0=$(date +%s)
sleep "${1:-100}"
for i in 1 2; do
  setps off; $OBS mark A "ps off #$i" >/dev/null; sleep 120
  setps on;  $OBS mark B "ps on #$i"  >/dev/null; sleep 120
done
$OBS mark --clear >/dev/null
for m in psys_w batt_w pkg_w; do
  echo "===== $m"
  $OBS ab --since $T0 --metric $m --settle 40 --expect-a dev.wifi.ps=off --expect-b dev.wifi.ps=on
done
$OBS window --since $T0 --by wifips
