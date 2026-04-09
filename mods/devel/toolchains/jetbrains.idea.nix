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
  {options.mods.devel.jetbrains.idea.enable = mkEnableOption "IntelliJ IDEA";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf config.mods.devel.jetbrains.idea.enable {
        home.packages = [(jbLib.wrapJetbrainsPackage unstable.jetbrains.idea "idea")];
      };
    }
  )
