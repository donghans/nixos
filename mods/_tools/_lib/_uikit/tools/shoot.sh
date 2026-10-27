#!/usr/bin/env bash
# 헤드리스 cage 안의 kitty 에서 TUI 를 띄워 grim 으로 촬영한다(화면은 사용자 데스크톱과 분리)
S=$1; APP=$2; NAME=$3; shift 3
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
before=$(ls $XDG_RUNTIME_DIR | grep '^wayland-[0-9]*$' | sort)
SOCK=$S/k-$NAME.sock; rm -f $SOCK
cage -- kitty -o allow_remote_control=yes --listen-on unix:$SOCK -o font_size=11 -e bash -c "$APP" >/dev/null 2>&1 &
CP=$!
sleep 4
after=$(ls $XDG_RUNTIME_DIR | grep '^wayland-[0-9]*$' | sort)
W=$(comm -13 <(echo "$before") <(echo "$after") | head -1)
i=0
for step in "$@"; do
  i=$((i+1))
  if [ "$step" = "-" ]; then sleep 4; else kitten @ --to unix:$SOCK send-text -- "$step" >/dev/null 2>&1; sleep 2.5; fi
  WAYLAND_DISPLAY=$W grim $S/shots/$NAME-$i.png
done
kill $CP 2>/dev/null; sleep 1; pkill -f "listen-on unix:$SOCK" 2>/dev/null
echo "$NAME done ($W)"
