# Tailscale 전용 VNC 원격 데스크톱 (wayvnc).
#
# 인증 없이 0.0.0.0에 바인딩하지만, 실제 접근은 tailscale0 인터페이스로만 가능함
# (mods.sys.services.tailscale.nix가 networking.firewall.trustedInterfaces에
# tailscale0을 추가하고, 그 외 인터페이스는 기본 drop 정책으로 막혀 있음 →
# 포트를 networking.firewall.allowedTCPPorts에 올리지 않으므로 LAN/공인망에서는
# 애초에 도달 불가). enable_auth=true로 바꾸려면 certificate_file/private_key_file/
# username/password를 추가로 채워야 함(현재는 tailnet 신뢰 경계만으로 충분하다고 판단).
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "wayvnc (Tailscale 전용 VNC 원격 데스크톱)" ({
  cfg,
  pkgs,
  lib,
  ...
}: {
  options = {
    port = lib.mkOption {
      type = lib.types.port;
      default = 5900;
      description = "wayvnc가 바인딩할 TCP 포트";
    };
  };
  hm = let
    wayvncConfig = pkgs.writeText "wayvnc-config" ''
      address=0.0.0.0
      port=${toString cfg.port}
      enable_auth=false
    '';
  in {
    home.packages = [pkgs.wayvnc];

    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -t service -p Restart=on-failure -p RestartSec=2 -- ${pkgs.wayvnc}/bin/wayvnc -r --config=${wayvncConfig}"
    ];
  };
})
