{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.docker;
in {
  config = mkIf (cfg.enable && isNixOS) {
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = ["docker"];
  };
}
