{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.node;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./node-module.nix args);
}
