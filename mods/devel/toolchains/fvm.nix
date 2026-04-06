{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.fvm;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./fvm-module.nix args);
}
