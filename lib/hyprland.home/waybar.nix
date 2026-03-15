{ pkgs, metaConfig, ... }: {
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

    modules-left = [ "hyprland/workspaces" "hyprland/submap" ];
    modules-center = [ "hyprland/window" ];
    modules-right = [ "tray" ]
    ++ (if metaConfig.isLaptop then [ "battery" ] else [ ])
    ++ [ "clock" ];

    "hyprland/workspaces" = {
      format = "{name}";
      on-click = "activate";
      all-outputs = false;
      sort-by-number = true;
      format-icons = {
        active = "";
        default = "";
      };
    };

    "hyprland/window" = {
      format = "{}";
      separate-outputs = true;
    };

    "tray" = {
      icon-size = 16;
      spacing = 12;
    };

    "clock" = {
      format = "{:%Y-%m-%d %H:%M}";
      tooltip-format = "{:%A, %B %d, %Y}";
    };
  };

  # waybar/style.css 내용
  # programs.waybar.style = ''
  #   * {
  #     font-family: FontAwesome, Roboto, Helvetica, Arial, sans-serif;
  #     font-size: 13px;
  #   }
  #   #waybar {
  #     background-color: rgba(43, 48, 59, 0.5);
  #     color: #ffffff;
  #   }
  # '';
}
