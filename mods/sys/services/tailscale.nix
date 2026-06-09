{mkMod, ...}:
mkMod __curPos "Tailscale Mesh VPN" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  options = {
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
    acceptRoutes = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "다른 노드가 광고한 서브넷 라우트를 수락할지 여부 (--accept-routes)";
    };
    stateFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "nix-secrets로 주입된 tailscale state 파일 경로. 존재 시 /var/lib/tailscale/tailscaled.state가 없을 때 복사해 재인증 없이 자동 연결";
    };
  };
  os = lib.mkMerge [
    (lib.mkIf (cfg.enable && cfg.stateFile != null) {
      systemd.services.tailscale-restore-state = {
        description = "Restore tailscale state from nix-secrets";
        before = ["tailscaled.service"];
        wantedBy = ["tailscaled.service"];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
        script = ''
          if [ ! -f /var/lib/tailscale/tailscaled.state ] && [ -f "${cfg.stateFile}" ]; then
            mkdir -p /var/lib/tailscale
            cp "${cfg.stateFile}" /var/lib/tailscale/tailscaled.state
            chmod 600 /var/lib/tailscale/tailscaled.state
            chown root:root /var/lib/tailscale/tailscaled.state
          fi
        '';
      };
    })
    (lib.mkIf cfg.enable {
      services.tailscale.enable = true;
      services.tailscale.extraSetFlags = ["--operator=${config.workspace.username}"]
        ++ lib.optionals cfg.acceptRoutes ["--accept-routes"];
      # exit node 클라이언트로 동작 시 exit node에서 돌아오는 패킷(src=1.1.1.1 등)이
      # tailscale0으로 들어오는데, 기본 strict rpfilter가 이를 drop함
      # → loose로 변경해 출구 인터페이스 일치 여부 검사 없이 라우트 존재 여부만 확인
      # (서버 역할 호스트는 useRoutingFeatures = "server"로 덮어쓰면 됨)
      services.tailscale.useRoutingFeatures = lib.mkDefault "client";
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
    })
  ];
  # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
  hm = lib.mkIf (cfg.enable && config.mods.gui.enable) {
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
    ];
  };
})
