{
  config,
  lib,
  pkgs,
  ...
} @ args:
with lib; let
  cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (import ./os-module.nix args);
}
