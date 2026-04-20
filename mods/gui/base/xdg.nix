{mkPartOf, ...}:
mkPartOf "mods.gui" ({pkgs, ...}: {
  os = {
    # (목적: Wayland 포털 탐색에 필요한 시스템 PATH 등록)
    environment.pathsToLink = ["/share/applications" "/share/xdg-desktop-portal"];
  };
  hm = {
    home.sessionVariables = {
      XDG_CURRENT_DESKTOP = "Hyprland";
      XDG_SESSION_TYPE = "wayland";
      XDG_SESSION_DESKTOP = "Hyprland";
    };

    home.packages = [pkgs.xdg-utils];

    xdg = {
      portal.enable = true;
      portal.extraPortals = with pkgs; [
        xdg-desktop-portal-gtk
      ];
      portal.config.common.default = ["hyprland" "gtk"];
      mimeApps.enable = true;
    };
  };
})
