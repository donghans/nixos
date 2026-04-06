{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.jetbrains.android-studio;
in {
  config = mkIf (cfg.enable || modCfg.enable) (
    if isNixOS
    then {
      # (목적: 물리 기기에서 Android 실기기 디버깅을 위한 udev 및 방화벽 허용)
      networking.firewall = {
        allowedTCPPorts = [5555]; # ADB over Network
        allowedUDPPorts = [5353]; # mDNS / Local Discovery
      };
      users.users.${config.workspace.username}.extraGroups = ["adbusers"];
    }
    else {
      home.packages = [pkgs.android-studio];
    }
  );
}
