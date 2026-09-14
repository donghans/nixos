# Vultr 2GB — headscale 컨트롤 플레인
# EC2+Lightsail+S3 통합 대체 — nginx TLS 직접 종단, GitHub DB 백업
{mkHostConfiguration, ...}:
mkHostConfiguration ({config, ...}: {
  os = {
    imports = [
      ./headscale-vps/e-772610158-xyz.nix
      ./headscale-vps/e-772610158-xyz-db-backup.nix
      ./headscale-vps/ip-forwarding.nix
    ];

    users.users.admin.openssh.authorizedKeys.keyFiles = [
      ./_deploy/headscale-vps.pub
    ];

    security.sudo.extraRules = [
      {
        users = ["admin"];
        commands = [
          {
            command = "ALL";
            options = ["NOPASSWD"];
          }
        ];
      }
    ];

    networking.nameservers = ["1.1.1.1" "8.8.8.8"];
    services.resolved.extraConfig = ''
      Cache=no-negative
    '';

    # Vultr에는 보안그룹 없음 → NixOS 방화벽 직접 제어
    networking.firewall = {
      enable = true;
      allowedTCPPorts = [22 80 443];
      allowedTCPPortRanges = [
        {
          from = 8000;
          to = 8999;
        }
      ];
      allowedUDPPorts = [3478 41641]; # STUN, WireGuard/tailscale
    };

    headscale.domain = "e.772610158.xyz";
    headscale.staticIpv4 = "141.164.59.97";

    mods.sys.services.tailscale = {
      enable = true;
      acceptRoutes = true;
      # state는 nixsec가 /var/lib/tailscale/tailscaled.state 로 직접 주입
    };

    services.headscale-db-backup = {
      enable = true;
      appId = "3995077";
      installationId = "138797641";
      privateKeyFile = "/var/lib/nix-secrets/github-apps/private-key.pem";
      repoUrl = "https://github.com/BITSTEP-IT/headscale-backup.git";
    };

    services.caddy = {
      enable = true;
      globalConfig = ''
        email 772610158.xyz@gmail.com
      '';
      # GHA가 SCP로 배포하는 동적 vhost 파일 로드
      extraConfig = ''
        import /etc/caddy/sites/*.caddy
      '';
      virtualHosts.${config.headscale.domain}.extraConfig = ''
        reverse_proxy 127.0.0.1:8080
      '';
    };

    environment.etc."caddy/sites/class24.caddy".text = ''
      class24.co.kr {
          request_body {
              max_size 50MB
          }
          handle /api/* {
              uri strip_prefix /api
              reverse_proxy 100.64.0.18:3000 {
                  transport http {
                      read_timeout 300s
                  }
              }
          }
          handle {
              reverse_proxy 100.64.0.18:4000
          }
      }
      admin.class24.co.kr {
          request_body {
              max_size 50MB
          }
          handle /api/* {
              uri strip_prefix /api
              reverse_proxy 100.64.0.18:5100 {
                  transport http {
                      read_timeout 300s
                  }
              }
          }
          handle {
              reverse_proxy 100.64.0.18:5000
          }
      }
    '';

    environment.etc."caddy/sites/minigame.caddy".text = ''
      minigame.whosfan.io {
          reverse_proxy 100.64.0.3:80
      }
    '';

    environment.etc."caddy/sites/genple.caddy".text = ''
      genple.ai {
          reverse_proxy 100.64.0.20:80
      }
    '';

    environment.etc."caddy/sites/shopify-dk-sync.caddy".text = ''
      whosfanstore-webhook.qubitic.com {
          reverse_proxy 100.64.0.25:9100
      }
    '';

    # dms(문서관리시스템) — server2-beelink-ser7-co의 dms LXC(100.64.0.33)에 다른
    # 작업자가 web/api/onlyoffice/converter를 채워넣을 예정.
    #
    # tailscale 내부망 전용으로 바꾼 구조 (2026-09-14):
    # - 예전엔 headscale-vps 공인 IP(80/443)로 그대로 노출 → 인터넷 전체에서 접근 가능했음
    # - 지금은 Caddy가 headscale-vps 자신의 tailscale IP(100.64.0.14)에만 bind
    #   → 공인 인터페이스에는 이 vhost가 아예 존재하지 않아 tailnet 밖에서는 접속 불가
    # - Cloudflare DNS(772610158.xyz)의 A 레코드도 100.64.0.14로 돌려둬야 함 (프록시 OFF)
    # - TLS는 Caddy 자체 auto_https 대신 security.acme(Cloudflare DNS-01)로 발급 —
    #   dev.genple.ai/demo.genple.ai와 동일한 트릭(공인 도메인 + DNS-01 + CGNAT IP A레코드)이지만
    #   여기서는 컨테이너 자신이 아니라 headscale-vps가 TLS 종단 + 라우팅을 대신 함
    security.acme.acceptTerms = true;
    security.acme.defaults.email = "772610158.xyz@gmail.com";
    security.acme.certs = let
      mkDmsCert = {}: {
        dnsProvider = "cloudflare";
        environmentFile = "/var/lib/nix-secrets/cloudflare/token";
        group = "caddy";
        reloadServices = ["caddy.service"];
      };
    in {
      "web.dms.772610158.xyz" = mkDmsCert {};
      "api.dms.772610158.xyz" = mkDmsCert {};
      "onlyoffice.dms.772610158.xyz" = mkDmsCert {};
      "converter.dms.772610158.xyz" = mkDmsCert {};
    };

    environment.etc."caddy/sites/dms.caddy".text = ''
      web.dms.772610158.xyz {
          bind 100.64.0.14
          tls /var/lib/acme/web.dms.772610158.xyz/cert.pem /var/lib/acme/web.dms.772610158.xyz/key.pem
          reverse_proxy 100.64.0.33:3000
      }
      api.dms.772610158.xyz {
          bind 100.64.0.14
          tls /var/lib/acme/api.dms.772610158.xyz/cert.pem /var/lib/acme/api.dms.772610158.xyz/key.pem
          reverse_proxy 100.64.0.33:4000
      }
      onlyoffice.dms.772610158.xyz {
          bind 100.64.0.14
          tls /var/lib/acme/onlyoffice.dms.772610158.xyz/cert.pem /var/lib/acme/onlyoffice.dms.772610158.xyz/key.pem
          reverse_proxy 100.64.0.33:8082
      }
      converter.dms.772610158.xyz {
          bind 100.64.0.14
          tls /var/lib/acme/converter.dms.772610158.xyz/cert.pem /var/lib/acme/converter.dms.772610158.xyz/key.pem
          reverse_proxy 100.64.0.33:3050
      }
    '';

    systemd.tmpfiles.rules = [
      "d /etc/caddy/sites 0755 admin root -"
      "d /home/admin/landings 0755 admin users -"
    ];

    virtualisation.docker.enable = true;
    virtualisation.docker.autoPrune.enable = true;
    virtualisation.docker.daemon.settings.dns = ["8.8.8.8" "8.8.4.4"];
    users.users.admin.extraGroups = ["docker"];

    # Docker 28+는 iptables 대신 nftables로 NAT 관리
    networking.nftables.enable = true;

    # systemd-networkd가 Docker veth/브리지를 가로채 br-*가 NO-CARRIER 되는 현상 방지
    systemd.network.networks."20-docker-veth" = {
      matchConfig.Name = "veth* br-* docker*";
      linkConfig.Unmanaged = true;
    };
  };
  hm = {};
})
