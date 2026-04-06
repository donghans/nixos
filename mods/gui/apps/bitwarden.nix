{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
if isNixOS
then {}
else
  with lib; let
    cfg = config.mods.gui.apps.bitwarden;
  in {
    config = mkIf cfg.enable {
      home.packages = with pkgs; [bitwarden-desktop bitwarden-cli];
    };
  }
