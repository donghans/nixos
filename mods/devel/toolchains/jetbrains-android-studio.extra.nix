{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel.jetbrains.android-studio;
in
  # (목적: networking 등 NixOS 전용 옵션이 home-manager 컨텍스트에서 평가되지 않도록
  #         isNixOS 분기를 모듈 레벨에서 처리)
  if isNixOS
  then
    mkIf cfg.enable {
      # (목적: ADB udev 규칙 설치 및 adbusers 그룹 생성)
      programs.adb.enable = true;
      networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
      users.users.${config.workspace.username}.extraGroups = ["adbusers"];
    }
  else
    mkIf cfg.enable {
      # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
      home.packages = [pkgs.android-tools];
    }
