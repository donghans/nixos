# sbox broker 의 최소 NixOS ct 이미지 정의 (로드맵 ⑪ — pilot §29-60·76). 이 이미지에는 broker 서비스·nftables·네트워크만 있고
# 패키지 관리자(apt)·dbus·polkit·getty·sshd·nix 데몬이 없다. 갱신 = 이미지를 다시 만들고 ct 를 교체(상태는 호스트가 밀어 넣는 설정뿐).
# 빌드: bash core/sbox/broker-image/build.sh   (정의 변경 → 새 이미지 → `sboxctl broker create --nix`)
{ config, lib, pkgs, modulesPath, ... }:
let
  brokerPy = ../broker_proxy.py;
  port = 3128;
in
{
  imports = [ "${modulesPath}/virtualisation/lxc-container.nix" ];

  system.stateVersion = "26.05";
  networking.hostName = "sbox-broker";
  networking.useDHCP = true;
  networking.useNetworkd = true;
  services.resolved.enable = false;   # broker 가 이름 해석을 직접 한다(상위 DNS 동시 질의) — 53 포트도 broker 가 씀
  networking.nameservers = [ "8.8.8.8" "9.9.9.9" ];

  # 최소화: 문서·기본 패키지·nix 데몬·ssh 없음
  documentation.enable = false;
  documentation.nixos.enable = false;
  environment.defaultPackages = lib.mkForce [ ];
  programs.command-not-found.enable = false;
  services.openssh.enable = lib.mkForce false;
  nix.enable = false;
  users.mutableUsers = false;
  users.users.root.hashedPassword = "!";   # 비밀번호 로그인 없음(관리는 호스트의 incus exec 만)
  users.allowNoPasswordLogin = true;
  systemd.services."getty@".enable = false;
  systemd.services."serial-getty@".enable = false;
  systemd.services."console-getty".enable = false;

  # 기본 시스템 도구 모음(coreutils·util-linux·curl·sudo 등 수백 개)을 비운다 — 첫 빌드는 /run/current-system/sw/bin 이 566개였다(pilot §29-76).
  # 남기는 것: 점검용 nft 와 셸(NixOS 활성화 스크립트가 bash 를 요구해 완전히 없앨 수는 없음)
  environment.corePackages = lib.mkForce [ pkgs.bashInteractive ];
  environment.systemPackages = [ pkgs.nftables ];
  security.sudo.enable = false;
  programs.nano.enable = lib.mkForce false;
  fonts.fontconfig.enable = lib.mkForce false;
  boot.supportedFilesystems = lib.mkForce [ ];   # vfat·bcache 등 파일시스템 도구(mkfs·fsck 류)가 sw/bin 에 들어오던 것
  boot.bcache.enable = false;
  services.lvm.enable = false;
  systemd.services.nix-channel-init.enable = lib.mkForce false;   # nix 가 없어 항상 실패하던 유닛
  programs.less.enable = lib.mkForce false;
  nix.channel.enable = false;      # nix-channel-init 서비스가 실패하던 것도 같이 사라짐
  services.nscd.enable = false;
  system.nssModules = lib.mkForce [ ];
  networking.firewall.allowedTCPPorts = [ 80 443 3128 ];   # NixOS 방화벽이 기본으로 input 을 막는다 — broker 가 받는 포트만 연다
  networking.firewall.allowedUDPPorts = [ 53 ];

  # 게이트웨이 규칙(방식 B, pilot §29-37): ct 의 443·80 은 이 컴퓨터의 프록시로 redirect, forward 는 명시적 기본 거부.
  # 체인 이름에 fwd 를 쓰지 말 것(nft 예약어).
  networking.nftables.enable = true;
  networking.nftables.flushRuleset = true;
  networking.nftables.ruleset = ''
    table ip sbox_gateway {
      chain pre {
        type nat hook prerouting priority dstnat; policy accept;
        iifname "eth0" ip saddr 10.100.1.200-10.100.1.250 tcp dport 443 redirect to :443
        iifname "eth0" ip saddr 10.100.1.200-10.100.1.250 tcp dport 80 redirect to :80
      }
    }
    table inet sbox_gateway_filter {
      chain forwardguard {
        type filter hook forward priority 0; policy drop;
      }
    }
  '';
  boot.kernel.sysctl."net.ipv4.ip_forward" = 0;

  systemd.tmpfiles.rules = [ "d /etc/broker 0755 root root -" ];

  systemd.services.sbox-broker = {
    description = "sbox broker (L7 egress: CONNECT proxy + 투명 TLS 443 + DNS stub)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      ExecStart = "${pkgs.python3}/bin/python3 -I ${brokerPy} --listen 0.0.0.0 --port ${toString port} --tls-port 443 --http-port 80 --dns-listen 0.0.0.0 --config /etc/broker/clients.json --log /var/log/broker/access.log";
      User = "nobody";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      CapabilityBoundingSet = "CAP_NET_BIND_SERVICE";
      LogsDirectory = "broker";
      Restart = "always";
      RestartSec = 2;
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      PrivateDevices = true;
      ProtectKernelTunables = true;
      ProtectControlGroups = true;
      RestrictAddressFamilies = "AF_INET AF_INET6 AF_UNIX";   # netlink(nf_tables 접근) 금지 — pilot §29-62
      RestrictNamespaces = true;
      LockPersonality = true;
      ProtectKernelModules = true;
      ProtectKernelLogs = true;
    };
  };
}
