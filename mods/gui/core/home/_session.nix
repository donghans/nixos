# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.home/_session.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{pkgs, ...}: {
  wayland.windowManager.hyprland.settings = {
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
}
