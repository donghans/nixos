{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.networkmanager;
in {
  options.mods.sys.services.networkmanager.enable = mkEnableOption "NetworkManager (nmcli + nm-applet)";
  config = mkIf cfg.enable (
    if isNixOS
    then {
      networking.networkmanager.enable = true;
      # (목적: networkmanager 그룹 멤버십 — CLI(nmcli) 및 GUI(nm-applet) 사용에 필요)
      users.users.${config.workspace.username}.extraGroups = ["networkmanager"];
    }
    else
      mkIf config.mods.gui.enable {
        # HM 사이드: GUI 활성화 시 nm-applet 트레이 실행
        wayland.windowManager.hyprland.settings.exec-once = [
          "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"
        ];
      }
  );
}
