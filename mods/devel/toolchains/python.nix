{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.python;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./python-module.nix args);
}
