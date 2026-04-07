{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.networkmanager;
in
  if isNixOS
  then {
    config = mkIf cfg.enable {
      networking.networkmanager.enable = true;
      # (목적: networkmanager 그룹 멤버십 — CLI(nmcli) 및 GUI(nm-applet) 사용에 필요)
      users.users.${config.workspace.username}.extraGroups = ["networkmanager"];
    };
  }
  else {
    # HM 사이드: GUI 활성화 시 nm-applet 트레이 실행
    config = mkIf (cfg.enable && config.mods.gui.enable) {
      wayland.windowManager.hyprland.settings.exec-once = [
        "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"
      ];
    };
  }
