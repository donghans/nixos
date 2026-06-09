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
    };
    hm = {};
  })
