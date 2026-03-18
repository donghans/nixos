{ pkgs, lib, ... }: {
  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkDefault [ ",preferred,auto,1" ];

    general = {
      gaps_in = 0;
      gaps_out = 0;
      border_size = 3;
      "col.active_border" = "rgba(33ccffee)";
      "col.inactive_border" = "rgba(595959aa)";
      resize_on_border = false;
      allow_tearing = false;
      layout = "dwindle";
    };

    dwindle = {
      pseudotile = true;
      preserve_split = true;
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
      always_follow_on_dnd = true;
      focus_on_activate = true;
    };
  };
}
