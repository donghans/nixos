#!/bin/sh
# Vivaldi 가 켜진 채로 "깨움을 줄이는 방법"의 효과를 번갈아 잰다. VARIANT: stop(SIGSTOP — 얻을 수 있는 최대치) · slack(타이머 슬랙 50ms — 깨움 묶기) · pin(CPU 1개에 고정) · vt(활성 VT 를 tty2 로)
# A = 기본, B = 변형. 끝나면(신호·실패 포함) 반드시 A 로 복구한다(SIGSTOP 을 남기지 않는다). 사용: VARIANT=slack proc_abab.sh   (덮개 닫고, Vivaldi 가 떠 있는 상태)
. "$(dirname "$0")/abab_lib.sh"
VARIANT=${VARIANT:?VARIANT=stop|slack|pin|vt}; PROC=${PROC:-vivaldi-bin}
_pids() { for d in /proc/[0-9]*; do [ "$(cat $d/comm 2>/dev/null)" = "$PROC" ] && echo "${d#/proc/}"; done; }
_ncpu=$(nproc); _all="0-$((_ncpu - 1))"
case "$VARIANT" in
  stop)  abab_set_a()    { for p in $(_pids); do kill -CONT "$p" 2>/dev/null; done; }
         abab_set_b()    { for p in $(_pids); do kill -STOP "$p" 2>/dev/null; done; }
         abab_verify_a() { for p in $(_pids); do case "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" in T|t) return 1 ;; esac; done; return 0; }
         abab_verify_b() { n=0; for p in $(_pids); do [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = T ] && n=$((n+1)); done; [ "$n" -ge 1 ]; } ;;
  slack) abab_set_a()    { for p in $(_pids); do sudo -n sh -c "echo 50000 > /proc/$p/timerslack_ns" 2>/dev/null; done; }
         abab_set_b()    { for p in $(_pids); do sudo -n sh -c "echo 50000000 > /proc/$p/timerslack_ns" || return 1; done; }
         abab_verify_a() { for p in $(_pids); do [ "$(sudo -n cat /proc/$p/timerslack_ns)" = 50000 ] || return 1; done; }
         abab_verify_b() { for p in $(_pids); do [ "$(sudo -n cat /proc/$p/timerslack_ns)" = 50000000 ] || return 1; done; } ;;
  pin)   abab_set_a()    { for p in $(_pids); do taskset -a -c -p "$_all" "$p" >/dev/null 2>&1; done; }
         abab_set_b()    { for p in $(_pids); do taskset -a -c -p 0 "$p" >/dev/null 2>&1 || return 1; done; }
         abab_verify_a() { for p in $(_pids); do [ "$(taskset -c -p $p | awk '{print $NF}')" = "$_all" ] || return 1; done; }
         abab_verify_b() { for p in $(_pids); do [ "$(taskset -c -p $p | awk '{print $NF}')" = 0 ] || return 1; done; } ;;
  vt)    _vt() { cat /sys/class/tty/tty0/active; }
         VT0=$(_vt)
         abab_set_a()    { sudo -n chvt "${VT0#tty}"; }
         abab_set_b()    { sudo -n chvt 2; }
         abab_verify_a() { sleep 1; [ "$(_vt)" = "$VT0" ]; }
         abab_verify_b() { sleep 1; [ "$(_vt)" = tty2 ]; } ;;
  *) echo "알 수 없는 VARIANT=$VARIANT"; exit 2 ;;
esac
abab_restore() { abab_set_a; echo "복구(A) variant=$VARIANT"; }
[ -n "$(_pids)" ] || { echo "✗ $PROC 프로세스가 없음 — 먼저 띄우세요"; exit 4; }
AB_ARGS="--ignore-app vivaldi --no-netdata $AB_ARGS"
abab_run
