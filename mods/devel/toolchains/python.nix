{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.python;
in
  {options.mods.devel.python.enable = mkEnableOption "Python toolchain";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) (import ./python.home.nix (args // {inherit pkgs;}));
    }
  )
