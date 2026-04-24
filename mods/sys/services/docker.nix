{mkMod, ...}:
mkMod __curPos "Docker Daemon and tools" ({
  config,
  unstable,
  ...
}: {
  os = {
    nixpkgs.overlays = [
      (_final: _prev: {inherit (unstable) docker-compose;})
    ];
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = ["docker"];
  };
})
