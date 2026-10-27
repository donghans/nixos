#!/bin/sh
# Vivaldi 가 켜진 채로 "깨움을 줄이는 방법"의 효과를 번갈아 잰다. VARIANT: stop(SIGSTOP — 얻을 수 있는 최대치) · slack(타이머 슬랙 50ms — 깨움 묶기) · pin(CPU 1개에 고정) · vt(활성 VT 를 tty2 로)
# A = 기본, B = 변형. 끝나면(신호·실패 포함) 반드시 A 로 복구한다(SIGSTOP 을 남기지 않는다). 사용: VARIANT=slack proc_abab.sh   (덮개 닫고, Vivaldi 가 떠 있는 상태)
. "$(dirname "$0")/abab_lib.sh"
VARIANT=${VARIANT:?VARIANT=stop|slack|pin|vt}; PROC=${PROC:-vivaldi-bin}
_pids() { pgrep -u "$(id -u)" -x "$PROC"; }      # comm 이 정확히 일치하는 내 프로세스(느린 /proc 순회 대신)
_ncpu=$(nproc); _all="0-$((_ncpu - 1))"
case "$VARIANT" in
  stop)  abab_set_a()    { for p in $(_pids); do kill -CONT "$p" 2>/dev/null; done; }
         abab_set_b()    { for p in $(_pids); do kill -STOP "$p" 2>/dev/null; done; }
         abab_verify_a() { for p in $(_pids); do case "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" in T|t) return 1 ;; esac; done; return 0; }
         abab_verify_b() { n=0; for p in $(_pids); do [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = T ] && n=$((n+1)); done; [ "$n" -ge 1 ]; } ;;
  slack) # timerslack_ns 는 스레드마다 따로다(/proc/<pid>/ 는 리더 스레드만) — 모든 tid 에 쓴다. 읽기·쓰기는 root 필요라 sudo 한 번에 묶는다. 0 을 쓰면 기본값으로 복귀.
         _tids() { for p in $(_pids); do ls /proc/$p/task 2>/dev/null; done; }
         _slack_set() { v=$1; sudo -n sh -c 'v=$1; shift; for t in "$@"; do echo $v > /proc/$t/timerslack_ns 2>/dev/null; done; exit 0' _ "$v" $(_tids); }
         _slack_frac() { v=$1; sudo -n sh -c 'for t in "$@"; do cat /proc/$t/timerslack_ns 2>/dev/null; done' _ $(_tids) | awk -v v="$v" '{n++; if ($1==v) k++} END{ if (n) printf "%d", 100*k/n; else print 0 }'; }
         abab_set_a()    { _slack_set 0; }
         abab_set_b()    { _slack_set 50000000; }
         abab_verify_a() { [ "$(_slack_frac 50000000)" -le 5 ]; }
         abab_verify_b() { [ "$(_slack_frac 50000000)" -ge 80 ]; } ;;
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
