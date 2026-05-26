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
      virtualisation.docker.rootless.daemon.settings = lib.mkIf cfg.rootless {dns = ["8.8.8.8" "8.8.4.4"];};
      users.users.${config.workspace.username}.extraGroups = lib.mkIf (!cfg.rootless) ["docker"];
      boot.kernel.sysctl."net.ipv4.ip_unprivileged_port_start" = lib.mkIf cfg.rootless 80;
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
