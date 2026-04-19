{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services."nix-cache-proxy";
  cacheDir = "/var/cache/nginx/nix-cache";

  # 서버면 localhost, 클라이언트면 workspace 주소, 둘 다 아니면 빈 문자열
  proxyUrl =
    if cfg.enable
    then "http://127.0.0.1:${toString cfg.port}"
    else if config.workspace.nixCacheAddr != ""
    then "http://${config.workspace.nixCacheAddr}"
    else "";
  hasProxy = proxyUrl != "";
in {
  options.mods.sys.services."nix-cache-proxy" = {
    enable = mkEnableOption "Nix binary cache proxy (caches cache.nixos.org)";

    port = mkOption {
      type = types.port;
      default = 7070;
      description = "Port for nginx to listen on";
    };

    maxSize = mkOption {
      type = types.str;
      default = "30g";
      description = "Maximum cache size (e.g. \"30g\", \"50g\")";
    };

    inactiveDays = mkOption {
      type = types.int;
      default = 90;
      description = "Cache expiry in days since last access";
    };
  };

  config =
    if isNixOS
    then
      mkMerge [
        # == 서버 모드: nginx 캐싱 프록시 실행 ==
        (mkIf cfg.enable {
          services.nginx = {
            enable = true;
            # (목적: proxy_cache_path는 http 블록에만 선언 가능)
            appendHttpConfig = ''
              proxy_cache_path ${cacheDir}
                levels=1:2
                keys_zone=nix_cache:64m
                max_size=${cfg.maxSize}
                inactive=${toString cfg.inactiveDays}d
                use_temp_path=off;
            '';
            virtualHosts."nix-cache-proxy" = {
              listen = [
                {
                  addr = "0.0.0.0";
                  inherit (cfg) port;
                }
              ];
              extraConfig = ''
                # (목적: 대용량 .nar 파일 수신 타임아웃 방지)
                proxy_read_timeout 600s;
                proxy_connect_timeout 30s;

                location / {
                  proxy_pass https://cache.nixos.org;
                  proxy_ssl_server_name on;
                  proxy_set_header Host cache.nixos.org;
                  # (목적: upstream 압축 해제 요청 방지 — 프록시가 중간에서 재압축하면 캐시 무효)
                  proxy_set_header Accept-Encoding "";

                  proxy_cache nix_cache;
                  # (목적: .nar/.narinfo는 content-addressed이므로 장기 캐싱 안전)
                  proxy_cache_valid 200 ${toString cfg.inactiveDays}d;
                  proxy_cache_valid 404 1m;
                  proxy_cache_use_stale error timeout updating;
                  # (목적: 동일 파일 동시 요청 시 upstream에 하나만 전달)
                  proxy_cache_lock on;
                  proxy_cache_lock_timeout 300s;
                  # (목적: upstream의 Cache-Control 헤더 무시하고 캐싱 강제)
                  proxy_ignore_headers Cache-Control Expires;

                  # (목적: 대용량 .nar 파일 디스크 버퍼링 — 메모리 부족 방지)
                  proxy_buffering on;
                  proxy_buffer_size 16k;
                  proxy_buffers 8 64k;
                  proxy_busy_buffers_size 128k;
                  proxy_max_temp_file_size 0;

                  add_header X-Cache-Status $upstream_cache_status;
                }
              '';
            };
          };

          # (목적: 캐시 디렉토리를 nginx 사용자 소유로 사전 생성)
          systemd.tmpfiles.rules = [
            "d ${cacheDir} 0750 nginx nginx -"
          ];

          # (목적: 로컬 네트워크 다른 호스트도 프록시 접근 가능)
          networking.firewall.allowedTCPPorts = [cfg.port];
        })

        # == substituter 설정: 서버=localhost, 클라이언트=원격주소 ==
        (mkIf hasProxy {
          nix.settings = {
            substituters = mkBefore [proxyUrl];
            trusted-substituters = [proxyUrl];
          };
        })
      ]
    else {};
}
