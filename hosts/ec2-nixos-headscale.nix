# EC2 t4g.micro headscale 컨트롤 플레인
# lightsail-nixos-headscale.nix 대체 — step-ca / Roles Anywhere 제거
# AWS 인증: IAM Instance Profile (EC2 전용, 자동)
# DB 백업: litestream → S3 (Instance Profile 자격증명 사용)
{
  mkHostConfiguration,
  pkgs,
  lib,
  ...
}:
let
  headscaleDomain      = "e2.772610158.xyz";
  derpDomain           = "d.r.772610158.xyz";
  oidcClientSecretFile = "/var/lib/nix-secrets/headscale/oidc_client_secret";
  s3BackupBucket       = "PLACEHOLDER-headscale-backup";  # 실제 S3 버킷명으로 교체

  headscaleConfigFile = (pkgs.formats.yaml {}).generate "headscale.yaml" {
    disable_check_updates = true;
    unix_socket            = "/run/headscale/headscale.sock";
    unix_socket_permission = "0660";
    server_url             = "https://${headscaleDomain}";
    listen_addr            = "127.0.0.1:8080";
    grpc_listen_addr       = "127.0.0.1:50443";
    metrics_listen_addr    = "127.0.0.1:9090";
    log.level              = "info";
    noise.private_key_path = "/var/lib/headscale/noise_private.key";
    prefixes = {
      v4         = "100.64.0.0/10";
      allocation = "sequential";
    };
    database = {
      type         = "sqlite3";
      sqlite.path  = "/var/lib/headscale/db.sqlite";
    };
    derp = {
      server.enabled     = false;  # DERP 릴레이는 lightsail-nixos-derp에서 운영
      urls               = ["https://controlplane.tailscale.com/derpmap/default"];
      paths              = ["/etc/headscale/derp-custom.yaml"];
      auto_update_enabled = true;
      update_frequency    = "3h";
    };
    dns = {
      magic_dns          = true;
      base_domain        = "i.772610158.xyz";
      override_local_dns = true;
      nameservers.global = [
        "1.1.1.1"
        "1.0.0.1"
        "2606:4700:4700::1111"
        "2606:4700:4700::1001"
      ];
      extra_records = [
        { name = "opnsense.i.772610158.xyz";   type = "A"; value = "192.168.1.1"; }
        { name = "headscale.i.772610158.xyz";  type = "A"; value = "192.168.1.2"; }
        { name = "vaultwarden.i.772610158.xyz"; type = "A"; value = "192.168.1.3"; }
        { name = "proxmox.i.772610158.xyz";    type = "A"; value = "192.168.1.222"; }
        { name = "veve.i.772610158.xyz";       type = "A"; value = "192.168.1.12"; }
      ];
    };
    oidc = {
      only_start_if_oidc_is_available = true;
      issuer              = "https://accounts.google.com";
      client_id           = "170530185854-nelsine6eg1casd7hl669taueriv16q6.apps.googleusercontent.com";
      client_secret_path  = oidcClientSecretFile;
      scope               = ["openid" "profile" "email"];
      email_verified_required = true;
      extra_params.prompt = "select_account";
      allowed_domains     = ["bitstep.it"];
      user_scope_strip_domain = true;
      pkce = { enabled = true; method = "S256"; };
    };
    taildrop.enabled = true;
  };
in
mkHostConfiguration (_: {
  os = {
    # == headscale ==
    services.headscale = {
      enable = true;
      settings.dns = {
        magic_dns   = true;
        base_domain = "i.772610158.xyz";
      };
    };
    systemd.services.headscale.script = lib.mkForce ''
      exec ${pkgs.headscale}/bin/headscale serve --config ${headscaleConfigFile}
    '';
    users.users.ec2-user.extraGroups = ["headscale"];

    # == 커스텀 DERP 맵 (lightsail-nixos-derp 서버) ==
    environment.etc."headscale/derp-custom.yaml".text = ''
      regions:
        900:
          regionid: 900
          regioncode: kr-lightsail
          regionname: Korea (Lightsail)
          nodes:
            - name: 900a
              regionid: 900
              hostname: ${derpDomain}
              stunport: 3478
              derpport: 443
    '';

    # == litestream → S3 (headscale DB 실시간 백업) ==
    # IAM Instance Profile 자격증명 자동 사용 — 별도 키 불필요
    systemd.services.litestream = {
      description = "Litestream SQLite replication";
      wantedBy    = ["multi-user.target"];
      after       = ["network-online.target"];
      wants       = ["network-online.target"];
      before      = ["headscale.service"];
      serviceConfig = {
        ExecStart = "${pkgs.litestream}/bin/litestream replicate " +
          "-config ${pkgs.writeText "litestream.yaml" ''
            dbs:
              - path: /var/lib/headscale/db.sqlite
                replicas:
                  - url: s3://${s3BackupBucket}/headscale/db
                    region: ap-northeast-2
          ''}";
        Restart     = "on-failure";
        User        = "headscale";
        StateDirectory = "headscale";
      };
    };
    systemd.services.headscale = {
      after    = ["litestream.service"];
      requires = ["litestream.service"];
    };

    # == EC2 네트워크 설정 ==
    # IMDS 라우트는 DHCP가 자동 처리 — 별도 설정 불필요
    networking.nameservers = ["1.1.1.1" "8.8.8.8"];
    services.resolved.extraConfig = "Cache=no-negative";

    # EC2 보안그룹이 외부 트래픽 제어 — NixOS 방화벽 비활성화
    networking.firewall.enable = false;

    # == SSM Session Manager (Instance Profile 자동 인증) ==
    services.amazon-ssm-agent.enable = true;

    # == Caddy 리버스 프록시 ==
    mods.sys.services.caddy = {
      configText = ''
        ${headscaleDomain} {
          reverse_proxy /web* localhost:80
          reverse_proxy * localhost:8080
        }
      '';
      reloadUser = "ec2-user";
    };

    systemd.tmpfiles.rules = ["d /opt/landings 0755 ec2-user users -"];
  };
  hm = {};
})
