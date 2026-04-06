{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.docker;
in
  if isNixOS
  then {
    config = mkIf cfg.enable {
      virtualisation.docker = {
        enable = true;
        autoPrune.enable = true;
      };
      users.users.${config.workspace.username}.extraGroups = ["docker"];
    };
  }
  else {}
