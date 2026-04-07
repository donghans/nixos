{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui.apps.bitwarden;
in
  {options.mods.gui.apps.bitwarden.enable = mkEnableOption "Bitwarden";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = with pkgs; [bitwarden-desktop bitwarden-cli];
      };
    }
  )
