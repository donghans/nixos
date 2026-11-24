# 격리 개발 VM 용 incus 브리지 `sboxbr0` + 호스트 방화벽 (plan dev-sandbox-pilot §4-2, S1)
#
# 목적: 격리하려는 개발 환경(incus VM `dev-nixos` 등)이 호스트의 서비스·내부망에 닿지 않게 하면서 외부 인터넷 NAT 만 허용한다.
# 기존 `incusbr0` 와 다른 점: incusbr0 는 방화벽 trustedInterfaces 라서(incus.nix) 게스트가 호스트의 0.0.0.0 바인딩 포트(22·5355·8443 등)에 닿는다
# (2026-11-21 incus 컨테이너·VM 경계 시험, note dev-sandbox-evidence). sboxbr0 는 신뢰 인터페이스에 넣지 않고 아래 규칙으로 막는다.
#
# 규칙(시험함: 임시 네트워크 네임스페이스에서 별도 표의 INPUT 동작 — note dev-sandbox-evidence 「sboxbr0 방화벽 초안」):
#  - INPUT: sboxbr0 에서 호스트로 오는 것은 ① 이미 맺어진 연결 ② DHCP(udp 67) ③ 브리지 주소(10.100.1.1)의 DNS(53)만 허용, 나머지는 drop.
#    DNS 를 브리지 주소로 제한하는 이유: 호스트의 dockerdns0(10.255.255.53)가 tailnet DNS(100.100.100.100)로 포워딩하므로 모든 로컬 주소의 53 을 열면 tailnet 이름이 풀린다.
#  - FORWARD: sboxbr0 → 사설·내부 대역(10/8·172.16/12·192.168/16·169.254/16·100.64/10 = LAN·docker·incusbr0·tailnet) drop, 다른 인터페이스 → sboxbr0 새 연결 drop.
#    인터넷으로 나가는 것은 NAT(incus 의 ipv4.nat)로 허용.
#  - 이 표의 accept 는 이 체인만 끝낸다. 뒤의 nixos-fw 도 sboxbr0 의 DHCP·DNS 를 받아야 하므로 extraInputRules 로 같은 조건을 연다
#    (networking.firewall.interfaces.sboxbr0.* 는 목적지 주소를 제한하지 못해 쓰지 않는다).
#
# 못 시험한 것(S1 적용 뒤 프로브로 확인): nixos-fw 와의 결합, UDP DNS/DHCP 실동작, FORWARD/NAT, incus 가 브리지에 자동으로 넣는 규칙(ipv4.firewall)과의 중복.
# 되돌리는 법: 호스트 toml 의 `incus-sbox` 를 false 로 하고 nixup. preseed 는 네트워크를 지우지 않으므로 VM 을 지운 뒤 `incus network delete sboxbr0`.
{mkMod, ...}:
mkMod __curPos "격리 개발 VM 용 incus 브리지(sboxbr0)와 호스트 방화벽" ({
  config,
  lib,
  ...
}: let
  # sboxbr0 전용 Nix 캐시(nix-serve-sbox.nix, 포트 5000) 예외. 그 모듈이 같은 hook+priority(-10)의
  # 별도 nft 표를 만들면 sbox-guard 의 마지막 `drop` 과 평가 순서가 보장되지 않아(둘 다 바뀔 수 있음:
  # 어느 쪽이 먼저 돌지 nftables 가 보증 안 함) 2026-11-22 접속 안 됨으로 재현됨 → 같은 체인 안에 직접 둔다.
  nixServeCacheRule = lib.optionalString config.mods.sys.services.nix-serve-sbox.enable ''
    iifname "sboxbr0" ip daddr 10.100.1.1 tcp dport 5000 accept
  '';
in {
  os = {
    assertions = [
      {
        assertion = config.mods.sys.services.incus.enable;
        message = "mods.sys.services.incus-sbox 는 mods.sys.services.incus.enable = true 가 필요합니다";
      }
    ];

    # incus-preseed 는 「덮어쓰거나 없으면 생성, 삭제는 안 함」이라 기존 incusbr0 는 그대로다.
    virtualisation.incus.preseed.networks = [
      {
        name = "sboxbr0";
        type = "bridge";
        config = {
          # incusbr0(10.100.0.0/24)와 겹치지 않는 부분망. auto 로 두면 incus 재시작마다 바뀔 수 있어 고정한다.
          "ipv4.address" = "10.100.1.1/24";
          "ipv4.nat" = "true";
          "ipv6.address" = "none";
          # DHCP 는 .100–.199 만(VM·골든·broker). ct 는 broker 가 있으면 sboxctl 이 만들 때부터 .200–.250 의 고정 주소를 배정한다 — 호스트가 주소 범위로
          # ct 를 구분해 게이트웨이 DNS 를 막을 수 있게(NIC ACL 로는 브리지 자신의 DNS 를 못 막는다, pilot §29-29). 범위를 바꾸면 sbox-guard 의 아래 규칙도 같이.
          "ipv4.dhcp.ranges" = "10.100.1.100-10.100.1.199";
          # 상위 DNS 를 공용으로 고정한다 — 안 그러면 호스트 dnsmasq 가 resolv.conf 의 tailnet DNS 를 따라가 VM 이 tailnet 이름을 해석한다(incus.nix 와 같은 이유).
          "raw.dnsmasq" = "server=1.1.1.1\nserver=8.8.8.8\nfilter-AAAA";
        };
      }
    ];

    # sbox 전체의 자원 합계 상한 (plan dev-sandbox-pilot §29-27, S69 1차 — 보안이 아니라 호스트가 응답 불가가 되지 않게).
    # 컨테이너의 cgroup 은 기본으로 cgroup 루트 바로 밑(`lxc.payload.<이름>`)에 생겨 user.slice·system.slice 와 같은 급의 형제로 경쟁한다
    # (ct 10개면 사용자 세션의 10배 몫을 요구할 수 있다 — 2026-11-23 직접 확인). `sboxctl create` 가 ct 마다 raw.lxc 로 이 slice 아래에 둔다
    # (`%n` 이 치환되지 않아 프로필 한 줄로는 안 된다 — 시험). 우선순위: user.slice(9000, core.cgroups.nix) > system.slice(100) > sbox.slice(50).
    #  - MemoryHigh 50%: 넘으면 ct 들이 회수·지연(죽지 않음 — 시험: 한도를 넘는 점유는 심하게 늦춰져 기어가고 호스트 PSI 가 오른다). MemoryMax 70%: 최후 상한(시험: 닿으면 8초 만에 sbox 안에서만 OOM kill, 호스트 무영향).
    #  - CPUQuota: 코어의 60% — 합계가 호스트 코어를 다 가져가지 못하게(weight 는 경쟁할 때만 효과). TasksMax: 합계 프로세스 수.
    # systemd-oomd 로 sbox 를 먼저 죽이는 설정은 일부러 넣지 않았다(OOM 최소화 방침 — 필요하면 2차에서 ManagedOOMMemoryPressure).
    systemd.slices.sbox = {
      description = "sbox 격리 환경(ct) 합계 자원 상한";
      sliceConfig =
        {
          CPUWeight = 50;
          IOWeight = 50;
          MemoryHigh = "50%";
          MemoryMax = "70%";
          # 스왑 상한: 없으면 sbox 가 호스트의 zram·디스크 스왑을 독점한다(2026-11-23 시험: 상한 없이 max 를 넘겨 쓰자 스왑으로 흡수돼 OOM 이 나지 않고 호스트 PSI 만 51% 까지 올랐다).
          # RAM 대비 비율이라 호스트가 달라져도 따라간다.
          MemorySwapMax = "15%";
          TasksMax = 16000;
        }
        // lib.optionalAttrs (config.workspace.cpuCount != null) {
          CPUQuota = "${toString (config.workspace.cpuCount * 60)}%";
        };
    };
    # slice 가 incus 보다 먼저 떠 있어야 ct 의 cgroup 부모가 한도를 가진 상태로 생긴다
    systemd.services.incus = {
      wants = ["sbox.slice"];
      after = ["sbox.slice"];
    };

    # 모든 sbox 컨테이너가 지킬 최소 하드닝 프로필 (plan dev-sandbox-pilot §29-20, 로드맵 S63). sboxctl create --kind ct 가 `-p sbox-ct` 로 붙인다.
    # default 프로필(incusbr0 NIC)을 대신하므로 NIC·루트 디스크를 여기서 직접 선언한다. preseed 는 프로필을 지우지 않는다.
    #  - security.idmap.isolated + size 1000000: ct 마다 호스트 uid 범위가 겹치지 않는다. 기본 65536 은 rootless Docker(subuid 65536 필요)가 깨진다.
    #    size 변경은 실행 중이면 설정만 바뀌고 uid_map 은 재시작 전까지 그대로다(§29-22 시험).
    #  - nic security.port_isolation: 같은 브리지의 ct↔ct 직접 통신 차단(게이트웨이로는 통신 가능).
    #  - 루트 디스크 size: btrfs quota 상한(기본 10GiB — 일반 Node+DB 개발은 3GiB 안팎, pilot §29-23; 큰 프로젝트만 --disk 로 올림). ct 별로 `sboxctl create --disk` 로 덮어쓴다. 실행 중에도 변경 가능.
    #  - limits.processes: fork 폭탄 방지(ct 별 상한).
    virtualisation.incus.preseed.profiles = [
      {
        name = "sbox-ct";
        description = "sbox 컨테이너 공통 하드닝 (mods/sys/services/incus-sbox.nix)";
        config = {
          "security.idmap.isolated" = "true";
          "security.idmap.size" = "1000000";
          "limits.processes" = "4096";
        };
        devices = {
          eth0 = {
            name = "eth0";
            type = "nic";
            network = "sboxbr0";
            "security.port_isolation" = "true";
          };
          root = {
            path = "/";
            pool = "default";
            type = "disk";
            size = "10GiB";
          };
        };
      }
    ];

    # VM 이 IPv6 RA 를 브리지로 보낼 때 호스트 IPv6 라우팅이 바뀌는 것을 방지(incus.nix 의 incusbr0 와 같은 이유)
    boot.kernel.sysctl."net.ipv6.conf.sboxbr0.accept_ra" = 0;

    networking.nftables.enable = true;

    # NixOS 방화벽(nixos-fw, hook input priority filter)보다 먼저(-10) 평가되는 별도 표. drop 은 최종이다.
    networking.nftables.tables.sbox-guard = {
      family = "inet";
      content = ''
        chain input {
          type filter hook input priority -10; policy accept;
          iifname "sboxbr0" ct state established,related accept
          iifname "sboxbr0" udp dport 67 accept
          # ct 대역(.200–.250)은 게이트웨이 DNS 를 쓰지 못한다 — ct 의 외부 연결은 broker 프록시(이름은 broker 가 해석)뿐이고, DNS 는 터널링 유출 경로라(S70-a, pilot §29-29).
          # broker·VM·골든은 DHCP 범위(.100–.199)라 영향 없음. 아래 accept 보다 앞에 있어야 한다.
          iifname "sboxbr0" ip saddr 10.100.1.200-10.100.1.250 ip daddr 10.100.1.1 meta l4proto { tcp, udp } th dport 53 limit rate 6/minute burst 10 packets log prefix "sbox-guard drop-ct-dns: " level warn
          iifname "sboxbr0" ip saddr 10.100.1.200-10.100.1.250 ip daddr 10.100.1.1 meta l4proto { tcp, udp } th dport 53 drop
          iifname "sboxbr0" ip daddr 10.100.1.1 udp dport 53 accept
          iifname "sboxbr0" ip daddr 10.100.1.1 tcp dport 53 accept
          ${nixServeCacheRule}
          # 핫스팟 모드(킬 스위치)에서 호스트가 broker·VM(DHCP 범위)의 forward TCP 를 redsocks(12345)로 REDIRECT 한다(hosts/msi-summit-me/hotspot-proxy-dispatcher.nix).
          # ct 대역(.200–.250)은 해당 없음 — 여기서 열지 않는다.
          iifname "sboxbr0" ip saddr 10.100.1.100-10.100.1.199 ip daddr 10.100.1.1 tcp dport 12345 accept
          # 막힌 시도의 흔적(커널 로그 → journald): 초당 폭주해도 로그는 분당 6건(+순간 10건)까지만. 접두사로 grep 한다:
          #   journalctl -k | grep 'sbox-guard'  (plan dev-sandbox-pilot §13 — 가시성 보강 2)
          iifname "sboxbr0" limit rate 6/minute burst 10 packets log prefix "sbox-guard drop-input: " level warn
          iifname "sboxbr0" drop
        }
        chain forward {
          type filter hook forward priority -10; policy accept;
          # ct 대역(.200–.250)은 호스트를 지나 브리지 밖(인터넷)으로 나가지 못한다 — ct 의 외부 연결은 broker 가 길목(기본 게이트웨이)에서 받아 프록시로만 나간다(방식 B,
          # pilot §29-37). ct 안에서 경로를 호스트로 되돌려도(권한 상승이 있어야 가능) 여기서 막힌다. broker·VM·골든은 DHCP 범위(.100–.199)라 영향 없음.
          # NIC ACL 이 tcp 443·80 을 아무 곳이나 허용하므로(가로채기 때문에) 이 규칙이 fail-closed 의 마지막 보루다.
          iifname "sboxbr0" oifname != "sboxbr0" ip saddr 10.100.1.200-10.100.1.250 limit rate 6/minute burst 10 packets log prefix "sbox-guard drop-ct-out: " level warn
          iifname "sboxbr0" oifname != "sboxbr0" ip saddr 10.100.1.200-10.100.1.250 drop
          iifname "sboxbr0" ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } limit rate 6/minute burst 10 packets log prefix "sbox-guard drop-forward-private: " level warn
          iifname "sboxbr0" ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } drop
          oifname "sboxbr0" iifname != "sboxbr0" ct state established,related accept
          oifname "sboxbr0" iifname != "sboxbr0" limit rate 6/minute burst 10 packets log prefix "sbox-guard drop-forward-in: " level warn
          oifname "sboxbr0" iifname != "sboxbr0" drop
        }
      '';
    };

    # nixos-fw 쪽에서도 sboxbr0 의 DHCP·DNS 만 연다(위 별도 표의 accept 는 nixos-fw 를 건너뛰지 못한다).
    networking.firewall.extraInputRules = ''
      iifname "sboxbr0" udp dport 67 accept
      iifname "sboxbr0" ip daddr 10.100.1.1 udp dport 53 accept
      iifname "sboxbr0" ip daddr 10.100.1.1 tcp dport 53 accept
      iifname "sboxbr0" ip saddr 10.100.1.100-10.100.1.199 ip daddr 10.100.1.1 tcp dport 12345 accept
      ${nixServeCacheRule}
    '';

    # VM→인터넷 TCP 단편화 방지(incus.nix 의 mss-clamp 는 incusbr0 만 대상이라 sboxbr0 용을 따로 둔다 — 같은 표의 체인을 중복 정의하지 않으려고 별도 표).
    networking.nftables.tables.mss-clamp-sbox = {
      family = "ip";
      content = ''
        chain forward {
          type filter hook forward priority mangle;
          iifname "sboxbr0" tcp flags syn tcp option maxseg size set rt mtu
          oifname "sboxbr0" tcp flags syn tcp option maxseg size set rt mtu
        }
      '';
    };
  };
})
