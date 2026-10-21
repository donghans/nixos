#!/bin/sh
# Netdata 켬(A) / 끔(B) 번갈아 측정 — abab_lib.sh 사용 예. 사용: netdata_abab.sh   (덮개를 닫고 배터리에서, 손대지 않기)
. "$(dirname "$0")/abab_lib.sh"
abab_set_a()    { sudo -n systemctl start netdata; }
abab_set_b()    { sudo -n systemctl stop netdata; }
abab_verify_a() { [ "$(systemctl is-active netdata)" = active ]; }
abab_verify_b() { [ "$(systemctl is-active netdata)" = inactive ]; }
ND_WAS=$(systemctl is-active netdata)
abab_restore()  { if [ "$ND_WAS" = active ]; then sudo -n systemctl start netdata >/dev/null 2>&1; else sudo -n systemctl stop netdata >/dev/null 2>&1; fi; echo "netdata=$(systemctl is-active netdata)"; }
abab_run
