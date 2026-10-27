#!/bin/sh
# 창이 보이는 작업공간(A) / 숨은 작업공간(B)에 있을 때의 전력 — 덮개를 닫으면 화면이 안 보이니 창을 숨겨 그리기·프레임 요청을 멈추면 이득인지(Vivaldi 한가한 비용 +0.4 W 가설).
# 사용: ws_hide_abab.sh  (덮개 닫고, 창이 떠 있는 상태에서)   환경: WIN_CLASS=vivaldi-stable(기본), HIDE_WS=special:ab(기본)
. "$(dirname "$0")/abab_lib.sh"
WIN_CLASS=${WIN_CLASS:-vivaldi-stable}; HIDE_WS=${HIDE_WS:-special:ab}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ] || HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr" 2>/dev/null | grep -v lock | head -1); export HYPRLAND_INSTANCE_SIGNATURE
_ws() { hyprctl clients -j | python3 -c "
import json,sys
cs=[c for c in json.load(sys.stdin) if c.get('class')=='$WIN_CLASS']
print(','.join(sorted({c['workspace']['name'] for c in cs})) if cs else 'none')"; }
WS0=$(_ws)
[ "$WS0" != none ] && case "$WS0" in *,*) echo "✗ 창이 여러 작업공간에 흩어져 있음($WS0)"; exit 4 ;; esac
[ "$WS0" != none ] || { echo "✗ $WIN_CLASS 창이 없음 — 먼저 띄워 두세요"; exit 4; }
[ "$WS0" = "$HIDE_WS" ] && { echo "✗ 이미 숨은 작업공간에 있음"; exit 4; }
_mv() { hyprctl dispatch "hl.dsp.window.move({ workspace = \"$1\", follow = false, window = \"class:^$WIN_CLASS\$\" })" >/dev/null; }
abab_set_a()    { _mv "$WS0"; }
abab_set_b()    { _mv "$HIDE_WS"; }
abab_verify_a() { [ "$(_ws)" = "$WS0" ]; }
abab_verify_b() { [ "$(_ws)" = "$HIDE_WS" ]; }
abab_restore()  { abab_set_a; echo "창 작업공간=$(_ws) (원래 $WS0)"; }
AB_ARGS="--ignore-app $WIN_CLASS --ignore-app vivaldi $AB_ARGS"
abab_run
