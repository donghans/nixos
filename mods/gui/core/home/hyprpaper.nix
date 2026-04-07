{pkgs, ...}: {
  # == 배경화면 데몬 ==
  wayland.windowManager.hyprland.settings.exec-once = [
    "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"
  ];
}
