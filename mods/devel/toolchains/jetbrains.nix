{mkMod, ...}:
mkMod __curPos "JetBrains common configs" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  options = {
    idea.enable = lib.mkEnableOption "IntelliJ IDEA";
    pycharm.enable = lib.mkEnableOption "PyCharm Professional";
    webstorm.enable = lib.mkEnableOption "WebStorm";
    datagrip.enable = lib.mkEnableOption "DataGrip";
    android-studio.enable = lib.mkEnableOption "Android Studio (ADB, UDP 5353)";
  };
  hm = lib.mkMerge (
    [
      # (목적: jetbrains.enable 마스터 스위치 — 하위 IDE 기본값 활성화)
      # (사용자는 lib.mkForce false로 개별 비활성화 가능)
      (lib.mkIf cfg.enable {
        mods.devel.toolchains.jetbrains = {
          idea.enable = lib.mkDefault true;
          webstorm.enable = lib.mkDefault true;
          pycharm.enable = lib.mkDefault true;
          datagrip.enable = lib.mkDefault true;
          android-studio.enable = lib.mkDefault true;
        };
      })
    ]
    ++ map (name:
      lib.mkIf config.mods.devel.toolchains.jetbrains.${name}.enable {
        home.packages = [pkgs.jetbrains-wrapped.${name}];
      })
    ["idea" "pycharm" "webstorm" "datagrip" "android-studio"]
  );
})
