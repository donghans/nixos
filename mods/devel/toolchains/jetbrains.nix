{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.jetbrains;
in
  {
    options.mods.devel.jetbrains = {
      enable = mkEnableOption "JetBrains common configs";
      idea.enable = mkEnableOption "IntelliJ IDEA";
      pycharm.enable = mkEnableOption "PyCharm Professional";
      webstorm.enable = mkEnableOption "WebStorm";
      datagrip.enable = mkEnableOption "DataGrip";
      android-studio.enable = mkEnableOption "Android Studio (ADB, UDP 5353)";
    };
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkMerge (
        [
          # (목적: jetbrains.enable 마스터 스위치 — 하위 IDE 기본값 활성화)
          # (사용자는 lib.mkForce false로 개별 비활성화 가능)
          (mkIf modCfg.enable {
            mods.devel.jetbrains = {
              idea.enable = mkDefault true;
              webstorm.enable = mkDefault true;
              pycharm.enable = mkDefault true;
              datagrip.enable = mkDefault true;
              android-studio.enable = mkDefault true;
            };
          })
        ]
        ++ map (name:
          mkIf config.mods.devel.jetbrains.${name}.enable {
            home.packages = [pkgs.jetbrains-wrapped.${name}];
          })
        ["idea" "pycharm" "webstorm" "datagrip" "android-studio"]
      );
    }
  )
