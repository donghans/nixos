{ pkgs, unstable, lib, metaConfig, ... }: let
  # 터치패드 토글 스크립트 (모든 터치패드 장치 순회 처리)
  toggleTouchpad = pkgs.writeShellScriptBin "hypr-toggle-touchpad" ''
    # 터치패드 키워드가 포함된 모든 장치 추출
    DEVICES=$(hyprctl devices -j | ${pkgs.jq}/bin/jq -r '.mice[] | select(.name | contains("touchpad")) | .name')

    if [ -z "$DEVICES" ]; then
      ${pkgs.libnotify}/bin/notify-send "Touchpad" "No touchpad device found!"
      exit 1
    fi

    STATUS_FILE="/tmp/touchpad_enabled"
    [ ! -f "$STATUS_FILE" ] && echo "true" > "$STATUS_FILE"
    CURRENT_STATUS=$(cat "$STATUS_FILE")

    if [ "$CURRENT_STATUS" = "true" ]; then
      echo "$DEVICES" | while read -r dev; do
        hyprctl keyword "device[$dev]:enabled" false
      done
      echo "false" > "$STATUS_FILE"
      ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:touchpad -u low "Touchpad" "Disabled"
    else
      echo "$DEVICES" | while read -r dev; do
        hyprctl keyword "device[$dev]:enabled" true
      done
      echo "true" > "$STATUS_FILE"
      ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:touchpad -u low "Touchpad" "Enabled"
    fi
  '';

  # 볼륨 조절 및 알림 스크립트
  volControl = pkgs.writeShellScriptBin "vol-control" ''
    case $1 in
      up) wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
      down) wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
      mute) wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
    esac

    VOL=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')
    MUTE=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | grep -q "MUTED" && echo " (Muted)" || echo "")
    ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:volume -h int:value:"$VOL" -u low "Volume" "$VOL%$MUTE"
  '';

  # 밝기 조절 및 알림 스크립트
  brtControl = pkgs.writeShellScriptBin "brt-control" ''
    case $1 in
      up) brightnessctl set 5%+ ;;
      down) brightnessctl set 5%- ;;
    esac

    BRT=$(brightnessctl -m | cut -d, -f4 | tr -d '%')
    ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
  '';
in {
  imports = [ ./base/developer.home.nix ];

  home.packages = with pkgs; [
    brightnessctl
    libnotify
    pamixer
  ];

  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkForce [
      "eDP-1,2560x1600@60,auto,1"
      "DP-2,preferred,auto-up,1"
    ];

    input.touchpad = {
      natural_scroll = true;
      tap-to-click = true;
      disable_while_typing = true;
    };

    bindel = [
      # 볼륨 및 밝기 조절 (피드백 포함)
      ",XF86AudioRaiseVolume, exec, ${volControl}/bin/vol-control up"
      ",XF86AudioLowerVolume, exec, ${volControl}/bin/vol-control down"
      ",XF86AudioMute, exec, ${volControl}/bin/vol-control mute"
      ",XF86MonBrightnessUp, exec, ${brtControl}/bin/brt-control up"
      ",XF86MonBrightnessDown, exec, ${brtControl}/bin/brt-control down"
    ];

    bindl = [
      # 터치패드 토글 (순수 Fn 조합키 인식 강화)
      ",XF86TouchpadToggle, exec, ${toggleTouchpad}/bin/hypr-toggle-touchpad"

      # 덮개 스위치
      ", switch:on:Lid Switch, exec, loginctl lock-session && hyprctl dispatch dpms off && tlp bat"
      ", switch:off:Lid Switch, exec, hyprctl dispatch dpms on && tlp start"
    ];
  };
}
