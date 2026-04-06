{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.jetbrains.android-studio;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    programs.adb.enable = true;
    networking.firewall.allowedUDPPorts = [5353];
    users.users.${config.workspace.username}.extraGroups = ["adbusers"];
  };
}
