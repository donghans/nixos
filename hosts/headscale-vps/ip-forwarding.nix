{lib, ...}: {
  imports = [
    ((import ../_lib/ip-forwarder.nix {inherit lib;}) {
      interface = "eth0";
      gateway = "141.164.58.1";
      subnetPrefix = 32;
      forwards = [
        {
          publicIp = "141.164.53.13";
          targetTs = "100.64.0.15";
        } # mac studio
        {
          publicIp = "158.247.252.54";
          targetTs = "100.64.0.5";
        } # ubuntu-2404
      ];
    })
  ];
  # 20-ip-forwarder-eth0.network이 Type=ether DHCP 설정보다 먼저 매칭되므로
  # DHCP를 명시적으로 추가해 기본 IP(141.164.59.97) 유지
  systemd.network.networks."20-ip-forwarder-eth0".networkConfig.DHCP = "ipv4";

  # DMZ IP 방화벽: DNAT 이전(priority -150)에 적용
  # - tailscale(100.64.0.0/10): 전체 허용
  # - 80, 443 및 비특권 포트(>= 1024): 전체 허용
  # - 그 외 특권 포트: 차단
  networking.nftables.tables.dmz-firewall = {
    family = "ip";
    content = ''
      chain prerouting {
        type filter hook prerouting priority -150;
        ip daddr { 141.164.53.13, 158.247.252.54 } ip saddr 100.64.0.0/10 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } tcp dport { 80, 443 } accept
        ip daddr { 141.164.53.13, 158.247.252.54 } tcp dport >= 1024 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } udp dport >= 1024 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } drop
      }
    '';
  };
}
