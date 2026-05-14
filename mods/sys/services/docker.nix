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
    # 시스템 데몬은 포트 포워딩 NAT에 iptables 커널 모듈이 필요
    (lib.mkIf (!cfg.rootless) {
      boot.kernelModules = ["ip_tables" "iptable_nat" "iptable_filter" "iptable_mangle"];
    })
  ];
})
