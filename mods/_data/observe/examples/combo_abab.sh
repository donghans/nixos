#!/bin/sh
# Netdata + Bitwarden 를 함께 켬(A) / 끔(B) 번갈아 — 두 효과를 합친 "한가한 바닥"(T25). 개별 효과(각 -0.3~-0.6 W)가 합쳐져 예전 기준선(2.7~3.0 W)을 설명하는지 확인.
# 사용: combo_abab.sh   (덮개 닫고 배터리, 손대지 않기)
. "$(dirname "$0")/abab_lib.sh"
. "$(dirname "$0")/bw_lib.sh"
abab_set_a()    { sudo -n systemctl start netdata && bw_start; }
abab_set_b()    { sudo -n systemctl stop netdata && bw_stop; }
abab_verify_a() { [ "$(systemctl is-active netdata)" = active ] && _bw_running; }
abab_verify_b() { [ "$(systemctl is-active netdata)" = inactive ] && ! _bw_running; }
abab_restore()  { sudo -n systemctl start netdata >/dev/null 2>&1; bw_start; echo "netdata=$(systemctl is-active netdata) bitwarden=$(_bw_running && echo 켜짐 || echo 꺼짐)"; }
abab_run
