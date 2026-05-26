{mkMod, ...}:
mkMod __curPos "Tailscale Mesh VPN" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  options = {
    preauthUser = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "headscale user/namespace (preauth key 파일 경로: /var/lib/nix-secrets/tailscale/<user>/<name>.preauth-key)";
    };
    preauthName = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "preauth key 식별자 (파일명)";
    };
    preauthLoginServer = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "headscale 서버 URL (비어있으면 공식 Tailscale 사용)";
    };
    advertiseExitNode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "exit node로 광고할지 여부";
    };
    advertiseRoutes = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = "광고할 서브넷 라우트 목록 (예: [\"192.168.11.0/24\"])";
    };
  };
  os = lib.mkMerge [
    {
      services.tailscale.enable = true;
      services.tailscale.extraSetFlags = ["--operator=${config.workspace.username}"];
      # nixos-fw의 기본 정책이 drop이라 tailscale0 인터페이스에서 오는
      # 트래픽도 차단됨 → 노드 간 접근이 안 되므로 trusted로 지정
      networking.firewall.trustedInterfaces = ["tailscale0"];
      networking.nftables.enable = true;
      # (목적: Tailscale WireGuard 캡슐화로 인한 MTU 축소 대응)
      networking.nftables.tables.tailscale-mss = {
        family = "inet";
        content = ''
          chain forward {
            type filter hook forward priority mangle;
            oifname "tailscale0" tcp flags syn tcp option maxseg size set rt mtu
            iifname "tailscale0" tcp flags syn tcp option maxseg size set rt mtu
          }
          chain output {
            type filter hook output priority mangle;
            oifname "tailscale0" tcp flags syn tcp option maxseg size set rt mtu
          }
        '';
      };
      # (목적: 물리 인터페이스 MTU를 1400으로 낮춰 Tailscale WireGuard 오버헤드 수용)
      systemd.network.links."10-tailscale-mtu" = {
        matchConfig.OriginalName = "en* eth* wl*";
        linkConfig.MTUBytes = "1400";
      };
    }
    # preauth key 파일로 자동 인증하는 oneshot 서비스
    (lib.mkIf (cfg.preauthUser != null && cfg.preauthName != null) (let
      keyFile = "/var/lib/nix-secrets/tailscale/${cfg.preauthUser}/${cfg.preauthName}.preauth-key";
    in {
      systemd.services.tailscale-autoauth = {
        description = "Tailscale automatic authentication via preauth key";
        after = ["tailscaled.service" "network-online.target"];
        wants = ["network-online.target"];
        requires = ["tailscaled.service"];
        wantedBy = ["multi-user.target"];
        path = [pkgs.tailscale];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
        script = ''
          if tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
            exit 0
          fi
          if [[ ! -f "${keyFile}" ]]; then
            exit 0
          fi
          tailscale up \
            --authkey="$(cat "${keyFile}")" \
            ${lib.optionalString (cfg.preauthLoginServer != "") ''--login-server="${cfg.preauthLoginServer}"''} \
            --accept-routes \
            ${lib.optionalString cfg.advertiseExitNode "--advertise-exit-node"} \
            ${lib.optionalString (cfg.advertiseRoutes != []) "--advertise-routes=${lib.concatStringsSep "," cfg.advertiseRoutes}"} \
            --reset
        '';
      };
    }))
  ];
  # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
  hm = lib.mkIf (cfg.enable && config.mods.gui.enable) {
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
    ];
  };
})
