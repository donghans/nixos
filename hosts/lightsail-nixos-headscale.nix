# lightsail-nixos-headscale 호스트 설정
# SSH 공개키는 hosts/deploy/lightsail-nixos-headscale.pub 에서 자동 로드됩니다.
#
# [nixup os 전 시크릿 주입]
#   scp intermediate_ca.key  root@<ip>:/var/lib/nix-secrets/step-ca/
#   scp password             root@<ip>:/var/lib/nix-secrets/step-ca/
#
# [SSM Parameter Store — 배포 전 1회]
#   aws ssm put-parameter --name /headscale/oidc_client_secret --type SecureString --value <secret>
{
  mkHostConfiguration,
  lib,
  pkgs,
  ...
}:
mkHostConfiguration (_: let
  keyFile = "/var/lib/nix-secrets/step-ca/intermediate_ca.key";
  passwordFile = "/var/lib/nix-secrets/step-ca/password";
  rootCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.root-ca.crt;
  intermediateCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.intermediate-ca.crt;
  headscaleDomain = "e2.772610158.xyz";
  oidcClientSecretFile = "/run/nix-secrets/headscale/oidc_client_secret";
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
        };
      };

      # 부팅 시 SSM Parameter Store에서 OIDC 시크릿을 가져와 tmpfs에 기록
      # /run/ 은 재부팅마다 초기화되므로 매 부팅 시 fresh 취득
      systemd.services.headscale-oidc-secret = {
        description = "Fetch headscale OIDC client secret from SSM Parameter Store";
        before = ["headscale.service"];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          RuntimeDirectory = "nix-secrets/headscale";
          RuntimeDirectoryMode = "0711";
          Environment = "AWS_CONFIG_FILE=/etc/aws/config";
          ExecStart = pkgs.writeShellScript "headscale-fetch-oidc-secret" ''
            ${pkgs.awscli2}/bin/aws ssm get-parameter \
              --name "/headscale/oidc_client_secret" \
              --with-decryption \
              --query "Parameter.Value" \
              --output text \
              > "${oidcClientSecretFile}"
            chmod 400 "${oidcClientSecretFile}"
            chown headscale "${oidcClientSecretFile}"
          '';
        };
      };

      # headscale은 OIDC 시크릿 fetch가 성공해야만 기동
      systemd.services.headscale = {
        after = ["headscale-oidc-secret.service"];
        requires = ["headscale-oidc-secret.service"];
      };

      # STUN (DERP 직접 연결 보조)
      networking.firewall.allowedUDPPorts = [3478];

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
      services.caddy.extraConfig = ''
        ${headscaleDomain} {
          reverse_proxy /web* localhost:80
          reverse_proxy * localhost:8080
        }
      '';
    }
  ];
})
