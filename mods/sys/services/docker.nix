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

  os = {
    nixpkgs.overlays = [
      (_final: _prev: {inherit (unstable) docker-compose;})
    ];
    virtualisation.docker.enable = lib.mkIf (!cfg.rootless) true;
    virtualisation.docker.autoPrune.enable = lib.mkIf (!cfg.rootless) true;
    virtualisation.docker.rootless.enable = lib.mkIf cfg.rootless true;
    virtualisation.docker.rootless.setSocketVariable = lib.mkIf cfg.rootless true;
    users.users.${config.workspace.username}.extraGroups = lib.mkIf (!cfg.rootless) ["docker"];
  };
})
