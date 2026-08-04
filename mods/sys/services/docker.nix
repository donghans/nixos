{
  mkMod,
  config,
  lib,
  unstable,
  ...
}:
mkMod __curPos "Docker Daemon and tools" ({cfg, ...}: {
  options.rootless = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Use rootless Docker (per-user daemon). Set false for system-wide daemon + docker group.";
  };

  os = lib.mkMerge [
    {
      nixpkgs.overlays = [
        (_final: _prev: {inherit (unstable) docker-compose;})
      ];
      virtualisation.docker.enable = lib.mkIf (!cfg.rootless) true;
      virtualisation.docker.autoPrune.enable = lib.mkIf (!cfg.rootless) true;
      virtualisation.docker.rootless.enable = lib.mkIf cfg.rootless true;
      virtualisation.docker.rootless.setSocketVariable = lib.mkIf cfg.rootless true;
      virtualisation.docker.rootless.daemon.settings = lib.mkIf cfg.rootless {
        dns = ["8.8.8.8" "8.8.4.4"];
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
      virtualisation.docker.daemon.settings.dns = ["8.8.8.8" "8.8.4.4"];
      systemd.network.networks."20-docker-veth" = {
        matchConfig.Name = "veth* br-* docker*";
        linkConfig.Unmanaged = true;
      };
    })
  ];
})
