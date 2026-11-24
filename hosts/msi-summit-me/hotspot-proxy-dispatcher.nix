# 휴대폰 핫스팟에 붙었을 때(클라이언트 wifi 연결) 게이트웨이(휴대폰)가 열어둔
# SOCKS5 프록시 주소를 /tmp/current_hotspot_proxy 에 기록하고,
#   1) 사용자의 systemd --user 세션 환경변수(http_proxy 등)에 반영 — curl/git 등
#      프록시 환경변수를 지원하는 CLI 도구가 새로 실행될 때 적용
#   2) redsocks + nftables로 로그인 유저(uid) 명의의 아웃바운드 TCP를 전부
#      투명 프록시로 리다이렉트 — 환경변수를 안 읽는 프로그램(Claude Code 등)도 포함
#   3) redsocks의 redudp(TPROXY) + nftables로 같은 유저의 아웃바운드 UDP도
#      SOCKS5 UDP ASSOCIATE로 릴레이 — DNS(53)·QUIC(HTTP/3) 포함
# wifi 연결이 끊기면 전부 원상복구.
#
# 킬 스위치(2026-11-24): 핫스팟 연결(이름 목록 또는 게이트웨이 1080 이 열린 wifi)에서는 sing-box 가 꺼져 있어도 규칙을 켜 둔다 — 프록시를 못 타면 연결이 거부될 뿐
# 폰의 일반 테더링 NAT 로 직접 나가지 않는다(테더링 한도 우회가 구조적으로 깨지지 않게). 자세한 근거: plan dev-sandbox-pilot §29-39.
#
# (이유) 핫스팟 SSID/UUID가 고정돼있지 않아 이름으로는 판별 불가.
#   대신 wifi 연결이 뜰 때마다 게이트웨이의 1080 포트가 실제로 열려있는지
#   TCP 연결을 시도해보고, 응답이 있을 때만 기록 — 프록시가 안 켜진 wifi에서는 no-op.
#
# UDP 리다이렉트가 TCP와 구조가 다른 이유:
#   REDIRECT(NAT)는 UDP 회신 시 원래 목적지 정보를 커널이 보존해주지 않아 redsocks가
#   목적지를 알 수 없다. 그래서 UDP는 TPROXY를 쓴다 — 로컬에서 나가는 패킷을
#   OUTPUT 체인에서 마킹 → `ip rule`로 lo로 재라우팅 → PREROUTING에서 TPROXY로
#   실제 캡처, 순서로 처리해야 한다(TPROXY 타겟 자체가 OUTPUT에서 동작하지 않음).
#   redudp가 IP_TRANSPARENT 소켓을 열려면 redsocks 프로세스에 CAP_NET_ADMIN이 필요.
#
# 한계:
#   - UDP 릴레이는 게이트웨이 SOCKS5 서버가 UDP ASSOCIATE를 구현해야 동작한다
#     (미구현 서버면 이 프록시를 안 타고 그대로 나간다 — TCP만 되던 예전과 동일).
#   - nft 리다이렉트는 로그인 유저(uid 1000)뿐 아니라 root(uid 0)도 잡는다.
#     (이유) tailscaled(root로 도는 시스템 서비스)가 헤드스케일 서버로 direct 접속을
#     시도하다 핫스팟 게이트웨이가 비-프록시 트래픽을 막아 "context deadline exceeded"로
#     로그인이 실패하는 문제 발견(2026-07-23) — root도 같이 리다이렉트해야 해결됨.
#     redsocks 프로세스 자신의 GW_IP:1080 상향 접속은 GW_IP가 보통 privateRanges(10/8,
#     192.168/16 등)에 속해 앞단 return 규칙에서 먼저 걸러지므로 리다이렉트 루프 없음.
#     (GW_IP가 privateRanges 밖의 공인 IP인 특이 케이스라면 루프 위험 있으니 확인 필요.)
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
  redudpPort = 10053;
  nftTable = "redsocks_hotspot";
  nftUdpTable = "redsocks_hotspot_udp";
  nftKillTable = "hotspot_killswitch";
  # 킬 스위치(2026-11-24): 이 이름의 wifi 연결(또는 게이트웨이 1080 이 열려 있는 wifi)에 붙어 있는 동안은 sing-box 가 꺼져 있어도 wlan0 로 나가는 것을
  # 「게이트웨이(폰)로 가는 연결·사설 대역」으로 제한한다 — 안 그러면 프록시를 안 탄 트래픽이 폰의 일반 테더링 NAT 로 나가 테더링 한도를 쓴다(통신사가 구분함).
  # sing-box 를 나중에 켜면 redsocks 가 연결마다 다시 시도하므로 따로 감지할 필요 없이 저절로 복구된다. 이름은 쉼표로 구분.
  hotspotConnections = "donghans-hotspot";
  # incus 브리지(sbox·dev VM)에서 호스트를 거쳐 나가는(forward) TCP 도 같은 프록시로 돌린다 — 호스트 자신의 OUTPUT 규칙만으로는 못 잡는다.
  sboxVmRange = "10.100.1.100-10.100.1.199";
  fwmark = "1";
  rtTable = "100";
  redsocksConf = "/run/redsocks-hotspot.conf";
  # 리다이렉트 대상에서 빼야 하는(직접 나가야 하는) 사설/특수 대역 — 여기 안 걸리면
  # 로컬 서비스·incus/docker 브리지·tailscale(CGNAT)까지 전부 프록시로 새서 끊긴다.
  privateRanges = "0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4";
in {
  # UDP TPROXY용 정책 라우팅(fwmark→lo)으로 들어온 패킷은 소스 주소 기준 rpfilter의
  # strict 역방향 경로 검사(`fib saddr . mark . iif oif exists`)를 통과 못 해 드롭된다.
  # ip route table ${rtTable}이 이 mark에 한해 모든 목적지를 local로 취급하므로,
  # 같은 조건(daddr . mark . iif type local)이면 예외적으로 허용.
  networking.firewall.extraReversePathFilterRules = ''
    meta mark ${fwmark} fib daddr . mark . iif type local accept
  '';

  systemd.services.redsocks-hotspot = {
    # (부팅 콘솔은 한글이 네모로 보이므로 영어: 휴대폰 핫스팟 SOCKS5 프록시용 redsocks 로컬 TCP/UDP 투명 프록시)
    description = "redsocks local TCP/UDP transparent proxy for the phone hotspot SOCKS5 proxy";
    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.redsocks}/bin/redsocks -c ${redsocksConf}";
      Restart = "on-failure";
      # redudp가 IP_TRANSPARENT로 바인드하려면 필요 (TPROXY UDP 릴레이).
      AmbientCapabilities = ["CAP_NET_ADMIN"];
      CapabilityBoundingSet = ["CAP_NET_ADMIN"];
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
        IP=${pkgs.iproute2}/bin/ip

        TYPE=$(${pkgs.networkmanager}/bin/nmcli -t -g connection.type connection show "$CONNECTION_UUID" 2>/dev/null)
        [ "$TYPE" = "802-11-wireless" ] || exit 0

        USER_UID=$(${pkgs.coreutils}/bin/id -u "$USERNAME")
        set_user_env() {
          ${pkgs.util-linux}/bin/runuser -u "$USERNAME" -- ${pkgs.bash}/bin/bash -c \
            "XDG_RUNTIME_DIR=/run/user/$USER_UID ${pkgs.systemd}/bin/systemctl --user $*"
        }

        teardown_redirect() {
          $NFT delete table ip ${nftTable} 2>/dev/null
          $NFT delete table inet ${nftUdpTable} 2>/dev/null
          $NFT delete table inet ${nftKillTable} 2>/dev/null
          $IP rule del fwmark ${fwmark} lookup ${rtTable} 2>/dev/null
          $IP route flush table ${rtTable} 2>/dev/null
          ${pkgs.systemd}/bin/systemctl stop redsocks-hotspot.service 2>/dev/null
          rm -f ${redsocksConf}
        }

        case "$ACTION" in
          up)
            GW_IP=$(${pkgs.iproute2}/bin/ip route | ${pkgs.gawk}/bin/awk '/default/ {print $3; exit}')
            [ -n "$GW_IP" ] || exit 0
            HOTSPOT=0
            case ",${hotspotConnections}," in *",$CONNECTION_ID,"*) HOTSPOT=1 ;; esac
            if ${pkgs.coreutils}/bin/timeout 1 ${pkgs.bash}/bin/bash -c "echo > /dev/tcp/$GW_IP/1080" 2>/dev/null; then HOTSPOT=1; fi
            [ "$HOTSPOT" = 1 ] || exit 0
            # 핫스팟 모드: sing-box(1080)가 꺼져 있어도 규칙은 켠다(킬 스위치) — 꺼져 있으면 연결이 거부되고 직접 나가지 않는다.
            echo "socks5 $GW_IP 1080" > /tmp/current_hotspot_proxy
            PROXY_URL="socks5h://$GW_IP:1080"
            set_user_env set-environment \
              "http_proxy=$PROXY_URL" "https_proxy=$PROXY_URL" "all_proxy=$PROXY_URL" \
              "HTTP_PROXY=$PROXY_URL" "HTTPS_PROXY=$PROXY_URL" "ALL_PROXY=$PROXY_URL" \
              "no_proxy=localhost,127.0.0.1,::1" "NO_PROXY=localhost,127.0.0.1,::1"

            # redsocks_conn_max 기본값 128 — Docker(여러 스택 동시 구동 시 컨테이너
            # 아웃바운드까지 전부 이걸 타므로) 트래픽으로 쉽게 소진돼 "reached
            # redsocks_conn_max limit"로 신규 연결이 백오프되다 DNS/TCP가 타임아웃되는
            # 현상 실측(2026-09-23). 주의: 이 heredoc은 redsocks.conf로 그대로 쓰이는데
            # redsocks 설정 파서는 '#' 주석을 지원하지 않아(2026-09-23 한 번 이걸로
            # "file parsing error ... unexpected char"로 서비스가 통째로 죽음) 여기
            # 안에는 절대 주석을 넣지 말 것 — 설명은 전부 nix 소스 쪽(바깥)에 둘 것.
            # (local_ip 0.0.0.0 — incus 브리지에서 forward 로 들어와 REDIRECT 된 연결도 받아야 한다. 외부(wlan0)에서는 방화벽이 이 포트를 열지 않는다.)
            cat > ${redsocksConf} <<EOF
        base {
            log_debug = off;
            log_info = off;
            daemon = off;
            redirector = iptables;
            redsocks_conn_max = 1024;
        }
        redsocks {
            local_ip = 0.0.0.0;
            local_port = ${toString redsocksPort};
            ip = $GW_IP;
            port = 1080;
            type = socks5;
        }
        redudp {
            local_ip = 0.0.0.0;
            local_port = ${toString redudpPort};
            ip = $GW_IP;
            port = 1080;
        }
        EOF
            ${pkgs.systemd}/bin/systemctl restart redsocks-hotspot.service

            $NFT add table ip ${nftTable} 2>/dev/null
            $NFT -- add chain ip ${nftTable} output '{ type nat hook output priority -100 ; }' 2>/dev/null
            $NFT flush chain ip ${nftTable} output
            $NFT add rule ip ${nftTable} output ip daddr '{ ${privateRanges} }' return
            # 로컬에서 나가는 TCP 는 uid 와 상관없이 전부(incus 의 dnsmasq(nobody)·systemd 서비스 포함 — 일부만 잡으면 나머지가 테더링으로 샌다). redsocks 자신의
            # GW_IP:1080 접속은 위 privateRanges return 에 걸려 루프 없음.
            $NFT add rule ip ${nftTable} output tcp dport != ${toString redsocksPort} redirect to :${toString redsocksPort}
            # incus 브리지에서 호스트를 거쳐 나가는 TCP: sbox 의 broker·VM(DHCP 범위)과 incusbr0 VM 을 같은 프록시로 돌린다. sbox ct(.200–.250)는 여기 해당 없음(어차피 호스트 밖으로 못 나감).
            $NFT -- add chain ip ${nftTable} prerouting '{ type nat hook prerouting priority dstnat ; }' 2>/dev/null
            $NFT flush chain ip ${nftTable} prerouting
            $NFT add rule ip ${nftTable} prerouting ip daddr '{ ${privateRanges} }' return
            $NFT add rule ip ${nftTable} prerouting iifname "sboxbr0" ip saddr ${sboxVmRange} tcp dport != ${toString redsocksPort} redirect to :${toString redsocksPort}
            $NFT add rule ip ${nftTable} prerouting iifname "incusbr0" tcp dport != ${toString redsocksPort} redirect to :${toString redsocksPort}

            # UDP: 로컬 발신 패킷을 lo로 재라우팅해 PREROUTING에서 TPROXY로 캡처.
            $IP rule add fwmark ${fwmark} lookup ${rtTable} 2>/dev/null
            $IP route replace local 0.0.0.0/0 dev lo table ${rtTable}

            $NFT add table inet ${nftUdpTable} 2>/dev/null
            $NFT -- add chain inet ${nftUdpTable} output '{ type route hook output priority mangle ; }' 2>/dev/null
            $NFT -- add chain inet ${nftUdpTable} prerouting '{ type filter hook prerouting priority mangle ; }' 2>/dev/null
            $NFT flush chain inet ${nftUdpTable} output
            $NFT flush chain inet ${nftUdpTable} prerouting
            $NFT add rule inet ${nftUdpTable} output ip daddr '{ ${privateRanges} }' return
            $NFT add rule inet ${nftUdpTable} output udp dport != ${toString redudpPort} meta mark set ${fwmark}
            $NFT add rule inet ${nftUdpTable} prerouting meta mark ${fwmark} meta l4proto udp tproxy to :${toString redudpPort}

            # 킬 스위치: 위 규칙을 빠져나간 것(프록시를 못 탄 UDP·ICMP·IPv6·forward 되는 비-TCP)은 wlan0 로 나가지 못한다. 허용: 게이트웨이(폰)·사설 대역·DHCP 브로드캐스트.
            $NFT delete table inet ${nftKillTable} 2>/dev/null
            $NFT -f - <<EOF
        table inet ${nftKillTable} {
            chain out {
                type filter hook output priority filter; policy accept;
                oifname "$INTERFACE" ip daddr { $GW_IP, ${privateRanges} } accept
                oifname "$INTERFACE" ip6 daddr fe80::/10 accept
                oifname "$INTERFACE" limit rate 6/minute burst 10 packets log prefix "hotspot-killswitch drop-out: " level warn
                oifname "$INTERFACE" counter drop
            }
            chain fwd {
                type filter hook forward priority filter; policy accept;
                oifname "$INTERFACE" ip daddr { $GW_IP, ${privateRanges} } accept
                oifname "$INTERFACE" limit rate 6/minute burst 10 packets log prefix "hotspot-killswitch drop-fwd: " level warn
                oifname "$INTERFACE" counter drop
            }
        }
        EOF
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
