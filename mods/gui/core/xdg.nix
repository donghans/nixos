{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (mkMerge [
    # == NixOS: XDG Portal 경로 노출 ==
    # (목적: Wayland 포털 탐색에 필요한 시스템 PATH 등록)
    (optionalAttrs isNixOS {
      environment.pathsToLink = ["/share/applications" "/share/xdg-desktop-portal"];
    })

    # == Home Manager: XDG Portal 설정 ==
    (optionalAttrs (!isNixOS) {
      home.packages = with pkgs; [
        xdg-desktop-portal-gtk
        xdg-desktop-portal-hyprland
        xdg-utils
      ];

      xdg = {
        portal.enable = true;
        portal.extraPortals = with pkgs; [
          xdg-desktop-portal-hyprland
          xdg-desktop-portal-gtk
        ];
        portal.config.common.default = ["hyprland" "gtk"];
        mimeApps.enable = true;
      };
    })
  ]);
}
