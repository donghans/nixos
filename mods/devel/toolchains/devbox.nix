{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.devbox;
in
  {options.mods.devel.devbox.enable = mkEnableOption "Devbox global profile";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) (import ./devbox.home.nix (args // {inherit pkgs;}));
    }
  )
