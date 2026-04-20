{mkMod, ...}:
mkMod __curPos "Docker Daemon and tools" ({config, ...}: {
  os = {
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = ["docker"];
  };
})
