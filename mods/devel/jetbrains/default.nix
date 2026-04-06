{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.jetbrains;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./jetbrains-module.nix args);
}
