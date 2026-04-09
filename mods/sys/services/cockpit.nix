{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.cockpit;
in {
  options.mods.sys.services.cockpit.enable = mkEnableOption "Cockpit Web Dashboard";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.cockpit.enable = true;
      services.cockpit.port = 9090;
    }
    else {}
  );
}
