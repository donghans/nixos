{
  pkgs,
  lib,
  metaConfig,
  ...
}: let
  # == Hardware Control Scripts ==
  # 볼륨 조절 및 알림 스크립트
  volumeControl = pkgs.writeShellScriptBin "vol-control" ''
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
  brightnessControl = pkgs.writeShellScriptBin "brt-control" ''
    case $1 in
      up) brightnessctl set 5%+ ;;
      down) brightnessctl set 5%- ;;
    esac

    BRT=$(brightnessctl -m | cut -d, -f4 | tr -d '%')
    ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
  '';

  # 터치패드 토글 스크립트 (Laptop 전용)
  toggleTouchpad = pkgs.writeShellScriptBin "hypr-toggle-touchpad" ''
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
in {
  home.packages = with pkgs;
    [
      libnotify
      pamixer
    ]
    ++ lib.optionals metaConfig.isLaptop [
      brightnessctl
    ];

  wayland.windowManager.hyprland.settings = {
    # == Generic Media Bindings ==
    bindel =
      [
        ", XF86AudioRaiseVolume, exec, ${volumeControl}/bin/vol-control up"
        ", XF86AudioLowerVolume, exec, ${volumeControl}/bin/vol-control down"
        ", XF86AudioMute, exec, ${volumeControl}/bin/vol-control mute"
      ]
      ++ lib.optionals metaConfig.isLaptop [
        ", XF86MonBrightnessUp, exec, ${brightnessControl}/bin/brt-control up"
        ", XF86MonBrightnessDown, exec, ${brightnessControl}/bin/brt-control down"
      ];

    # == Laptop Specific Bindings ==
    bindl = lib.mkIf metaConfig.isLaptop [
      # 터치패드 토글
      "$mainMod CTRL, XF86TouchpadToggle, exec, ${toggleTouchpad}/bin/hypr-toggle-touchpad"

      # 덮개 스위치 (로그인 잠금 및 전원 관리)
      ", switch:on:Lid Switch, exec, loginctl lock-session && hyprctl dispatch dpms off && tlp bat"
      ", switch:off:Lid Switch, exec, hyprctl dispatch dpms on && tlp start"
    ];
  };
}
