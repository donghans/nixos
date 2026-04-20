{mkModHere, ...}:
# (목적: networking 등 NixOS 전용 옵션이 home-manager 컨텍스트에서 평가되지 않도록
#         isNixOS 분기를 os/hm 블록으로 처리)
# android-studio.enable은 jetbrains.nix에서 선언 — desc=null로 중복 선언 방지
mkModHere __curPos null ({
  config,
  pkgs,
  lib,
  ...
}: let
  asCfg = config.mods.devel.toolchains.jetbrains.android-studio;
in {
  os = lib.mkIf asCfg.enable {
    # (목적: ADB udev 규칙 설치 및 adbusers 그룹 생성)
    programs.adb.enable = true;
    networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
    users.users.${config.workspace.username}.extraGroups = ["adbusers"];
  };
  hm = lib.mkIf asCfg.enable {
    # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
    home.packages = [pkgs.android-tools];
  };
})
