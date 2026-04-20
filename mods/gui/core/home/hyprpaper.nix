{mkMod, ...}:
mkMod __curPos null ({
  pkgs,
  lib,
  ...
}: {
  hm = {
    # == 배경화면 데몬 ==
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"
    ];
  };
})
