{
  pkgs,
  unstable,
  config,
  lib,
  isNixOS ? false,
  ...
}:
(import ./_lib.jetbrains.nix {inherit pkgs;}).mkJetbrainsModule {
  ideName = "pycharm";
  ideLabel = "PyCharm";
  pkgAttr = unstable.jetbrains.pycharm;
} {inherit config lib isNixOS;}
