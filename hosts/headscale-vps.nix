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
    # 작업자가 web/api/onlyoffice/converter를 채워넣을 예정. 서비스가 아직 없어도
    # 도메인만 미리 연결해둔다.
    environment.etc."caddy/sites/dms.caddy".text = ''
      web.dms.772610158.xyz {
          reverse_proxy 100.64.0.33:3000
      }
      api.dms.772610158.xyz {
          reverse_proxy 100.64.0.33:4000
      }
      onlyoffice.dms.772610158.xyz {
          reverse_proxy 100.64.0.33:8082
      }
      converter.dms.772610158.xyz {
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
