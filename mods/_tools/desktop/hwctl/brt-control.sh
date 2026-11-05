# 배터리 절전으로 밝기를 낮춘 상태(displayctl brightness)면 먼저 원래 밝기로 깨운다.
# 안 그러면 낮춘 밝기 기준으로 조절된 뒤 hypridle 의 복귀(wake)가 원래 밝기로 덮어써서 사용자의 변경이 사라진다.
# 낮춘 상태일 때만 displayctl(파이썬)을 부른다 — 평소 키 입력에 지연을 주지 않으려고 런타임 상태 파일을 쉘에서 먼저 본다.
if grep -qs '"dimmed": [0-9]' "${XDG_RUNTIME_DIR:-/tmp}/displayctl-brightness.json"; then
  command -v displayctl >/dev/null && displayctl brightness wake
fi
case $1 in
  up) @brightnessctl@ set 5%+ ;;
  down) @brightnessctl@ set 5%- ;;
esac

BRT=$(@brightnessctl@ -m | cut -d, -f4 | tr -d '%')
@notify_send@ -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
