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
  {options.mods.devel.jetbrains.datagrip.enable = mkEnableOption "DataGrip";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf config.mods.devel.jetbrains.datagrip.enable {
        home.packages = [(jbLib.wrapJetbrainsPackage unstable.jetbrains.datagrip "datagrip")];
      };
    }
  )
