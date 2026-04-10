{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel.jetbrains.webstorm;
in
  {
    options.mods.devel.jetbrains.webstorm.enable = mkEnableOption "WebStorm";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [pkgs.jetbrains-wrapped.webstorm];
      };
    }
  )
