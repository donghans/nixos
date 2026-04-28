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
        -----BEGIN CERTIFICATE-----
        MIIBkjCCATmgAwIBAgIQZrFUQgbIq/vvhfCHPsPT3DAKBggqhkjOPQQDAjAoMQ4w
        DAYDVQQKEwVNeSBDQTEWMBQGA1UEAxMNTXkgQ0EgUm9vdCBDQTAeFw0yNjA0Mjgw
        MTA4MjNaFw0zNjA0MjUwMTA4MjNaMCgxDjAMBgNVBAoTBU15IENBMRYwFAYDVQQD
        Ew1NeSBDQSBSb290IENBMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE+zHuKfWq
        0yEF+wGiU6/4PuPkcQbXczJZPHZUQatPHy8G/o8GA7bveEFQA4utxV5ollRH6hW4
        +07r561MaaGQw6NFMEMwDgYDVR0PAQH/BAQDAgEGMBIGA1UdEwEB/wQIMAYBAf8C
        AQEwHQYDVR0OBBYEFFlHSrguhGthbTPkFN5fI+ym7I4xMAoGCCqGSM49BAMCA0cA
        MEQCIDm6DkHEoJg/rseNnLVPOMP46KXwkv47FMuxgjX4DQ7TAiAYo4SVLZXiqLC/
        rHh+DyUggEIjn6lbnsijLSEXOBkLig==
        -----END CERTIFICATE-----
      '';
      environment.etc."step-ca/intermediate_ca.crt".text = ''
        -----BEGIN CERTIFICATE-----
        MIIBvjCCAWOgAwIBAgIRAPdJPX2YTxrEjAn58MeCVdYwCgYIKoZIzj0EAwIwKDEO
        MAwGA1UEChMFTXkgQ0ExFjAUBgNVBAMTDU15IENBIFJvb3QgQ0EwHhcNMjYwNDI4
        MDEwODI0WhcNMzYwNDI1MDEwODI0WjAwMQ4wDAYDVQQKEwVNeSBDQTEeMBwGA1UE
        AxMVTXkgQ0EgSW50ZXJtZWRpYXRlIENBMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcD
        QgAEMPt8DZFXQ3CmOTI46AsVjX1Q5x9EdVK8Quk4gt1MUQKUzUOqTTdaus2E43Q2
        zOoNpQYuqxHJmgG5y2DUzNJg36NmMGQwDgYDVR0PAQH/BAQDAgEGMBIGA1UdEwEB
        /wQIMAYBAf8CAQAwHQYDVR0OBBYEFIpKghvgwYQZDjm9BtQUVABgpVERMB8GA1Ud
        IwQYMBaAFFlHSrguhGthbTPkFN5fI+ym7I4xMAoGCCqGSM49BAMCA0kAMEYCIQDj
        cHdgKsmLr9xvpJfT3+DP7xv984gYrwAqSNl8ecaPUgIhAIu7UMLNEXNcA5OX35St
        Ba7wbv+GGReaRBAtEo33fGgh
        -----END CERTIFICATE-----
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
    })
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
        caCertFile = "/etc/step-ca/root_ca.crt";
        trustAnchorArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:trust-anchor/77dd2115-b7a2-4490-b15b-db5f4709c4e5";
        profileArn = "arn:aws:rolesanywhere:ap-northeast-2:732799293614:profile/c56e7711-ec84-400c-a641-8d222685184f";
        roleArn = "arn:aws:iam::732799293614:role/StepCaRolesAnywhereRole";
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
