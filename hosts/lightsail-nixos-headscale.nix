# lightsail-nixos-headscale 호스트 설정
# SSH 공개키는 hosts/deploy/lightsail-nixos-headscale.pub 에서 자동 로드됩니다.
{
  mkHostConfiguration,
  pkgs,
  lib,
  ...
}:
mkHostConfiguration (_: let
  keyFile = "/var/lib/nix-secrets/step-ca/intermediate_ca.key";
  passwordFile = "/var/lib/nix-secrets/step-ca/password";
  rootCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.root-ca.crt;
  intermediateCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.intermediate-ca.crt;
  headscaleDomain = "e.772610158.xyz";
  oidcClientSecretFile = "/var/lib/nix-secrets/headscale/oidc_client_secret";
  # NixOS headscale 모듈은 v6 prefix를 항상 주입함 → script override로 우회
  headscaleConfigFile = (pkgs.formats.yaml {}).generate "headscale.yaml" {
    disable_check_updates = true;
    unix_socket = "/run/headscale/headscale.sock";
    unix_socket_permission = "0660";
    server_url = "https://${headscaleDomain}";
    listen_addr = "127.0.0.1:8080";
    grpc_listen_addr = "127.0.0.1:50443";
    metrics_listen_addr = "127.0.0.1:9090";
    log.level = "info";
    prefixes = {
      v4 = "10.127.0.0/17";
      allocation = "sequential";
    };
    database = {
      type = "sqlite3";
      sqlite.path = "/var/lib/headscale/db.sqlite";
    };
    derp = {
      server = {
        enabled = true;
        region_id = 999;
        region_code = "headscale";
        region_name = "Headscale Embedded DERP";
        stun_listen_addr = "0.0.0.0:3478";
        automatically_add_embedded_derp_region = true;
      };
      urls = ["https://controlplane.tailscale.com/derpmap/default"];
      auto_update_enabled = true;
      update_frequency = "3h";
    };
    dns = {
      magic_dns = true;
      base_domain = "i.772610158.xyz";
      override_local_dns = true;
      nameservers.global = [
        "1.1.1.1"
        "1.0.0.1"
        "2606:4700:4700::1111"
        "2606:4700:4700::1001"
      ];
      extra_records = [
        {
          name = "opnsense.i.772610158.xyz";
          type = "A";
          value = "192.168.1.1";
        }
        {
          name = "headscale.i.772610158.xyz";
          type = "A";
          value = "192.168.1.2";
        }
        {
          name = "vaultwarden.i.772610158.xyz";
          type = "A";
          value = "192.168.1.3";
        }
        {
          name = "proxmox.i.772610158.xyz";
          type = "A";
          value = "192.168.1.222";
        }
        {
          name = "veve.i.772610158.xyz";
          type = "A";
          value = "192.168.1.12";
        }
      ];
    };
    oidc = {
      only_start_if_oidc_is_available = true;
      issuer = "https://accounts.google.com";
      client_id = "170530185854-nelsine6eg1casd7hl669taueriv16q6.apps.googleusercontent.com";
      client_secret_path = oidcClientSecretFile;
      scope = ["openid" "profile" "email"];
      email_verified_required = true;
      extra_params.prompt = "select_account";
      allowed_domains = ["bitstep.it"];
      user_scope_strip_domain = true;
      pkce = {
        enabled = true;
        method = "S256";
      };
    };
    taildrop.enabled = true;
  };
in {
  os = lib.mkMerge [
    {
      environment.etc."step-ca/root_ca.crt".text = rootCaPem;
      environment.etc."step-ca/intermediate_ca.crt".text = intermediateCaPem;
      services.step-ca = {
        enable = true;
        address = "0.0.0.0";
        port = 8443;
        intermediatePasswordFile = passwordFile;
        settings = {
          root = "/etc/step-ca/root_ca.crt";
          crt = "/etc/step-ca/intermediate_ca.crt";
          key = keyFile;
          dnsNames = ["c.772610158.xyz"];
          db = {
            type = "badger";
            dataSource = "/var/lib/step-ca/db";
          };
          authority.provisioners = [
            {
              type = "ACME";
              name = "acme";
            }
          ];
          tls = {
            minVersion = 1.2;
            maxVersion = 1.3;
            renegotiation = false;
          };
        };
      };
      systemd.services.step-ca.serviceConfig.ReadOnlyPaths = [
        (builtins.dirOf keyFile)
      ];
    }
    {
      # == headscale ==
      services.headscale = {
        enable = true;
        settings = {
          server_url = "https://${headscaleDomain}";
          listen_addr = "127.0.0.1:8080";
          grpc_listen_addr = "127.0.0.1:50443";
          metrics_listen_addr = "127.0.0.1:9090";
          log.level = "info";

          prefixes = {
            v4 = "10.127.0.0/17";
            v6 = "fd7a:115c:a1e0::/48";
            allocation = "sequential";
          };

          derp = {
            server = {
              enabled = true;
              region_id = 999;
              region_code = "headscale";
              region_name = "Headscale Embedded DERP";
              stun_listen_addr = "0.0.0.0:3478";
              automatically_add_embedded_derp_region = true;
            };
            urls = ["https://controlplane.tailscale.com/derpmap/default"];
            auto_update_enabled = true;
            update_frequency = "3h";
          };

          dns = {
            magic_dns = true;
            base_domain = "i.772610158.xyz";
            override_local_dns = true;
            nameservers.global = [
              "1.1.1.1"
              "1.0.0.1"
              "2606:4700:4700::1111"
              "2606:4700:4700::1001"
            ];
            extra_records = [
              {
                name = "opnsense.i.772610158.xyz";
                type = "A";
                value = "192.168.1.1";
              }
              {
                name = "headscale.i.772610158.xyz";
                type = "A";
                value = "192.168.1.2";
              }
              {
                name = "vaultwarden.i.772610158.xyz";
                type = "A";
                value = "192.168.1.3";
              }
              {
                name = "proxmox.i.772610158.xyz";
                type = "A";
                value = "192.168.1.222";
              }
              {
                name = "veve.i.772610158.xyz";
                type = "A";
                value = "192.168.1.12";
              }
            ];
          };

          oidc = {
            only_start_if_oidc_is_available = true;
            issuer = "https://accounts.google.com";
            client_id = "170530185854-nelsine6eg1casd7hl669taueriv16q6.apps.googleusercontent.com";
            client_secret_path = oidcClientSecretFile;
            scope = ["openid" "profile" "email"];
            email_verified_required = true;
            extra_params.prompt = "select_account";
            allowed_domains = ["bitstep.it"];
            user_scope_strip_domain = true;
            pkce = {
              enabled = true;
              method = "S256";
            };
          };

          taildrop.enabled = true;
          unix_socket_permission = "0660";
        };
      };

      # v6 없는 custom config로 실행하도록 script override
      systemd.services.headscale.script = lib.mkForce ''
        exec ${pkgs.headscale}/bin/headscale serve --config ${headscaleConfigFile}
      '';

      users.users.ec2-user.extraGroups = ["headscale"];

      # Lightsail 네트워크 방화벽이 외부 트래픽을 제어하므로 NixOS 방화벽은 비활성화
      networking.firewall.enable = false;

      # == AWS IAM Roles Anywhere ==
      mods.sys.services.aws-roles-anywhere = {
        domain = "r.772610158.xyz";
        caServer = "https://c.772610158.xyz:8443/acme/acme/directory";
        caCert = rootCaPem;
        trustAnchorArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:trust-anchor/77dd2115-b7a2-4490-b15b-db5f4709c4e5";
        profileArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:profile/c56e7711-ec84-400c-a641-8d222685184f";
        roleArn = "arn:aws:iam::732799293614:role/StepCaRolesAnywhereRole";
      };

      services.amazon-ssm-agent.enable = true;

      # step-ca는 같은 서버에서 실행되므로 localhost로 해석
      networking.hosts."127.0.0.1" = ["c.772610158.xyz"];

      # Cloudflare DNS-01 TXT 레코드 전파 확인을 위해 공개 DNS 추가
      networking.nameservers = ["1.1.1.1" "8.8.8.8"];

      # systemd-resolved가 NXDOMAIN을 캐시하지 않도록 (step-ca DNS-01 검증 실패 방지)
      services.resolved.extraConfig = "Cache=no-negative";

      # DHCP에서 AWS VPC DNS(172.26.0.2)를 기본 라우터로 쓰지 않도록
      systemd.network.networks."05-ens5" = {
        matchConfig.Name = "ens5";
        networkConfig.DHCP = "ipv4";
        dhcpV4Config.UseDNS = false;
      };

      # == Caddy reverse proxy ==
      mods.sys.services.caddy = {
        configText = ''
          ${headscaleDomain} {
            reverse_proxy /web* localhost:80
            reverse_proxy * localhost:8080
          }
        '';
        reloadUser = "ec2-user";
      };

      # landing page 배포 스크립트가 사용하는 작업 디렉터리
      systemd.tmpfiles.rules = ["d /opt/landings 0755 ec2-user users -"];
    }
  ];
})
