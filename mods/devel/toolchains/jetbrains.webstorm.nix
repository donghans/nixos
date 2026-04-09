{
  pkgs,
  unstable,
  config,
  lib,
  isNixOS ? false,
  ...
}:
(import ./_lib.jetbrains.nix {inherit pkgs;}).mkJetbrainsModule {
  ideName = "webstorm";
  ideLabel = "WebStorm";
  pkgAttr = unstable.jetbrains.webstorm;
} {inherit config lib isNixOS;}
