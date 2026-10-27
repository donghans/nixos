#!/bin/sh
# 사용: wifi_switch.sh <목표 NetworkManager 프로필> <실패 시 복귀 프로필>   (root 로: sudo systemd-run --collect <이 스크립트> A B)
# 전환 뒤 게이트웨이 핑이 안 되면 복귀 프로필로 되돌린다(원격 세션이 끊기는 것을 막는 안전장치).
export PATH=/run/current-system/sw/bin:$PATH
nmcli dev wifi rescan ifname wlan0 >/dev/null 2>&1; sleep 5
nmcli -w 25 con up "$1" ifname wlan0
sleep 8
gw=$(ip route show default | awk '{print $3; exit}')
if [ -n "$gw" ] && ping -c 2 -W 2 "$gw" >/dev/null 2>&1; then echo "성공: $(nmcli -t -f NAME con show --active | grep -v '^lo' | head -1) gw=$gw"
else echo "실패 → $2 복귀"; nmcli -w 25 con up "$2" ifname wlan0; fi
