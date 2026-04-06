# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.home/_bind.hwctl.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{
  pkgs,
  lib,
  config,
  metaConfig,
  ...
}: let
  # == Hardware Control Scripts ==
  # 볼륨 조절 및 알림 스크립트
  volumeControl = pkgs.writeShellScriptBin "vol-control" ''
    case $1 in
      up) ${pkgs.wireplumber}/bin/wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
      down) ${pkgs.wireplumber}/bin/wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
      mute) ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
    esac

    VOL=$(${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')
    MUTE=$(${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@ | grep -q "MUTED" && echo " (Muted)" || echo "")
    ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:volume -h int:value:"$VOL" -u low "Volume" "$VOL%$MUTE"
  '';

  # 밝기 조절 및 알림 스크립트
  brightnessControl = pkgs.writeShellScriptBin "brt-control" ''
    case $1 in
      up) ${pkgs.brightnessctl}/bin/brightnessctl set 5%+ ;;
      down) ${pkgs.brightnessctl}/bin/brightnessctl set 5%- ;;
    esac

    BRT=$(${pkgs.brightnessctl}/bin/brightnessctl -m | cut -d, -f4 | tr -d '%')
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
  options.wayland.windowManager.hyprland = {
    touchpadToggleKey = lib.mkOption {
      type = lib.types.str;
      default = ", XF86TouchpadToggle";
      description = "Touchpad toggle key binding for Hyprland.";
    };
    lidSwitchOnExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is closed (switch:on).";
    };
    lidSwitchOffExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is opened (switch:off).";
    };
  };

  config = {
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
        # 터치패드 토글 (설정된 키 사용)
        "${config.wayland.windowManager.hyprland.touchpadToggleKey}, exec, ${toggleTouchpad}/bin/hypr-toggle-touchpad"

        # 덮개 스위치 (로그인 잠금 및 전원 관리)
        ", switch:on:Lid Switch, exec, loginctl lock-session && hyprctl dispatch dpms off${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd != "") " && ${config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd}"}"
        ", switch:off:Lid Switch, exec, hyprctl dispatch dpms on${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd != "") " && ${config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd}"}"
      ];
    };
  };
}
