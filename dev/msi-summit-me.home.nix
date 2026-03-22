{ pkgs, unstable, lib, metaConfig, ... }: {
  imports = [ ./base/developer.home.nix ];

  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkForce [
      "eDP-1,2560x1600@60,auto,1" # 2560x1600@165, 60?
      "DP-2,preferred,auto-up,1"
    ];

    input.touchpad = {
      # 기타 유용한 설정들
      natural_scroll = true;
      tap-to-click = true;
      disable_while_typing = true;
    };

    bindl = [
      # 덮개를 닫을 때 (Lid Switch On)
      ", switch:on:Lid Switch, exec, loginctl lock-session && hyprctl dispatch dpms off && tlp bat"

      # 덮개를 열 때 (Lid Switch Off)
      ", switch:off:Lid Switch, exec, hyprctl dispatch dpms on && tlp start"
    ];
  };
}
