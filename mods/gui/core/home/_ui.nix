_: {
  # == Hyprland Compositor 설정 ==
  wayland.windowManager.hyprland.settings = {
    general = {
      gaps_in = 0;
      gaps_out = 0;
      border_size = 3;
      "col.active_border" = "rgba(33ccffee)";
      "col.inactive_border" = "rgba(595959aa)";
    };

    decoration = {
      rounding = 0;
      active_opacity = 1.0;
      inactive_opacity = 0.75;
      shadow.enabled = false;
      blur.enabled = false;
    };

    animations.enabled = "no";

    misc = {
      force_default_wallpaper = -1;
      disable_hyprland_logo = false;
    };
  };
}
