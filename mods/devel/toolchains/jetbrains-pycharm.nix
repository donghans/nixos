{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel.jetbrains.pycharm;
in
  {
    options.mods.devel.jetbrains.pycharm.enable = mkEnableOption "PyCharm Professional";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [pkgs.jetbrains-wrapped.pycharm];
      };
    }
  )
