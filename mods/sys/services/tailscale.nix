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
      # nixos-fw의 기본 정책이 drop이라 tailscale0 인터페이스에서 오는
      # 트래픽도 차단됨 → 노드 간 접근이 안 되므로 trusted로 지정
      networking.firewall.trustedInterfaces = ["tailscale0"];
    }
    else
      mkIf config.mods.gui.enable {
        # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
        wayland.windowManager.hyprland.settings.exec-once = mkOrder 500 [
          "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
        ];
      }
  );
}
