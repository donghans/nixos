{
  lib,
  pkgs,
  config,
  ...
}: let
  cfg = config.headscale;

  headscaleConfigFile = (pkgs.formats.yaml {}).generate "headscale.yaml" (
    {
      disable_check_updates = cfg.disableCheckUpdates;
      unix_socket = cfg.unixSocket;
      unix_socket_permission = cfg.unixSocketPermission;
      server_url = "https://${cfg.domain}";
      listen_addr = cfg.listenAddr;
      grpc_listen_addr = cfg.grpcListenAddr;
      metrics_listen_addr = cfg.metricsListenAddr;
      log.level = cfg.logLevel;
      noise.private_key_path = cfg.noisePrivateKeyPath;
      prefixes =
        {
          v4 = cfg.prefixesV4;
          inherit (cfg) allocation;
        }
        // lib.optionalAttrs (cfg.prefixesV6 != null) {
          v6 = cfg.prefixesV6;
        };
      database =
        {
          type = "sqlite3";
          sqlite =
            {
              path = cfg.sqlitePath;
            }
            // lib.optionalAttrs cfg.sqliteWriteAheadLog {
              write_ahead_log = cfg.sqliteWriteAheadLog;
            }
            // lib.optionalAttrs (cfg.sqliteWalAutocheckpoint != null) {
              wal_autocheckpoint = cfg.sqliteWalAutocheckpoint;
            };
        }
        // lib.optionalAttrs (cfg.gormPrepareStmt || cfg.gormParameterizedQueries || cfg.gormSkipErrRecordNotFound || cfg.gormSlowThreshold != null) {
          gorm =
            {}
            // lib.optionalAttrs cfg.gormPrepareStmt {prepare_stmt = cfg.gormPrepareStmt;}
            // lib.optionalAttrs cfg.gormParameterizedQueries {parameterized_queries = cfg.gormParameterizedQueries;}
            // lib.optionalAttrs cfg.gormSkipErrRecordNotFound {skip_err_record_not_found = cfg.gormSkipErrRecordNotFound;}
            // lib.optionalAttrs (cfg.gormSlowThreshold != null) {slow_threshold = cfg.gormSlowThreshold;};
        };
      derp = {
        server = {
          enabled = cfg.enableDerp;
          region_id = cfg.derpRegionId;
          region_code = cfg.derpRegionCode;
          region_name = cfg.derpRegionName;
          stun_listen_addr = "0.0.0.0:3478";
          private_key_path = "/var/lib/headscale/derp_server_private.key";
          automatically_add_embedded_derp_region = true;
          ipv4 = cfg.staticIpv4;
        };
        urls = ["https://controlplane.tailscale.com/derpmap/default"];
        paths = [];
        auto_update_enabled = true;
        update_frequency = "3h";
      };
      dns = {
        magic_dns = true;
        base_domain = cfg.baseDomain;
        override_local_dns = true;
        nameservers.global = [
          "1.1.1.1"
          "1.0.0.1"
          "2606:4700:4700::1111"
          "2606:4700:4700::1001"
        ];
        extra_records = cfg.extraRecords;
      };
      taildrop.enabled = true;
    }
    // (lib.optionalAttrs (cfg.oidc != null) {inherit (cfg) oidc;})
  );
in {
  options.headscale = {
    domain = lib.mkOption {
      type = lib.types.str;
      description = "headscale domain";
    };
    baseDomain = lib.mkOption {
      type = lib.types.str;
      description = "headscale base domain for magic DNS";
    };
    staticIpv4 = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "public IP for stun/derp";
    };
    enableDerp = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "whether to enable embedded DERP server";
    };
    derpRegionId = lib.mkOption {
      type = lib.types.int;
      default = 999;
      description = "embedded DERP region ID";
    };
    derpRegionCode = lib.mkOption {
      type = lib.types.str;
      default = "headscale";
      description = "embedded DERP region code";
    };
    derpRegionName = lib.mkOption {
      type = lib.types.str;
      default = "Headscale Embedded DERP";
      description = "embedded DERP region name";
    };
    extraRecords = lib.mkOption {
      type = lib.types.listOf lib.types.attrs;
      default = [];
      description = "Extra DNS A/AAAA records for MagicDNS";
    };
    oidc = lib.mkOption {
      type = lib.types.nullOr lib.types.attrs;
      default = null;
      description = "optional oidc configuration";
    };
    disableCheckUpdates = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "disable check updates";
    };
    unixSocket = lib.mkOption {
      type = lib.types.str;
      default = "/run/headscale/headscale.sock";
      description = "unix socket path";
    };
    unixSocketPermission = lib.mkOption {
      type = lib.types.str;
      default = "0660";
      description = "unix socket permission";
    };
    listenAddr = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:8080";
      description = "listen address";
    };
    grpcListenAddr = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:50443";
      description = "grpc listen address";
    };
    metricsListenAddr = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:9090";
      description = "metrics listen address";
    };
    logLevel = lib.mkOption {
      type = lib.types.str;
      default = "info";
      description = "log level";
    };
    noisePrivateKeyPath = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/headscale/noise_private.key";
      description = "noise private key path";
    };
    prefixesV4 = lib.mkOption {
      type = lib.types.str;
      default = "100.64.0.0/10";
      description = "ipv4 prefix";
    };
    prefixesV6 = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "ipv6 prefix";
    };
    allocation = lib.mkOption {
      type = lib.types.str;
      default = "sequential";
      description = "ip allocation method";
    };
    sqlitePath = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/headscale/db.sqlite";
      description = "sqlite path";
    };
    sqliteWriteAheadLog = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "sqlite write ahead log";
    };
    sqliteWalAutocheckpoint = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "sqlite wal autocheckpoint";
    };
    gormPrepareStmt = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "gorm prepare statement";
    };
    gormParameterizedQueries = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "gorm parameterized queries";
    };
    gormSkipErrRecordNotFound = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "gorm skip error record not found";
    };
    gormSlowThreshold = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "gorm slow threshold";
    };
  };

  config = {
    services.headscale = {
      enable = true;
      settings.dns = {
        magic_dns = true;
        base_domain = cfg.baseDomain;
        nameservers = {
          global = ["1.1.1.1"];
        };
      };
    };

    systemd.services.headscale.script = lib.mkForce ''
      exec ${pkgs.headscale}/bin/headscale serve --config ${headscaleConfigFile}
    '';

    systemd.tmpfiles.rules =
      [
        "z /var/lib/headscale/noise_private.key 0600 headscale headscale -"
      ]
      ++ lib.optionals cfg.enableDerp [
        "z /var/lib/headscale/derp_server_private.key 0600 headscale headscale -"
      ]
      ++ lib.optionals (cfg.oidc != null) [
        "z ${cfg.oidc.client_secret_path} 0640 headscale headscale -"
      ];
  };
}
