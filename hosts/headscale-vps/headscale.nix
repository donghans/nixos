{
  config,
  pkgs,
  lib,
  ...
}: let
  headscaleDomain = config.headscale.domain;
  oidcClientSecretFile = "/var/lib/nix-secrets/headscale/oidc_client_secret";

  headscaleConfigFile = (pkgs.formats.yaml {}).generate "headscale.yaml" {
    disable_check_updates = true;
    unix_socket = "/run/headscale/headscale.sock";
    unix_socket_permission = "0660";
    server_url = "https://${headscaleDomain}";
    listen_addr = "127.0.0.1:8080"; # nginx가 localhost로 프록시
    grpc_listen_addr = "127.0.0.1:50443";
    metrics_listen_addr = "127.0.0.1:9090";
    log.level = "info";
    noise.private_key_path = "/var/lib/headscale/noise_private.key";
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
        region_id = 900;
        region_code = "kr-vps";
        region_name = "Korea (VPS)";
        stun_listen_addr = "0.0.0.0:3478";
        private_key_path = "/var/lib/headscale/derp_server_private.key";
        # exit node 클라이언트가 DERP relay IP를 exclusion route로 추가할 수 있도록 공인 IPv4 노출
        ipv4 = config.headscale.staticIpv4;
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
  options.headscale = {
    domain = lib.mkOption {
      type = lib.types.str;
      description = "headscale 컨트롤 플레인 도메인";
    };
    staticIpv4 = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "embedded DERP server(region 900)에 노출할 공인 IPv4 (exit node 클라이언트 exclusion route용)";
    };
  };

  config = {
    services.headscale = {
      enable = true;
      # NixOS 모듈 assertion 통과용 (magic_dns=true 기본값 → base_domain 필수)
      # 실제 런타임 설정은 위의 headscaleConfigFile이 담당 (lib.mkForce로 덮어씀)
      settings.dns = {
        magic_dns = true;
        base_domain = "i.772610158.xyz";
      };
    };
    systemd.services.headscale.script = lib.mkForce ''
      exec ${pkgs.headscale}/bin/headscale serve --config ${headscaleConfigFile}
    '';
    users.users.admin.extraGroups = ["headscale"];

    systemd.tmpfiles.rules = [
      "z ${oidcClientSecretFile} 0640 headscale headscale -"
      # inject_secrets가 root:root로 전송하므로 매 활성화 시 소유자 교정
      "z /var/lib/headscale/noise_private.key 0600 headscale headscale -"
      "z /var/lib/headscale/derp_server_private.key 0600 headscale headscale -"
    ];
  };
}
