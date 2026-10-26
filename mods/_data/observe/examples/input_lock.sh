#!/bin/sh
# input_lock.sh — 시험 중 오입력 방지: 터치패드·마우스·내장 키보드를 Hyprland 에서 끈다(덮개·전원·밝기 키·터치스크린은 그대로).
# 사용: input_lock.sh on [보험분=90] | off.  abab_lib 에서는 ABAB_LOCK_CMD=$PWD/input_lock.sh 로 쓴다.
#   on  : 자동 복구 타이머(ds-inputguard)를 함께 건다 — 틀이 죽어도 보험분 뒤에 풀린다.
#   off : hypr-input-policy 가 있으면 그것으로 사용자 정책(터치패드·터치스크린 마지막 설정, 힌지 모드)을 복원, 없으면 장치를 모두 켠다.
# 대상: INPUT_LOCK_DEVICES(공백 구분)가 있으면 그것, 없으면 `hyprctl devices -j` 의 마우스·터치패드와 이름에 keyboard 가 든 키보드(가상·단축키 장치 제외).
# Hyprland 0.55 는 `hyprctl keyword device[..]` 가 안 되고 eval(Lua)만 된다(장부 #128).
export PATH=/run/wrappers/bin:$PATH
export HYPRLAND_INSTANCE_SIGNATURE=${HYPRLAND_INSTANCE_SIGNATURE:-$(ls /run/user/"$(id -u)"/hypr 2>/dev/null | head -1)}
devs() {
    [ -n "$INPUT_LOCK_DEVICES" ] && { echo "$INPUT_LOCK_DEVICES" | tr ' ' '\\n'; return; }
    hyprctl devices -j | python3 -c "
import json,sys
d=json.load(sys.stdin)
for m in d.get('mice',[]): print(m['name'])
for k in d.get('keyboards',[]):
    n=k['name']
    if 'keyboard' in n and not n.startswith(('hl-virtual','wvkbd')) and 'virtual' not in n: print(n)"
}
set_all() { bad=0; for d in $(devs); do [ "$(hyprctl eval "hl.device({ name = \\"$d\\", enabled = $1 })" 2>&1)" = ok ] || bad=$((bad+1)); done; echo "입력 장치 $1 (실패 $bad개)"; [ "$bad" = 0 ]; }
case "$1" in
    on)  systemctl --user stop ds-inputguard.timer ds-inputguard.service 2>/dev/null
         systemd-run --user --unit=ds-inputguard --collect --quiet --on-active="${2:-90}m" "$0" off
         set_all false ;;
    off) systemctl --user stop ds-inputguard.timer 2>/dev/null
         if command -v hypr-input-policy >/dev/null 2>&1; then hypr-input-policy; echo "입력 정책 재적용 rc=$?"; else set_all true; fi ;;
    *)   echo "사용: $0 on [보험분] | off" >&2; exit 2 ;;
esac
