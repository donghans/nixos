# lightsail-nixos-headscale 호스트 설정
# SSH 공개키는 hosts/deploy/lightsail-nixos-headscale.pub 에서 자동 로드됩니다.
#
# [nixup os 전 시크릿 주입]
#   scp intermediate_ca.key root@<ip>:/var/lib/step-ca-secrets/
#   scp password            root@<ip>:/var/lib/step-ca-secrets/password
{
  mkHostConfiguration,
  lib,
  ...
}:
mkHostConfiguration (_: let
  keyFile = "/var/lib/step-ca-secrets/intermediate_ca.key";
  passwordFile = "/var/lib/step-ca-secrets/password";
  rootCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.root-ca.crt;
  intermediateCaPem = builtins.readFile ./deploy/lightsail-nixos-headscale.intermediate-ca.crt;
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
          server_url = "https://e2.772610158.xyz";
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
        caServer = "https://c.772610158.xyz:8443/acme/acme/directory";
        caCert = rootCaPem;
        trustAnchorArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:trust-anchor/77dd2115-b7a2-4490-b15b-db5f4709c4e5";
        profileArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:profile/c56e7711-ec84-400c-a641-8d222685184f";
        roleArn = "arn:aws:iam::732799293614:role/StepCaRolesAnywhereRole";
      };

      # step-ca는 같은 서버에서 실행되므로 localhost로 해석
      networking.hosts."127.0.0.1" = ["c.772610158.xyz"];

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
