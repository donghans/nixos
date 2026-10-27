f="${XDG_RUNTIME_DIR:-/tmp}/lid_brightness"
b=@brightnessctl@
case $1 in
  off)
    cur=$($b get)
    if [ "$cur" -gt 0 ] 2>/dev/null; then echo "$cur" > "$f"; fi
    $b -q set 0
    ;;
  on)
    if [ -s "$f" ]; then $b -q set "$(cat "$f")" && rm -f "$f"; fi
    ;;
esac
