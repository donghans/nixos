{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
if isNixOS
then {}
else
  with lib; let
    cfg = config.mods.devel;
    modCfg = config.mods.devel.python;
  in {
    config = mkIf (cfg.enable || modCfg.enable) (import ./python.home.nix (args // {inherit pkgs;}));
  }
