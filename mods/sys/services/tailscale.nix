{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.tailscale;
in {
  options.mods.sys.services.tailscale.enable = mkEnableOption "Tailscale Mesh VPN";
  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.tailscale.enable = true;
    }
    else
      mkIf config.mods.gui.enable {
        # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
        wayland.windowManager.hyprland.settings.exec-once = [
          "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
        ];
      }
  );
}
