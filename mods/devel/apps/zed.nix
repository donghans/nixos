{
  config,
  lib,
  pkgs,
  unstable,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.zed;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    home.packages = [unstable.zed-editor];
  };
}
