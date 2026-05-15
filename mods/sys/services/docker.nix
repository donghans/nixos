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
      users.users.${config.workspace.username}.extraGroups = lib.mkIf (!cfg.rootless) ["docker"];
      boot.kernel.sysctl."net.ipv4.ip_unprivileged_port_start" = lib.mkIf cfg.rootless 80;
    }
    # 시스템 데몬은 컨테이너 아웃바운드 NAT에 nftables 필요 (Docker 28 네이티브 지원)
    (lib.mkIf (!cfg.rootless) {
      networking.nftables.enable = true;
    })
  ];
})
