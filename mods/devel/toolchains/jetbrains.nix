{mkModOf, ...}:
mkModOf "mods.devel" __curPos "JetBrains common configs" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  options = {
    android-studio.enable = lib.mkEnableOption "Android Studio (ADB, UDP 5353)";
  };
  # (목적: ADB udev 규칙, mDNS 포트, adbusers 그룹 — NixOS 전용)
  os = lib.mkIf config.mods.devel.toolchains.jetbrains.android-studio.enable {
    programs.adb.enable = true;
    networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)
    users.users.${config.workspace.username}.extraGroups = ["adbusers"];
  };
  hm = lib.mkMerge (
    [
      # (목적: jetbrains.enable 마스터 스위치 — 하위 IDE 기본값 활성화)
      # (사용자는 lib.mkForce false로 개별 비활성화 가능)
      (lib.mkIf cfg.enable {
        mods.devel.toolchains.jetbrains = {
          android-studio.enable = lib.mkDefault true;
        };
      })
    ]
    ++ map (name:
      lib.mkIf config.mods.devel.toolchains.jetbrains.${name}.enable {
        home.packages = [pkgs.jetbrains-wrapped.${name}];
      })
    ["android-studio"]
    ++ [
      # (목적: adb, fastboot 등 SDK 커맨드라인 툴)
      (lib.mkIf config.mods.devel.toolchains.jetbrains.android-studio.enable {
        home.packages = [pkgs.android-tools];
      })
    ]
  );
})
