{pkgs, ...}: {
  wayland.windowManager.hyprland.enable = true;

  wayland.windowManager.hyprland.systemd = {
    enable = true;
    variables = ["--all"];
  };

  wayland.windowManager.hyprland.settings = {
    "$mainMod" = "SUPER";

    ### INPUT ###
    input = {
      kb_layout = "kr";
      kb_options = "korean:ralt_hangul,korean:rctrl_hanja";

      follow_mouse = 1;
      sensitivity = 0;
      touchpad = {
        natural_scroll = true;
      };
    };

    # [OPTIONAL] 특정 하드웨어 전용 설정
    # device = [ { name = "epic-mouse-v1"; sensitivity = -0.5; } ];

    exec-once = [
      # == System Services ==
      "rfkill unblock bluetooth && bluetoothctl power on"

      # == UI & App Services (via UWSM) ==
      "uwsm app -- fcitx5"
      "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"
      "uwsm app -- ${pkgs.waybar}/bin/waybar"
      "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"
      "uwsm app -- ${pkgs.wl-clip-persist}/bin/wl-clip-persist --clipboard regular"
      "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
    ];
  };

  home.sessionVariables = {
    # == Environment Variables ==
    XCURSOR_SIZE = "24";
    HYPRCURSOR_SIZE = "24";
    XCURSOR_THEME = "Bibata-Modern-Ice";

    GTK_IM_MODULE = ""; # (주의: GTK4부터는 공백 권장)
    QT_IM_MODULE = "fcitx";
    XMODIFIERS = "@im=fcitx";
    SDL_IM_MODULE = "fcitx";
    INPUT_METHOD = "fcitx";

    GTK_THEME = "Adwaita-dark";
    QT_QPA_PLATFORM = "wayland;xcb";

    XDG_CURRENT_DESKTOP = "Hyprland";
    XDG_SESSION_TYPE = "wayland";
    XDG_SESSION_DESKTOP = "Hyprland";
    ELECTRON_OZONE_PLATFORM_HINT = "auto";
  };

  xdg = {
    portal.enable = true;
    portal.extraPortals = with pkgs; [
      xdg-desktop-portal-hyprland
      xdg-desktop-portal-gtk
    ];

    portal.config.common.default = ["hyprland" "gtk"];

    mimeApps.enable = true;
  };

  programs = {
    bash.enable = true;
    gh.enable = true;
  };

  services.cliphist.enable = true;

  services.my-notification-logger.enable = true;
}
