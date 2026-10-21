#!/bin/sh
# Vivaldi(탭이 열린 채 한가한 상태) 켬(A) / 끔(B) 번갈아 — 브라우저 자체의 전력 비용. 끌 때는 PID 로만(메인 프로세스 확인 후 TERM, 강제 종료 없음).
# 켤 때는 systemd 사용자 단위(내 셸 환경 오염 방지, 디버깅 포트 포함 래퍼 사용). 시작 직후 탭을 다시 불러오는 비용이 있어 SETTLE 을 길게(기본 150초) 잡는다.
# 끝나면 처음 상태(꺼져 있었으면 끔, 켜져 있었으면 켬)로 복구.
. "$(dirname "$0")/abab_lib.sh"
SETTLE=${SETTLE:-150}; export SETTLE
_vv_main() { ps -u "$(id -u)" -o pid=,args= | awk '/vivaldi-bin/ && !/--type=/ && !/crashpad/ {print $1; exit}'; }
_vv_running() { [ -n "$(_vv_main)" ]; }
VV_WAS_RUNNING=0; _vv_running && VV_WAS_RUNNING=1
abab_set_a() {
    _vv_running && return 0
    systemctl --user reset-failed vivaldi-ab 2>/dev/null
    systemd-run --user --collect --unit=vivaldi-ab env -u LD_LIBRARY_PATH "${VIVALDI:-$HOME/.nix-profile/bin/vivaldi}" >/dev/null 2>&1
    for _n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do _vv_running && return 0; sleep 2; done
    return 1
}
abab_set_b() {
    p=$(_vv_main); [ -z "$p" ] && return 0
    case "$(ps -o args= -p "$p")" in *vivaldi-bin*) kill -TERM "$p" ;; *) echo "FAIL: PID $p 가 Vivaldi 메인이 아님"; return 1 ;; esac
    for _n in $(seq 1 40); do _vv_running || return 0; sleep 1; done
    return 1
}
abab_verify_a() { _vv_running; }
abab_verify_b() { ! _vv_running; }
abab_restore()  { if [ "$VV_WAS_RUNNING" = 1 ]; then abab_set_a; else abab_set_b; fi; echo "vivaldi=$(_vv_running && echo 켜짐 || echo 꺼짐)"; }
AB_ARGS="--ignore-app vivaldi $AB_ARGS"
abab_run
