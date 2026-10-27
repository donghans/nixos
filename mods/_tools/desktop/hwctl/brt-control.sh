case $1 in
  up) @brightnessctl@ set 5%+ ;;
  down) @brightnessctl@ set 5%- ;;
esac

BRT=$(@brightnessctl@ -m | cut -d, -f4 | tr -d '%')
@notify_send@ -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
