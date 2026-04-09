{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.docker;
in {
  options.mods.sys.services.docker.enable = mkEnableOption "Docker Daemon and tools";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      virtualisation.docker = {
        enable = true;
        autoPrune.enable = true;
      };
      users.users.${config.workspace.username}.extraGroups = ["docker"];
    }
    else {}
  );
}
