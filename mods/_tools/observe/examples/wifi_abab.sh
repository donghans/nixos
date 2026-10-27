#!/bin/sh
# Wi-Fi 절전 끔(A) / 켬(B) 번갈아 — abab_lib 사용. 사용: wifi_abab.sh   (덮개 닫고, 배터리 또는 ABAB_AC_MODE=1 로 AC 연결 상태에서)
. "$(dirname "$0")/abab_lib.sh"
IW=${IW:-$(command -v iw)}; [ -n "$IW" ] || IW=$(ls -d /nix/store/*-iw-*/bin 2>/dev/null | head -1)/iw
IF=${IF:-$(ls /sys/class/net | grep -E '^wl' | head -1)}
_ps() { "$IW" dev "$IF" get power_save | awk '{print $3}'; }
abab_set_a()    { sudo -n "$IW" dev "$IF" set power_save off; }
abab_set_b()    { sudo -n "$IW" dev "$IF" set power_save on; }
abab_verify_a() { [ "$(_ps)" = off ]; }
abab_verify_b() { [ "$(_ps)" = on ]; }
abab_restore()  { sudo -n "$IW" dev "$IF" set power_save "${WIFI_PS_ORIG:-off}" >/dev/null 2>&1; echo "wifi power_save=$(_ps)"; }
WIFI_PS_ORIG=$(_ps)
AB_ARGS="--expect-a dev.wifi.ps=off --expect-b dev.wifi.ps=on $AB_ARGS"
abab_run
