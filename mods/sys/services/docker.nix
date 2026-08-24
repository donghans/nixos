{
  mkMod,
  config,
  lib,
  unstable,
  ...
}:
mkMod __curPos "Docker Daemon and tools" ({
  cfg,
  pkgs,
  ...
}: {
  options.rootless = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Use rootless Docker (per-user daemon). Set false for system-wide daemon + docker group.";
  };

  os = lib.mkMerge [
    {
      # (목적: 컨테이너 안에서 apk/npm 등이 DNS 응답의 AAAA 레코드를 골라 붙으려다
      #        실패하는 문제 방지 — rootless netns(slirp4netns)에는 IPv6 경로가
      #        전혀 없는데(호스트 자체도 핫스팟에서는 IPv6 라우트가 없음, 2026-08-24 실측),
      #        apk 등 일부 클라이언트는 AAAA 응답을 받으면 A로 폴백하지 않고 그대로
      #        연결 시도하다 타임아웃 → "DNS: transient error"로 오진단됨.
      #        고정 IP(10.255.255.53)를 가진 더미 인터페이스에 AAAA를 걸러주는
      #        로컬 dnsmasq를 띄우고, 컨테이너 DNS를 그쪽으로 돌려서 원천 차단.
      #        고정 IP를 쓰는 이유: Tailscale IP(100.64.0.4)는 재등록 시 바뀔 수 있어
      #        하드코딩하기 부적합 — dockerd 전용 IP를 별도로 소유)
      # (주의: 이 호스트는 systemd-networkd가 아니라 NetworkManager를 쓰므로
      #        systemd.network.netdevs는 무시됨(2026-08-24 실측: systemd-networkd.service
      #        자체가 존재하지 않아 dnsmasq가 "unknown interface dockerdns0"로 죽음)
      #        → networkd에 의존하지 않는 순수 iproute2 oneshot으로 더미 인터페이스 생성)
      systemd.services.docker-dns-dummy-iface = {
        description = "dockerdns0 dummy interface for AAAA-filtering local resolver";
        wantedBy = ["multi-user.target"];
        before = ["dnsmasq.service"];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = pkgs.writeShellScript "docker-dns-dummy-iface-start" ''
            set -e
            ${pkgs.iproute2}/bin/ip link show dockerdns0 >/dev/null 2>&1 || \
              ${pkgs.iproute2}/bin/ip link add dockerdns0 type dummy
            ${pkgs.iproute2}/bin/ip addr replace 10.255.255.53/32 dev dockerdns0
            ${pkgs.iproute2}/bin/ip link set dockerdns0 up
          '';
          ExecStop = pkgs.writeShellScript "docker-dns-dummy-iface-stop" ''
            ${pkgs.iproute2}/bin/ip link del dockerdns0 || true
          '';
        };
      };
      services.dnsmasq = {
        enable = true;
        settings = {
          interface = ["dockerdns0"];
          bind-interfaces = true;
          no-resolv = true;
          no-hosts = true;
          server = ["100.100.100.100"];
          filter-AAAA = true;
        };
      };
      systemd.services.dnsmasq = {
        after = ["docker-dns-dummy-iface.service"];
        requires = ["docker-dns-dummy-iface.service"];
      };
      nixpkgs.overlays = [
        (_final: _prev: {inherit (unstable) docker-compose;})
      ];
      virtualisation.docker.enable = lib.mkIf (!cfg.rootless) true;
      virtualisation.docker.autoPrune.enable = lib.mkIf (!cfg.rootless) true;
      virtualisation.docker.rootless.enable = lib.mkIf cfg.rootless true;
      virtualisation.docker.rootless.setSocketVariable = lib.mkIf cfg.rootless true;
      virtualisation.docker.rootless.daemon.settings = lib.mkIf cfg.rootless {
        # (이유: 모바일 핫스팟 테더링에서 공용 DNS(8.8.8.8/8.8.4.4)로 나가는 순수 UDP/53 질의를
        #        통신사가 드롭하는 것을 2026-08-24 실측 확인 — raw UDP DNS 질의로 8.8.8.8/1.1.1.1은
        #        타임아웃, 100.100.100.100(Tailscale MagicDNS, WireGuard 터널로 캡슐화되어
        #        통신사가 일반 DNS 트래픽으로 식별 못함)은 정상 응답. 안정적인 공유기 환경에서는
        #        원래도 문제없이 동작하던 값이라 회귀 없음.
        #        다만 100.100.100.100을 그대로 쓰면 AAAA 응답 때문에 apk 등이 실패하는
        #        문제가 남아있어(위 dnsmasq 참고), 최종적으로는 그 필터를 거친
        #        10.255.255.53을 사용)
        dns = ["10.255.255.53"];
        # btrfs 네이티브 CoW 레이어 공유 활성화 (genple-new backlog
        # 1785507667-docker-btrfs-storage-driver-cow 사전 작업, 2026-08-01)
        storage-driver = "btrfs";
        # (목적: BuildKit 빌드 캐시가 무한정 쌓이는 것 방지 — btrfs storage-driver라 캐시 레이어
        #        하나하나가 subvolume이라, 캐시가 쌓일수록 btrfs-cleaner 부하도 같이 늘어남)
        # (이유: stress-test가 매번 새 이미지를 빌드하는 워크로드라 캐시 재사용률이 낮음(2026-08-04
        #        실측: dangling 이미지 상당수 SHARED SIZE=0B) → 캐시를 오래 들고 있을 가치가 낮음)
        builder.gc = {
          enabled = true;
          policy = [
            {keepStorage = "20GB";}
          ];
        };
      };
      users.users.${config.workspace.username}.extraGroups = lib.mkIf (!cfg.rootless) ["docker"];
      boot.kernel.sysctl."net.ipv4.ip_unprivileged_port_start" = lib.mkIf cfg.rootless 80;

      # (목적: rootless dockerd는 유저 매니저의 app.slice에 들어가는데, 이는 Hyprland가 속한
      #        session.slice와 형제 관계 + 동일 기본 weight(100)라 컨테이너를 많이 띄우면
      #        데스크탑과 동급으로 CPU/IO를 다퉈 Wayland가 버벅임. 별도 슬라이스로 분리해
      #        컴포즈 파일과 무관하게 dockerd(+모든 하위 컨테이너)를 일괄 저우선순위화)
      # (주의: weight=20은 너무 낮음 — 데스크탑엔 여전히 밀리지만, 컨테이너 안에서 도는 실제
      #        워크로드(예: 통합테스트 대상 앱)가 nix 빌드 등 다른 백그라운드 작업한테까지
      #        밀려 굶는 사고가 재현됨(2026-08-04). background.slice(수동 임시작업용)와는
      #        분리된 "정상 워크로드" 취급으로 weight를 system.slice와 비슷한 수준으로 올림)
      systemd.user.slices."docker.slice".sliceConfig = lib.mkIf cfg.rootless {
        CPUWeight = 150;
        IOWeight = 150;
      };
      systemd.user.services.docker.serviceConfig = lib.mkIf cfg.rootless {
        Slice = "docker.slice";
        Nice = 15; # (nice 상향 = 우선순위 하향, fork로 모든 컨테이너 프로세스에 상속)
        IOSchedulingClass = "idle";
      };

      # (목적: rootless는 !cfg.rootless 분기의 virtualisation.docker.autoPrune 같은 내장
      #        정리 기능이 없어서 dangling 이미지가 무한정 쌓임 — 매일 48시간 지난 것만 정리)
      # (이유: 2026-08-04에 stress-test 반복 실행으로 이미지 197개/79GB, 볼륨 147개/21GB가
      #        쌓여 btrfs subvolume 과다로 btrfs-cleaner가 상시 부하 걸린 사고 재발 방지.
      #        볼륨은 디버깅용 데이터 보존 가능성 때문에 자동 삭제 대상에서 제외 — 수동 정리 유지)
      systemd.user.services.docker-prune = lib.mkIf cfg.rootless {
        description = "Prune dangling Docker images older than 48h";
        serviceConfig = {
          Type = "oneshot";
          Environment = "DOCKER_HOST=unix://%t/docker.sock";
          ExecStart = "${config.virtualisation.docker.rootless.package}/bin/docker image prune -af --filter until=48h";
          Slice = "background.slice";
        };
      };
      systemd.user.timers.docker-prune = lib.mkIf cfg.rootless {
        description = "Daily dangling Docker image cleanup";
        timerConfig = {
          OnCalendar = "daily";
          Persistent = true;
        };
        wantedBy = ["timers.target"];
      };
    }
    # 시스템 데몬은 컨테이너 아웃바운드 NAT에 nftables 필요 (Docker 28 네이티브 지원)
    # 그리고 veth/브리지 인터페이스를 systemd-networkd가 가로채지 않도록 20번으로 명시 제외
    (lib.mkIf (!cfg.rootless) {
      networking.nftables.enable = true;
      # (이유: 위 rootless 분기와 동일 — 모바일 핫스팟에서 8.8.8.8/8.8.4.4 UDP/53 질의가
      #        통신사에 의해 드롭되는 문제 회피 + AAAA 필터링, 2026-08-24)
      virtualisation.docker.daemon.settings.dns = ["10.255.255.53"];
      systemd.network.networks."20-docker-veth" = {
        matchConfig.Name = "veth* br-* docker*";
        linkConfig.Unmanaged = true;
      };
    })
  ];
})
