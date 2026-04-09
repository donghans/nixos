{
  config,
  lib,
  pkgs,
  unstable,
  isNixOS ? false,
  ...
}:
with lib; let
  jbLib = import ./_lib.jetbrains.nix {inherit pkgs;};
in
  {options.mods.devel.jetbrains.pycharm.enable = mkEnableOption "PyCharm";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf config.mods.devel.jetbrains.pycharm.enable {
        home.packages = [(jbLib.wrapJetbrainsPackage unstable.jetbrains.pycharm "pycharm")];
      };
    }
  )
