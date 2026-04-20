{mkMod, ...}:
mkMod __curPos "NetworkManager (nmcli + nm-applet)" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  os = {
    networking.networkmanager.enable = true;
    # (목적: networkmanager 그룹 멤버십 — CLI(nmcli) 및 GUI(nm-applet) 사용에 필요)
    users.users.${config.workspace.username}.extraGroups = ["networkmanager"];
  };
  hm = lib.mkIf config.mods.gui.enable {
    # HM 사이드: GUI 활성화 시 nm-applet 트레이 실행
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"
    ];
  };
})
