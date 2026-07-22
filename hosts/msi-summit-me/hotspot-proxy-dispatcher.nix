# 휴대폰 핫스팟에 붙었을 때(클라이언트 wifi 연결) 게이트웨이(휴대폰)가 열어둔
# SOCKS5 프록시 주소를 /tmp/current_hotspot_proxy 에 기록하고,
#   1) 사용자의 systemd --user 세션 환경변수(http_proxy 등)에 반영 — curl/git 등
#      프록시 환경변수를 지원하는 CLI 도구가 새로 실행될 때 적용
#   2) redsocks + nftables로 로그인 유저(uid) 명의의 아웃바운드 TCP를 전부
#      투명 프록시로 리다이렉트 — 환경변수를 안 읽는 프로그램(Claude Code 등)도 포함
# wifi 연결이 끊기면 전부 원상복구.
#
# (이유) 핫스팟 SSID/UUID가 고정돼있지 않아 이름으로는 판별 불가.
#   대신 wifi 연결이 뜰 때마다 게이트웨이의 1080 포트가 실제로 열려있는지
#   TCP 연결을 시도해보고, 응답이 있을 때만 기록 — 프록시가 안 켜진 wifi에서는 no-op.
#
# 한계:
#   - UDP는 대상 SOCKS5 서버(휴대폰 프록시 앱)가 UDP ASSOCIATE를 구현해야 하는데
#     보통 안 됨 + redsocks도 TCP만 리다이렉트 — DNS(UDP 53)·QUIC(HTTP/3)·화상회의는
#     이 프록시를 안 타고 그대로 나간다.
#   - nft 리다이렉트는 `meta skuid`로 로그인 유저(uid 1000)의 트래픽만 잡는다 —
#     root로 도는 시스템 서비스(sshd 등)는 건드리지 않아 안전.
#   - NetworkManager dispatcher는 root로 실행되므로 systemctl --user는 runuser로
#     대상 유저 세션에 진입해 XDG_RUNTIME_DIR을 맞춰줘야 한다. 이미 실행 중인
#     프로세스는 nft 리다이렉트는 즉시 적용되지만(커널 레벨), 환경변수 쪽은 새로
#     실행되는 프로세스부터 적용된다.
{
  pkgs,
  config,
  ...
}: let
  redsocksPort = 12345;
  nftTable = "redsocks_hotspot";
  redsocksConf = "/run/redsocks-hotspot.conf";
  # 리다이렉트 대상에서 빼야 하는(직접 나가야 하는) 사설/특수 대역 — 여기 안 걸리면
  # 로컬 서비스·incus/docker 브리지·tailscale(CGNAT)까지 전부 프록시로 새서 끊긴다.
  privateRanges = "0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4";
in {
  systemd.services.redsocks-hotspot = {
    description = "휴대폰 핫스팟 SOCKS5 프록시용 redsocks 로컬 TCP 투명 프록시";
    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.redsocks}/bin/redsocks -c ${redsocksConf}";
      Restart = "on-failure";
    };
    # multi-user.target에 안 걸어둠 — dispatcher가 프록시 감지 시에만 직접 start/stop.
  };

  networking.networkmanager.dispatcherScripts = [
    {
      type = "basic";
      source = pkgs.writeShellScript "hotspot-proxy-dispatcher" ''
        INTERFACE=$1
        ACTION=$2
        USERNAME="${config.workspace.username}"
        NFT=${pkgs.nftables}/bin/nft

        TYPE=$(${pkgs.networkmanager}/bin/nmcli -t -g connection.type connection show "$CONNECTION_UUID" 2>/dev/null)
        [ "$TYPE" = "802-11-wireless" ] || exit 0

        USER_UID=$(${pkgs.coreutils}/bin/id -u "$USERNAME")
        set_user_env() {
          ${pkgs.util-linux}/bin/runuser -u "$USERNAME" -- ${pkgs.bash}/bin/bash -c \
            "XDG_RUNTIME_DIR=/run/user/$USER_UID ${pkgs.systemd}/bin/systemctl --user $*"
        }

        teardown_redirect() {
          $NFT delete table ip ${nftTable} 2>/dev/null
          ${pkgs.systemd}/bin/systemctl stop redsocks-hotspot.service 2>/dev/null
          rm -f ${redsocksConf}
        }

        case "$ACTION" in
          up)
            GW_IP=$(${pkgs.iproute2}/bin/ip route | ${pkgs.gawk}/bin/awk '/default/ {print $3; exit}')
            [ -n "$GW_IP" ] || exit 0
            if ${pkgs.coreutils}/bin/timeout 1 ${pkgs.bash}/bin/bash -c "echo > /dev/tcp/$GW_IP/1080" 2>/dev/null; then
              echo "socks5 $GW_IP 1080" > /tmp/current_hotspot_proxy
              PROXY_URL="socks5h://$GW_IP:1080"
              set_user_env set-environment \
                "http_proxy=$PROXY_URL" "https_proxy=$PROXY_URL" "all_proxy=$PROXY_URL" \
                "HTTP_PROXY=$PROXY_URL" "HTTPS_PROXY=$PROXY_URL" "ALL_PROXY=$PROXY_URL" \
                "no_proxy=localhost,127.0.0.1,::1" "NO_PROXY=localhost,127.0.0.1,::1"

              cat > ${redsocksConf} <<EOF
        base {
            log_debug = off;
            log_info = off;
            daemon = off;
            redirector = iptables;
        }
        redsocks {
            local_ip = 127.0.0.1;
            local_port = ${toString redsocksPort};
            ip = $GW_IP;
            port = 1080;
            type = socks5;
        }
        EOF
              ${pkgs.systemd}/bin/systemctl restart redsocks-hotspot.service

              $NFT add table ip ${nftTable} 2>/dev/null
              $NFT -- add chain ip ${nftTable} output '{ type nat hook output priority -100 ; }' 2>/dev/null
              $NFT flush chain ip ${nftTable} output
              $NFT add rule ip ${nftTable} output ip daddr '{ ${privateRanges} }' return
              $NFT add rule ip ${nftTable} output meta skuid "$USER_UID" tcp dport != ${toString redsocksPort} redirect to :${toString redsocksPort}
            fi
            ;;
          down)
            rm -f /tmp/current_hotspot_proxy
            set_user_env unset-environment \
              http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY no_proxy NO_PROXY
            teardown_redirect
            ;;
        esac
      '';
    }
  ];
}
