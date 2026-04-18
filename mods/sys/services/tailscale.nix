{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.tailscale;
in {
  options.mods.sys.services.tailscale.enable = mkEnableOption "Tailscale Mesh VPN";
  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.tailscale.enable = true;
      # nixos-fw의 기본 정책이 drop이라 tailscale0 인터페이스에서 오는
      # 트래픽도 차단됨 → 노드 간 접근이 안 되므로 trusted로 지정
      networking.firewall.trustedInterfaces = ["tailscale0"];
      networking.nftables.enable = true;
      # (목적: Tailscale WireGuard 캡슐화로 인한 MTU 축소 대응)
      # WireGuard는 패킷당 ~60 바이트 오버헤드를 추가하므로,
      # tailscale0 경유 TCP 연결의 MSS를 경로 MTU에 맞게 클램프.
      # - forward: VM/컨테이너 등 포워드 트래픽 (incusbr0 → tailscale0)
      # - output: 호스트 자신이 개시하는 TCP 연결 (git clone, SSH 등)
      # 이 규칙이 없으면 TLS ClientHello 같은 큰 패킷이 드롭되어
      # 연결이 무한히 대기 상태가 됨.
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
      # WireGuard 캡슐화 오버헤드(~60 바이트)가 더해져도 업스트림 MTU(1500)를 초과하지 않도록
      # 물리 인터페이스 MTU를 미리 줄여둠. → 대용량 패킷 유실(TLS 타임아웃 등) 방지
      # .link 파일은 udev가 인터페이스 초기화 시 적용하므로
      # NetworkManager·systemd-networkd 모두에서 동작함.
      # en*/eth*: 유선 이더넷, wl*: 무선랜 (veth·bridge·tailscale0 등 가상 인터페이스는 미매칭)
      systemd.network.links."10-tailscale-mtu" = {
        matchConfig.OriginalName = "en* eth* wl*";
        linkConfig.MTUBytes = "1400";
      };
    }
    else
      mkIf config.mods.gui.enable {
        # HM 사이드: GUI 활성화 시 Tailscale 시스템 트레이 실행
        wayland.windowManager.hyprland.settings.exec-once = mkOrder 500 [
          "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
        ];
      }
  );
}
