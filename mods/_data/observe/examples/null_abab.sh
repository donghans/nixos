#!/bin/sh
# null_abab.sh — 널(null) 시험: A 와 B 가 같은 조건(아무것도 바꾸지 않음)으로 번갈아 잰다. 쌍별 A−B 의 흩어짐이 이 환경(덮개·AC·한가함)의 **소음 폭**이다.
# 판정 임계는 이 값 기준으로 정한다(0.3 W 같은 임의값 대신). 사용: ABAB_AC_MODE=1 SEG=300 PAIRS=3 ./null_abab.sh
HERE=$(dirname "$0")
. "$HERE/abab_lib.sh"
abab_set_a() { :; }
abab_set_b() { :; }
abab_verify_a() { true; }
abab_verify_b() { true; }
abab_restore() { :; }
abab_run
