# lightsail-nixos-headscale 호스트 설정
# SSH 공개키는 hosts/deploy/lightsail-nixos-headscale.pub 에서 자동 로드됩니다.
#
# [시크릿 주입 후 nixup os 실행]
#   scp intermediate_ca.key root@<ip>:/var/lib/step-ca-secrets/
#   scp password            root@<ip>:/var/lib/step-ca-secrets/password
#   ssh root@<ip> /opt/nixos/core/scripts/nixup.sh os
#   → secretsReady=true가 되어 step-ca 유닛 자동 생성·활성화
{
  mkHostConfiguration,
  lib,
  ...
}:
mkHostConfiguration (_: let
  keyFile = "/var/lib/step-ca-secrets/intermediate_ca.key";
  passwordFile = "/var/lib/step-ca-secrets/password";
  secretsReady = builtins.pathExists keyFile && builtins.pathExists passwordFile;
in {
  os = lib.mkMerge [
    # step-ca: 시크릿 존재 시에만 유닛 생성
    (lib.mkIf secretsReady {
      environment.etc."step-ca/root_ca.crt".text = ''
        PLACEHOLDER_ROOT_CA_PEM
      '';
      environment.etc."step-ca/intermediate_ca.crt".text = ''
        PLACEHOLDER_INTERMEDIATE_CA_PEM
      '';
      services.step-ca = {
        enable = true;
        address = "0.0.0.0";
        port = 8443;
        intermediatePasswordFile = passwordFile;
        settings = {
          root = "/etc/step-ca/root_ca.crt";
          crt = "/etc/step-ca/intermediate_ca.crt";
          key = keyFile;
          dnsNames = ["ca.PLACEHOLDER_TAILSCALE_DOMAIN"];
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
    })
    {
      # == headscale ==
      services.headscale = {
        enable = true;
        settings = {
          server_url = "https://PLACEHOLDER_HEADSCALE_DOMAIN";
          listen_addr = "127.0.0.1:8080";
          grpc_listen_addr = "127.0.0.1:50443";
          metrics_listen_addr = "127.0.0.1:9090";
          log.level = "info";
          dns = {
            magic_dns = true;
            base_domain = "headscale.local";
            nameservers.global = ["1.1.1.1" "8.8.8.8"];
          };
        };
      };

      # == AWS IAM Roles Anywhere ==
      mods.sys.services.aws-roles-anywhere = {
        domain = "r.772610158.xyz";
        trustAnchorArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:trust-anchor/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX";
        profileArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:profile/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX";
        roleArn = "arn:aws:iam::732799293614:role/XXXXXX";
      };

      # == Caddy reverse proxy ==
      services.caddy.extraConfig = ''
        PLACEHOLDER_HEADSCALE_DOMAIN {
          reverse_proxy /web* localhost:80
          reverse_proxy * localhost:8080
        }
      '';
    }
  ];
})
