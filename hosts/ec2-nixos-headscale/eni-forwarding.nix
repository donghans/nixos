{lib, ...}: let
  # ── ENI 작업 후 채울 값 ──────────────────────────────────────
  # null 또는 ""이면 DNAT/policy routing 비활성화 (ENI 없는 상태와 동일)
  secIpMac = null; # Mac Studio EIP secondary IP (예: "172.31.x.11")
  secIpIncus = null; # Incus VM EIP secondary IP   (예: "172.31.x.12")
  eth1Gateway = ""; # subnet gateway              (예: "172.31.x.1")
  subnetPrefix = 20; # subnet prefix 길이
  # ─────────────────────────────────────────────────────────────

  # headscale nodes list 로 확인한 실제 Tailscale IP 기입
  macStudioTs = "100.64.x.x"; # Mac Studio Tailscale IP
  incusVmTs = "100.64.x.x"; # Incus VM Tailscale IP

  hasEni = secIpMac != null && secIpIncus != null && eth1Gateway != "";
in {
  # 패킷 포워딩 — ENI 유무 무관하게 항상 활성화 (무해)
  boot.kernel.sysctl."net.ipv4.ip_forward" = 1;

  # eth1 네트워크 설정
  # 90-ethernet(core.network.nix)보다 우선 적용 (숫자 20 < 90)
  # eth1이 없으면 systemd-networkd가 매칭 없이 무시 → 안전
  systemd.network.networks."20-eth1" = {
    matchConfig.Name = "eth1";
    networkConfig.DHCP = "ipv4";
    # primary IP는 DHCP로 받되, default route 추가는 절대 허용 안 함
    dhcpV4Config = {
      UseGateway = false;
      UseRoutes = false;
      UseDNS = false;
    };
    # secondary IP 정적 추가 — hasEni일 때만 ([Address] 섹션)
    address = lib.optionals hasEni [
      "${secIpMac}/${toString subnetPrefix}"
      "${secIpIncus}/${toString subnetPrefix}"
    ];
    # return path policy routing — secondary IP가 있을 때만
    routingPolicyRules = lib.optionals hasEni [
      {
        routingPolicyRuleConfig = {
          From = secIpMac;
          Table = 101;
          Priority = 100;
        };
      }
      {
        routingPolicyRuleConfig = {
          From = secIpIncus;
          Table = 101;
          Priority = 101;
        };
      }
    ];
    routes = lib.optionals hasEni [
      {
        routeConfig = {
          Destination = "0.0.0.0/0";
          Gateway = eth1Gateway;
          Table = 101;
        };
      }
    ];
  };

  # nftables DNAT — secondary IP가 있을 때만 규칙 생성
  # tailscale.nix가 nftables.enable = true 처리하므로 중복 불필요
  networking.nftables.tables.eni-forwarding = lib.mkIf hasEni {
    family = "ip";
    content = ''
      chain prerouting {
        type nat hook prerouting priority -100;
        ip daddr ${secIpMac}   dnat to ${macStudioTs}
        ip daddr ${secIpIncus} dnat to ${incusVmTs}
      }
      chain postrouting {
        type nat hook postrouting priority 100;
        oifname "tailscale0" masquerade
      }
    '';
  };
}
