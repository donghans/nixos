{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.jetbrains;
in {
  options.mods.devel.jetbrains.enable = mkEnableOption "Jetbrains common configs";

  config = mkIf (modCfg.enable && !isNixOS) {
    # == jetbrains.enable 마스터 스위치: 하위 IDE 기본값 활성화 ==
    # (사용자는 `lib.mkForce false`로 개별 비활성화 가능)
    mods.devel.jetbrains = {
      idea.enable = mkDefault true;
      webstorm.enable = mkDefault true;
      pycharm.enable = mkDefault true;
      datagrip.enable = mkDefault true;
      android-studio.enable = mkDefault true;
    };
  };
}
