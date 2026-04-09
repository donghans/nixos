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
in {
  options.mods.devel.jetbrains.webstorm.enable = mkEnableOption "WebStorm";
  config = mkIf (!isNixOS && config.mods.devel.jetbrains.webstorm.enable) {
    home.packages = [(jbLib.wrapJetbrainsPackage unstable.jetbrains.webstorm "webstorm")];
  };
}
