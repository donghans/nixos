{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.devbox;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./devbox-module.nix args);
}
