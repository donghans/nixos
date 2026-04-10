{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel.jetbrains.datagrip;
in
  {
    options.mods.devel.jetbrains.datagrip.enable = mkEnableOption "DataGrip";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [pkgs.jetbrains-wrapped.datagrip];
      };
    }
  )
