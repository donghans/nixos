{
  mkHostConfiguration,
  pkgs,
  lib,
  ...
}: let
  mkTailscaleProxy = import ./_lib/incus-tailscale-proxy.nix {inherit lib pkgs;};
in
  mkHostConfiguration (_: {
    os = {
      imports = [
        (mkTailscaleProxy "mac-studio" {
          vmName = "mac-studio-proxy";
          vmIp = "192.168.11.202";
          stateFile = "/var/lib/nix-secrets/tailscale/system/mac-studio-proxy.state";
          enableLanForward = false;
        })
        ./server2-beelink-ser7-co/incus-ubuntu-vm.nix
        ./server2-beelink-ser7-co/incus-cardgame-lxc.nix
        ./server2-beelink-ser7-co/incus-adx-lxc.nix
        ./server2-beelink-ser7-co/incus-class24-lxc.nix
        ./server2-beelink-ser7-co/incus-genple-lxc.nix
        ./server2-beelink-ser7-co/incus-genple-demo-lxc.nix
        ./server2-beelink-ser7-co/incus-shopify-dk-sync-lxc.nix
        ./server2-beelink-ser7-co/incus-lxc-backup.nix
      ];

      # tailscale 모듈 옵션 (문자열이라 toConfig 제약으로 toml 경유 불가 → nix에서 직접 설정)
      mods.sys.services.tailscale = {
        advertiseExitNode = true;
        advertiseRoutes = ["192.168.11.0/24"];
      };

      # mods 기본값은 "client" (rpfilter loose) → exit node 서버는 "server"로 덮어씀
      # "server": 커널 IP forwarding 활성화 (advertiseExitNode 동작에 필수)
      services.tailscale.useRoutingFeatures = "server";

      # exit node 포워딩: NixOS nftables forward chain 기본 policy가 drop이라
      # trustedInterfaces는 INPUT만 허용 → FORWARD는 명시적으로 추가 필요
      networking.firewall.extraForwardRules = ''
        iifname "tailscale0" accept
      '';

      # TODO: 공인 IP 또는 포트포워딩(TCP 443, UDP 3478) 확보 시 독립 DERP 서버 고려
      # headscale-vps 트래픽 분산 목적 — 현재는 Double-NAT 환경이라 적용 불가
      # 활성화 시 headscale-vps headscale.nix의 derp.paths에 이 서버 region YAML 추가 필요
      #
      # services.tailscale.derper = {
      #   enable = true;
      #   domain = "derp.YOURDOMAIN.com";  # 공인 도메인 필요
      #   configureNginx = true;            # nginx 역프록시 + Let's Encrypt 자동 설정
      #   openFirewall = true;
      #   stunPort = 3478;
      #   verifyClients = true;             # headscale 노드만 허용
      # };
    };
    hm = {};
  })
