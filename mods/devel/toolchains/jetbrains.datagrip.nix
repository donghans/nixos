{
  pkgs,
  unstable,
  config,
  lib,
  isNixOS ? false,
  ...
}:
(import ./_lib.jetbrains.nix {inherit pkgs;}).mkJetbrainsModule {
  ideName = "datagrip";
  ideLabel = "DataGrip";
  pkgAttr = unstable.jetbrains.datagrip;
} {inherit config lib isNixOS;}
