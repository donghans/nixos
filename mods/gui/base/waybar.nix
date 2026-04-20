{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  config,
  lib,
  ...
}: {
  hm = {
    # waybar 세션 시작
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "uwsm app -- ${pkgs.waybar}/bin/waybar"
    ];

    programs.waybar.enable = true;

    # waybar/config 내용
    programs.waybar.settings.mainBar = {
      layer = "top";
      position = "top";
      height = 24;

      margin-top = 0;
      margin-bottom = 0;
      margin-left = 0;
      margin-right = 0;

      modules-left = ["hyprland/workspaces" "hyprland/submap"];
      modules-center = ["hyprland/window"];
      modules-right =
        ["tray"]
        ++ (
          if config.workspace.type == "laptop"
          then ["battery"]
          else []
        )
        ++ ["clock"];

      "hyprland/workspaces" = {
        format = "{name}";
        on-click = "activate";
        all-outputs = false;
        sort-by-number = true;
      };

      "hyprland/window" = {
        format = "{}";
        separate-outputs = true;
      };

      "battery" = {
        format = "{} %";
        states = {
          warning = 30;
          critical = 15;
        };
      };

      "tray" = {
        icon-size = 18;
        spacing = 4;
      };

      "clock" = {
        format = "{:%Y-%m-%d %H:%M}";
        tooltip-format = "{:%A, %B %d, %Y}";
      };
    };

    programs.waybar.style = builtins.readFile ../../_data/waybar/style.css;
  };
})
