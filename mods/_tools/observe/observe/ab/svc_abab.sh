#!/bin/sh
# 시스템 서비스 묶음 켬(A) / 정지(B) 번갈아 — 한가할 때 상시 서비스가 먹는 전력. 정지·시작만 하고 설정·데이터는 건드리지 않는다.
# 사용: UNITS="cups.socket cups.service incus.socket incus.service bluetooth.service dnsmasq.service" SEG=240 PAIRS=3 svc_abab.sh   (덮개 닫고 배터리, 손대지 않기)
#   UNITS 는 정지 순서대로(소켓을 먼저 — 소켓이 살아 있으면 접속이 오면 서비스가 다시 뜬다). 시작도 같은 순서.
#   끝나면(신호·실패 포함) 시작 때 켜져 있던 유닛만 다시 켠다. root 명령은 sudo -n systemctl.
#   USER_STOP="유닛 …" 은 사용자(systemctl --user) 유닛을 시험 내내 멈춰 두고 끝나면 켜져 있던 것만 되살린다(A·B 양쪽에 같은 조건 — 예: bluetooth 를 D-Bus 로 되살리는 app-blueman@autostart.service).
# 정지 직후 다른 프로세스(예: blueman 이 D-Bus 로)가 다시 켜 버리면 verify 가 실패해 중단한다 — 그 서비스는 목록에서 빼거나 따로 다룬다.
. "$(dirname "$0")/abab_lib.sh"
UNITS=${UNITS:?UNITS=\"유닛 유닛 …\" (정지 순서대로)}
SC=${SC:-sudo -n systemctl}
_svc_active() { systemctl is-active --quiet "$1"; }
WAS_ACTIVE=""; for _u in $UNITS; do _svc_active "$_u" && WAS_ACTIVE="$WAS_ACTIVE $_u"; done
[ -n "$WAS_ACTIVE" ] || { echo "✗ UNITS 중 켜져 있는 유닛이 없음"; exit 3; }
USER_STOP=${USER_STOP:-}; USER_WAS=""
for _x in $USER_STOP; do systemctl --user is-active --quiet "$_x" && USER_WAS="$USER_WAS $_x"; done
for _x in $USER_WAS; do systemctl --user stop "$_x" || { echo "✗ 사용자 유닛 정지 실패: $_x"; exit 3; }; done
[ -z "$USER_WAS" ] || echo "사용자 유닛 정지(시험 내내): $USER_WAS"
abab_set_a()    { for _u in $WAS_ACTIVE; do _svc_active "$_u" || $SC start "$_u" || return 1; done; }
abab_set_b()    { for _u in $WAS_ACTIVE; do ! _svc_active "$_u" || $SC stop "$_u" || return 1; done; }
abab_verify_a() { for _u in $WAS_ACTIVE; do _svc_active "$_u" || return 1; done; }
abab_verify_b() { for _u in $WAS_ACTIVE; do ! _svc_active "$_u" || { echo "  (정지 후에도 켜져 있음: $_u)"; return 1; }; done; }
abab_restore()  { for _x in $USER_WAS; do systemctl --user start "$_x" >/dev/null 2>&1; done; [ -z "$USER_WAS" ] || echo "사용자 유닛 복구: $(for _x in $USER_WAS; do printf '%s=%s ' "$_x" "$(systemctl --user is-active "$_x")"; done)"; for _u in $WAS_ACTIVE; do _svc_active "$_u" || $SC start "$_u" >/dev/null 2>&1; done; echo "서비스 복구: 켜짐=$(for _u in $WAS_ACTIVE; do _svc_active "$_u" && printf '%s ' "$_u"; done) · 꺼짐=$(for _u in $WAS_ACTIVE; do _svc_active "$_u" || printf '%s ' "$_u"; done)"; }
AB_ARGS="--ignore-app incusd --ignore-app cupsd --ignore-app bluetoothd --ignore-app tailscaled $AB_ARGS"
abab_run
