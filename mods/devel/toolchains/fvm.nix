{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.fvm;
in
  {options.mods.devel.fvm.enable = mkEnableOption "Flutter Version Management";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) (import ./fvm.home.nix (args // {inherit pkgs;}));
    }
  )
