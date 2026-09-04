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
  # - 원격제어 프로토콜(VNC 5900·RDP 3389): 공개망에서는 차단 — 인터넷에서 상시 스캔당하는
  #   대표적 표적이라 열어 둘 이유가 없다(2026-09-03: mac-studio 화면공유가 전세계 스캐너에
  #   두드려져 remotemanagementd 크래시 루프 + TIME_WAIT 32k 고갈까지 갔던 사고의 재발 방지).
  #   Tailscale 경유(위 줄)는 이 차단을 안 타므로 내부 사용은 그대로다.
  # - 그 외 80, 443 및 비특권 포트(>= 1024): 전체 허용 — 임의 포트를 미리 정하지 않고 쓰는
  #   운영 방식(대표 재량)을 그대로 유지한다. 화이트리스트로 좁히지 않는다.
  # - 그 외 특권 포트: 차단
  networking.nftables.tables.dmz-firewall = {
    family = "ip";
    content = ''
      chain prerouting {
        type filter hook prerouting priority -150;
        ip daddr { 141.164.53.13, 158.247.252.54 } ip saddr 100.64.0.0/10 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } tcp dport { 5900, 3389 } drop
        ip daddr { 141.164.53.13, 158.247.252.54 } tcp dport { 80, 443 } accept
        ip daddr { 141.164.53.13, 158.247.252.54 } tcp dport >= 1024 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } udp dport >= 1024 accept
        ip daddr { 141.164.53.13, 158.247.252.54 } drop
      }
    '';
  };
}
