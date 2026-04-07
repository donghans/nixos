{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.node;
in
  {options.mods.devel.node.enable = mkEnableOption "Node.js toolchain";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) (import ./node.home.nix (args // {inherit pkgs;}));
    }
  )
