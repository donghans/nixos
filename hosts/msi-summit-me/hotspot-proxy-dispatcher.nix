# 휴대폰 핫스팟에 붙었을 때(클라이언트 wifi 연결) 게이트웨이(휴대폰)가 열어둔
# SOCKS5 프록시 주소를 /tmp/current_hotspot_proxy 에 기록/삭제.
#
# (이유) 핫스팟 SSID/UUID가 고정돼있지 않아 이름으로는 판별 불가.
#   대신 wifi 연결이 뜰 때마다 게이트웨이의 1080 포트가 실제로 열려있는지
#   TCP 연결을 시도해보고, 응답이 있을 때만 기록 — 프록시가 안 켜진 wifi에서는 no-op.
{pkgs, ...}: {
  networking.networkmanager.dispatcherScripts = [
    {
      type = "basic";
      source = pkgs.writeShellScript "hotspot-proxy-dispatcher" ''
        INTERFACE=$1
        ACTION=$2

        TYPE=$(${pkgs.networkmanager}/bin/nmcli -t -g connection.type connection show "$CONNECTION_UUID" 2>/dev/null)
        [ "$TYPE" = "802-11-wireless" ] || exit 0

        case "$ACTION" in
          up)
            GW_IP=$(${pkgs.iproute2}/bin/ip route | awk '/default/ {print $3; exit}')
            [ -n "$GW_IP" ] || exit 0
            if ${pkgs.coreutils}/bin/timeout 1 ${pkgs.bash}/bin/bash -c "echo > /dev/tcp/$GW_IP/1080" 2>/dev/null; then
              echo "socks5 $GW_IP 1080" > /tmp/current_hotspot_proxy
            fi
            ;;
          down)
            rm -f /tmp/current_hotspot_proxy
            ;;
        esac
      '';
    }
  ];
}
