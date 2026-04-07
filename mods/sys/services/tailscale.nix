{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.tailscale;
in
  if isNixOS
  then {
    config = mkIf cfg.enable {
      services.tailscale.enable = true;
    };
  }
  else {
    # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
    config = mkIf (cfg.enable && config.mods.gui.enable) {
      wayland.windowManager.hyprland.settings.exec-once = [
        "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
      ];
    };
  }
