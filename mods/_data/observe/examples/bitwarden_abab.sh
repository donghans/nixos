#!/bin/sh
# Bitwarden(Electron 트레이) 켬(A) / 끔(B) 번갈아 — #59 의 Chromium 컴포지터 순환(트레이 ~176/s) 원인 확인(T20).
# 사용: bitwarden_abab.sh   (덮개 닫고 배터리, 손대지 않기). 끝나면 켜진 상태로 복구(볼트는 잠긴 상태로 다시 시작될 수 있음).
. "$(dirname "$0")/abab_lib.sh"
. "$(dirname "$0")/bw_lib.sh"
abab_set_a()    { bw_start; }
abab_set_b()    { bw_stop; }
abab_verify_a() { _bw_running; }
abab_verify_b() { ! _bw_running; }
BW_WAS_RUNNING=0; _bw_running && BW_WAS_RUNNING=1
abab_restore()  { if [ "$BW_WAS_RUNNING" = 1 ]; then bw_start; else bw_stop; fi; echo "bitwarden=$(_bw_running && echo 켜짐 || echo 꺼짐)"; }
AB_ARGS="--ignore-app bitwarden-desktop $AB_ARGS"
abab_run
