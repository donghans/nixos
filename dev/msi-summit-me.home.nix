{
  pkgs,
  lib,
  ...
}: {
  # == Home Configuration ==
  imports = [./base/developer.home.nix];

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
  };
}
