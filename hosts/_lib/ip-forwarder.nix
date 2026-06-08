{lib}: {
  interface,
  gateway,
  subnetPrefix ? 24,
  routingTable ? 101,
  # true: 해당 인터페이스에 DHCP 설정 추가 (secondary NIC 전용)
  # false: IP alias 방식 (Vultr 등 단일 NIC + secondary IP, 기본값)
  dhcp ? false,
  # [ { publicIp, targetTs, staticAssign ? true } ]
  #   publicIp:     포워딩받을 공인 IP
  #   targetTs:     tailscale 목적지 IP
  #   staticAssign: true  → address 섹션에 정적 추가 (기본값)
  #                 false → DHCP가 이미 할당한 IP (ENI primary IP 케이스)
  forwards,
}: let
  tagged =
    lib.imap1 (i: f: {
      inherit (f) publicIp;
      inherit (f) targetTs;
      staticAssign = f.staticAssign or true;
      priority = 99 + i; # 100, 101, 102 … — table은 공유
    })
    forwards;
in {
  boot.kernel.sysctl."net.ipv4.ip_forward" = 1;

  systemd.network.networks."20-ip-forwarder-${interface}" =
    {
      matchConfig.Name = interface;

      address =
        map (f: "${f.publicIp}/${toString subnetPrefix}")
        (lib.filter (f: f.staticAssign) tagged);

      routingPolicyRules =
        map (f: {
          From = f.publicIp;
          Table = routingTable;
          Priority = f.priority;
        })
        tagged;

      routes = [
        {
          Destination = "0.0.0.0/0";
          Gateway = gateway;
          Table = routingTable;
        }
      ];
    }
    // lib.optionalAttrs dhcp {
      networkConfig.DHCP = "ipv4";
      dhcpV4Config = {
        UseGateway = false;
        UseRoutes = false;
        UseDNS = false;
      };
    };

  networking.nftables.tables.ip-forwarder = {
    family = "ip";
    content = ''
      chain prerouting {
        type nat hook prerouting priority -100;
        ${lib.concatMapStrings (f: ''
          ip daddr ${f.publicIp} dnat to ${f.targetTs}
        '')
        tagged}
      }
      chain postrouting {
        type nat hook postrouting priority 100;
        oifname "tailscale0" masquerade
      }
    '';
  };
}
