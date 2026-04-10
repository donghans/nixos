{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.python;
  pythonEnv = pkgs.python312.withPackages (ps:
    with ps; [
      pip
      virtualenv
    ]);
in
  {
    options.mods.devel.python.enable = mkEnableOption "Python toolchain";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf modCfg.enable {
        home.packages = [pythonEnv];
      };
    }
  )
