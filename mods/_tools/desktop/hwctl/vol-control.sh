case $1 in
  up) @wpctl@ set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
  down) @wpctl@ set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
  mute) @wpctl@ set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
  mic)
    @wpctl@ set-mute @DEFAULT_AUDIO_SOURCE@ toggle
    if @wpctl@ get-volume @DEFAULT_AUDIO_SOURCE@ | grep -q "MUTED"; then STATE="Muted"; else STATE="On"; fi
    @notify_send@ -h string:x-canonical-private-synchronous:microphone -u low "Microphone" "$STATE"
    exit 0 ;;
esac

VOL=$(@wpctl@ get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')
MUTE=$(@wpctl@ get-volume @DEFAULT_AUDIO_SINK@ | grep -q "MUTED" && echo " (Muted)" || echo "")
@notify_send@ -h string:x-canonical-private-synchronous:volume -h int:value:"$VOL" -u low "Volume" "$VOL%$MUTE"
