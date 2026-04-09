{
  lib,
  config,
  ...
}:
with lib; let
  inherit (import ../_lib.nix {inherit lib;}) importDir;
in {
  imports =
    [./core]
    ++ importDir ./apps
    ++ importDir ./utils;

  options.mods.gui.enable = mkEnableOption "GUI Bundle (Hyprland, Waybar, etc)";

  config = mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}
