{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.jetbrains.android-studio;
in
  {
    options.mods.devel.jetbrains.android-studio.enable = mkEnableOption "Android Studio (ADB, UDP 5353)";
  }
  // (
    if isNixOS
    then {
      config = mkIf modCfg.enable {
        # (목적: ADB udev 규칙 설치 및 adbusers 그룹 생성)
        programs.adb.enable = true;
        networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
        users.users.${config.workspace.username}.extraGroups = ["adbusers"];
      };
    }
    else {
      config = mkIf modCfg.enable {
        home.packages = [
          pkgs.android-tools # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
          pkgs.jetbrains-wrapped.android-studio
        ];
      };
    }
  )
