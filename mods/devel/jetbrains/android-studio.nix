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
      # (목적: ADB udev 규칙 설치 및 adbusers 그룹 생성)
      programs.adb.enable = true;
      networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
      users.users.${config.workspace.username}.extraGroups = ["adbusers"];
    }
    else {
      home.packages = with pkgs; [
        android-studio
        android-tools # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
      ];
    }
  );
}
