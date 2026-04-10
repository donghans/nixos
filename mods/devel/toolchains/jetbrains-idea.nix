{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel.jetbrains.idea;
in
  {
    options.mods.devel.jetbrains.idea.enable = mkEnableOption "IntelliJ IDEA";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [pkgs.jetbrains-wrapped.idea];
      };
    }
  )
