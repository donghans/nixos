{
  config,
  lib,
  pkgs,
  unstable,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.jetbrains.android-studio;
  enabled = cfg.enable || modCfg.enable;
  jbLib = import ./_lib.jetbrains.nix {inherit pkgs;};
in
  {options.mods.devel.jetbrains.android-studio.enable = mkEnableOption "Android Studio (ADB, UDP 5353)";}
  // (
    if isNixOS
    then {
      config = mkIf enabled {
        # (목적: ADB udev 규칙 설치 및 adbusers 그룹 생성)
        programs.adb.enable = true;
        networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
        users.users.${config.workspace.username}.extraGroups = ["adbusers"];
      };
    }
    else {
      config = mkIf enabled {
        home.packages = [
          pkgs.android-tools # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
          (jbLib.wrapJetbrainsPackage unstable.android-studio "android-studio")
        ];
      };
    }
  )
