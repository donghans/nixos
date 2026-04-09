{
  pkgs,
  unstable,
  config,
  lib,
  isNixOS ? false,
  ...
}:
(import ./_lib.jetbrains.nix {inherit pkgs;}).mkJetbrainsModule {
  ideName = "idea";
  ideLabel = "IntelliJ IDEA";
  pkgAttr = unstable.jetbrains.idea;
} {inherit config lib isNixOS;}
