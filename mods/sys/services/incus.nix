{mkMod, ...}:
mkMod __curPos "Incus hypervisor" ({config, ...}: {
  os = {
    virtualisation.incus.enable = true;
    virtualisation.incus.ui.enable = true;
    networking.firewall.allowedTCPPorts = [8443];
    # nixos-fw의 기본 정책이 drop이라 VM→호스트 트래픽(DHCP 등)도 차단됨
    networking.firewall.trustedInterfaces = ["incusbr0"];
    networking.nftables.enable = true;
    # (목적: VM→인터넷 TCP 단편화 방지)
    # wlo1 MTU가 1400으로 설정된 환경에서 VM이 MSS=1460을 협상하면
    # 호스트가 IP 단편화를 수행해야 함. SYN 패킷에서 rt mtu 기준으로
    # MSS를 클램프하면 단편화 없이 전송 가능한 크기로 자동 조정됨.
    networking.nftables.tables.mss-clamp = {
      family = "ip";
      content = ''
        chain forward {
          type filter hook forward priority mangle;
          iifname "incusbr0" tcp flags syn tcp option maxseg size set rt mtu
          oifname "incusbr0" tcp flags syn tcp option maxseg size set rt mtu
        }
      '';
    };
    # (목적: incus TAP 장치를 systemd-networkd가 가로채지 않도록 명시 제외)
    # incus가 VM용 TAP(tap*, tape* 등)을 생성하면 90-ethernet.network(Type=ether, DHCP=ipv4)가
    # 해당 TAP을 먼저 잡아 incusbr0 bridge slave 등록을 해제해 버림 → VM이 DHCP IP를 못 받음.
    # 20번 우선순위로 TAP 인터페이스를 Unmanaged 처리해 incus가 직접 브리지에 연결하도록 함.
    systemd.network.networks."20-incus-tap" = {
      matchConfig.Name = "tap*";
      linkConfig.Unmanaged = true;
    };
    # VM이 IPv6 RA를 브리지로 보낼 때 호스트 IPv6 라우팅이 바뀌는 것을 방지
    # (RA를 수락하면 Tailscale 등 호스트 IPv6 연결이 끊김)
    boot.kernel.sysctl."net.ipv6.conf.incusbr0.accept_ra" = 0;
    # (목적: VM 첫 패킷 2~3초 지연 방지)
    # br_netfilter가 켜지면 브릿지 트래픽이 브릿지 레벨·IP 레벨에서 conntrack을 이중으로 거침.
    # 첫 패킷에서 두 레이어가 conntrack entry를 동시에 생성하려다 충돌 → 수 초 지연.
    # incus가 자체 nftables로 forwarding을 관리하므로 br_netfilter 개입 불필요.
    # Docker는 IP 레벨(table ip filter)에서 FORWARD 규칙을 관리하므로 영향 없음.
    boot.kernel.sysctl."net.bridge.bridge-nf-call-iptables" = 0;
    boot.kernel.sysctl."net.bridge.bridge-nf-call-ip6tables" = 0;
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
  };
})
