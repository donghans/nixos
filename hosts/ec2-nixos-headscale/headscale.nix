{
  pkgs,
  lib,
  ...
}: let
  headscaleDomain = "e.772610158.xyz";
  oidcClientSecretFile = "/var/lib/nix-secrets/headscale/oidc_client_secret";
  s3BackupBucket = "headscale-backup-732799293614-ap-northeast-2-an";

  # exit node 활성화 시 tailscale이 DERP relay IP(/32)를 exclusion route로 추가할 때
  # built-in DERP server(region 900)는 paths를 override해서 IPv4를 주입할 수 없음
  # → 같은 엔드포인트를 별도 region(901)으로 추가해 static IPv4를 DERP map에 노출
  derpStaticIpv4Json = pkgs.writeText "derp-static-ipv4.json" (builtins.toJSON {
    Regions."901" = {
      RegionID = 901;
      RegionCode = "kr-ec2-ip";
      RegionName = "Korea (EC2) IP";
      Nodes = [
        {
          Name = "901a";
          RegionID = 901;
          HostName = headscaleDomain;
          IPv4 = "52.79.193.53";
          DERPPort = 443;
          STUNPort = 3478;
          STUNOnly = false;
        }
      ];
    };
  });

  headscaleConfigFile = (pkgs.formats.yaml {}).generate "headscale.yaml" {
    disable_check_updates = true;
    unix_socket = "/run/headscale/headscale.sock";
    unix_socket_permission = "0660";
    server_url = "https://${headscaleDomain}";
    listen_addr = "0.0.0.0:8080"; # Lightsail VPC 백본에서 포워딩 받음
    grpc_listen_addr = "127.0.0.1:50443";
    metrics_listen_addr = "127.0.0.1:9090";
    log.level = "info";
    noise.private_key_path = "/var/lib/headscale/noise_private.key";
    derp.server.private_key_path = "/var/lib/headscale/derp_server_private.key";
    prefixes = {
      v4 = "100.64.0.0/10";
      allocation = "sequential";
    };
    database = {
      type = "sqlite3";
      sqlite.path = "/var/lib/headscale/db.sqlite";
    };
    derp = {
      server = {
        enabled = true;
        # Caddy(Lightsail $5) → EC2:8080으로 프록시됨
        # STUN: 리슨만 함, EC2 공인 IP 없어 외부 접근 불가 (Tailscale 기본 STUN 사용)
        region_id = 900;
        region_code = "kr-ec2";
        region_name = "Korea (EC2)";
        stun_listen_addr = "0.0.0.0:3478";
      };
      urls = ["https://controlplane.tailscale.com/derpmap/default"];
      paths = ["${derpStaticIpv4Json}"];
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
  # == headscale ==
  # settings는 headscaleConfigFile로 직접 관리 (v6 prefix 제거 목적)
  # enable = true: user/group/socket/StateDirectory 등 모듈 인프라만 활용
  services.headscale = {
    enable = true;
    settings.dns = {
      magic_dns = true;
      base_domain = "i.772610158.xyz";
    };
  };
  systemd.services.headscale.script = lib.mkForce ''
    exec ${pkgs.headscale}/bin/headscale serve --config ${headscaleConfigFile}
  '';
  users.users.ec2-user.extraGroups = ["headscale"];

  # inject_secrets가 root:root 600으로 생성하므로 매 활성화 시 소유자 교정
  systemd.tmpfiles.rules = [
    "z ${oidcClientSecretFile} 0640 headscale headscale -"
  ];

  # headscale 내장 DERP(server.enabled=true) + static IPv4 명시 (derp.paths로 region 900 override)

  # == litestream → S3 (headscale DB 실시간 백업) ==
  # IAM Instance Profile 자격증명 자동 사용 — 별도 키 불필요
  systemd.services.litestream = {
    description = "Litestream SQLite replication";
    wantedBy = ["multi-user.target"];
    after = ["network-online.target"];
    wants = ["network-online.target"];
    before = ["headscale.service"];
    serviceConfig = {
      ExecStart =
        "${pkgs.litestream}/bin/litestream replicate "
        + "-config ${pkgs.writeText "litestream.yaml" ''
          dbs:
            - path: /var/lib/headscale/db.sqlite
              replicas:
                - url: s3://${s3BackupBucket}/headscale/db
                  region: ap-northeast-2
        ''}";
      Restart = "on-failure";
      User = "headscale";
      StateDirectory = "headscale";
    };
  };
  systemd.services.headscale = {
    after = ["litestream.service"];
    requires = ["litestream.service"];
  };
}
