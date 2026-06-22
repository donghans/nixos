{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    imports = [
      ./rpi-4b-me/e-772551232-xyz.nix
      ./rpi-4b-me/vaultwarden.nix
    ];

    users.users.root.openssh.authorizedKeys.keyFiles = [
      ./_deploy/rpi-4b-me.pub
    ];

    # 1. Caddy 역프록시 설정 (헤드스케일 도메인 자동 HTTPS 종단)
    services.caddy = {
      enable = true;
      virtualHosts."e.772551232.xyz".extraConfig = ''
        reverse_proxy 127.0.0.1:8080
      '';
    };

    # 2. 방화벽 추가 허용 (HTTP: 80, HTTPS: 443, STUN: 3478, Tailscale: 41641)
    networking.firewall = {
      allowedTCPPorts = [80 443];
      allowedUDPPorts = [3478 41641];
    };

    # 3. Tailscale Exit Node 설정
    mods.sys.services.tailscale = {
      advertiseExitNode = true;
      # RPi가 물려있는 로컬 대역(192.168.0.0/24)을 광고하고 싶다면 아래 주석을 해제하세요.
      # advertiseRoutes = ["192.168.0.0/24"];
    };

    # exit node 동작을 위해 커널 IP forwarding 활성화
    services.tailscale.useRoutingFeatures = "server";

    # nftables에서 tailscale0 가상 인터페이스 포워딩 트래픽 허용
    networking.firewall.extraForwardRules = ''
      iifname "tailscale0" accept
    '';
  };
  hm = {};
})
