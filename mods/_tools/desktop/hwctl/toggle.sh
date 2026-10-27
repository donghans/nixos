if [ "$(@posture@ get mode)" != laptop ]; then
  @notify_send@ -u low "@label@" "@locked_msg@"
  exit 0
fi
cur=$(@input_policy@ --print | cut -d' ' -f@field@)
if [ "$cur" = true ]; then new=false; shown=Disabled; else new=true; shown=Enabled; fi
mkdir -p "$HOME/.local/state/hypr"
echo "$new" > "$HOME/.local/state/hypr/@file@"
@input_policy@
@notify_send@ -h string:x-canonical-private-synchronous:@bin@ -u low "@label@" "$shown"
