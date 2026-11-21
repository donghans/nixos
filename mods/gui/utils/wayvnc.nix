# Tailscale 전용 VNC 원격 데스크톱 (wayvnc).
#
# 인증 없이 이 호스트의 tailnet(tailscale0) 주소에만 바인딩한다. 예전에는 0.0.0.0 에 바인딩하고
# 방화벽(tailscale0 만 신뢰)에 통제를 맡겼으나, incusbr0 등 다른 신뢰 인터페이스의 게스트도 5900 에
# 접속되는 것이 확인되어(2026-11-21) 바인딩 주소 자체를 제한했다. enable_auth=true로 바꾸려면
# certificate_file/private_key_file/username/password를 추가로 채워야 함(현재는 tailnet 신뢰 경계만으로
# 충분하다고 판단).
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "wayvnc (Tailscale 전용 VNC 원격 데스크톱)" ({
  cfg,
  pkgs,
  lib,
  ...
}: {
  options = {
    port = lib.mkOption {
      type = lib.types.port;
      default = 5900;
      description = "wayvnc가 바인딩할 TCP 포트";
    };
  };
  hm = let
    # tailnet 주소에만 바인딩한다(0.0.0.0 이면 incusbr0 같은 신뢰 인터페이스의 게스트도 인증 없는 VNC 에 닿는다 —
    # 2026-11-21 incus 컨테이너·VM 경계 시험, `note/dev-sandbox-evidence`). 주소는 호스트마다 다르고 부팅 직후엔
    # 없을 수 있어서 시작할 때 읽는다. 못 얻으면 실패 종료하고 uwsm 의 Restart=on-failure 가 다시 시도한다.
    wayvncTailnet = pkgs.writeShellScript "wayvnc-tailnet" ''
      ip=""
      for _ in $(seq 1 30); do
        ip=$(/run/current-system/sw/bin/tailscale ip -4 2>/dev/null | head -n 1)
        [ -n "$ip" ] && break
        sleep 2
      done
      if [ -z "$ip" ]; then
        echo "wayvnc-tailnet: tailscale IPv4 주소를 얻지 못해 시작하지 않는다(0.0.0.0 으로 열지 않음)" >&2
        exit 1
      fi
      cfg="''${XDG_RUNTIME_DIR:-/tmp}/wayvnc-tailnet.conf"
      printf 'address=%s\nport=%s\nenable_auth=false\n' "$ip" ${toString cfg.port} > "$cfg"
      exec ${pkgs.wayvnc}/bin/wayvnc -r --config="$cfg"
    '';
  in {
    home.packages = [pkgs.wayvnc];

    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -t service -p Restart=on-failure -p RestartSec=2 -- ${wayvncTailnet}"
    ];
  };
})
