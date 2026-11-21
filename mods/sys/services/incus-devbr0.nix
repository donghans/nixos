# 격리 개발 VM 용 incus 브리지 `devbr0` + 호스트 방화벽 (plan dev-sandbox-pilot §4-2, S1)
#
# 목적: 격리하려는 개발 환경(incus VM `dev-nixos` 등)이 호스트의 서비스·내부망에 닿지 않게 하면서 외부 인터넷 NAT 만 허용한다.
# 기존 `incusbr0` 와 다른 점: incusbr0 는 방화벽 trustedInterfaces 라서(incus.nix) 게스트가 호스트의 0.0.0.0 바인딩 포트(22·5355·8443 등)에 닿는다
# (2026-11-21 incus 컨테이너·VM 경계 시험, note dev-sandbox-evidence). devbr0 는 신뢰 인터페이스에 넣지 않고 아래 규칙으로 막는다.
#
# 규칙(시험함: 임시 네트워크 네임스페이스에서 별도 표의 INPUT 동작 — note dev-sandbox-evidence 「devbr0 방화벽 초안」):
#  - INPUT: devbr0 에서 호스트로 오는 것은 ① 이미 맺어진 연결 ② DHCP(udp 67) ③ 브리지 주소(10.100.1.1)의 DNS(53)만 허용, 나머지는 drop.
#    DNS 를 브리지 주소로 제한하는 이유: 호스트의 dockerdns0(10.255.255.53)가 tailnet DNS(100.100.100.100)로 포워딩하므로 모든 로컬 주소의 53 을 열면 tailnet 이름이 풀린다.
#  - FORWARD: devbr0 → 사설·내부 대역(10/8·172.16/12·192.168/16·169.254/16·100.64/10 = LAN·docker·incusbr0·tailnet) drop, 다른 인터페이스 → devbr0 새 연결 drop.
#    인터넷으로 나가는 것은 NAT(incus 의 ipv4.nat)로 허용.
#  - 이 표의 accept 는 이 체인만 끝낸다. 뒤의 nixos-fw 도 devbr0 의 DHCP·DNS 를 받아야 하므로 extraInputRules 로 같은 조건을 연다
#    (networking.firewall.interfaces.devbr0.* 는 목적지 주소를 제한하지 못해 쓰지 않는다).
#
# 못 시험한 것(S1 적용 뒤 프로브로 확인): nixos-fw 와의 결합, UDP DNS/DHCP 실동작, FORWARD/NAT, incus 가 브리지에 자동으로 넣는 규칙(ipv4.firewall)과의 중복.
# 되돌리는 법: 호스트 toml 의 `incus-devbr0` 를 false 로 하고 nixup. preseed 는 네트워크를 지우지 않으므로 VM 을 지운 뒤 `incus network delete devbr0`.
{mkMod, ...}:
mkMod __curPos "격리 개발 VM 용 incus 브리지(devbr0)와 호스트 방화벽" ({config, ...}: {
  os = {
    assertions = [
      {
        assertion = config.mods.sys.services.incus.enable;
        message = "mods.sys.services.incus-devbr0 는 mods.sys.services.incus.enable = true 가 필요합니다";
      }
    ];

    # incus-preseed 는 「덮어쓰거나 없으면 생성, 삭제는 안 함」이라 기존 incusbr0 는 그대로다.
    virtualisation.incus.preseed.networks = [
      {
        name = "devbr0";
        type = "bridge";
        config = {
          # incusbr0(10.100.0.0/24)와 겹치지 않는 부분망. auto 로 두면 incus 재시작마다 바뀔 수 있어 고정한다.
          "ipv4.address" = "10.100.1.1/24";
          "ipv4.nat" = "true";
          "ipv6.address" = "none";
          # 상위 DNS 를 공용으로 고정한다 — 안 그러면 호스트 dnsmasq 가 resolv.conf 의 tailnet DNS 를 따라가 VM 이 tailnet 이름을 해석한다(incus.nix 와 같은 이유).
          "raw.dnsmasq" = "server=1.1.1.1\nserver=8.8.8.8\nfilter-AAAA";
        };
      }
    ];

    # VM 이 IPv6 RA 를 브리지로 보낼 때 호스트 IPv6 라우팅이 바뀌는 것을 방지(incus.nix 의 incusbr0 와 같은 이유)
    boot.kernel.sysctl."net.ipv6.conf.devbr0.accept_ra" = 0;

    networking.nftables.enable = true;

    # NixOS 방화벽(nixos-fw, hook input priority filter)보다 먼저(-10) 평가되는 별도 표. drop 은 최종이다.
    networking.nftables.tables.devbr0-guard = {
      family = "inet";
      content = ''
        chain input {
          type filter hook input priority -10; policy accept;
          iifname "devbr0" ct state established,related accept
          iifname "devbr0" udp dport 67 accept
          iifname "devbr0" ip daddr 10.100.1.1 udp dport 53 accept
          iifname "devbr0" ip daddr 10.100.1.1 tcp dport 53 accept
          iifname "devbr0" drop
        }
        chain forward {
          type filter hook forward priority -10; policy accept;
          iifname "devbr0" ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } drop
          oifname "devbr0" iifname != "devbr0" ct state established,related accept
          oifname "devbr0" iifname != "devbr0" drop
        }
      '';
    };

    # nixos-fw 쪽에서도 devbr0 의 DHCP·DNS 만 연다(위 별도 표의 accept 는 nixos-fw 를 건너뛰지 못한다).
    networking.firewall.extraInputRules = ''
      iifname "devbr0" udp dport 67 accept
      iifname "devbr0" ip daddr 10.100.1.1 udp dport 53 accept
      iifname "devbr0" ip daddr 10.100.1.1 tcp dport 53 accept
    '';

    # VM→인터넷 TCP 단편화 방지(incus.nix 의 mss-clamp 는 incusbr0 만 대상이라 devbr0 용을 따로 둔다 — 같은 표의 체인을 중복 정의하지 않으려고 별도 표).
    networking.nftables.tables.mss-clamp-devbr0 = {
      family = "ip";
      content = ''
        chain forward {
          type filter hook forward priority mangle;
          iifname "devbr0" tcp flags syn tcp option maxseg size set rt mtu
          oifname "devbr0" tcp flags syn tcp option maxseg size set rt mtu
        }
      '';
    };
  };
})
