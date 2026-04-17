{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.incus;
in {
  options.mods.sys.services.incus.enable = mkEnableOption "Incus hypervisor";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      virtualisation.incus.enable = true;
      virtualisation.incus.ui.enable = true;
      networking.firewall.allowedTCPPorts = [8443];
      # nixos-fw의 기본 정책이 drop이라 VM→호스트 트래픽(DHCP 등)도 차단됨
      networking.firewall.trustedInterfaces = ["incusbr0"];
      networking.nftables.enable = true;
      # VM이 IPv6 RA를 브리지로 보낼 때 호스트 IPv6 라우팅이 바뀌는 것을 방지
      # (RA를 수락하면 Tailscale 등 호스트 IPv6 연결이 끊김)
      boot.kernel.sysctl."net.ipv6.conf.incusbr0.accept_ra" = 0;
      users.users.${config.workspace.username}.extraGroups = ["incus-admin"];

      virtualisation.incus.preseed = {
        config = {
          "core.https_address" = ":8443";
        };
        networks = [
          {
            name = "incusbr0";
            type = "bridge";
            config = {
              # auto로 두면 incus 재시작마다 IP가 바뀌어 VM 네트워크가 끊김
              "ipv4.address" = "10.100.0.1/24";
              # IPv6 NAT가 제대로 동작하지 않아 VM에서 IPv6 인터넷 불가
              # → Firefox 등이 IPv6를 우선 시도하다 실패하므로 비활성화
              "ipv6.address" = "none";
              "ipv4.nat" = "true";
              # Windows는 DHCP Discover에 broadcast 플래그를 세우지 않아
              # dnsmasq가 unicast 응답을 시도하다 실패함 → 항상 broadcast로 응답
              # server=: resolv.conf의 Tailscale DNS 대신 공용 DNS로 포워딩
              # filter-AAAA: AAAA 레코드 차단 → Firefox의 IPv6 우선 시도 방지
              "raw.dnsmasq" = "dhcp-broadcast\nserver=1.1.1.1\nserver=8.8.8.8\nfilter-AAAA";
            };
          }
        ];
        storage_pools = [
          {
            name = "default";
            driver = "btrfs";
            config = {
              source = "/var/lib/incus/storage-pools/default";
            };
          }
        ];
        profiles = [
          {
            name = "default";
            devices = {
              eth0 = {
                name = "eth0";
                network = "incusbr0";
                type = "nic";
              };
              root = {
                path = "/";
                pool = "default";
                type = "disk";
              };
            };
          }
        ];
      };
    }
    else {}
  );
}
