{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.mods.gui.apps.bitwarden;
in {
  config = mkIf cfg.enable {
    home.packages = with pkgs; [bitwarden-desktop bitwarden-cli];
  };
}
