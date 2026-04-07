{
  config,
  lib,
  unstable,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.zed;
in
  {options.mods.devel.zed.enable = mkEnableOption "Zed editor";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) {
        home.packages = [unstable.zed-editor];
      };
    }
  )
