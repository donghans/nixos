{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui.apps.speedcrunch;
in
  {options.mods.gui.apps.speedcrunch.enable = mkEnableOption "SpeedCrunch";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [pkgs.speedcrunch];
      };
    }
  )
